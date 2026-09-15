"""Workflow vocabularies shared by the ORM, the API schemas, and the frontend.

These are the words a revenue office actually uses, not internal codes: a record is
*assigned*, *approved*, *escalated to the Tehsildar*, or *sent back for re-scan*.
Keeping them in one enum rather than as free-form strings on the model is what lets
the queue query, the audit trail, and the analytics rollups agree on what a status
means without a shared constants file per layer.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Priority", "ReviewAction", "ReviewStatus", "UserRole"]


class UserRole(StrEnum):
    """Who a signed-in user is, in revenue-department terms.

    Ordered least to most privileged; :meth:`outranks` is the single place that
    ordering is encoded, so a new role is added here and nowhere else.
    """

    AUDITOR = "auditor"
    """Read-only oversight -- Accountant General's office, RTI cell, internal audit.
    Sees every record and the full audit trail; can change nothing."""

    OPERATOR = "operator"
    """Data-entry operator at the taluk office. Uploads scans and keys corrections,
    but cannot approve a record into the register -- the separation of duties the
    whole workflow exists to enforce."""

    REVIEWER = "reviewer"
    """Revenue Inspector / Tehsildar. Adjudicates the queue: approves, rejects,
    escalates, and assigns work to operators."""

    ADMIN = "admin"
    """District Collectorate / system administrator. Everything a reviewer can do,
    plus user management and validation-policy configuration."""

    @property
    def rank(self) -> int:
        return {"auditor": 0, "operator": 1, "reviewer": 2, "admin": 3}[self.value]

    def outranks_or_equals(self, other: UserRole) -> bool:
        return self.rank >= other.rank

    @property
    def label(self) -> str:
        return {
            "auditor": "Auditor",
            "operator": "Data Entry Operator",
            "reviewer": "Revenue Inspector",
            "admin": "District Administrator",
        }[self.value]


class ReviewStatus(StrEnum):
    """Where a parcel sits in the adjudication workflow.

    ``PENDING -> IN_REVIEW -> {APPROVED, REJECTED, ESCALATED}``, with ``ESCALATED``
    able to return to ``IN_REVIEW`` once a senior officer picks it up. The terminal
    states are deliberately not final-final: a re-extraction of the same scan resets
    the parcel to ``PENDING``, because the thing that was approved no longer exists.
    """

    PENDING = "pending"
    """Extracted, not yet looked at by a human."""

    IN_REVIEW = "in_review"
    """Claimed by a named reviewer. Prevents two officers adjudicating the same
    record in parallel, which is the failure mode a shared queue always has."""

    APPROVED = "approved"
    """Adjudicated as fit to enter the register."""

    REJECTED = "rejected"
    """Unusable as extracted -- re-scan or manual entry required."""

    ESCALATED = "escalated"
    """Beyond the reviewer's authority (boundary dispute, suspected fraud, area
    contradiction the document itself cannot resolve). Waits for a senior officer."""

    @property
    def is_terminal(self) -> bool:
        return self in {ReviewStatus.APPROVED, ReviewStatus.REJECTED}

    @property
    def label(self) -> str:
        return {
            "pending": "Pending triage",
            "in_review": "In review",
            "approved": "Approved",
            "rejected": "Rejected",
            "escalated": "Escalated",
        }[self.value]


#: Which transitions the API will accept. Anything not listed is a 409, not a silent
#: no-op -- an audit trail that records impossible transitions is worse than useless.
ALLOWED_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    ReviewStatus.PENDING: {ReviewStatus.IN_REVIEW, ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.ESCALATED},
    ReviewStatus.IN_REVIEW: {ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.ESCALATED, ReviewStatus.PENDING},
    ReviewStatus.ESCALATED: {ReviewStatus.IN_REVIEW, ReviewStatus.APPROVED, ReviewStatus.REJECTED},
    # Re-opening a decided record is allowed but only back into review, never
    # straight to the opposite decision -- the reopen itself has to be auditable.
    ReviewStatus.APPROVED: {ReviewStatus.IN_REVIEW},
    ReviewStatus.REJECTED: {ReviewStatus.IN_REVIEW},
}


class Priority(StrEnum):
    """Triage band, derived (never hand-set) from the pipeline's own scores.

    See :func:`app.services.triage.assess_priority` for the derivation. Bands rather
    than a raw number because the SLA clock is negotiated per band with the district
    office, and because "critical" is an instruction a reviewer can act on where
    "87.4" is not.
    """

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"low": 0, "normal": 1, "high": 2, "critical": 3}[self.value]


class ReviewAction(StrEnum):
    """The verbs the audit trail records. One row per action, never an update."""

    CORRECTED = "corrected"
    """A field value was changed by a human."""

    ACCEPTED = "accepted"
    """A machine-extracted value was explicitly confirmed as correct."""

    FLAGGED = "flagged"
    """Marked as suspect without a corrected value to offer."""

    ASSIGNED = "assigned"
    STATUS_CHANGED = "status_changed"
    NOTE_ADDED = "note_added"
    REVALIDATED = "revalidated"
    """The rule engine was re-run against the parcel after a correction."""
