"""The user account model backing authentication and role-based authorization."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .enums import UserRole


class User(Base):
    """A revenue-department account.

    Scoped to a jurisdiction (``district``) rather than being global: a Tehsildar in
    Belagavi has no business adjudicating Madurai's queue, and carrying the district
    on the account is what lets the queue endpoint default to *their* workload
    without every client having to remember to pass a filter.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    designation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """Free-text official title as it should appear on a signed report -- "Tehsildar,
    Belagavi Taluk". Distinct from `role`, which is what the API authorizes on."""

    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default=UserRole.OPERATOR.value, index=True)
    district: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def role_enum(self) -> UserRole:
        return UserRole(self.role)
