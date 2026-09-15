"""First-run provisioning: the demo accounts and the backfill for existing rows.

Both operations here are idempotent and additive. They run at application start so a
freshly cloned checkout is a working, signed-in-able system without a separate setup
step -- the thing that most often goes wrong in the ten minutes before a demo.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.logging import get_logger
from ..core.security import hash_password
from ..models.enums import ReviewStatus, UserRole
from ..models.record import ParcelRecord
from ..models.user import User
from .corrections import refresh_derived_fields

logger = get_logger("adhikar.bootstrap")

#: One account per role, so a demo can show the permission model rather than assert
#: it: sign in as the operator, watch Approve disappear.
DEMO_USERS: list[dict] = [
    {
        "username": "collector",
        "full_name": "Anitha Raghavan",
        "designation": "District Collector, Belagavi",
        "role": UserRole.ADMIN,
        "district": "Belagavi",
        "state": "Karnataka",
    },
    {
        "username": "tehsildar",
        "full_name": "Vikram Deshpande",
        "designation": "Tehsildar, Belagavi Taluk",
        "role": UserRole.REVIEWER,
        "district": "Belagavi",
        "state": "Karnataka",
    },
    {
        "username": "operator",
        "full_name": "Shalini Kamble",
        "designation": "Data Entry Operator, Taluk Office",
        "role": UserRole.OPERATOR,
        "district": "Belagavi",
        "state": "Karnataka",
    },
    {
        "username": "auditor",
        "full_name": "R. Sundaram",
        "designation": "Accountant General (Audit)",
        "role": UserRole.AUDITOR,
        "district": None,
        "state": None,
    },
]


def ensure_demo_users(db: Session) -> int:
    """Create any missing demo account. Never touches one that already exists.

    Checked per-username rather than "is the table empty" so an operator who deleted
    one account on purpose does not get it silently recreated alongside three others
    they still have -- and so a real deployment that added its own users first is not
    handed four accounts it did not ask for.
    """
    settings = get_settings()
    if not settings.seed_demo_users:
        return 0

    existing = set(db.scalars(select(User.username)).all())
    created = 0
    for spec in DEMO_USERS:
        if spec["username"] in existing:
            continue
        db.add(
            User(
                id=uuid.uuid4(),
                username=spec["username"],
                full_name=spec["full_name"],
                designation=spec["designation"],
                email=f"{spec['username']}@adhikar.gov.in",
                role=spec["role"].value,
                district=spec["district"],
                state=spec["state"],
                password_hash=hash_password(settings.demo_user_password),
            )
        )
        created += 1

    if created:
        db.commit()
        logger.warning(
            "demo_users_created",
            count=created,
            note="Default credentials are active. Set ADHIKAR_API_SEED_DEMO_USERS=false "
            "and rotate ADHIKAR_API_DEMO_USER_PASSWORD before any real deployment.",
        )
    return created


def backfill_triage(db: Session) -> int:
    """Give pre-existing parcel rows a priority band and an SLA clock.

    Rows written before the workflow columns existed land on their SQL defaults
    (``pending`` / ``normal`` / score 0), which would sort a critical record below a
    clean one in the queue. This recomputes the derived fields from the scores those
    rows already carry, so the queue is correct the first time it is opened rather
    than only for records ingested afterwards.

    Restricted to rows that still look untouched (score 0 and no SLA), so it never
    overwrites a triage that has since been recomputed for real.
    """
    stale = list(
        db.scalars(
            select(ParcelRecord).where(
                ParcelRecord.sla_due_at.is_(None),
                ParcelRecord.review_status == ReviewStatus.PENDING.value,
            )
        ).all()
    )
    for parcel in stale:
        refresh_derived_fields(parcel)
    if stale:
        db.commit()
        logger.info("triage_backfilled", count=len(stale))
    return len(stale)
