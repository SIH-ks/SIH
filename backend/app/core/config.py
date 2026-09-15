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

SQLITE_URL = f"sqlite:///{_BACKEND_ROOT / 'data' / 'adhikar.db'}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADHIKAR_API_", env_file=".env", extra="ignore")

    app_name: str = "Adhikar API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    database_url: str = Field(
        default=SQLITE_URL,
        description=(
            "SQLite by default -- zero setup, no Docker/Postgres required, and "
            "geometry is stored as portable JSON rather than a PostGIS column (see "
            "app.models.record.ParcelRecord.geometry) so the same models work "
            "unchanged against either backend. Point this at a "
            "'postgresql+psycopg://...' URL for a production deployment; nothing "
            "else in this module needs to change."
        ),
    )
    database_fallback_to_sqlite: bool = Field(
        default=True,
        description=(
            "When the configured database is unreachable at startup, fall back to the "
            "bundled SQLite file rather than crashing. This exists because a demo "
            "machine without Docker running should still boot a working API -- a "
            "silent downgrade would be wrong in production, so `/health` reports "
            "`database.fallback_active` and the startup log says so loudly. Set false "
            "for any deployment where 'wrong database' is worse than 'no database'."
        ),
    )
    redis_url: str = "redis://localhost:6379/0"
    """Unused while ingestion runs synchronously (see app.api.v1.routers.upload) --
    reserved for the Celery worker path in a production deployment."""

    # --- AuthN / AuthZ --------------------------------------------------------
    jwt_secret: str = Field(default="change-me-in-production", repr=False)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 12 * 60
    """A revenue officer's working day. Short enough that a shared terminal doesn't
    stay authenticated overnight, long enough that a reviewer isn't re-authenticating
    mid-queue."""

    require_auth: bool = Field(
        default=True,
        description=(
            "Enforce JWT auth + RBAC on every endpoint except /health, /auth/login and "
            "the OpenAPI docs. Kept as a switch (rather than being unconditional) so "
            "the API can be exercised bare with curl during development; it defaults "
            "to on because an open land-records API is not a defensible default."
        ),
    )
    seed_demo_users: bool = Field(
        default=True,
        description=(
            "Create the four demo accounts (admin/reviewer/operator/auditor) at startup "
            "if the users table is empty. Never overwrites an existing account, so "
            "turning this on against a real deployment is a no-op once real users exist."
        ),
    )
    demo_user_password: str = Field(default="adhikar@2026", repr=False)

    # --- Storage --------------------------------------------------------------
    object_storage_bucket: str = "adhikar-scans"
    object_storage_endpoint: str | None = None  # set for MinIO; None uses AWS default

    local_storage_dir: Path = _BACKEND_ROOT / "data" / "uploads"
    """Where original scans and rendered page images land when no object-storage
    endpoint is configured -- the zero-setup path `ingest_upload` actually uses
    today. Served back to the frontend via the `/static` mount in `app.main`."""

    cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    max_upload_size_mb: int = 25
    max_batch_upload_files: int = 25

    # --- Service levels -------------------------------------------------------
    sla_hours_by_priority: dict[str, int] = Field(
        default_factory=lambda: {"critical": 24, "high": 72, "normal": 168, "low": 336},
        description=(
            "How long a parcel may sit in the review queue before it counts as an SLA "
            "breach, keyed by the priority the triage service assigns. These are the "
            "numbers a district office negotiates, so they live in settings rather than "
            "being hard-coded next to the queue query."
        ),
    )

    minutes_saved_per_record: float = Field(
        default=22.0,
        description=(
            "Manual keying + cross-checking time displaced by one auto-validated "
            "record, used only for the 'staff hours saved' figure on the analytics "
            "page. A department-supplied constant, not a measurement -- the API "
            "returns it alongside the derived total so the number is never presented "
            "without its assumption."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
