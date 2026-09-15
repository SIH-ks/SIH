"""Parcel query, review-workflow and audit endpoints.

This is what the reviewer console reads from and writes to. Three ideas shape it:

* **Read paths are paged and total-counted.** A land-records console that shows
  "50 records" over a database of fifty thousand is lying to the officer using it.
* **Write paths are role-gated and audited.** Every mutation goes through
  :func:`_record_event`, so there is no way to change a record without leaving a row
  behind saying who did it, from where, and what the value was before.
* **Nothing derived is stored twice.** Triage reasons, SLA state and issue counts are
  recomputed by :mod:`app.services.corrections` after any change rather than patched
  at each call site.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ....core.logging import get_logger
from ....db.base import get_db
from ....models.enums import (
    ALLOWED_TRANSITIONS,
    Priority,
    ReviewAction,
    ReviewStatus,
    UserRole,
)
from ....models.record import Document, ParcelRecord, ReviewEvent
from ....schemas.record import (
    AssignRequest,
    AuditEntry,
    BulkResult,
    BulkStatusRequest,
    CorrectionResponse,
    DocumentSummary,
    Page,
    ParcelDetail,
    ParcelSummary,
    ReviewCorrectionRequest,
    ReviewEventResponse,
    StatusChangeRequest,
)
from ....services.corrections import (
    CorrectionError,
    apply_correction,
    refresh_derived_fields,
    revalidate,
)
from ....services.triage import assess_priority
from ...deps import (
    CurrentUser,
    client_ip,
    current_user,
    require_admin,
    require_operator,
    require_reviewer,
)

router = APIRouter(prefix="/parcels", tags=["parcels"])
logger = get_logger("adhikar.parcels")

SortField = Literal["priority", "updated_at", "created_at", "mismatch", "confidence", "village", "area"]

_SORT_COLUMNS = {
    "priority": ParcelRecord.priority_score,
    "updated_at": ParcelRecord.updated_at,
    "created_at": ParcelRecord.created_at,
    "mismatch": ParcelRecord.mismatch_score,
    "confidence": ParcelRecord.confidence_score,
    "village": ParcelRecord.village,
    "area": ParcelRecord.total_area_sq_metre,
}

_OPEN_STATES = [ReviewStatus.PENDING.value, ReviewStatus.IN_REVIEW.value, ReviewStatus.ESCALATED.value]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_event(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    action: ReviewAction,
    actor: CurrentUser,
    request: Request,
    field_path: str = "$",
    previous: Any = None,
    new: Any = None,
    note: str | None = None,
) -> ReviewEvent:
    """Append one audit row. The single write path for the audit trail.

    Values are wrapped in ``{"value": ...}`` rather than stored bare so the column can
    hold a scalar, an object or null without the reader having to guess which -- and
    so a future event type can add sibling keys without a migration.
    """
    event = ReviewEvent(
        id=uuid.uuid4(),
        parcel_id=parcel_id,
        field_path=field_path,
        previous_value={"value": previous},
        new_value={"value": new},
        action=action.value,
        reviewer=actor.username,
        reviewer_role=actor.role.value,
        note=note,
        source_ip=client_ip(request),
    )
    db.add(event)
    return event


def _get_parcel(db: Session, parcel_id: uuid.UUID) -> ParcelRecord:
    parcel = db.get(ParcelRecord, parcel_id)
    if parcel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="parcel not found")
    return parcel


def _detail(parcel: ParcelRecord, *, document: Document | None = None) -> ParcelDetail:
    """Project one row into the detail DTO, computing the triage explanation fresh."""
    assessment = assess_priority(
        mismatch_score=parcel.mismatch_score,
        confidence_score=parcel.confidence_score,
        validation_highest_severity=parcel.validation_highest_severity,
        validation_issue_count=parcel.validation_issue_count,
        recommended_action=parcel.recommended_action,
    )
    detail = ParcelDetail.model_validate(parcel)
    detail.triage_reasons = assessment.reasons
    if document is not None:
        detail.document = DocumentSummary.model_validate(document)
    return detail


def _apply_filters(stmt, *, filters: dict[str, Any]):
    """Translate the query surface into WHERE clauses.

    Extracted from the endpoint so the list, the GeoJSON export and the CSV export
    all filter identically -- an export that quietly covers a different set of records
    than the table it was launched from is the kind of discrepancy that discredits a
    whole report.
    """
    if q := filters.get("q"):
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ParcelRecord.village.ilike(needle),
                ParcelRecord.district.ilike(needle),
                ParcelRecord.khata_number.ilike(needle),
                ParcelRecord.survey_number.ilike(needle),
                ParcelRecord.parcel_key.ilike(needle),
                ParcelRecord.state.ilike(needle),
            )
        )
    for column, key in (
        (ParcelRecord.state, "state"),
        (ParcelRecord.district, "district"),
        (ParcelRecord.village, "village"),
        (ParcelRecord.review_status, "review_status"),
        (ParcelRecord.priority, "priority"),
        (ParcelRecord.assigned_to, "assigned_to"),
        (ParcelRecord.validation_highest_severity, "severity"),
        (ParcelRecord.recommended_action, "recommended_action"),
    ):
        value = filters.get(key)
        if value is not None:
            stmt = stmt.where(column == (value.value if hasattr(value, "value") else value))

    if (requires_review := filters.get("requires_review")) is not None:
        stmt = stmt.where(ParcelRecord.requires_human_review == requires_review)
    if (min_mismatch := filters.get("min_mismatch")) is not None:
        stmt = stmt.where(ParcelRecord.mismatch_score >= min_mismatch)
    if (max_confidence := filters.get("max_confidence")) is not None:
        stmt = stmt.where(ParcelRecord.confidence_score <= max_confidence)
    if filters.get("unassigned"):
        stmt = stmt.where(ParcelRecord.assigned_to.is_(None))
    if filters.get("overdue"):
        stmt = stmt.where(
            ParcelRecord.sla_due_at.isnot(None),
            ParcelRecord.sla_due_at < datetime.now(UTC),
            ParcelRecord.review_status.in_(_OPEN_STATES),
        )
    if filters.get("open_only"):
        stmt = stmt.where(ParcelRecord.review_status.in_(_OPEN_STATES))
    if filters.get("has_geometry"):
        stmt = stmt.where(ParcelRecord.geometry.isnot(None))
    return stmt


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("", response_model=Page[ParcelSummary])
def list_parcels(
    response: Response,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    q: str | None = Query(None, description="Free-text across village, district, khata, survey no., parcel key."),
    state: str | None = None,
    district: str | None = None,
    village: str | None = None,
    review_status: ReviewStatus | None = None,
    priority: Priority | None = None,
    severity: str | None = None,
    recommended_action: str | None = None,
    assigned_to: str | None = None,
    unassigned: bool = False,
    overdue: bool = False,
    open_only: bool = False,
    requires_review: bool | None = None,
    min_mismatch: float | None = Query(None, ge=0, le=100),
    max_confidence: float | None = Query(None, ge=0, le=1),
    sort: SortField = "updated_at",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[ParcelSummary]:
    """Paged, filtered, sorted parcel list -- the reviewer console's grid.

    ``min_mismatch`` is the discrepancy-engine score (0-100): filtering on it is how a
    Tehsildar pulls up "everything that disagrees with the map by more than X".
    ``max_confidence`` is its extraction-side counterpart -- "show me what the model
    itself was unsure about" -- and the two together are the standard triage sweep.
    """
    filters = locals()
    stmt = _apply_filters(select(ParcelRecord), filters=filters)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    column = _SORT_COLUMNS[sort]
    ordering = column.desc() if order == "desc" else column.asc()
    # Secondary key on the primary key: without it, rows with equal sort values can
    # come back in a different order per page and a record silently appears twice
    # while another is never shown at all.
    rows = db.scalars(stmt.order_by(ordering, ParcelRecord.id).limit(limit).offset(offset)).all()

    response.headers["X-Total-Count"] = str(total)
    return Page[ParcelSummary](
        items=[ParcelSummary.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/queue", response_model=Page[ParcelSummary])
def review_queue(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
    scope: Literal["mine", "unassigned", "district", "all"] = "all",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ParcelSummary]:
    """The prioritised worklist: open records, worst first.

    ``scope`` is what makes this a *work* list rather than another table. ``mine`` is
    what an officer opens at the start of a shift; ``unassigned`` is the shared pool
    they pull the next record from; ``district`` is their jurisdiction's whole
    backlog, defaulting to the district on their own account so the common case needs
    no filter at all.
    """
    stmt = select(ParcelRecord).where(ParcelRecord.review_status.in_(_OPEN_STATES))

    if scope == "mine":
        stmt = stmt.where(ParcelRecord.assigned_to == user.username)
    elif scope == "unassigned":
        stmt = stmt.where(ParcelRecord.assigned_to.is_(None))
    elif scope == "district" and user.district:
        stmt = stmt.where(ParcelRecord.district == user.district)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(ParcelRecord.priority_score.desc(), ParcelRecord.sla_due_at.asc(), ParcelRecord.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[ParcelSummary](
        items=[ParcelSummary.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/facets", response_model=dict)
def facets(db: Session = Depends(get_db), _: CurrentUser = Depends(current_user)) -> dict:
    """Distinct jurisdiction values, for the console's filter dropdowns.

    Returned as a nested state -> district -> village tree rather than three flat
    lists, so choosing "Karnataka" can narrow the district list without a second
    request. Small enough to send whole at district scale; a national deployment
    would page this by parent instead.
    """
    rows = db.execute(
        select(ParcelRecord.state, ParcelRecord.district, ParcelRecord.village, func.count(ParcelRecord.id))
        .group_by(ParcelRecord.state, ParcelRecord.district, ParcelRecord.village)
        .order_by(ParcelRecord.state, ParcelRecord.district, ParcelRecord.village)
    ).all()

    tree: dict[str, dict[str, dict[str, int]]] = {}
    for state, district, village, count in rows:
        districts = tree.setdefault(state or "Unknown", {})
        villages = districts.setdefault(district or "Unknown", {})
        villages[village or "Unknown"] = int(count)

    return {
        "tree": tree,
        "states": sorted(tree),
        "districts": sorted({d for ds in tree.values() for d in ds}),
        "review_statuses": [{"value": s.value, "label": s.label} for s in ReviewStatus],
        "priorities": [p.value for p in sorted(Priority, key=lambda p: -p.rank)],
    }


@router.get("/geojson", response_model=dict)
def parcels_geojson(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    state: str | None = None,
    district: str | None = None,
    review_status: ReviewStatus | None = None,
    limit: int = Query(2000, ge=1, le=20000),
) -> dict:
    """Every matched cadastral polygon as one RFC 7946 ``FeatureCollection``.

    This is what turns the console from a list of records into a *map of a district*:
    a supervisor sees where the disagreements cluster, which is information no
    per-record view can convey. Records with no matched geometry are omitted rather
    than emitted with a null geometry -- a GeoJSON feature without coordinates is
    valid but silently invisible, and an omission the caller can count is better than
    a feature they cannot see.
    """
    stmt = _apply_filters(
        select(ParcelRecord).where(ParcelRecord.geometry.isnot(None)),
        filters={"state": state, "district": district, "review_status": review_status},
    )
    rows = db.scalars(stmt.limit(limit)).all()

    total_matching = db.scalar(
        select(func.count()).select_from(
            _apply_filters(
                select(ParcelRecord.id),
                filters={"state": state, "district": district, "review_status": review_status},
            ).subquery()
        )
    ) or 0

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": str(r.id),
                "geometry": r.geometry,
                "properties": {
                    "parcel_id": str(r.id),
                    "parcel_key": r.parcel_key,
                    "village": r.village,
                    "district": r.district,
                    "state": r.state,
                    "khata_number": r.khata_number,
                    "survey_number": r.survey_number,
                    "mismatch_score": r.mismatch_score,
                    "confidence_score": r.confidence_score,
                    "review_status": r.review_status,
                    "priority": r.priority,
                    "severity": r.validation_highest_severity,
                    "issue_count": r.validation_issue_count,
                    "area_sq_metre": float(r.total_area_sq_metre) if r.total_area_sq_metre is not None else None,
                },
            }
            for r in rows
        ],
        "properties": {
            "returned": len(rows),
            "total_matching_filter": total_matching,
            "without_geometry": max(total_matching - len(rows), 0),
        },
    }


# Declared before the `/{parcel_id}` routes on purpose: Starlette matches paths in
# registration order, so with these below it a POST to /parcels/bulk/status would be
# routed to /parcels/{parcel_id}/status with parcel_id="bulk" and fail as a malformed
# UUID rather than reaching this handler at all.
@router.post("/bulk/status", response_model=BulkResult)
def bulk_status(
    payload: BulkStatusRequest,
    request: Request,
    actor: CurrentUser = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> BulkResult:
    """Apply one decision to many records -- the "approve all clean records" motion.

    Records whose current state does not permit the transition are reported in
    ``skipped`` with the reason, not silently dropped. The whole batch commits once,
    so a failure part-way leaves no half-applied decision behind.
    """
    updated: list[uuid.UUID] = []
    skipped: list[dict] = []

    for parcel_id in payload.parcel_ids:
        parcel = db.get(ParcelRecord, parcel_id)
        if parcel is None:
            skipped.append({"parcel_id": str(parcel_id), "reason": "not found"})
            continue
        try:
            _transition(
                db, parcel, payload.status, actor=actor, request=request, note=payload.note, commit=False
            )
            updated.append(parcel_id)
        except HTTPException as exc:
            skipped.append({"parcel_id": str(parcel_id), "reason": str(exc.detail)})

    db.commit()
    logger.info("bulk_status", status=payload.status.value, updated=len(updated), skipped=len(skipped))
    return BulkResult(updated=updated, skipped=skipped, total_requested=len(payload.parcel_ids))


@router.get("/{parcel_id}", response_model=ParcelDetail)
def get_parcel(
    parcel_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(current_user)
) -> ParcelDetail:
    parcel = db.scalar(
        select(ParcelRecord).options(selectinload(ParcelRecord.document)).where(ParcelRecord.id == parcel_id)
    )
    if parcel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="parcel not found")
    return _detail(parcel, document=parcel.document)


@router.get("/{parcel_id}/events", response_model=list[ReviewEventResponse])
def parcel_events(
    parcel_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(current_user)
) -> list[ReviewEvent]:
    """This record's full audit trail, oldest first.

    Oldest-first because it renders as a timeline the reviewer reads downward, and a
    provenance chain read backwards is much harder to follow than a list of
    notifications is.
    """
    _get_parcel(db, parcel_id)
    return list(
        db.scalars(
            select(ReviewEvent).where(ReviewEvent.parcel_id == parcel_id).order_by(ReviewEvent.created_at.asc())
        ).all()
    )


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


@router.post("/{parcel_id}/review", response_model=CorrectionResponse, status_code=status.HTTP_201_CREATED)
def submit_correction(
    parcel_id: uuid.UUID,
    correction: ReviewCorrectionRequest,
    request: Request,
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
) -> CorrectionResponse:
    """Record -- and, by default, apply -- a human correction to one field.

    Applying it re-runs the entire rule engine against the corrected record (see
    :mod:`app.services.corrections` for why that is not optional), so the response
    carries the findings count before and after. A reviewer who fixes a mis-read
    sub-division area and watches ``AREA_SUM_MISMATCH`` clear has been *shown* that
    their correction was right, which is worth considerably more than a toast saying
    "saved".
    """
    parcel = _get_parcel(db, parcel_id)

    if not correction.apply:
        event = _record_event(
            db,
            parcel_id=parcel_id,
            action=ReviewAction.FLAGGED,
            actor=actor,
            request=request,
            field_path=correction.field_path,
            new=correction.new_value,
            note=correction.note,
        )
        db.commit()
        db.refresh(event)
        db.refresh(parcel)
        return CorrectionResponse(
            event=ReviewEventResponse.model_validate(event),
            applied=False,
            revalidated=False,
            issues_before=parcel.validation_issue_count,
            issues_after=parcel.validation_issue_count,
            highest_severity_after=parcel.validation_highest_severity,
            parcel=_detail(parcel),
        )

    try:
        result = apply_correction(parcel, field_path=correction.field_path, new_value=correction.new_value)
    except CorrectionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    event = _record_event(
        db,
        parcel_id=parcel_id,
        action=ReviewAction.CORRECTED,
        actor=actor,
        request=request,
        field_path=correction.field_path,
        previous=result.previous_value,
        new=result.new_value,
        note=correction.note,
    )
    db.commit()
    db.refresh(event)
    db.refresh(parcel)

    logger.info(
        "correction_applied",
        parcel_id=str(parcel_id),
        field=correction.field_path,
        issues_before=result.issues_before,
        issues_after=result.issues_after,
    )
    return CorrectionResponse(
        event=ReviewEventResponse.model_validate(event),
        applied=True,
        revalidated=result.revalidated,
        revalidation_note=result.revalidation_note,
        issues_before=result.issues_before,
        issues_after=result.issues_after,
        highest_severity_after=result.highest_severity_after,
        parcel=_detail(parcel),
    )


@router.post("/{parcel_id}/status", response_model=ParcelDetail)
def change_status(
    parcel_id: uuid.UUID,
    payload: StatusChangeRequest,
    request: Request,
    actor: CurrentUser = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> ParcelDetail:
    """Move a record through the adjudication workflow.

    Reviewer role or above: an operator may key corrections all day, but the decision
    to put a record into the register is a different act by a different person. That
    separation is the reason this endpoint and ``/review`` have different guards.
    """
    parcel = _get_parcel(db, parcel_id)
    return _transition(db, parcel, payload.status, actor=actor, request=request, note=payload.note)


def _transition(
    db: Session,
    parcel: ParcelRecord,
    target: ReviewStatus,
    *,
    actor: CurrentUser,
    request: Request,
    note: str | None,
    commit: bool = True,
) -> ParcelDetail:
    current = ReviewStatus(parcel.review_status)
    if target == current:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"record is already {current.label.lower()}")
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"cannot move a record from {current.label.lower()} to {target.label.lower()}. "
                f"Re-open it into review first."
            ),
        )
    if current.is_terminal and not actor.role.outranks_or_equals(UserRole.REVIEWER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="re-opening a decided record requires a reviewer")

    parcel.review_status = target.value
    if target.is_terminal:
        parcel.decided_by = actor.username
        parcel.decided_at = datetime.now(UTC)
        parcel.decision_note = note
    elif target is ReviewStatus.IN_REVIEW:
        # Claiming a record assigns it: a record "in review" by nobody in particular
        # is the state that lets two officers duplicate each other's work.
        parcel.assigned_to = parcel.assigned_to or actor.username
        parcel.assigned_at = parcel.assigned_at or datetime.now(UTC)
        parcel.decided_by = None
        parcel.decided_at = None

    _record_event(
        db,
        parcel_id=parcel.id,
        action=ReviewAction.STATUS_CHANGED,
        actor=actor,
        request=request,
        previous=current.value,
        new=target.value,
        note=note,
    )
    if commit:
        db.commit()
        db.refresh(parcel)
    logger.info("status_changed", parcel_id=str(parcel.id), **{"from": current.value, "to": target.value})
    return _detail(parcel)


@router.post("/{parcel_id}/assign", response_model=ParcelDetail)
def assign(
    parcel_id: uuid.UUID,
    payload: AssignRequest,
    request: Request,
    actor: CurrentUser = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> ParcelDetail:
    """Claim a record, hand it to a colleague, or release it back to the pool."""
    parcel = _get_parcel(db, parcel_id)
    previous = parcel.assigned_to

    parcel.assigned_to = payload.assignee
    parcel.assigned_at = datetime.now(UTC) if payload.assignee else None
    if payload.assignee and parcel.review_status == ReviewStatus.PENDING.value:
        parcel.review_status = ReviewStatus.IN_REVIEW.value

    _record_event(
        db,
        parcel_id=parcel_id,
        action=ReviewAction.ASSIGNED,
        actor=actor,
        request=request,
        previous=previous,
        new=payload.assignee,
        note=payload.note,
    )
    db.commit()
    db.refresh(parcel)
    return _detail(parcel)


@router.post("/{parcel_id}/revalidate", response_model=ParcelDetail)
def revalidate_parcel(
    parcel_id: uuid.UUID,
    request: Request,
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ParcelDetail:
    """Re-run the rule engine against the stored artifact as it now stands.

    Needed whenever the *policy* changes rather than the record: a district that
    loosens its area tolerance from 0.5% to 1% wants yesterday's flagged records
    re-judged under today's rules, without re-running OCR over the scans.
    """
    parcel = _get_parcel(db, parcel_id)
    before = parcel.validation_issue_count
    try:
        artifact = dict(parcel.artifact_json)
        artifact["validation_issues"] = revalidate(artifact)
        parcel.artifact_json = artifact
    except CorrectionError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"this record cannot be re-validated: {exc}",
        ) from exc

    refresh_derived_fields(parcel)
    _record_event(
        db,
        parcel_id=parcel_id,
        action=ReviewAction.REVALIDATED,
        actor=actor,
        request=request,
        previous=before,
        new=parcel.validation_issue_count,
        note=f"rule engine re-run: {before} → {parcel.validation_issue_count} findings",
    )
    db.commit()
    db.refresh(parcel)
    return _detail(parcel)


@router.delete("/{parcel_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_parcel(
    parcel_id: uuid.UUID, _: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> None:
    """Remove a parcel and its audit trail. Administrator only.

    Exists for the one legitimate case -- a test upload or a scan of the wrong
    document -- and is deliberately the only destructive endpoint in the API. Note
    that this takes the audit trail with it (``cascade="all, delete-orphan"``), which
    is why it is gated at the highest role: a deployment with retention obligations
    should disable this route rather than rely on nobody calling it.
    """
    parcel = _get_parcel(db, parcel_id)
    db.delete(parcel)
    db.commit()


# ---------------------------------------------------------------------------
# Cross-parcel audit
# ---------------------------------------------------------------------------

audit_router = APIRouter(prefix="/audit", tags=["audit"])


@audit_router.get("/events", response_model=Page[AuditEntry])
def audit_events(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    reviewer: str | None = None,
    action: str | None = None,
    district: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[AuditEntry]:
    """The department-wide audit trail, newest first.

    Every authenticated role can read this, including ``auditor`` -- which is the
    entire reason that role exists. An audit trail only the people being audited can
    read is not one.
    """
    stmt = (
        select(ReviewEvent, ParcelRecord.parcel_key, ParcelRecord.village, ParcelRecord.district)
        .join(ParcelRecord, ParcelRecord.id == ReviewEvent.parcel_id)
    )
    if reviewer:
        stmt = stmt.where(ReviewEvent.reviewer == reviewer)
    if action:
        stmt = stmt.where(ReviewEvent.action == action)
    if district:
        stmt = stmt.where(ParcelRecord.district == district)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(ReviewEvent.created_at.desc(), ReviewEvent.id).limit(limit).offset(offset)
    ).all()

    items = []
    for event, parcel_key, village, district_name in rows:
        entry = AuditEntry.model_validate(event)
        entry.parcel_key = parcel_key
        entry.village = village
        entry.district = district_name
        items.append(entry)

    return Page[AuditEntry](items=items, total=total, limit=limit, offset=offset)
