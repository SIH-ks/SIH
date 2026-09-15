"""ORM models for ownership-succession cases and the ownership event chain.

Two tables, added for two different reasons.

``succession_cases`` follows the same pattern as ``parcels``: the authoritative
object is the ai-engine's own JSON (the normalised
:class:`~adhikar.schemas.succession.SuccessionCase` and the
:class:`~adhikar.schemas.succession.SuccessionReport` it produced), stored verbatim so
the assessment stays re-auditable years later against the engine version that made
it. The scalar columns beside it -- outcome, risk band and score, parcel identity --
are a *projection* for filtering and sorting, rewritten from the JSON on every
re-validation so the two cannot drift.

``ownership_events`` is the one place this feature genuinely needs relational storage
rather than another JSON blob. The event chain also lives inside ``report_json``, but
a chain nested per case can only answer "what happened in this case". The question a
revenue office actually asks is *"show me every ownership event ever recorded against
Khasra 125/2"* -- across cases, across parcels, ordered by date -- and that is a
query, not a document. Rows here are derived, never hand-edited: a re-validation
deletes and rewrites this case's events from the report, so they cannot come to
disagree with the documents they depict.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base

_JSONB_OR_JSON = JSONB(none_as_null=True).with_variant(JSON(none_as_null=True), "sqlite")
"""JSONB on Postgres, plain JSON on SQLite -- the same variant ``parcels`` uses.

``none_as_null=True`` for the same load-bearing reason documented there: without it
SQLAlchemy stores a Python ``None`` as the JSON value ``null``, which is not SQL
NULL, and every ``IS NOT NULL`` filter matches every row.
"""


class SuccessionCaseRecord(Base):
    """One assessed ownership transition: the documents submitted and what they showed.

    Named ``...Record`` to keep it distinct from the engine's
    :class:`adhikar.schemas.succession.SuccessionCase`, which is the domain object
    this row stores. They are deliberately different types: the engine's is a
    document bundle with no identity or workflow, this one is a row with both.
    """

    __tablename__ = "succession_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    case_reference: Mapped[str] = mapped_column(String(128), index=True)
    """Human-facing handle for the case, e.g. ``SUC/BLG/2025/0041``. Indexed but not
    unique: re-filing the same reference after a rejection is normal office practice,
    and rejecting it here would push the workaround into the reference itself."""

    parcel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("parcels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """The register record this case concerns, when it was raised against one.

    ``SET NULL`` rather than ``CASCADE``: deleting a parcel row must not silently
    destroy the assessment of a disputed succession on it. The case keeps
    ``parcel_key`` and remains readable on its own."""

    parcel_key: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    district: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    village: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # -- the engine's verdict, projected for querying -----------------------------
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    """``validated`` | ``incomplete`` | ``inconsistent`` | ``review_required``.

    There is deliberately no value here meaning *fraud*: see
    :class:`adhikar.schemas.succession.SuccessionOutcome`. A column that could hold
    one would eventually be filtered on, charted, and quoted."""

    risk_level: Mapped[str] = mapped_column(String(16), index=True)
    risk_score: Mapped[float] = mapped_column(default=0.0, index=True)
    event_type: Mapped[str] = mapped_column(String(48), default="no_transition_detected", index=True)
    recommended_action: Mapped[str] = mapped_column(String(48), index=True)

    death_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    """True only when a submitted certificate names a person the *previous record*
    recorded as owner -- not merely that a certificate was submitted."""

    heir_count: Mapped[int] = mapped_column(Integer, default=0)
    check_count: Mapped[int] = mapped_column(Integer, default=0)
    open_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    """Checks that did not come back clear. The number the queue sorts a case by."""

    # -- the authoritative documents -----------------------------------------------
    case_json: Mapped[dict] = mapped_column(_JSONB_OR_JSON)
    """The normalised ``SuccessionCase`` as the engine received it. Re-validation
    reads this, so it must round-trip through the engine's schema."""

    report_json: Mapped[dict] = mapped_column(_JSONB_OR_JSON)
    """The full ``SuccessionReport``: every check, its evidence, the risk arithmetic
    and the timeline. This is what the console renders and what an export carries."""

    normalization_warnings: Mapped[list] = mapped_column(JSON, default=list)
    """How the submission was *read* -- a date that would not parse, an area unit
    nobody recognised. Kept beside the findings because "this was assessed without a
    date of death" changes what the findings mean."""

    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    """``documents.id`` values for scans ingested through the normal upload path and
    referenced by this case. A plain list rather than an association table: nothing
    queries from document back to case, and a join table for a fact only ever read
    in one direction is cost without benefit."""

    notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list[OwnershipEventRecord]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="OwnershipEventRecord.sequence",
    )

    # "Open succession work in my district, worst first" -- one operation to the
    # planner, which the single-column indexes above cannot serve between them.
    __table_args__ = (
        Index("ix_succession_queue", "outcome", "district", "risk_score"),
    )


class OwnershipEventRecord(Base):
    """One node of the ownership chain, as the submitted documents record it.

    Derived from the report, never authored: :func:`app.services.succession.persist_case`
    rewrites the whole set whenever a case is re-validated. Storing them relationally
    is what makes a parcel's ownership history answerable as a query across cases
    rather than only inside the one case that happened to assemble it.
    """

    __tablename__ = "ownership_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("succession_cases.id", ondelete="CASCADE"), index=True
    )

    sequence: Mapped[int] = mapped_column(Integer, default=0)
    """Position on the timeline, as the engine ordered it. Kept so the stored chain
    renders in the same order the report did without re-deriving the tie-breaks."""

    event_type: Mapped[str] = mapped_column(String(32), index=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    date_stated: Mapped[bool] = mapped_column(Boolean, default=True)
    """False when the date was inferred (from a revenue year, say) rather than read
    off the document. The console draws inferred positions differently, and an
    analytics query that treated the two alike would report false precision."""

    parcel_key: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    """Indexed because this is the column the cross-case history query filters on."""

    person: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    from_owners: Mapped[list] = mapped_column(JSON, default=list)
    to_owners: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(String(2048), default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    """The documents this event was read from, so a node on the timeline can be
    clicked through to the page it came from."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped[SuccessionCaseRecord] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_ownership_events_history", "parcel_key", "event_date"),
    )
