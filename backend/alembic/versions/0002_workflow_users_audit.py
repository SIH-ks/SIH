"""Review workflow, user accounts, and a richer audit trail.

Revision ID: 0002_workflow_users_audit
Revises: 0001_initial_schema
Create Date: 2026-09-10

Three additive changes, none of which rewrite existing data:

* ``users`` -- account records backing JWT auth and the four-role permission model.
* ``parcels`` gains the adjudication-workflow columns (status, priority band and
  score, assignment, SLA clock, decision) that turn the console from a viewer into a
  work queue. Every one is nullable or carries a server default, so existing rows
  land in a valid state (``pending`` / ``normal``) rather than needing a data
  migration; ``app.services.bootstrap.backfill_triage`` then recomputes their real
  priority from the scores they already carry.
* ``review_events`` gains ``reviewer_role`` and ``source_ip``, denormalized at write
  time so the trail records who someone *was* when they acted, not who they are now.

The two composite indexes at the end serve the queue view's hot path ("open work in
my district, worst first") and jurisdiction filtering. Neither can be served by the
single-column indexes alone, since both filter on one column and order by another.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_workflow_users_audit"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("designation", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="operator"),
        sa.Column("district", sa.String(128), nullable=True),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_district", "users", ["district"])
    op.create_index("ix_users_state", "users", ["state"])
    op.create_index("ix_users_is_active", "users", ["is_active"])

    # -- parcels: adjudication workflow -------------------------------------------
    op.add_column("parcels", sa.Column("review_status", sa.String(16), nullable=False, server_default="pending"))
    op.add_column("parcels", sa.Column("priority", sa.String(16), nullable=False, server_default="normal"))
    op.add_column("parcels", sa.Column("priority_score", sa.Float, nullable=False, server_default="0"))
    op.add_column("parcels", sa.Column("assigned_to", sa.String(64), nullable=True))
    op.add_column("parcels", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("parcels", sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("parcels", sa.Column("decided_by", sa.String(64), nullable=True))
    op.add_column("parcels", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("parcels", sa.Column("decision_note", sa.String(2048), nullable=True))
    op.add_column("parcels", sa.Column("correction_count", sa.Integer, nullable=False, server_default="0"))
    op.add_column(
        "parcels", sa.Column("has_human_corrections", sa.Boolean, nullable=False, server_default=sa.false())
    )

    op.create_index("ix_parcels_review_status", "parcels", ["review_status"])
    op.create_index("ix_parcels_priority", "parcels", ["priority"])
    op.create_index("ix_parcels_priority_score", "parcels", ["priority_score"])
    op.create_index("ix_parcels_assigned_to", "parcels", ["assigned_to"])
    op.create_index("ix_parcels_sla_due_at", "parcels", ["sla_due_at"])
    op.create_index("ix_parcels_decided_by", "parcels", ["decided_by"])
    op.create_index("ix_parcels_decided_at", "parcels", ["decided_at"])
    op.create_index("ix_parcels_has_human_corrections", "parcels", ["has_human_corrections"])
    op.create_index("ix_parcels_queue", "parcels", ["review_status", "district", "priority_score"])
    op.create_index("ix_parcels_jurisdiction", "parcels", ["state", "district", "village"])

    # -- review_events: fuller provenance ------------------------------------------
    op.add_column("review_events", sa.Column("reviewer_role", sa.String(32), nullable=True))
    op.add_column("review_events", sa.Column("source_ip", sa.String(64), nullable=True))
    op.create_index("ix_review_events_action", "review_events", ["action"])
    op.create_index("ix_review_events_reviewer", "review_events", ["reviewer"])
    op.create_index("ix_review_events_created_at", "review_events", ["created_at"])


def downgrade() -> None:
    for name in (
        "ix_review_events_created_at",
        "ix_review_events_reviewer",
        "ix_review_events_action",
    ):
        op.drop_index(name, table_name="review_events")
    op.drop_column("review_events", "source_ip")
    op.drop_column("review_events", "reviewer_role")

    for name in (
        "ix_parcels_jurisdiction",
        "ix_parcels_queue",
        "ix_parcels_has_human_corrections",
        "ix_parcels_decided_at",
        "ix_parcels_decided_by",
        "ix_parcels_sla_due_at",
        "ix_parcels_assigned_to",
        "ix_parcels_priority_score",
        "ix_parcels_priority",
        "ix_parcels_review_status",
    ):
        op.drop_index(name, table_name="parcels")
    for column in (
        "has_human_corrections",
        "correction_count",
        "decision_note",
        "decided_at",
        "decided_by",
        "sla_due_at",
        "assigned_at",
        "assigned_to",
        "priority_score",
        "priority",
        "review_status",
    ):
        op.drop_column("parcels", column)

    op.drop_table("users")
