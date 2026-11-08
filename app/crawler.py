"""Small, explicit audit of linked pages; never probes guessed backup paths."""
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from .scanner import fetch_http
from .insights import inspect_page

def crawl_site(url: str, limit: int = 5) -> dict:
    origin = urlsplit(url)
    root = f'{origin.scheme}://{origin.netloc}'
    robot = RobotFileParser()
    try:
        status, _, body, _, final = fetch_http(root+'/robots.txt')
        if urlsplit(final).netloc != origin.netloc:
            return {'pages':[], 'reason':'robots_unavailable'}
        if status == 200: robot.parse(body.splitlines())
        elif status == 404: robot.parse([])
        else: return {'pages':[], 'reason':'robots_unavailable'}
    except Exception:
        return {'pages':[], 'reason':'robots_unavailable'}
    queue, seen, pages = [url], set(), []
    while queue and len(pages)<limit and len(seen)<20:
        current=queue.pop(0)
        if current in seen: continue
        seen.add(current)
        if not robot.can_fetch('SitePulse',current): continue
        try:
            status, ms, html, headers, final = fetch_http(current)
            if urlsplit(final).netloc != origin.netloc: continue
            if 'html' not in headers.get('Content-Type','').lower(): continue
            evidence=inspect_page(html,headers,final)
            soup=BeautifulSoup(html,'html.parser')
            for a in soup.find_all('a',href=True):
                parts=urlsplit(urljoin(final,a['href']))
                if parts.scheme==origin.scheme and parts.netloc==origin.netloc and not parts.query and not parts.path.lower().endswith(('.pdf','.zip','.png','.jpg','.exe')):
                    queue.append(f'{root}{parts.path or "/"}')
            # Sparse text and old-looking paths are review hints, not proof of abandonment.
            for node in soup(['script','style','nav','footer']): node.decompose()
            words=len(soup.get_text(' ',strip=True).split())
            pages.append({'url':final,'status':status,'response_ms':ms,'words':words,'sparse':words<50,'tasks':evidence['tasks'],'forms':evidence['forms'],'plugins':evidence['plugins']})
        except Exception:
            pages.append({'url':current,'status':None,'words':None,'sparse':False,'tasks':[],'forms':[],'plugins':[]})
        time.sleep(0.3)
    return {'pages':pages,'reason':None,'limit':limit}
