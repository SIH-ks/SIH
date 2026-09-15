"""SQLAlchemy engine, session factory, and the declarative base.

The engine is chosen at import time with one twist worth reading: if the configured
database cannot be reached and ``ADHIKAR_API_DATABASE_FALLBACK_TO_SQLITE`` is on
(the default), the module falls back to the bundled SQLite file instead of raising.
That exists so a machine without Docker running still boots a working API. It is a
loud fallback, never a silent one -- it logs at warning level and ``/health`` reports
``database.fallback_active: true`` -- and a deployment where the wrong database is
worse than no database turns it off in one setting.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..core.config import SQLITE_URL, get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def _build_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        # A file-based SQLite connection is created fresh per pooled connection, so
        # FastAPI's per-request session (potentially on a different thread than the
        # one that opened it, under the threaded test client / some ASGI servers)
        # would otherwise trip SQLite's same-thread check for no reason relevant here
        # -- SQLAlchemy's own connection pool, not our code, ever crosses threads.
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args=(
            {"check_same_thread": False}
            if is_sqlite
            # Fail fast rather than hanging a worker for the OS-default TCP timeout
            # when Postgres is configured but not listening -- the fallback below can
            # only help if the failure surfaces promptly.
            else {"connect_timeout": 3}
        ),
    )


def _reachable(candidate: Engine) -> bool:
    try:
        with candidate.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("database at %s is unreachable: %s", candidate.url.render_as_string(), exc)
        return False


engine = _build_engine(settings.database_url)

database_fallback_active = False
"""True when the configured database was unreachable and SQLite was substituted.
Read by ``/health`` (and surfaced in the console's system-status readout) so the
substitution is always visible to whoever is looking at the running system."""

if not settings.database_url.startswith("sqlite") and not _reachable(engine):
    if settings.database_fallback_to_sqlite:
        logger.warning(
            "Falling back to bundled SQLite at %s. Data written now will NOT be in the "
            "configured database. Set ADHIKAR_API_DATABASE_FALLBACK_TO_SQLITE=false to "
            "make this a hard failure instead.",
            SQLITE_URL,
        )
        engine = _build_engine(SQLITE_URL)
        database_fallback_active = True
    else:
        logger.error("Configured database is unreachable and SQLite fallback is disabled.")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the backend."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
