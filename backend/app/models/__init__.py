"""ORM models. Import from here so Base.metadata sees every table before
create_all()/Alembic autogenerate runs."""
from __future__ import annotations

from .enums import ALLOWED_TRANSITIONS, Priority, ReviewAction, ReviewStatus, UserRole
from .record import Document, ParcelRecord, ReviewEvent
from .succession import OwnershipEventRecord, SuccessionCaseRecord
from .user import User

__all__ = [
    "ALLOWED_TRANSITIONS",
    "Document",
    "OwnershipEventRecord",
    "ParcelRecord",
    "Priority",
    "ReviewAction",
    "ReviewEvent",
    "ReviewStatus",
    "SuccessionCaseRecord",
    "User",
    "UserRole",
]
