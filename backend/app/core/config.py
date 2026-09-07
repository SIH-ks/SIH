"""Backend settings, sourced from the environment.

Separate from :mod:`adhikar.config` (the ai-engine's own settings) -- this module
only carries what the API/DB layer needs (connection strings, auth secrets, CORS);
engine tuning stays in the ai-engine package so the engine remains usable standalone.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADHIKAR_API_", env_file=".env", extra="ignore")

    app_name: str = "Adhikar API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    database_url: PostgresDsn = Field(
        default="postgresql+psycopg://adhikar:adhikar@localhost:5432/adhikar",
        description="PostGIS-enabled PostgreSQL connection string.",
    )
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = Field(default="change-me-in-production", repr=False)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    object_storage_bucket: str = "adhikar-scans"
    object_storage_endpoint: str | None = None  # set for MinIO; None uses AWS default

    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    max_upload_size_mb: int = 25


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
