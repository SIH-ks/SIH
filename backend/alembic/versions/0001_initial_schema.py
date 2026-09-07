"""Initial schema: documents, parcels, review_events.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-07

Note on ``geometry``: stored as plain JSONB (a raw GeoJSON object), not a PostGIS
``Geography`` column -- see the docstring on
``app.models.record.ParcelRecord.geometry`` for why. This migration targets
Postgres specifically (SQLite dev uses ``Base.metadata.create_all()`` instead, see
``app.main``'s lifespan handler), so it no longer needs the PostGIS extension at
all.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("declared_record_format", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("declared_state", sa.String(64), nullable=True),
        sa.Column("source_system", sa.String(128), nullable=True),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("uploaded_by", sa.String(255), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "parcels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parcel_key", sa.String(512), nullable=False),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("district", sa.String(128), nullable=True),
        sa.Column("village", sa.String(128), nullable=True),
        sa.Column("khata_number", sa.String(64), nullable=True),
        sa.Column("survey_number", sa.String(64), nullable=True),
        sa.Column("total_area_sq_metre", sa.Numeric(18, 4), nullable=True),
        sa.Column("record_format", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("geometry", postgresql.JSONB, nullable=True),
        sa.Column("mismatch_score", sa.Float, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("recommended_action", sa.String(32), nullable=True),
        sa.Column("requires_human_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("artifact_json", postgresql.JSONB, nullable=False),
        sa.Column("page_image_urls", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("validation_issue_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("validation_highest_severity", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    for col in (
        "document_id",
        "state",
        "district",
        "village",
        "khata_number",
        "survey_number",
        "parcel_key",
        "mismatch_score",
        "confidence_score",
        "recommended_action",
        "requires_human_review",
        "validation_highest_severity",
    ):
        op.create_index(f"ix_parcels_{col}", "parcels", [col])

    op.create_table(
        "review_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parcel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("field_path", sa.String(512), nullable=False),
        sa.Column("previous_value", postgresql.JSONB, nullable=True),
        sa.Column("new_value", postgresql.JSONB, nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reviewer", sa.String(255), nullable=False),
        sa.Column("note", sa.String(2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_review_events_parcel_id", "review_events", ["parcel_id"])


def downgrade() -> None:
    op.drop_table("review_events")
    op.drop_table("parcels")
    op.drop_table("documents")
