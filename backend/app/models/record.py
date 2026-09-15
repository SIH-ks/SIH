"""ORM models: documents, parcels (with PostGIS geometry), and validation runs.

Design note: the full :class:`~adhikar.schemas.artifact.ExtractionArtifact` is stored
verbatim as JSONB (`artifact_json`) -- it is the auditable source of truth and its
schema evolves with the ai-engine package. The relational/PostGIS columns alongside
it (parcel identifiers, geometry, mismatch/confidence scores) exist purely so
PostgreSQL can index, filter and spatially query at scale; they are a queryable
*projection* of the artifact, not a competing representation of it. On re-extraction
both are rewritten together, so they never silently drift apart.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from .enums import Priority, ReviewStatus

_JSONB_OR_JSON = JSONB(none_as_null=True).with_variant(JSON(none_as_null=True), "sqlite")
"""JSONB on Postgres, plain JSON on SQLite -- the one column-type difference this
schema still needs between the two backends every other column already tolerates.

``none_as_null=True`` is load-bearing, not tidiness: by default SQLAlchemy stores a
Python ``None`` in a JSON column as the JSON value ``null``, which is *not* SQL NULL.
Every ``geometry IS NOT NULL`` filter -- the one the map view and the GeoJSON export
are built on -- would then match every row, including the parcels that have no
matched cadastral polygon at all."""


class Document(Base):
    """A single uploaded scan (one PDF or image)."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    media_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int]
    page_count: Mapped[int]
    declared_record_format: Mapped[str] = mapped_column(String(32), default="unknown")
    declared_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1024))
    """Object-storage key for the original file (S3/MinIO)."""

    uploaded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parcels: Mapped[list[ParcelRecord]] = relationship(back_populates="document", cascade="all, delete-orphan")


class ParcelRecord(Base):
    """One extracted parcel: the queryable projection of an artifact parcel.

    ``artifact_json`` holds the complete Pydantic-serialised
    :class:`~adhikar.schemas.land_record.LandParcelRecord`, plus provenance for its
    fields, exactly as the ai-engine produced it.
    """

    __tablename__ = "parcels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)

    parcel_key: Mapped[str] = mapped_column(String(512), index=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    district: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    village: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    khata_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    survey_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    total_area_sq_metre: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    record_format: Mapped[str] = mapped_column(String(32), default="unknown")

    geometry: Mapped[dict | None] = mapped_column(_JSONB_OR_JSON, nullable=True)
    """Matched cadastral polygon, when the discrepancy engine found one -- stored as
    a raw GeoJSON ``Polygon``/``MultiPolygon`` object.

    Deliberately a portable JSON column rather than GeoAlchemy2's PostGIS-specific
    ``Geography`` type: nothing in this API layer runs a spatial SQL query against
    it (``ST_Intersects``, ``ST_Area``, ...) -- the discrepancy engine already
    computes geodesic area and topology in the ai-engine (shapely + pyproj) before
    this row is ever written, so the column only ever needs to store and return the
    polygon, not query on its shape. That lets the same model run unchanged against
    SQLite (no PostGIS/Docker required for local dev) and Postgres alike. A
    production deployment that *does* want to query by geometry (e.g. "parcels
    within this village boundary") would reintroduce a real PostGIS column
    alongside this one rather than replacing it -- that's an additive migration,
    not a breaking change to what's here.
    """

    mismatch_score: Mapped[float | None] = mapped_column(nullable=True, index=True)
    confidence_score: Mapped[float | None] = mapped_column(nullable=True, index=True)
    recommended_action: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    requires_human_review: Mapped[bool] = mapped_column(default=False, index=True)

    artifact_json: Mapped[dict] = mapped_column(_JSONB_OR_JSON)
    """The complete LandParcelRecord, plus per-field provenance (bbox, confidence,
    extractor) and this parcel's validation issues -- see
    ``app.services.ingestion._build_parcel_row`` for exactly what's folded in."""

    page_image_urls: Mapped[list] = mapped_column(JSON, default=list)
    """Relative ``/static/...`` URLs of the source document's rendered pages, in
    order -- what the frontend's Document Viewer actually displays. Denormalized
    from the parent :class:`Document` onto each parcel row so a parcel-detail fetch
    never needs a second round trip for something the viewer always needs."""

    validation_issue_count: Mapped[int] = mapped_column(default=0)
    validation_highest_severity: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    # -- Adjudication workflow ---------------------------------------------------
    # The pipeline's `recommended_action` above is what the *machine* thinks should
    # happen; everything in this block is what a *human* has actually done about it.
    # Keeping the two separate is what makes "the model said auto-approve and the
    # Tehsildar disagreed" a queryable fact rather than a lost one.

    review_status: Mapped[str] = mapped_column(
        String(16), default=ReviewStatus.PENDING.value, index=True
    )
    priority: Mapped[str] = mapped_column(String(16), default=Priority.NORMAL.value, index=True)
    priority_score: Mapped[float] = mapped_column(default=0.0, index=True)
    """The continuous 0-100 triage score `priority` is banded from -- kept alongside
    the band so the queue can sort strictly within a band without a tie-break scan."""

    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    """Username of the officer who has claimed this record, or NULL for unclaimed."""

    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    """When this record breaches its priority band's service level. Stored rather
    than computed on read so "overdue" is a plain indexed comparison in SQL instead
    of a per-row calculation the database cannot filter on."""

    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    decision_note: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    """How many fields a human has had to fix on this record. The single most useful
    number for measuring whether the extraction model is actually improving."""

    has_human_corrections: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="parcels")
    review_events: Mapped[list[ReviewEvent]] = relationship(
        back_populates="parcel", cascade="all, delete-orphan", order_by="ReviewEvent.created_at"
    )

    # The queue view's hot path: "unclaimed work in my district, worst first".
    # A composite index because filtering on status then ordering by score is one
    # operation to the planner, and the single-column indexes above cannot serve it.
    __table_args__ = (
        Index("ix_parcels_queue", "review_status", "district", "priority_score"),
        Index("ix_parcels_jurisdiction", "state", "district", "village"),
    )


class ReviewEvent(Base):
    """An audit-trail entry: a human reviewer accepted or corrected a field.

    Every correction is additive -- the prior artifact JSON is never overwritten in
    place, only superseded, so the review history itself stays reconstructable.
    """

    __tablename__ = "review_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"), index=True)

    field_path: Mapped[str] = mapped_column(String(512))
    """JSON path into the artifact, matching FieldProvenance keys. For events that
    are not about a single field (a status change, an assignment) this is ``"$"`` --
    the whole record -- rather than NULL, so every row answers "what did this touch?"
    with the same kind of value."""

    previous_value: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    action: Mapped[str] = mapped_column(String(32), index=True)  # see models.enums.ReviewAction
    reviewer: Mapped[str] = mapped_column(String(255), index=True)
    reviewer_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """The role the reviewer held *at the time of the action*. Denormalized on
    purpose: an audit trail that re-reads the user's current role would silently
    rewrite history the moment somebody is promoted."""

    note: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    parcel: Mapped[ParcelRecord] = relationship(back_populates="review_events")
