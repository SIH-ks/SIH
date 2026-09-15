"""Ownership succession cases and the ownership event chain.

Revision ID: 0003_succession_cases
Revises: 0002_workflow_users_audit
Create Date: 2026-09-15

Purely additive: two new tables and nothing touched on the existing four. No
existing row changes, no column is dropped or retyped, and every read path in the
API before this revision behaves identically after it -- so this can be applied to a
live database without a maintenance window, and ``downgrade`` is a clean drop rather
than a reconstruction.

``succession_cases.parcel_id`` is ``ON DELETE SET NULL`` rather than ``CASCADE``,
which is the one decision in here worth a second look. Deleting a parcel already
takes its audit trail with it (see ``parcels`` -> ``review_events``); letting it also
destroy the assessment of a *disputed succession* on that land would be a much larger
loss, and the case stays readable on its own because ``parcel_key`` is denormalized
onto it.

``ownership_events`` does cascade from its case, because an event row is derived
output -- re-validating a case rewrites the whole set -- and an orphaned chain
depicting documents nobody can find is worse than no chain.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_succession_cases"
down_revision: Union[str, None] = "0002_workflow_users_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: JSONB on PostgreSQL, plain JSON on SQLite -- matching the variant `parcels` uses,
#: so the same migration runs unmodified against both backends.
_JSON = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "succession_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_reference", sa.String(length=128), nullable=False),
        sa.Column("parcel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parcel_key", sa.String(length=512), nullable=True),
        sa.Column("state", sa.String(length=64), nullable=True),
        sa.Column("district", sa.String(length=128), nullable=True),
        sa.Column("village", sa.String(length=128), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("risk_score", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "event_type",
            sa.String(length=48),
            server_default="no_transition_detected",
            nullable=False,
        ),
        sa.Column("recommended_action", sa.String(length=48), nullable=False),
        sa.Column("death_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("heir_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("check_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("open_finding_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("case_json", _JSON, nullable=False),
        sa.Column("report_json", _JSON, nullable=False),
        sa.Column("normalization_warnings", sa.JSON(), nullable=True),
        sa.Column("document_ids", sa.JSON(), nullable=True),
        sa.Column("notes", sa.String(length=2048), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["parcel_id"], ["parcels.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_succession_cases_case_reference", "succession_cases", ["case_reference"])
    op.create_index("ix_succession_cases_parcel_id", "succession_cases", ["parcel_id"])
    op.create_index("ix_succession_cases_parcel_key", "succession_cases", ["parcel_key"])
    op.create_index("ix_succession_cases_state", "succession_cases", ["state"])
    op.create_index("ix_succession_cases_district", "succession_cases", ["district"])
    op.create_index("ix_succession_cases_village", "succession_cases", ["village"])
    op.create_index("ix_succession_cases_outcome", "succession_cases", ["outcome"])
    op.create_index("ix_succession_cases_risk_level", "succession_cases", ["risk_level"])
    op.create_index("ix_succession_cases_risk_score", "succession_cases", ["risk_score"])
    op.create_index("ix_succession_cases_event_type", "succession_cases", ["event_type"])
    op.create_index(
        "ix_succession_cases_recommended_action", "succession_cases", ["recommended_action"]
    )
    op.create_index("ix_succession_cases_death_verified", "succession_cases", ["death_verified"])
    op.create_index("ix_succession_cases_created_by", "succession_cases", ["created_by"])
    # The queue's hot path: open cases in one district, worst first. Filtering on one
    # column and ordering by another is a single operation to the planner, and no
    # combination of the single-column indexes above can serve it.
    op.create_index("ix_succession_queue", "succession_cases", ["outcome", "district", "risk_score"])

    op.create_table(
        "ownership_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("date_stated", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("parcel_key", sa.String(length=512), nullable=True),
        sa.Column("person", sa.String(length=255), nullable=True),
        sa.Column("from_owners", sa.JSON(), nullable=True),
        sa.Column("to_owners", sa.JSON(), nullable=True),
        sa.Column("description", sa.String(length=2048), server_default="", nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["succession_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ownership_events_case_id", "ownership_events", ["case_id"])
    op.create_index("ix_ownership_events_event_type", "ownership_events", ["event_type"])
    op.create_index("ix_ownership_events_event_date", "ownership_events", ["event_date"])
    op.create_index("ix_ownership_events_parcel_key", "ownership_events", ["parcel_key"])
    op.create_index("ix_ownership_events_person", "ownership_events", ["person"])
    # "Every ownership event ever recorded against this khasra, in order" -- the
    # cross-case history query, which is the reason these rows are relational at all
    # rather than living only inside each case's report JSON.
    op.create_index("ix_ownership_events_history", "ownership_events", ["parcel_key", "event_date"])


def downgrade() -> None:
    op.drop_table("ownership_events")
    op.drop_table("succession_cases")
