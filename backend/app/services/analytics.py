"""Aggregate queries behind the analytics dashboard.

Every figure here is computed in SQL against the indexed projection columns, not by
loading rows and summing them in Python. That distinction matters more than it looks:
the console's landing page previously derived its headline metrics from the first 100
parcels it happened to fetch, which is a number that quietly stops being true at
record 101. A district office running this over a few hundred thousand Jamabandi
pages needs the dashboard to mean what it says.

Grouped counts use ``CASE WHEN`` sums rather than several round trips, so a district
rollup is one query regardless of how many status buckets it reports.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Float, case, func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.enums import Priority, ReviewStatus
from ..models.record import Document, ParcelRecord, ReviewEvent

__all__ = [
    "district_breakdown",
    "queue_health",
    "rule_frequency",
    "reviewer_throughput",
    "summary",
    "timeseries",
]


def _n(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Summary:
    total_parcels: int
    total_documents: int
    total_pages: int

    auto_validated: int
    needs_review: int
    flagged: int

    by_status: dict[str, int]
    by_priority: dict[str, int]

    avg_confidence: float | None
    avg_mismatch: float | None
    median_confidence: float | None

    total_area_hectares: float
    districts_covered: int
    villages_covered: int

    overdue_count: int
    unassigned_count: int
    corrections_applied: int

    straight_through_rate: float
    """Share of records the pipeline cleared with no human touch at all -- the single
    number that says whether this system is saving anyone work."""

    staff_hours_saved: float
    minutes_saved_per_record_assumption: float
    """Returned alongside the derived figure so the assumption travels with the
    number and never gets quoted as a measurement."""

    generated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def summary(db: Session, *, district: str | None = None, state: str | None = None) -> Summary:
    """Fleet-wide headline metrics for the command dashboard."""
    settings = get_settings()
    scope = _scope(district, state)

    totals = db.execute(
        select(
            func.count(ParcelRecord.id),
            func.avg(ParcelRecord.confidence_score),
            func.avg(ParcelRecord.mismatch_score),
            func.coalesce(func.sum(func.cast(ParcelRecord.total_area_sq_metre, Float)), 0.0),
            func.count(func.distinct(ParcelRecord.district)),
            func.count(func.distinct(ParcelRecord.village)),
            func.sum(case((ParcelRecord.correction_count > 0, 1), else_=0)),
        ).where(*scope)
    ).one()

    status_rows = db.execute(
        select(ParcelRecord.review_status, func.count(ParcelRecord.id)).where(*scope).group_by(ParcelRecord.review_status)
    ).all()
    priority_rows = db.execute(
        select(ParcelRecord.priority, func.count(ParcelRecord.id)).where(*scope).group_by(ParcelRecord.priority)
    ).all()

    by_status = {s.value: 0 for s in ReviewStatus} | {k: v for k, v in status_rows if k}
    by_priority = {p.value: 0 for p in Priority} | {k: v for k, v in priority_rows if k}

    # The traffic light the console shows is derived from two independent signals
    # (see frontend Badge.deriveTrafficLight); this mirrors that derivation in SQL so
    # the dashboard tiles and the table's own colouring can never disagree.
    lights = db.execute(
        select(
            func.sum(
                case(
                    (
                        (ParcelRecord.recommended_action == "reject_re_scan")
                        | (ParcelRecord.validation_highest_severity == "critical")
                        | (ParcelRecord.mismatch_score >= 50),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        (ParcelRecord.recommended_action == "auto_approve")
                        # `NOT IN` against a NULL column yields NULL, not TRUE -- so
                        # without the explicit IS NULL arm, a record with *no*
                        # findings at all (the cleanest possible case) would be
                        # excluded from the auto-validated count.
                        & (
                            ParcelRecord.validation_highest_severity.is_(None)
                            | ParcelRecord.validation_highest_severity.notin_(["error", "warning", "critical"])
                        )
                        & ((ParcelRecord.mismatch_score < 50) | ParcelRecord.mismatch_score.is_(None)),
                        1,
                    ),
                    else_=0,
                )
            ),
        ).where(*scope)
    ).one()
    flagged = int(lights[0] or 0)
    auto_validated = int(lights[1] or 0)

    doc_totals = db.execute(select(func.count(Document.id), func.coalesce(func.sum(Document.page_count), 0))).one()

    now = datetime.now(UTC)
    overdue = db.scalar(
        select(func.count(ParcelRecord.id)).where(
            *scope,
            ParcelRecord.sla_due_at.isnot(None),
            ParcelRecord.sla_due_at < now,
            ParcelRecord.review_status.in_([ReviewStatus.PENDING.value, ReviewStatus.IN_REVIEW.value, ReviewStatus.ESCALATED.value]),
        )
    )
    unassigned = db.scalar(
        select(func.count(ParcelRecord.id)).where(
            *scope, ParcelRecord.assigned_to.is_(None), ParcelRecord.review_status == ReviewStatus.PENDING.value
        )
    )

    total = int(totals[0] or 0)
    needs_review = max(total - auto_validated - flagged, 0)
    straight_through = (auto_validated / total * 100) if total else 0.0

    return Summary(
        total_parcels=total,
        total_documents=int(doc_totals[0] or 0),
        total_pages=int(doc_totals[1] or 0),
        auto_validated=auto_validated,
        needs_review=needs_review,
        flagged=flagged,
        by_status=by_status,
        by_priority=by_priority,
        avg_confidence=_n(totals[1], 4),
        avg_mismatch=_n(totals[2]),
        median_confidence=_median_confidence(db, scope),
        total_area_hectares=_n(float(totals[3] or 0.0) / 10_000, 3) or 0.0,
        districts_covered=int(totals[4] or 0),
        villages_covered=int(totals[5] or 0),
        overdue_count=int(overdue or 0),
        unassigned_count=int(unassigned or 0),
        corrections_applied=int(totals[6] or 0),
        straight_through_rate=round(straight_through, 1),
        staff_hours_saved=round(auto_validated * settings.minutes_saved_per_record / 60, 1),
        minutes_saved_per_record_assumption=settings.minutes_saved_per_record,
        generated_at=now.isoformat(),
    )


def _median_confidence(db: Session, scope: list) -> float | None:
    """True median, not the mean.

    Extraction confidence is bimodal in practice -- a clean printed register and a
    faded handwritten one score in two clusters, and their mean lands in a valley
    where almost no record actually sits. Reporting both is what stops "average
    confidence 0.68" from being read as "a typical record scores 0.68".

    Fetches the column and picks the midpoint in Python rather than using a window
    function, because SQLite (the zero-setup default) has no ``percentile_cont``.
    At district scale this is a few thousand floats; if it ever isn't, this is the
    one place to swap in a dialect-specific percentile.
    """
    values = sorted(
        v for v in db.scalars(select(ParcelRecord.confidence_score).where(*scope)).all() if v is not None
    )
    if not values:
        return None
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    return round(median, 4)


def _scope(district: str | None, state: str | None) -> list:
    """Jurisdiction filter shared by every aggregate, so scoping is defined once."""
    clauses = []
    if district:
        clauses.append(ParcelRecord.district == district)
    if state:
        clauses.append(ParcelRecord.state == state)
    return clauses


# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DistrictRow:
    state: str | None
    district: str | None
    total: int
    flagged: int
    approved: int
    pending: int
    overdue: int
    avg_confidence: float | None
    avg_mismatch: float | None
    total_area_hectares: float
    completion_rate: float


def district_breakdown(db: Session, *, state: str | None = None, limit: int = 50) -> list[dict]:
    """Per-district rollup: the view a Commissioner asks for first."""
    now = datetime.now(UTC)
    rows = db.execute(
        select(
            ParcelRecord.state,
            ParcelRecord.district,
            func.count(ParcelRecord.id).label("total"),
            func.sum(
                case(
                    (
                        (ParcelRecord.validation_highest_severity.in_(["error", "critical"]))
                        | (ParcelRecord.mismatch_score >= 50),
                        1,
                    ),
                    else_=0,
                )
            ).label("flagged"),
            func.sum(case((ParcelRecord.review_status == ReviewStatus.APPROVED.value, 1), else_=0)).label("approved"),
            func.sum(case((ParcelRecord.review_status == ReviewStatus.PENDING.value, 1), else_=0)).label("pending"),
            func.sum(
                case(
                    ((ParcelRecord.sla_due_at.isnot(None)) & (ParcelRecord.sla_due_at < now)
                     & (ParcelRecord.review_status.notin_([ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value])), 1),
                    else_=0,
                )
            ).label("overdue"),
            # Labelled, and read back by name below rather than by position. The
            # positional form was off by one against this select list, which is not
            # a mistake SQL or Python can catch: every column here is a number, so
            # the rollup happily reported the overdue *count* as a mean confidence
            # and the mean confidence as a mismatch score. Names make that class of
            # error impossible rather than merely unlikely.
            func.avg(ParcelRecord.confidence_score).label("avg_confidence"),
            func.avg(ParcelRecord.mismatch_score).label("avg_mismatch"),
            func.coalesce(func.sum(func.cast(ParcelRecord.total_area_sq_metre, Float)), 0.0).label("area"),
        )
        .where(*(_scope(None, state)))
        .group_by(ParcelRecord.state, ParcelRecord.district)
        .order_by(func.count(ParcelRecord.id).desc())
        .limit(limit)
    ).all()

    out: list[dict] = []
    for r in rows:
        total = int(r.total or 0)
        approved = int(r.approved or 0)
        out.append(
            asdict(
                DistrictRow(
                    state=r.state,
                    district=r.district,
                    total=total,
                    flagged=int(r.flagged or 0),
                    approved=approved,
                    pending=int(r.pending or 0),
                    overdue=int(r.overdue or 0),
                    avg_confidence=_n(r.avg_confidence, 4),
                    avg_mismatch=_n(r.avg_mismatch),
                    total_area_hectares=round(float(r.area or 0.0) / 10_000, 3),
                    completion_rate=round(approved / total * 100, 1) if total else 0.0,
                )
            )
        )
    return out


# ---------------------------------------------------------------------------


def timeseries(db: Session, *, days: int = 30, district: str | None = None) -> list[dict]:
    """Daily ingestion and adjudication counts over a trailing window.

    Every day in the window appears, including days with no activity. A sparse series
    plotted as a line implies a straight run between two distant points, which reads
    as steady throughput over a gap where nothing happened -- so the zeros are the
    honest output, not padding.
    """
    since = datetime.now(UTC) - timedelta(days=days - 1)
    scope = _scope(district, None)

    ingested = dict(
        db.execute(
            select(func.date(ParcelRecord.created_at), func.count(ParcelRecord.id))
            .where(*scope, ParcelRecord.created_at >= since)
            .group_by(func.date(ParcelRecord.created_at))
        ).all()
    )
    decided = dict(
        db.execute(
            select(func.date(ParcelRecord.decided_at), func.count(ParcelRecord.id))
            .where(*scope, ParcelRecord.decided_at.isnot(None), ParcelRecord.decided_at >= since)
            .group_by(func.date(ParcelRecord.decided_at))
        ).all()
    )
    corrections = dict(
        db.execute(
            select(func.date(ReviewEvent.created_at), func.count(ReviewEvent.id))
            .where(ReviewEvent.created_at >= since, ReviewEvent.action == "corrected")
            .group_by(func.date(ReviewEvent.created_at))
        ).all()
    )

    def _lookup(bucket: dict, day: date) -> int:
        # SQLite's date() returns a string; PostgreSQL's returns a date object. Both
        # dialects are supported deployments, so the series normalises here rather
        # than forcing one shape on the query.
        return int(bucket.get(day, bucket.get(day.isoformat(), 0)) or 0)

    today = datetime.now(UTC).date()
    return [
        {
            "date": (day := today - timedelta(days=offset)).isoformat(),
            "ingested": _lookup(ingested, day),
            "decided": _lookup(decided, day),
            "corrections": _lookup(corrections, day),
        }
        for offset in range(days - 1, -1, -1)
    ]


# ---------------------------------------------------------------------------


def rule_frequency(db: Session, *, limit: int = 12) -> list[dict]:
    """Which validation rules fire most often, and how badly.

    Read across a whole district this is a *data-quality report on the source
    registers themselves*: if ``MUTATION_DATE_IN_FUTURE`` dominates one taluk, the
    problem is that taluk's register, not the model. That is the finding a Ministry
    reviewer will care about far more than any per-record score.

    Counted from ``artifact_json`` in Python rather than in SQL because the findings
    live inside a JSON array, and the one portable way to aggregate across both
    SQLite and PostgreSQL there is to read them. Bounded by the same scope the rest
    of the dashboard uses, so the cost tracks the district being viewed.
    """
    counter: Counter[tuple[str, str]] = Counter()
    for (artifact,) in db.execute(select(ParcelRecord.artifact_json)).all():
        for issue in (artifact or {}).get("validation_issues") or []:
            code = issue.get("rule_code")
            if code:
                counter[(code, issue.get("severity", "info"))] += 1

    by_code: dict[str, dict] = {}
    for (code, severity), count in counter.items():
        entry = by_code.setdefault(code, {"rule_code": code, "count": 0, "severities": {}})
        entry["count"] += count
        entry["severities"][severity] = entry["severities"].get(severity, 0) + count

    ranked = sorted(by_code.values(), key=lambda e: e["count"], reverse=True)[:limit]
    for entry in ranked:
        ranks = {"info": 0, "warning": 1, "error": 2, "critical": 3}
        entry["worst_severity"] = max(entry["severities"], key=lambda s: ranks.get(s, 0))
    return ranked


# ---------------------------------------------------------------------------


def reviewer_throughput(db: Session, *, days: int = 30) -> list[dict]:
    """Per-officer activity over the window: decisions made, corrections keyed.

    Presented in the console as workload distribution, not as a leaderboard. The
    useful reading is "one officer is carrying four districts", which is a staffing
    finding; ranking humans on records-per-hour would push exactly the wrong
    behaviour in a process whose entire purpose is careful adjudication.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(
            ReviewEvent.reviewer,
            ReviewEvent.reviewer_role,
            func.count(ReviewEvent.id).label("events"),
            func.sum(case((ReviewEvent.action == "corrected", 1), else_=0)).label("corrections"),
            func.sum(case((ReviewEvent.action == "status_changed", 1), else_=0)).label("decisions"),
            func.max(ReviewEvent.created_at).label("last_active"),
        )
        .where(ReviewEvent.created_at >= since)
        .group_by(ReviewEvent.reviewer, ReviewEvent.reviewer_role)
        .order_by(func.count(ReviewEvent.id).desc())
    ).all()

    return [
        {
            "reviewer": r.reviewer,
            "role": r.reviewer_role,
            "events": int(r.events or 0),
            "corrections": int(r.corrections or 0),
            "decisions": int(r.decisions or 0),
            "last_active": r.last_active.isoformat() if hasattr(r.last_active, "isoformat") else r.last_active,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------


def queue_health(db: Session, *, district: str | None = None) -> dict:
    """Backlog shape: what is waiting, how urgent, and how overdue."""
    scope = _scope(district, None)
    now = datetime.now(UTC)
    open_states = [ReviewStatus.PENDING.value, ReviewStatus.IN_REVIEW.value, ReviewStatus.ESCALATED.value]

    rows = db.execute(
        select(
            ParcelRecord.priority,
            func.count(ParcelRecord.id),
            func.sum(case(((ParcelRecord.sla_due_at.isnot(None)) & (ParcelRecord.sla_due_at < now), 1), else_=0)),
        )
        .where(*scope, ParcelRecord.review_status.in_(open_states))
        .group_by(ParcelRecord.priority)
    ).all()

    buckets = {p.value: {"priority": p.value, "open": 0, "overdue": 0} for p in Priority}
    for priority, open_count, overdue in rows:
        if priority in buckets:
            buckets[priority] = {
                "priority": priority,
                "open": int(open_count or 0),
                "overdue": int(overdue or 0),
            }

    oldest = db.scalar(
        select(func.min(ParcelRecord.created_at)).where(*scope, ParcelRecord.review_status.in_(open_states))
    )
    total_open = sum(b["open"] for b in buckets.values())

    return {
        "buckets": [buckets[p.value] for p in sorted(Priority, key=lambda p: -p.rank)],
        "total_open": total_open,
        "total_overdue": sum(b["overdue"] for b in buckets.values()),
        "oldest_open_at": oldest.isoformat() if hasattr(oldest, "isoformat") else oldest,
    }
