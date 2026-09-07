"""API-facing Pydantic schemas.

These are response/request DTOs, deliberately kept separate from both the ORM models
(:mod:`app.models.record`) and the ai-engine's domain schemas
(:mod:`adhikar.schemas`) -- the API's public contract should be free to evolve
independently of storage layout and of the engine's internal representation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    media_type: str
    page_count: int
    declared_record_format: str
    ingested_at: datetime


class ParcelSummary(BaseModel):
    """Lightweight row for list/table views -- the reviewer console's grid."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    parcel_key: str
    state: str | None
    district: str | None
    village: str | None
    khata_number: str | None
    survey_number: str | None
    total_area_sq_metre: Decimal | None
    mismatch_score: float | None
    confidence_score: float | None
    recommended_action: str | None
    requires_human_review: bool
    validation_issue_count: int
    validation_highest_severity: str | None
    updated_at: datetime


class ParcelDetail(ParcelSummary):
    """Full artifact for one parcel -- the reviewer console's detail/edit view."""

    artifact_json: dict
    """The LandParcelRecord dump, plus ``provenance`` (per-field bbox/confidence)
    and ``validation_issues`` folded in -- see ``services.ingestion._build_parcel_row``."""

    geometry: dict | None = None
    """Matched cadastral polygon as raw GeoJSON, when the discrepancy engine found
    one. ``None`` is the expected, honest state for a real upload when no cadastral
    geometry source is configured -- not an error."""

    page_image_urls: list[str] = []
    """Relative ``/static/...`` URLs of the source document's rendered pages, for
    the Document Viewer."""


class ReviewCorrectionRequest(BaseModel):
    """A reviewer's correction to one field."""

    field_path: str
    new_value: dict | str | float | int | bool | None
    note: str | None = None


class ReviewEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    field_path: str
    action: str
    reviewer: str
    note: str | None
    created_at: datetime


class UploadResponse(BaseModel):
    document: DocumentSummary
    parcels: list[ParcelSummary]
    warnings: list[str] = []


class ErrorResponse(BaseModel):
    error_type: str
    message: str
    context: dict = {}
