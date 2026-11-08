import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL") or f"postgresql+psycopg2://sitepulse:{quote_plus(os.getenv('POSTGRES_PASSWORD', 'sitepulse'))}@db:5432/sitepulse"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
if engine.dialect.name == 'sqlite':
    @event.listens_for(engine, 'connect')
    def enable_sqlite_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    with SessionLocal() as session:
        yield session
