from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
import sys
import asyncio
import contextlib
import difflib
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from .database import Base, engine, get_db, SessionLocal
from .models import MaintenanceLog, Site, ScanSnapshot, utcnow
from .scanner import ScanError, SiteScanner, normalize_target

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # v0.1 databases predate the per-page evidence column.
    columns={c['name'] for c in inspect(engine).get_columns('sites')}
    with engine.begin() as connection:
        for name, kind in [('insights','JSON'),('shield_url','VARCHAR(500)'),('shield_secret','TEXT'),('shield_state','VARCHAR(20)')]:
            if name not in columns:
                connection.execute(text(f'ALTER TABLE sites ADD COLUMN {name} {kind}'))
    monitor = asyncio.create_task(daily_monitor())
    try: yield
    finally:
        monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError): await monitor

def check_due_sites():
    with SessionLocal() as db:
        due = db.scalars(select(Site).where(Site.checked_at < utcnow()-timedelta(days=1)).limit(10)).all()
        for site in due:
            try:
                apply_scan(site, scanner.scan(site.url))
                save_snapshot(db, site)
                db.commit()
            except Exception:
                db.rollback()

async def daily_monitor():
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(check_due_sites)

app = FastAPI(title='SitePulse', lifespan=lifespan)
asset_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / 'frontend' / 'assets'
app.mount('/assets', StaticFiles(directory=asset_root), name='assets')
origins = [x.strip() for x in os.getenv('CORS_ORIGINS', '').split(',') if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])
scanner = SiteScanner()

class Onboarding(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=500)
    @field_validator('client_name', 'url')
    @classmethod
    def strip_nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Must not be blank')
        return value

class Note(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    @field_validator('body')
    @classmethod
    def strip_nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Must not be blank')
        return value

def site_data(site):
    return {**{key: getattr(site, key) for key in ('id', 'client_name', 'url', 'hostname', 'http_status', 'response_ms', 'domain_expires_at', 'ssl_expires_at', 'structure_hash', 'structure_changed', 'registrar', 'last_error', 'created_at', 'checked_at', 'insights', 'shield_state')}, 'shield_configured':bool(site.shield_url and site.shield_secret)}

def get_site(db, site_id):
    site = db.scalar(select(Site).where(Site.id == site_id).options(selectinload(Site.logs)))
    if site is None:
        raise HTTPException(404, 'Site not found')
    return site

def apply_scan(site, result):
    insights = getattr(result, 'insights', {})
    previous = site.insights or {}
    if insights and previous:
        before = {d['host'] for d in previous.get('dependencies', [])}
        after = {d['host'] for d in insights.get('dependencies', [])}
        insights['changes'] = {'added_dependencies':sorted(after-before), 'removed_dependencies':sorted(before-after), 'title_changed':previous.get('seo',{}).get('title') != insights.get('seo',{}).get('title'), 'lost_headers':[k for k,v in previous.get('security',{}).items() if v and not insights.get('security',{}).get(k)]}
    site.insights = insights or None
    old = site.structure_hash
    site.structure_changed = bool(old and result.structure_hash and old != result.structure_hash)
    for key in ('http_status', 'response_ms', 'domain_expires_at', 'ssl_expires_at', 'structure_hash', 'registrar'):
        value = getattr(result, key)
        # Keep the previous fingerprint if the new fetch could not produce one.
        if key != 'structure_hash' or value is not None:
            setattr(site, key, value)
    site.last_error = result.error
    site.checked_at = utcnow()

def run_scan(url):
    try:
        return scanner.scan(url)
    except (ScanError, ValueError) as exc:
        raise HTTPException(422, f'Invalid or unreachable target: {getattr(exc, "code", "invalid_url")}') from exc

def save_snapshot(db, site):
    if site.insights and 'critical' in site.insights:
        db.add(ScanSnapshot(site_id=site.id, critical=site.insights['critical']))
        db.flush()
        old = db.scalars(select(ScanSnapshot).where(ScanSnapshot.site_id==site.id).order_by(ScanSnapshot.id.desc()).offset(30)).all()
        for row in old: db.delete(row)

@app.get('/api/dashboard')
def dashboard(db: Session = Depends(get_db)):
    sites = db.scalars(select(Site).order_by(Site.created_at.desc(), Site.id.desc())).all()
    now = datetime.now(timezone.utc)
    expiring = sum(1 for s in sites if s.domain_expires_at and now <= (s.domain_expires_at.replace(tzinfo=timezone.utc) if s.domain_expires_at.tzinfo is None else s.domain_expires_at) <= now + timedelta(days=30))
    down = sum(1 for s in sites if s.http_status is None or s.http_status >= 400)
    return {'total_sites': len(sites), 'expiring_domains': expiring, 'down_sites': down, 'sites': [site_data(s) for s in sites]}

@app.post('/api/sites/onboarding', status_code=201)
def onboard(payload: Onboarding, db: Session = Depends(get_db)):
    result = run_scan(payload.url)
    site = Site(client_name=payload.client_name, url=result.url, hostname=result.hostname)
    apply_scan(site, result)
    db.add(site)
    try:
        db.flush()
        save_snapshot(db, site)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'This URL is already monitored') from exc
    db.refresh(site)
    return site_data(site)

@app.post('/api/sites/{site_id}/scan')
def rescan(site_id: int, db: Session = Depends(get_db)):
    site = get_site(db, site_id)
    result = run_scan(site.url)
    apply_scan(site, result)
    save_snapshot(db, site)
    db.commit()
    return site_data(site)

@app.post('/api/sites/{site_id}/logs', status_code=201)
def add_log(site_id: int, payload: Note, db: Session = Depends(get_db)):
    get_site(db, site_id)
    log = MaintenanceLog(site_id=site_id, body=payload.body)
    db.add(log)
    db.commit()
    db.refresh(log)
    return {'id': log.id, 'site_id': log.site_id, 'body': log.body, 'created_at': log.created_at}

@app.get('/api/sites/{site_id}')
def details(site_id: int, db: Session = Depends(get_db)):
    site = get_site(db, site_id)
    return {**site_data(site), 'logs': [{'id': log.id, 'body': log.body, 'created_at': log.created_at} for log in site.logs]}

@app.get('/api/sites/{site_id}/timeline')
def timeline(site_id: int, db: Session = Depends(get_db)):
    get_site(db,site_id)
    rows=db.scalars(select(ScanSnapshot).where(ScanSnapshot.site_id==site_id).order_by(ScanSnapshot.id.desc()).limit(30)).all()
    result=[]
    for i,row in enumerate(rows):
        prior=rows[i+1] if i+1<len(rows) else None
        before=prior.critical if prior else []
        diff=[{'kind':line[0],'text':line[2:]} for line in difflib.ndiff(before,row.critical) if line[0]!='?'] if prior else []
        result.append({'id':row.id,'captured_at':row.captured_at,'previous_at':prior.captured_at if prior else None,'diff':diff,'added':sum(d['kind']=='+' for d in diff),'removed':sum(d['kind']=='-' for d in diff)})
    return result

@app.post('/api/sites/{site_id}/crawl')
def crawl(site_id: int, db: Session = Depends(get_db)):
    from .crawler import crawl_site
    site=get_site(db,site_id)
    return crawl_site(site.url)

@app.get('/api/sites/{site_id}/report.pdf')
def report(site_id: int, lang: str = 'tr', db: Session = Depends(get_db)):
    from .reports import create_report
    site=get_site(db,site_id)
    return Response(create_report(site_data(site), [{'body':l.body,'created_at':l.created_at.isoformat()} for l in site.logs], lang), media_type='application/pdf', headers={'Content-Disposition':f'attachment; filename="SitePulse-{site_id}.pdf"'})

class ShieldPairing(BaseModel):
    url: str = Field(max_length=500)
    secret: str = Field(min_length=32,max_length=200)

class ShieldAction(BaseModel):
    action: str

@app.post('/api/sites/{site_id}/shield/config')
def pair_shield(site_id:int, payload:ShieldPairing, db:Session=Depends(get_db)):
    site=get_site(db,site_id)
    url, host=normalize_target(payload.url)
    if not url.startswith('https://') or host != site.hostname:
        raise HTTPException(422,'Receiver must use HTTPS on the monitored hostname')
    site.shield_url=url
    site.shield_secret=payload.secret
    db.commit()
    return {'configured':True}

@app.post('/api/sites/{site_id}/shield')
def shield(site_id:int, payload:ShieldAction, db:Session=Depends(get_db)):
    from .utilities import dispatch_payment_shield_webhook
    site=get_site(db,site_id)
    if payload.action not in ('suspend','resume') or not site.shield_url or not site.shield_secret:
        raise HTTPException(422,'Configure a receiver and choose suspend or resume')
    normalize_target(site.shield_url)
    try:
        dispatch_payment_shield_webhook(site.shield_url,site.id,payload.action,'0','N/A',site.shield_secret)
    except Exception as exc:
        raise HTTPException(502,'Receiver did not confirm the change') from exc
    site.shield_state=payload.action
    db.add(MaintenanceLog(site_id=site.id,body=f'Payment Shield: receiver confirmed {payload.action}'))
    db.commit()
    return {'state':site.shield_state}

@app.post('/api/sites/{site_id}/plugins/inventory')
def plugin_inventory(site_id:int, db:Session=Depends(get_db)):
    from .utilities import dispatch_payment_shield_webhook
    site=get_site(db,site_id)
    if not site.shield_url or not site.shield_secret:
        raise HTTPException(422,'Pair an owner-installed WordPress receiver first')
    normalize_target(site.shield_url)
    try:
        data=dispatch_payment_shield_webhook(site.shield_url,site.id,'inventory','0','N/A',site.shield_secret)
        return {'plugins':data.get('plugins',[]),'updates_checked_at':data.get('updates_checked_at')}
    except Exception as exc:
        raise HTTPException(502,'Inventory receiver did not respond') from exc

@app.get('/', include_in_schema=False)
def index():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return FileResponse(root / 'frontend' / 'index.html')
