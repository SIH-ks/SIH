"""Ownership succession: submit a bundle, assess it, read the chain back.

Shaped like the rest of the API rather than as a parallel world: reads are paged and
total-counted, writes are role-gated at the same boundary (an operator files a case;
approving the *record* that results is still a reviewer's act on the parcel), and
every write against a parcel leaves a row in the existing audit trail rather than a
private one.

The endpoint worth calling out is ``POST /succession/validate``. It assesses a bundle
without filing it, which is what lets a clerk check a submission at the counter
before accepting it -- and it means the engine can be exercised end to end with no
database writes at all.

One thing this router will not do: conclude anything. Every response carries the
engine's disclaimer, the strongest outcome is ``review_required``, and there is no
endpoint that marks a succession as valid. Adjudication happens on the parcel,
through the workflow that already exists, by somebody with a name.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ....core.logging import get_logger
from ....db.base import get_db
from ....models.enums import ReviewAction
from ....models.record import ParcelRecord, ReviewEvent
from ....models.succession import OwnershipEventRecord, SuccessionCaseRecord
from ....schemas.record import Page
from ....schemas.succession import (
    OwnershipEventResponse,
    SuccessionCaseDetail,
    SuccessionCaseSummary,
    SuccessionRequest,
    SuccessionValidationResponse,
)
from ....services.succession import (
    SuccessionError,
    assemble_case,
    assess,
    next_case_reference,
    persist_case,
    report_payload,
    revalidate_case,
)
from ...deps import CurrentUser, client_ip, current_user, require_admin, require_operator

router = APIRouter(prefix="/succession", tags=["succession"])
logger = get_logger("adhikar.succession")

SortField = Literal["risk", "created_at", "updated_at", "village"]

_SORT_COLUMNS = {
    "risk": SuccessionCaseRecord.risk_score,
    "created_at": SuccessionCaseRecord.created_at,
    "updated_at": SuccessionCaseRecord.updated_at,
    "village": SuccessionCaseRecord.village,
}

#: Outcomes that still need somebody to act. `validated` is the only one that does not.
_OPEN_OUTCOMES = ["incomplete", "inconsistent", "review_required"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_case(db: Session, case_id: uuid.UUID) -> SuccessionCaseRecord:
    row = db.scalar(
        select(SuccessionCaseRecord)
        .options(selectinload(SuccessionCaseRecord.events))
        .where(SuccessionCaseRecord.id == case_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="succession case not found")
    return row


def _detail(row: SuccessionCaseRecord) -> SuccessionCaseDetail:
    detail = SuccessionCaseDetail.model_validate(
        {
            **{c.name: getattr(row, c.name) for c in row.__table__.columns},
            "report": row.report_json,
            "normalization_warnings": row.normalization_warnings or [],
            "document_ids": [str(d) for d in (row.document_ids or [])],
            "events": [OwnershipEventResponse.model_validate(e) for e in row.events],
        }
    )
    return detail


def _audit(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    actor: CurrentUser,
    request: Request,
    note: str,
    previous: Any = None,
    new: Any = None,
) -> None:
    """Record a succession action against the parcel's own audit trail.

    Deliberately the *existing* trail rather than a succession-private one. An
    officer asking "what has happened to this record" must get one answer; a second
    log that only the succession screen reads is how a record acquires a history
    nobody can see in full.
    """
    db.add(
        ReviewEvent(
            id=uuid.uuid4(),
            parcel_id=parcel_id,
            field_path="$.succession",
            previous_value={"value": previous},
            new_value={"value": new},
            action=ReviewAction.FLAGGED.value,
            reviewer=actor.username,
            reviewer_role=actor.role.value,
            note=note,
            source_ip=client_ip(request),
        )
    )


# ---------------------------------------------------------------------------
# Assess
# ---------------------------------------------------------------------------


@router.post("/validate", response_model=SuccessionValidationResponse)
def validate_bundle(
    payload: SuccessionRequest,
    request: Request,
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
) -> SuccessionValidationResponse:
    """Assess a bundle of succession documents, and file it unless asked not to.

    The one entry point for the feature. Documents may come from the register
    (``parcel_id`` / ``current_parcel_id``, reusing extractions the OCR + Vision-LLM
    pipeline already produced) or from the submission itself; both are normalised by
    the same deterministic code before any rule runs.

    Set ``persist=false`` to assess without filing -- checking a submission at the
    counter, or exercising the engine without writing anything.

    The response is decision *support*. Its strongest outcome is ``review_required``,
    it carries the disclaimer in the payload, and nothing here approves a record:
    that remains an act on the parcel, by a reviewer, through the existing workflow.
    """
    case_id = payload.case_reference or "case"
    try:
        assembly = assemble_case(
            db,
            case_id=case_id,
            documents=payload.documents,
            parcel_id=payload.parcel_id,
            current_parcel_id=payload.current_parcel_id,
            parcel_key=payload.parcel_key,
            notes=payload.notes,
            submitted_by=actor.username,
        )
    except SuccessionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    report = assess(assembly.case)

    if not payload.persist:
        logger.info(
            "succession_assessed",
            outcome=report.outcome.value,
            risk=report.risk_score,
            persisted=False,
        )
        return SuccessionValidationResponse(
            report=report_payload(report),
            normalization_warnings=assembly.warnings,
            persisted=False,
        )

    reference = payload.case_reference or next_case_reference(
        db, district=assembly.parcel.district if assembly.parcel else None
    )
    row = persist_case(
        db,
        assembly=assembly,
        report=report,
        case_reference=reference,
        created_by=actor.username,
        notes=payload.notes,
    )
    if row.parcel_id is not None:
        _audit(
            db,
            parcel_id=row.parcel_id,
            actor=actor,
            request=request,
            note=(
                f"Succession case {reference} filed: {report.outcome.value}, "
                f"{report.risk_level.value} risk ({report.risk_score})."
            ),
            new=reference,
        )
    db.commit()
    db.refresh(row)

    logger.info(
        "succession_filed",
        case=reference,
        outcome=report.outcome.value,
        risk=report.risk_score,
        findings=len(report.findings),
    )
    return SuccessionValidationResponse(
        report=row.report_json,
        normalization_warnings=assembly.warnings,
        persisted=True,
        case=_detail(row),
    )


@router.post("/cases/{case_id}/revalidate", response_model=SuccessionCaseDetail)
def revalidate(
    case_id: uuid.UUID,
    request: Request,
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
) -> SuccessionCaseDetail:
    """Re-run the succession rules over a filed case under the current policy.

    Needed when the *policy* changes rather than the case: a district that re-weights
    ``SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED`` wants yesterday's cases re-banded
    under today's weights. Re-reads no documents -- the stored bundle is already
    normalised, exactly as ``POST /parcels/{id}/revalidate`` re-judges without
    re-running OCR.
    """
    row = _get_case(db, case_id)
    before = (row.outcome, row.risk_score)
    try:
        report = revalidate_case(row)
    except SuccessionError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"this case cannot be re-validated: {exc}",
        ) from exc

    if row.parcel_id is not None:
        _audit(
            db,
            parcel_id=row.parcel_id,
            actor=actor,
            request=request,
            note=(
                f"Succession case {row.case_reference} re-validated: "
                f"{before[0]} ({before[1]}) → {report.outcome.value} ({report.risk_score})."
            ),
            previous=before[0],
            new=report.outcome.value,
        )
    db.commit()
    db.refresh(row)
    return _detail(row)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/cases", response_model=Page[SuccessionCaseSummary])
def list_cases(
    response: Response,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    q: str | None = Query(default=None, description="Matches case reference, parcel key, village or district."),
    state: str | None = None,
    district: str | None = None,
    village: str | None = None,
    outcome: str | None = None,
    risk_level: str | None = None,
    event_type: str | None = None,
    open_only: bool = Query(default=False, description="Exclude cases whose every check came back clear."),
    min_risk: float | None = Query(default=None, ge=0, le=100),
    parcel_id: uuid.UUID | None = None,
    sort: SortField = "risk",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[SuccessionCaseSummary]:
    """Filed cases, paged and total-counted.

    ``total`` is the count across the whole filtered set, not the page -- a list that
    says "50 cases" over a district holding five hundred is lying to the officer
    reading it.
    """
    stmt = select(SuccessionCaseRecord)

    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                SuccessionCaseRecord.case_reference.ilike(needle),
                SuccessionCaseRecord.parcel_key.ilike(needle),
                SuccessionCaseRecord.village.ilike(needle),
                SuccessionCaseRecord.district.ilike(needle),
            )
        )
    for column, value in (
        (SuccessionCaseRecord.state, state),
        (SuccessionCaseRecord.district, district),
        (SuccessionCaseRecord.village, village),
        (SuccessionCaseRecord.outcome, outcome),
        (SuccessionCaseRecord.risk_level, risk_level),
        (SuccessionCaseRecord.event_type, event_type),
        (SuccessionCaseRecord.parcel_id, parcel_id),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    if open_only:
        stmt = stmt.where(SuccessionCaseRecord.outcome.in_(_OPEN_OUTCOMES))
    if min_risk is not None:
        stmt = stmt.where(SuccessionCaseRecord.risk_score >= min_risk)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = _SORT_COLUMNS[sort]
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())

    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    response.headers["X-Total-Count"] = str(total)
    return Page(
        items=[SuccessionCaseSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/cases/{case_id}", response_model=SuccessionCaseDetail)
def get_case(
    case_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(current_user)
) -> SuccessionCaseDetail:
    """One case in full: the bundle as read, every check, the risk arithmetic, the chain."""
    return _detail(_get_case(db, case_id))


@router.get("/cases/{case_id}/events", response_model=list[OwnershipEventResponse])
def case_events(
    case_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(current_user)
) -> list[OwnershipEventRecord]:
    """This case's ownership chain, oldest first.

    Oldest-first because it renders as a timeline the reviewer reads downward; a
    provenance chain read backwards is much harder to follow.
    """
    _get_case(db, case_id)
    return list(
        db.scalars(
            select(OwnershipEventRecord)
            .where(OwnershipEventRecord.case_id == case_id)
            .order_by(OwnershipEventRecord.sequence.asc())
        ).all()
    )


@router.get("/cases/{case_id}/explain", response_model=dict)
def explain_case(
    case_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(current_user)
) -> dict:
    """Why this case scored what it did, and what each finding rests on.

    A separate endpoint from the detail because it answers a different question and
    is read by a different person: the detail is what happened, this is why the
    machine said so. Every number here decomposes -- the risk score is the plain sum
    of the contributions listed, and each contribution names the check and the
    documents behind it.
    """
    row = _get_case(db, case_id)
    report = row.report_json
    return {
        "case_reference": row.case_reference,
        "outcome": row.outcome,
        "risk_level": row.risk_level,
        "risk_score": row.risk_score,
        "risk_contributions": report.get("risk_contributions", []),
        "checks": report.get("checks", []),
        "issues": report.get("issues", []),
        "findings": report.get("findings", []),
        "evidence_documents": report.get("evidence_documents", []),
        "normalization_warnings": row.normalization_warnings or [],
        "recommended_action": row.recommended_action,
        "disclaimer": report.get("disclaimer"),
    }


@router.get("/history", response_model=list[OwnershipEventResponse])
def parcel_history(
    parcel_key: str = Query(description="The parcel whose ownership history to assemble."),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[OwnershipEventRecord]:
    """Every ownership event recorded against one parcel, across every case.

    This is why the chain is stored relationally rather than only inside each case's
    report: a timeline nested per case can answer "what happened in this case", and
    the question a revenue office actually asks is "what has ever happened to this
    land". Dated events first, in order; undated ones follow.
    """
    return list(
        db.scalars(
            select(OwnershipEventRecord)
            .where(OwnershipEventRecord.parcel_key == parcel_key)
            .order_by(
                OwnershipEventRecord.event_date.is_(None),
                OwnershipEventRecord.event_date.asc(),
                OwnershipEventRecord.sequence.asc(),
            )
            .limit(limit)
        ).all()
    )


@router.get("/summary", response_model=dict)
def summary(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    district: str | None = None,
) -> dict:
    """Counts by outcome and risk band, for the dashboard panel."""
    stmt = select(SuccessionCaseRecord)
    if district:
        stmt = stmt.where(SuccessionCaseRecord.district == district)
    rows = db.scalars(stmt).all()

    by_outcome: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for row in rows:
        by_outcome[row.outcome] = by_outcome.get(row.outcome, 0) + 1
        by_risk[row.risk_level] = by_risk.get(row.risk_level, 0) + 1

    open_cases = [r for r in rows if r.outcome in _OPEN_OUTCOMES]
    return {
        "total_cases": len(rows),
        "open_cases": len(open_cases),
        "by_outcome": by_outcome,
        "by_risk_level": by_risk,
        "deaths_verified": sum(1 for r in rows if r.death_verified),
        "avg_risk_score": (
            round(sum(r.risk_score for r in rows) / len(rows), 2) if rows else 0.0
        ),
    }


@router.delete(
    "/cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_case(
    case_id: uuid.UUID, _: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> None:
    """Remove a case and its derived chain. Administrator only.

    Exists for a case filed against the wrong parcel. Gated at the highest role for
    the same reason parcel deletion is: it destroys an assessment of a disputed
    succession, and a deployment with retention obligations should disable the route
    rather than rely on nobody calling it. The parcel's own audit trail keeps the row
    recording that the case was filed.
    """
    row = _get_case(db, case_id)
    db.delete(row)
    db.commit()


@router.get("/parcels/{parcel_id}/cases", response_model=list[SuccessionCaseSummary])
def cases_for_parcel(
    parcel_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(current_user)
) -> list[SuccessionCaseRecord]:
    """Succession cases raised against one parcel, newest first.

    What the parcel detail page calls to decide whether to show its succession panel.
    """
    if db.get(ParcelRecord, parcel_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="parcel not found")
    return list(
        db.scalars(
            select(SuccessionCaseRecord)
            .where(SuccessionCaseRecord.parcel_id == parcel_id)
            .order_by(SuccessionCaseRecord.created_at.desc())
        ).all()
    )
