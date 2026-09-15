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
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import Priority, ReviewStatus, UserRole

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A page of results plus the totals a table's footer needs.

    The list endpoints previously returned a bare array, which meant the console
    could show "50 records" while the database held fifty thousand. Carrying ``total``
    alongside the page is the difference between a table and a table you can trust.
    """

    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    media_type: str
    byte_size: int = 0
    page_count: int
    declared_record_format: str
    uploaded_by: str | None = None
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

    # -- workflow projection ---------------------------------------------------
    review_status: ReviewStatus = ReviewStatus.PENDING
    priority: Priority = Priority.NORMAL
    priority_score: float = 0.0
    assigned_to: str | None = None
    sla_due_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    correction_count: int = 0
    has_human_corrections: bool = False

    created_at: datetime | None = None
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

    decision_note: str | None = None
    triage_reasons: list[str] = []
    """Why the triage service put this record where it did in the queue. Computed on
    read rather than stored: the explanation must track the current scores, and a
    stored copy would go stale the first time a correction changed them."""

    document: DocumentSummary | None = None


class ParcelListFilters(BaseModel):
    """Documents the query surface in one place, for the OpenAPI schema's benefit."""

    q: str | None = None
    state: str | None = None
    district: str | None = None
    village: str | None = None
    review_status: ReviewStatus | None = None
    priority: Priority | None = None
    assigned_to: str | None = None
    requires_review: bool | None = None
    overdue: bool | None = None
    min_mismatch: float | None = None
    max_confidence: float | None = None
    severity: str | None = None


# ---------------------------------------------------------------------------
# Review workflow
# ---------------------------------------------------------------------------


class ReviewCorrectionRequest(BaseModel):
    """A reviewer's correction to one field."""

    field_path: str = Field(
        description="Dotted/bracket path into the artifact, e.g. `owners[0].name.raw`. "
        "A leading `$.` is accepted so a ValidationIssue's own `json_path` can be passed through."
    )
    new_value: Any = None
    note: str | None = None
    apply: bool = Field(
        default=True,
        description=(
            "Write the value into the stored artifact and re-run the rule engine. "
            "Set false to record the reviewer's intent in the audit trail without "
            "changing the record -- used when a correction needs a second signature."
        ),
    )


class CorrectionResponse(BaseModel):
    event: ReviewEventResponse
    applied: bool
    revalidated: bool
    revalidation_note: str | None = None
    issues_before: int
    issues_after: int
    highest_severity_after: str | None
    parcel: ParcelDetail


class StatusChangeRequest(BaseModel):
    status: ReviewStatus
    note: str | None = None


class AssignRequest(BaseModel):
    assignee: str | None = Field(
        default=None, description="Username to assign to, or null to release the record back to the pool."
    )
    note: str | None = None


class BulkStatusRequest(BaseModel):
    parcel_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    status: ReviewStatus
    note: str | None = None


class BulkResult(BaseModel):
    """Per-record outcomes, never a bare success count.

    A bulk approval that silently skipped nine of forty records because they were in
    an incompatible state would be an audit failure, so every id is accounted for
    with the reason it was or was not changed.
    """

    updated: list[uuid.UUID] = []
    skipped: list[dict] = []
    total_requested: int


class ReviewEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    field_path: str
    previous_value: dict | None = None
    new_value: dict | None = None
    action: str
    reviewer: str
    reviewer_role: str | None = None
    note: str | None
    created_at: datetime


class AuditEntry(ReviewEventResponse):
    """An audit row joined to enough parcel identity to be readable on its own.

    The audit page lists events across every parcel, where a bare ``parcel_id`` UUID
    tells a reader nothing. Joining the identifiers in the query is one round trip;
    making the client fetch each parcel would be N.
    """

    parcel_key: str | None = None
    village: str | None = None
    district: str | None = None


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    document: DocumentSummary
    parcels: list[ParcelSummary]
    warnings: list[str] = []
    duplicate_of: uuid.UUID | None = None
    """Set when this exact file (by SHA-256) was already ingested. The upload is not
    re-processed; the existing document is returned instead. Re-running an expensive
    OCR/LLM pipeline over a byte-identical scan produces a second set of parcel rows
    that a reviewer then has to reconcile against the first -- silently deduplicating
    is the behaviour a bulk-scanning workflow needs."""

    processing_ms: float | None = None


class BatchUploadResponse(BaseModel):
    results: list[UploadResponse] = []
    failures: list[dict] = []
    """One entry per file that could not be processed, with its filename and reason.
    A batch is not all-or-nothing: a single corrupt scan in a folder of two hundred
    must not discard the other one hundred and ninety-nine."""

    succeeded: int
    failed: int


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    full_name: str
    designation: str | None = None
    email: str | None = None
    role: UserRole
    district: str | None = None
    state: str | None = None
    is_active: bool = True
    last_login_at: datetime | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str
    role: UserRole = UserRole.OPERATOR
    designation: str | None = None
    email: str | None = None
    district: str | None = None
    state: str | None = None


class ErrorResponse(BaseModel):
    error_type: str
    message: str
    context: dict = {}


# `CorrectionResponse` references `ReviewEventResponse` before it is defined (the
# request/response pairs read better grouped by feature than in dependency order).
# `from __future__ import annotations` defers the annotation, so the model is built
# here, once the module namespace is complete.
CorrectionResponse.model_rebuild()
