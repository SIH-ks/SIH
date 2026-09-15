"""Aggregate reporting endpoints backing the analytics dashboard.

Thin by design: every one of these delegates to :mod:`app.services.analytics`, which
does the work in SQL. Keeping the aggregation out of the router is what lets the same
figures be reused by the CSV/report exporters without a second implementation that
could disagree with the screen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ....db.base import get_db
from ....services import analytics
from ...deps import CurrentUser, current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=dict)
def summary(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    district: str | None = None,
    state: str | None = None,
) -> dict:
    """Headline metrics for the command dashboard, over the whole corpus.

    Scoped by jurisdiction rather than by the caller's own district: a Collector
    comparing two taluks and an officer looking at their own both need this, and
    silently narrowing to the caller's district would make the national figure
    unreachable.
    """
    return analytics.summary(db, district=district, state=state).to_dict()


@router.get("/districts", response_model=list[dict])
def districts(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    state: str | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    return analytics.district_breakdown(db, state=state, limit=limit)


@router.get("/timeseries", response_model=list[dict])
def timeseries(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    days: int = Query(30, ge=1, le=365),
    district: str | None = None,
) -> list[dict]:
    """Daily ingestion, adjudication and correction counts over a trailing window."""
    return analytics.timeseries(db, days=days, district=district)


@router.get("/rules", response_model=list[dict])
def rules(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    limit: int = Query(12, ge=1, le=60),
) -> list[dict]:
    """Most-fired validation rules -- effectively a quality report on the registers."""
    return analytics.rule_frequency(db, limit=limit)


@router.get("/throughput", response_model=list[dict])
def throughput(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    days: int = Query(30, ge=1, le=365),
) -> list[dict]:
    return analytics.reviewer_throughput(db, days=days)


@router.get("/queue-health", response_model=dict)
def queue_health(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    district: str | None = None,
) -> dict:
    return analytics.queue_health(db, district=district)
