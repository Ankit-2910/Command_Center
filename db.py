"""
OBSIDIAN — Persistent storage layer
Supabase PostgreSQL via SQLAlchemy
"""
import os
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set. Configure in .env or Render env vars.")

# Supabase Session Pooler requires sslmode=require
if "sslmode" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,        # CRITICAL: avoids stale connections on Render
    pool_recycle=300,
    connect_args={"connect_timeout": 10}
)

SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))

@contextmanager
def get_session():
    """Use: with get_session() as s: s.execute(...)"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def health_check() -> bool:
    """Lightweight DB ping for /healthz endpoint."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"[DB HEALTHCHECK FAIL] {e}")
        return False

def execute_raw(query: str, params: dict = None):
    """Quick helper for one-off queries. Returns list of dicts."""
    with get_session() as s:
        result = s.execute(text(query), params or {})
        if result.returns_rows:
            return [dict(row._mapping) for row in result]
        return []