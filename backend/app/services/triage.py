"""Queue triage: turning a parcel's pipeline scores into a priority and an SLA clock.

The reviewer console's whole value proposition is "look at these forty records, in
this order". That ordering is this module. It is deliberately a small, pure,
explainable function rather than a learned ranker: a Tehsildar asked *why* this
record is at the top of their queue is owed a sentence, not a model card -- so
:func:`assess_priority` returns the reasons alongside the score, and the API hands
them to the UI verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..core.config import get_settings
from ..models.enums import Priority

__all__ = ["TriageAssessment", "assess_priority", "sla_due_at"]


# Weights sum to 100 so the resulting score reads as "percent of maximum concern".
# They encode a revenue office's actual escalation order: a record that contradicts
# the cadastral map is worse than one the OCR merely found hard to read, because the
# first implies a dispute on the ground and the second implies a better scan.
_W_MISMATCH = 34.0
_W_SEVERITY = 30.0
_W_CONFIDENCE = 22.0
_W_ISSUE_VOLUME = 8.0
_W_ACTION = 6.0

_SEVERITY_WEIGHT = {"critical": 1.0, "error": 0.7, "warning": 0.35, "info": 0.1}
_ACTION_WEIGHT = {
    "reject_re_scan": 1.0,
    "field_verification": 0.8,
    "review_queue": 0.5,
    "auto_approve": 0.0,
}


@dataclass(slots=True)
class TriageAssessment:
    """Why a record sits where it sits in the queue."""

    score: float
    """0-100. Higher means "look at this sooner"."""

    priority: Priority
    reasons: list[str] = field(default_factory=list)
    """Human-readable drivers, most significant first. Shown in the queue UI as the
    record's justification -- never more than three, because a reviewer scanning a
    list will not read a fourth."""


def assess_priority(
    *,
    mismatch_score: float | None,
    confidence_score: float | None,
    validation_highest_severity: str | None,
    validation_issue_count: int,
    recommended_action: str | None,
) -> TriageAssessment:
    """Score one parcel for the review queue.

    Every component degrades gracefully to zero when its input is missing, which is
    the correct behaviour and not merely a convenience: a parcel with no matched
    cadastral geometry has no *evidence* of a mismatch, and inventing a penalty for
    the absence of evidence would push unmatched records to the top of every queue
    forever. Confidence is the exception -- a missing confidence score is treated as
    mid-band (0.5) rather than perfect, because an unscored extraction genuinely is
    less trustworthy than a scored-high one.
    """
    reasons: list[tuple[float, str]] = []

    # -- geometric disagreement with the cadastral map -----------------------------
    mismatch_component = 0.0
    if mismatch_score is not None:
        mismatch_component = min(mismatch_score, 100.0) / 100.0 * _W_MISMATCH
        if mismatch_score >= 50:
            reasons.append((mismatch_component, f"Area disagrees with the cadastral map by {mismatch_score:.0f}%"))
        elif mismatch_score >= 15:
            reasons.append((mismatch_component, f"Moderate area mismatch ({mismatch_score:.0f}%) against the map"))

    # -- worst validation finding ---------------------------------------------------
    severity_component = _SEVERITY_WEIGHT.get(validation_highest_severity or "", 0.0) * _W_SEVERITY
    if validation_highest_severity in {"critical", "error"}:
        # Worded to avoid an article agreeing with a value ("a error"): the
        # severity is data, so it goes after the noun rather than in front of it.
        reasons.append(
            (severity_component, f"Rule engine raised a finding at {validation_highest_severity} severity")
        )

    # -- extraction confidence ------------------------------------------------------
    effective_confidence = 0.5 if confidence_score is None else max(0.0, min(confidence_score, 1.0))
    confidence_component = (1.0 - effective_confidence) * _W_CONFIDENCE
    if effective_confidence < 0.6:
        reasons.append((confidence_component, f"Low extraction confidence ({effective_confidence * 100:.0f}%)"))

    # -- sheer number of findings ---------------------------------------------------
    # Saturating at five: the difference between one finding and four says something
    # about the record, the difference between nine and twelve does not.
    volume_component = min(validation_issue_count, 5) / 5.0 * _W_ISSUE_VOLUME
    if validation_issue_count >= 3:
        reasons.append((volume_component, f"{validation_issue_count} validation findings on one record"))

    # -- what the discrepancy engine itself recommended -------------------------------
    action_component = _ACTION_WEIGHT.get(recommended_action or "", 0.3) * _W_ACTION
    if recommended_action == "reject_re_scan":
        reasons.append((action_component, "Pipeline recommends rejecting the scan outright"))
    elif recommended_action == "field_verification":
        reasons.append((action_component, "Pipeline recommends physical field verification"))

    score = round(
        mismatch_component + severity_component + confidence_component + volume_component + action_component, 2
    )

    reasons.sort(key=lambda pair: pair[0], reverse=True)
    top_reasons = [text for _, text in reasons[:3]]
    if not top_reasons:
        top_reasons = ["Clean extraction — no findings, no geometric disagreement"]

    return TriageAssessment(score=score, priority=_band(score), reasons=top_reasons)


def _band(score: float) -> Priority:
    """Cut the continuous score into the four bands the SLA table is keyed by.

    Thresholds chosen so that any single maximal signal (a critical finding at 30, a
    total area mismatch at 34) lands a record in HIGH on its own, while CRITICAL
    requires two independent systems to agree something is wrong -- which is exactly
    the standard a human should have to meet before jumping the queue.
    """
    if score >= 55:
        return Priority.CRITICAL
    if score >= 30:
        return Priority.HIGH
    if score >= 12:
        return Priority.NORMAL
    return Priority.LOW


def sla_due_at(priority: Priority, *, since: datetime | None = None) -> datetime:
    """When a record at this priority breaches its service level."""
    settings = get_settings()
    hours = settings.sla_hours_by_priority.get(priority.value, 168)
    return (since or datetime.now(UTC)) + timedelta(hours=hours)
