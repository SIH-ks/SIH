"""Parcel query and review endpoints -- what the reviewer console and the GIS map
view read from."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....db.base import get_db
from ....models.record import ParcelRecord, ReviewEvent
from ....schemas.record import ParcelDetail, ParcelSummary, ReviewCorrectionRequest, ReviewEventResponse

router = APIRouter(prefix="/parcels", tags=["parcels"])


@router.get("", response_model=list[ParcelSummary])
def list_parcels(
    db: Session = Depends(get_db),
    state: str | None = Query(None),
    district: str | None = Query(None),
    village: str | None = Query(None),
    requires_review: bool | None = Query(None),
    min_mismatch: float | None = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ParcelRecord]:
    """List parcels for the reviewer console grid, with the filters it needs.

    ``min_mismatch`` is the discrepancy-engine score (0-100) -- filtering on it is
    how a Tehsildar pulls up "everything that disagrees with the map by more than X".
    """
    stmt = select(ParcelRecord)
    if state:
        stmt = stmt.where(ParcelRecord.state == state)
    if district:
        stmt = stmt.where(ParcelRecord.district == district)
    if village:
        stmt = stmt.where(ParcelRecord.village == village)
    if requires_review is not None:
        stmt = stmt.where(ParcelRecord.requires_human_review == requires_review)
    if min_mismatch is not None:
        stmt = stmt.where(ParcelRecord.mismatch_score >= min_mismatch)
    stmt = stmt.order_by(ParcelRecord.updated_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


@router.get("/{parcel_id}", response_model=ParcelDetail)
def get_parcel(parcel_id: uuid.UUID, db: Session = Depends(get_db)) -> ParcelRecord:
    parcel = db.get(ParcelRecord, parcel_id)
    if parcel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="parcel not found")
    return parcel


@router.post("/{parcel_id}/review", response_model=ReviewEventResponse, status_code=status.HTTP_201_CREATED)
def submit_correction(
    parcel_id: uuid.UUID,
    correction: ReviewCorrectionRequest,
    reviewer: str = Query(..., description="Reviewer identity, from the auth layer in production."),
    db: Session = Depends(get_db),
) -> ReviewEvent:
    """Record a human correction to one field.

    This endpoint intentionally does not mutate ``artifact_json`` in place -- see
    :class:`~app.models.record.ReviewEvent`'s docstring. Applying the correction back
    onto the artifact (and re-running validation against the corrected value) is a
    natural next endpoint; left out of this reference implementation to keep the
    audit-trail write path -- the part every review workflow depends on being
    correct -- unambiguous.
    """
    parcel = db.get(ParcelRecord, parcel_id)
    if parcel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="parcel not found")

    previous = _read_path(parcel.artifact_json, correction.field_path)

    event = ReviewEvent(
        id=uuid.uuid4(),
        parcel_id=parcel_id,
        field_path=correction.field_path,
        previous_value={"value": previous},
        new_value={"value": correction.new_value},
        action="corrected",
        reviewer=reviewer,
        note=correction.note,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _read_path(data: dict, path: str) -> object:
    """Best-effort dotted-path read from the artifact JSON, for the audit record.

    Deliberately tolerant: a path that does not resolve returns ``None`` rather than
    raising, since this value is informational (what to show a reviewer as "before"),
    not something correctness depends on.
    """
    current: object = data
    for part in path.replace("$.", "").split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
    return current
