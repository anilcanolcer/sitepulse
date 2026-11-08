"""Public-site probe: HTTP, TLS expiry, WHOIS, and a structural HTML fingerprint."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import ssl
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field
from .insights import inspect_page

USER_AGENT = "SitePulse/1.0 (desktop; local monitor)"
BODY_LIMIT = 1_000_000
HTTP_TIMEOUT = 12
WHOIS_TIMEOUT = 12
SKIP_TAGS = {"script", "style", "noscript", "template"}


class ScanError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ScanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    hostname: str
    http_status: int | None = None
    response_ms: int | None = None
    domain_expires_at: datetime | None = None
    ssl_expires_at: datetime | None = None
    structure_hash: str | None = None
    registrar: str | None = None
    error: str | None = None
    insights: dict = Field(default_factory=dict)


class SiteScanner:
    def check_availability(self, raw_url: str) -> ScanResult:
        url, hostname=normalize_target(raw_url)
        result=ScanResult(url=url,hostname=hostname)
        try:
            result.http_status,result.response_ms,_,_,_=fetch_http(url)
        except (ScanError, requests.RequestException, OSError):
            result.error='request_failed'
        try: result.ssl_expires_at=ssl_expiry(hostname)
        except (OSError,ssl.SSLError,ScanError): pass
        return result

    def scan(self, raw_url: str) -> ScanResult:
        url, hostname = normalize_target(raw_url)
        result = ScanResult(url=url, hostname=hostname)
        try:
            status, millis, html, headers, final_url = fetch_http(url)
            result.http_status = status
            result.response_ms = millis
            if html:
                result.structure_hash = structure_hash(html)
                if 'html' in headers.get('Content-Type', '').lower():
                    result.insights = inspect_page(html, headers, final_url)
        except ScanError as exc:
            result.error = exc.code
        except requests.RequestException:
            result.error = "request_failed"
        except OSError:
            result.error = "request_failed"

        try:
            result.ssl_expires_at = ssl_expiry(hostname)
        except (OSError, ssl.SSLError, ScanError):
            result.ssl_expires_at = None

        try:
            expires, registrar = domain_expiry(hostname)
            result.domain_expires_at = expires
            result.registrar = registrar
        except Exception:
            result.domain_expires_at = None
            result.registrar = None
        return result


def normalize_target(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    if not text or any(ch.isspace() for ch in text):
        raise ScanError("invalid_url")
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ScanError("invalid_url")
    if parts.username or parts.password:
        raise ScanError("invalid_url")
    host = parts.hostname.rstrip(".").lower()
    assert_public_host(host)
    path = parts.path or "/"
    port = f":{parts.port}" if parts.port else ""
    netloc = host + port
    return urlunsplit((parts.scheme, netloc, path, "", "")), host


def assert_public_host(host: str) -> None:
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local") or host.endswith(".localhost"):
        raise ScanError("private_host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ScanError("dns_failed") from exc
    addresses = {item[4][0] for item in infos}
    if not addresses:
        raise ScanError("dns_failed")
    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise ScanError("dns_failed") from exc
        if not ip.is_global:
            raise ScanError("private_host")


def fetch_http(url: str) -> tuple[int, int, str, dict, str]:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    current = url
    started = datetime.now(timezone.utc)
    response: requests.Response | None = None
    try:
        for _ in range(5):
            host = urlsplit(current).hostname or ""
            assert_public_host(host)
            response = session.get(
                current,
                timeout=HTTP_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                response.close()
                response = None
                if not location:
                    raise ScanError("request_failed")
                current = urljoin(current, location)
                continue
            break
        else:
            raise ScanError("request_failed")
        if response is None:
            raise ScanError("request_failed")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(16_384):
            if not chunk:
                continue
            chunks.append(chunk)
            size += len(chunk)
            if size >= BODY_LIMIT:
                break
        elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        encoding = response.encoding or "utf-8"
        html = b"".join(chunks).decode(encoding, errors="replace")
        return response.status_code, max(elapsed, 0), html, dict(response.headers), current
    finally:
        if response is not None:
            response.close()
        session.close()


def structure_hash(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(list(SKIP_TAGS)):
        tag.decompose()
    parts: list[str] = []
    budget = 0
    for element in soup.find_all(True):
        names = ",".join(sorted(str(name) for name in element.attrs.keys()))
        depth = sum(1 for parent in element.parents if getattr(parent, 'name', None) not in (None, '[document]'))
        piece = f"{depth}:{element.name}[{names}]"
        parts.append(piece)
        budget += len(piece)
        if budget >= 6000:
            break
    sketch = "/".join(parts)
    return hashlib.md5(sketch.encode("utf-8")).hexdigest()


def ssl_expiry(hostname: str) -> datetime | None:
    assert_public_host(hostname)
    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, 443), timeout=8) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as secure:
                return _cert_not_after(secure.getpeercert())
    except ssl.SSLCertVerificationError:
        loose = ssl._create_unverified_context()
        with socket.create_connection((hostname, 443), timeout=8) as sock:
            with loose.wrap_socket(sock, server_hostname=hostname) as secure:
                return _cert_not_after(secure.getpeercert())


def _cert_not_after(cert: dict[str, Any] | None) -> datetime | None:
    if not cert:
        return None
    raw = cert.get("notAfter")
    if not isinstance(raw, str):
        return None
    parsed = datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z")
    return parsed.replace(tzinfo=timezone.utc)


def domain_expiry(hostname: str) -> tuple[datetime | None, str | None]:
    import whois

    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["record"] = whois.whois(hostname)
        except Exception as exc:
            box["error"] = exc

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(WHOIS_TIMEOUT)
    if worker.is_alive() or "record" not in box:
        return None, None
    record = box["record"]
    expires = getattr(record, "expiration_date", None)
    if isinstance(expires, list):
        expires = next((item for item in expires if isinstance(item, datetime)), None)
    if isinstance(expires, datetime):
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    else:
        expires = None
    registrar = getattr(record, "registrar", None)
    if isinstance(registrar, list):
        registrar = registrar[0] if registrar else None
    if not isinstance(registrar, str):
        registrar = None
    return expires, (registrar.strip() or None)


scanner = SiteScanner()
