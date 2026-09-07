"""Backend settings, sourced from the environment.

Separate from :mod:`adhikar.config` (the ai-engine's own settings) -- this module
only carries what the API/DB layer needs (connection strings, auth secrets, CORS);
engine tuning stays in the ai-engine package so the engine remains usable standalone.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADHIKAR_API_", env_file=".env", extra="ignore")

    app_name: str = "Adhikar API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    database_url: str = Field(
        default=f"sqlite:///{_BACKEND_ROOT / 'data' / 'adhikar.db'}",
        description=(
            "SQLite by default -- zero setup, no Docker/Postgres required, and "
            "geometry is stored as portable JSON rather than a PostGIS column (see "
            "app.models.record.ParcelRecord.geometry) so the same models work "
            "unchanged against either backend. Point this at a "
            "'postgresql+psycopg://...' URL for a production deployment; nothing "
            "else in this module needs to change."
        ),
    )
    redis_url: str = "redis://localhost:6379/0"
    """Unused while ingestion runs synchronously (see app.api.v1.routers.upload) --
    reserved for the Celery worker path in a production deployment."""

    jwt_secret: str = Field(default="change-me-in-production", repr=False)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    object_storage_bucket: str = "adhikar-scans"
    object_storage_endpoint: str | None = None  # set for MinIO; None uses AWS default

    local_storage_dir: Path = _BACKEND_ROOT / "data" / "uploads"
    """Where original scans and rendered page images land when no object-storage
    endpoint is configured -- the zero-setup path `ingest_upload` actually uses
    today. Served back to the frontend via the `/static` mount in `app.main`."""

    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    max_upload_size_mb: int = 25


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
