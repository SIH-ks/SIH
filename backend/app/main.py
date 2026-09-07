"""FastAPI application entrypoint.

Run with: ``uvicorn app.main:app --reload`` from the ``backend/`` directory.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from adhikar.exceptions import AdhikarError

from .api.v1.routers import api_router
from .core.config import get_settings
from .db.base import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201, ARG001
    # Development convenience only -- production schema changes go through Alembic
    # migrations (backend/alembic/), never create_all().
    if get_settings().environment == "development":
        Base.metadata.create_all(bind=engine)
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=(
        "Intelligent Land Record Digitization and Validation System (SIH26018). "
        "OCR + Vision-LLM extraction, arithmetic consistency validation, and "
        "geospatial discrepancy scoring for Jamabandi and 7/12 Extract records."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
def health() -> dict[str, str]:
    return {"status": "ok"}
