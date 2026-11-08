from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
import sys
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from .database import Base, engine, get_db
from .models import MaintenanceLog, Site, utcnow
from .scanner import ScanError, SiteScanner

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title='SitePulse', lifespan=lifespan)
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
    return {key: getattr(site, key) for key in ('id', 'client_name', 'url', 'hostname', 'http_status', 'response_ms', 'domain_expires_at', 'ssl_expires_at', 'structure_hash', 'structure_changed', 'registrar', 'last_error', 'created_at', 'checked_at')}

def get_site(db, site_id):
    site = db.scalar(select(Site).where(Site.id == site_id).options(selectinload(Site.logs)))
    if site is None:
        raise HTTPException(404, 'Site not found')
    return site

def apply_scan(site, result):
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

@app.get('/', include_in_schema=False)
def index():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return FileResponse(root / 'frontend' / 'index.html')
