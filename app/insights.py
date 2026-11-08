"""Evidence from one HTTP response; no JavaScript execution or whole-site crawl."""
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup

def safe_parts(base, raw):
    try:
        parts=urlsplit(urljoin(base,str(raw)))
        if parts.scheme not in ('http','https') or not parts.hostname:
            return None
        return parts
    except ValueError:
        return None

def inspect_page(html: str, headers: dict, url: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    headers = {k.lower(): v for k, v in headers.items()}
    title = soup.title.get_text(' ', strip=True)[:250] if soup.title else ''
    meta = soup.find('meta', attrs={'name': 'description'})
    robots = soup.find('meta', attrs={'name': 'robots'})
    canonical = soup.find('link', rel='canonical')
    dependencies = {}
    links={}
    for anchor in soup.find_all('a',href=True):
        target=safe_parts(url,anchor['href'])
        if target is None:continue
        address=f'{target.scheme}://{target.hostname}{target.path or "/"}'
        links[address]={'url':address,'external':target.hostname!=urlsplit(url).hostname}
    mixed = []
    for tag, attr in [('script','src'),('link','href'),('iframe','src')]:
        for item in soup.find_all(tag):
            if tag == 'link' and 'stylesheet' not in item.get('rel', []):
                continue
            raw = item.get(attr, '')
            if not raw:
                continue
            parts = safe_parts(url, raw)
            if parts is None: continue
            absolute = parts.geturl()
            if urlsplit(url).scheme == 'https' and parts.scheme == 'http':
                mixed.append(absolute[:250])
            if parts.scheme in ('http', 'https') and parts.hostname != urlsplit(url).hostname:
                dependencies.setdefault(parts.hostname, set()).add(tag)
    forms = []
    for form in soup.find_all('form')[:30]:
        target = safe_parts(url, form.get('action') or url)
        if target is None: continue
        forms.append({'host': target.hostname, 'method': form.get('method','get').upper(), 'https': target.scheme == 'https', 'external': target.hostname != urlsplit(url).hostname, 'password': bool(form.find('input', attrs={'type':'password'}))})
    tech = []
    generator = soup.find('meta', attrs={'name':'generator'})
    if generator and generator.get('content'):
        tech.append({'name': str(generator['content'])[:100], 'evidence': 'meta generator'})
    lower = html.lower()
    for name, marker in [('WordPress','/wp-content/'),('Next.js','/_next/'),('Shopify','cdn.shopify.com'),('Webflow','data-wf-page'),('Wix','static.wixstatic.com')]:
        if marker in lower:
            tech.append({'name':name,'evidence':marker})
    security = {name: bool(headers.get(name)) for name in ['strict-transport-security','content-security-policy','x-content-type-options','referrer-policy']}
    security['frame-protection'] = bool(headers.get('x-frame-options') or 'frame-ancestors' in headers.get('content-security-policy','').lower())
    images = soup.find_all('img')
    critical = []
    for tag, attr in [('script','src'),('iframe','src'),('link','href'),('form','action')]:
        for element in soup.find_all(tag):
            if tag == 'link' and 'stylesheet' not in element.get('rel',[]): continue
            raw = element.get(attr)
            if raw is None: continue
            target = safe_parts(url,raw)
            if target is None: continue
            # Query values and form contents can contain personal data or tokens.
            safe = f'{target.scheme}://{target.hostname}{target.path}'
            critical.append(f'<{tag} {attr}="{safe[:300]}">')
    plugins = sorted(set(__import__('re').findall(r'/wp-content/plugins/([a-zA-Z0-9_-]+)/',html)))[:40]
    seo = {'title':title,'description':str(meta.get('content',''))[:500] if meta else '', 'canonical':str(canonical.get('href',''))[:500] if canonical else '', 'h1_count':len(soup.find_all('h1')), 'language':str(soup.html.get('lang',''))[:40] if soup.html else '', 'image_count':len(images),'missing_alt':sum(1 for img in images if not img.has_attr('alt')), 'noindex': 'noindex' in ((str(robots.get('content','')) if robots else '')+' '+headers.get('x-robots-tag','')).lower()}
    tasks = []
    def add(code, priority, evidence):
        tasks.append({'code':code, 'priority':priority, 'evidence':str(evidence)[:500]})
    if mixed: add('mixed','high',len(mixed))
    if any(not f['https'] and f['password'] for f in forms): add('password_form','high','HTTP / password')
    if seo['noindex']: add('noindex','review','noindex')
    missing = [k for k,v in security.items() if not v]
    if missing: add('headers','review',', '.join(missing))
    if not title: add('title','review','<title>')
    if not seo['description']: add('description','low','meta description')
    if seo['missing_alt']: add('alt','review',seo['missing_alt'])
    if not seo['language']: add('language','low','html[lang]')
    if any(f['external'] for f in forms): add('form_destination','review',', '.join(sorted({f['host'] or '' for f in forms if f['external']})))
    # Transparent checklist score, not a vulnerability or business-risk probability.
    checks = [bool(title),bool(seo['description']),bool(seo['language']),not seo['missing_alt'],not mixed,not any(not f['https'] and f['password'] for f in forms),*security.values()]
    return {'page_url':url,'technology':tech[:10], 'dependencies':[{'host':host,'types':sorted(types)} for host,types in sorted(dependencies.items())][:60], 'links':{'total':len(links),'external':sum(link['external'] for link in links.values()),'internal':sum(not link['external'] for link in links.values()),'items':list(links.values())[:40]},'forms':forms, 'security':security, 'seo':seo, 'tasks':tasks, 'mixed_content':mixed[:10], 'critical':sorted(set(critical))[:300], 'plugins':plugins, 'score':round(100*sum(checks)/len(checks)), 'checks_passed':sum(checks), 'checks_total':len(checks)}
