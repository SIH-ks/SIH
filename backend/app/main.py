"""FastAPI application entrypoint.

Run with: ``uvicorn app.main:app --reload`` from the ``backend/`` directory.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from adhikar.exceptions import AdhikarError
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from .api.v1.routers import api_router
from .core.config import get_settings
from .core.logging import RequestContextMiddleware, configure_logging, get_logger
from .db.base import Base, SessionLocal, database_fallback_active, engine
from .db.dev_schema import reconcile_sqlite_schema
from .models import (  # noqa: F401 - registers tables on Base.metadata
    OwnershipEventRecord,
    ParcelRecord,
    ReviewEvent,
    SuccessionCaseRecord,
    User,
)
from .services.bootstrap import backfill_triage, ensure_demo_users

settings = get_settings()
configure_logging(json_output=settings.environment != "development")
logger = get_logger("adhikar.app")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201, ARG001
    if settings.environment == "development":
        # Development convenience only -- production schema changes go through Alembic
        # migrations (backend/alembic/), never create_all(). The second call covers
        # what create_all() cannot: adding a column to a table that already exists,
        # which is what a developer with a pre-existing adhikar.db actually hits.
        Base.metadata.create_all(bind=engine)
        reconcile_sqlite_schema(engine, Base.metadata)

    # First-run provisioning. Both steps are idempotent and additive (see
    # app.services.bootstrap), so this costs one query on every subsequent boot and
    # means a fresh clone is a signed-in-able system with a correctly ordered queue
    # rather than a login screen nobody has an account for.
    db = SessionLocal()
    try:
        ensure_demo_users(db)
        backfill_triage(db)
    except Exception:  # noqa: BLE001 - never let provisioning stop the API from serving
        logger.exception("bootstrap_failed")
        db.rollback()
    finally:
        db.close()

    logger.info(
        "startup",
        environment=settings.environment,
        auth_enforced=settings.require_auth,
        database=engine.dialect.name,
        database_fallback_active=database_fallback_active,
    )
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "Intelligent Land Record Digitization and Validation System (SIH26018). "
        "OCR + Vision-LLM extraction, arithmetic consistency validation, and "
        "geospatial discrepancy scoring for Jamabandi and 7/12 Extract records, "
        "with a role-gated review workflow and a fully auditable correction trail."
    ),
    version="1.0.0",
    lifespan=lifespan,
    contact={"name": "Adhikar — SIH26018"},
    license_info={"name": "For evaluation use"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # The console reads paging totals off this header; without exposing it, the
    # browser hides it from JavaScript and every table silently loses its count.
    expose_headers=["X-Total-Count", "X-Request-ID"],
)
# Analytics payloads and GeoJSON collections are large and highly repetitive; the
# 1 KB floor keeps small JSON responses from paying compression overhead for nothing.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(RequestContextMiddleware)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(api_router, prefix=settings.api_v1_prefix)

# The zero-setup local storage backend `ingestion.py` actually writes to (original
# scans + rendered page PNGs) -- served directly rather than through a DB-backed
# download endpoint since these are static, content-hashed files. Swap for a
# reverse-proxy/CDN rule in front of the real object-storage bucket in production;
# nothing else in the API needs to change since `page_image_urls` is already just
# an opaque relative URL as far as callers are concerned.
settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=settings.local_storage_dir), name="uploads")


@app.exception_handler(AdhikarError)
async def adhikar_error_handler(request: Request, exc: AdhikarError) -> JSONResponse:  # noqa: ARG001
    """Every engine failure surfaces as a structured, typed error body."""
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=exc.to_dict())


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness + readiness in one probe.

    Reports ``degraded`` rather than failing the request when the database is
    unreachable: an orchestrator needs to distinguish "this process is wedged, restart
    it" from "this process is fine, its dependency is not", and a 503 here would
    conflate the two into a restart loop that fixes nothing.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "version": app.version,
        "environment": settings.environment,
        "database": {
            "dialect": engine.dialect.name,
            "reachable": db_ok,
            "fallback_active": database_fallback_active,
        },
    }
