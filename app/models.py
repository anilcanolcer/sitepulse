from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_ms: Mapped[int | None] = mapped_column(Integer)
    domain_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ssl_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    structure_hash: Mapped[str | None] = mapped_column(String(32))
    structure_changed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    registrar: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(String(80))
    insights: Mapped[dict | None] = mapped_column(JSON)
    shield_url: Mapped[str | None] = mapped_column(String(500))
    shield_secret: Mapped[str | None] = mapped_column(Text)
    shield_state: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    logs: Mapped[list['MaintenanceLog']] = relationship(back_populates='site', cascade='all, delete-orphan', passive_deletes=True, order_by='MaintenanceLog.created_at, MaintenanceLog.id')

class ScanSnapshot(Base):
    __tablename__ = 'scan_snapshots'
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey('sites.id', ondelete='CASCADE'), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    critical: Mapped[list] = mapped_column(JSON)

class MaintenanceLog(Base):
    __tablename__ = 'maintenance_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey('sites.id', ondelete='CASCADE'), index=True, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    site: Mapped[Site] = relationship(back_populates='logs')
