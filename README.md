# SitePulse

Self-hosted client-site dashboard using FastAPI, PostgreSQL, Tailwind CSS, and Alpine.js.

## Windows desktop

Install Python 3.12 on Windows and run `python -m pip install -r requirements-desktop.txt`, then `python desktop.py`. The desktop app uses SQLite at `%LOCALAPPDATA%\SitePulse\sitepulse.db` and opens the same dashboard in a WebView2 window. To build an EXE, run `python -m PyInstaller --noconfirm --clean sitepulse.spec`; the result is `dist/SitePulse.exe`. Windows WebView2 and internet access for the dashboard CDN assets and website checks are required. GitHub Actions also builds an EXE artifact on each push.

The desktop API listens on a random loopback port while the app is open. Other local processes can access it: use the app only on a trusted computer and account. No authentication is implemented.

```text
SitePulse/
├── app/
│   ├── __init__.py
│   ├── database.py
│   ├── models.py
│   ├── scanner.py
│   ├── main.py
│   └── utilities.py
├── frontend/
│   └── index.html
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

Install Docker Desktop with Compose, start Docker, and run `docker-compose up --build` (or `docker compose up --build`) in this directory. Open http://localhost:8000. PostgreSQL data persists in the `postgres_data` volume. Stop with `docker-compose down`; adding `-v` deletes that data.

The app listens on localhost by default. `PORT`, `BIND_ADDRESS`, and `POSTGRES_PASSWORD` can be set in the environment or a local `.env` file. Set a strong database password before first startup; changing it later does not update an existing PostgreSQL volume's credentials. Set `CORS_ORIGINS` on the API service only if a separate frontend origin is needed. The default same-origin frontend needs no CORS configuration.

Onboarding runs a scan immediately. Use **Run a new scan** to compare the DOM fingerprint with the previous successful fingerprint; checks do not run automatically. Domain expiry is sourced from WHOIS and may be unavailable, especially for some registries and subdomains. TLS expiry requires a verifiable certificate. Network failures and unavailable information are shown as down or unknown; an HTTP status below 400 is considered online. Domain warnings count expirations within the next 30 days, excluding already expired domains. Response time includes redirects and up to the first 1 MB of response content. The MD5 fingerprint represents a bounded sketch of tag nesting and attribute names, not page text or a security guarantee.

The AI report utility only creates a chat-completions payload. The payment shield utility only signs and dispatches a webhook; configure and call these functions from trusted application code, and implement the receiver separately. They do not call an AI provider, process payments, or suspend websites automatically.

This application has no login or authorization and is intended for trusted local use. Do not expose it to untrusted users or networks without adding authentication, authorization, CSRF protection, and network controls. Scanning rejects DNS answers that are not public, but DNS can change between validation and connection; use egress filtering or an isolated network to protect internal services. The frontend requires internet access to load the Tailwind and Alpine CDN scripts, and scans require outbound DNS, HTTP(S), WHOIS, and TLS access.
