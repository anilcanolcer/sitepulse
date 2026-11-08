from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON, Numeric
from decimal import Decimal
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class AppPreference(Base):
    __tablename__ = 'app_preferences'
    id: Mapped[int] = mapped_column(primary_key=True)
    theme: Mapped[str] = mapped_column(String(10),nullable=False)
    language: Mapped[str] = mapped_column(String(2),nullable=False)

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
    availability_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hosting_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monthly_fee: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, server_default='0', nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default='TRY', server_default='TRY', nullable=False)
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
    kind: Mapped[str] = mapped_column(String(20), default='note', server_default='note', nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='recorded', server_default='recorded', nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    site: Mapped[Site] = relationship(back_populates='logs')
