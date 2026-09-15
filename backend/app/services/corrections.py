"""Applying a human correction to a stored artifact, and re-validating the result.

The original reference implementation recorded corrections into the audit trail but
never applied them: ``artifact_json`` kept the machine's reading forever. That made
the console a viewer, not a workflow -- a reviewer could say "this area is wrong"
and the next person to open the record would still see the wrong area, with a note
attached.

This module closes that loop, and does the one thing that makes closing it safe:
after writing the corrected value it **re-runs the full rule engine** against the
corrected record. Correcting a sub-division's area can resolve an
``AREA_SUM_MISMATCH`` -- or create one. A system that let a human edit a field
without re-checking the arithmetic would be worse than one that did not let them
edit at all, because the stale green tick would carry the reviewer's authority.

The audit trail stays additive throughout: :class:`~app.models.record.ReviewEvent`
rows record every before/after pair, so the machine's original reading is always
reconstructable even though ``artifact_json`` now holds the corrected one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, get_args, get_origin

from adhikar.schemas.land_record import LandParcelRecord
from adhikar.schemas.validation import ValidationPolicy
from adhikar.validation import DEFAULT_POLICY, run_all
from pydantic import BaseModel, ValidationError

from ..models.record import ParcelRecord
from .triage import assess_priority, sla_due_at

__all__ = [
    "CorrectionError",
    "CorrectionResult",
    "apply_correction",
    "read_path",
    "refresh_derived_fields",
    "strip_computed_fields",
]

_SEGMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")

#: Keys the backend folds into ``artifact_json`` alongside the parcel record itself
#: (see ``services.ingestion._build_parcel_row``). They are *ours*, not the engine's,
#: so they are stripped before the dict is handed back to ``LandParcelRecord``.
_BACKEND_ONLY_KEYS = {"provenance", "validation_issues"}


class CorrectionError(Exception):
    """A correction could not be applied. Carries a reviewer-readable reason."""


@dataclass(slots=True)
class CorrectionResult:
    field_path: str
    previous_value: Any
    new_value: Any
    issues_before: int
    issues_after: int
    highest_severity_after: str | None
    revalidated: bool
    """False when the corrected record no longer parses as a ``LandParcelRecord`` --
    the correction is still stored and audited, but the rule engine could not be run
    against it, and the caller must not report validation results as current."""

    revalidation_note: str | None = None


# ---------------------------------------------------------------------------
# Path addressing
# ---------------------------------------------------------------------------


def _segments(path: str) -> list[str | int]:
    """Split ``owners[0].name.raw`` into ``["owners", 0, "name", "raw"]``.

    Accepts an optional ``$.`` JSONPath prefix so the same strings the validation
    engine emits in ``ValidationIssue.json_path`` can be passed straight through --
    that is what lets the console's "fix this finding" button address the exact field
    a rule complained about.
    """
    cleaned = path.strip()
    if cleaned.startswith("$."):
        cleaned = cleaned[2:]
    elif cleaned == "$":
        raise CorrectionError("'$' addresses the whole record, which cannot be corrected as one field.")

    out: list[str | int] = []
    pos = 0
    while pos < len(cleaned):
        if cleaned[pos] == ".":
            pos += 1
            continue
        match = _SEGMENT.match(cleaned, pos)
        if match is None:
            raise CorrectionError(f"malformed field path {path!r} at offset {pos}")
        name, index = match.groups()
        out.append(name if name is not None else int(index))
        pos = match.end()

    if not out:
        raise CorrectionError(f"empty field path {path!r}")
    return out


def read_path(data: Any, path: str) -> Any:
    """Best-effort read. Returns ``None`` for a path that does not resolve.

    Tolerant on purpose: this feeds the "before" value shown in an audit entry, which
    is informational. Writing, by contrast, is strict -- see :func:`_write_path`.
    """
    try:
        segments = _segments(path)
    except CorrectionError:
        return None

    current = data
    for segment in segments:
        if isinstance(segment, int):
            if not isinstance(current, list) or not 0 <= segment < len(current):
                return None
            current = current[segment]
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(segment)
    return current


def _write_path(data: dict, path: str, value: Any) -> Any:
    """Write ``value`` at ``path``, returning what was there before.

    Strict: a path whose parent does not exist raises rather than materialising
    intermediate objects. Auto-creating a missing ``owners[3]`` would let a typo in a
    field path invent a fourth owner on a land record, which is precisely the kind of
    silent damage an audited system must not do.
    """
    segments = _segments(path)
    current: Any = data

    for depth, segment in enumerate(segments[:-1]):
        if isinstance(segment, int):
            if not isinstance(current, list) or not 0 <= segment < len(current):
                raise CorrectionError(f"no element at index {segment} in {'.'.join(map(str, segments[:depth]))!r}")
            current = current[segment]
        else:
            if not isinstance(current, dict) or segment not in current or current[segment] is None:
                raise CorrectionError(
                    f"field path {path!r} does not resolve: {segment!r} is absent on this record."
                )
            current = current[segment]

    last = segments[-1]
    if isinstance(last, int):
        if not isinstance(current, list) or not 0 <= last < len(current):
            raise CorrectionError(f"no element at index {last} to correct in {path!r}")
        previous = current[last]
        current[last] = _coerce(previous, value)
        return previous

    if not isinstance(current, dict):
        raise CorrectionError(f"field path {path!r} does not address an object field")
    if last not in current:
        raise CorrectionError(f"unknown field {last!r} on this record — nothing at {path!r} to correct.")
    previous = current[last]
    current[last] = _coerce(previous, value)
    return previous


def _coerce(previous: Any, value: Any) -> Any:
    """Match the incoming value to the shape the field already had.

    Corrections arrive from an HTML form, so everything is a string. Writing the
    string ``"9420"`` into a numeric field would round-trip fine through JSON and
    then fail Pydantic validation on the way back in, turning a legitimate correction
    into an un-revalidatable record. Coercing here keeps the artifact's own types
    stable; a value that genuinely cannot be coerced is passed through unchanged so
    the Pydantic error names the real problem rather than one this function invented.
    """
    if value is None or previous is None:
        return value
    if isinstance(previous, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1", "y"}
        return bool(value)
    if isinstance(previous, (int, float)) and not isinstance(value, (int, float)):
        try:
            return type(previous)(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return value
    if isinstance(previous, str) and not isinstance(value, str):
        # ``sq_metre`` round-trips through JSON as a *string* (Pydantic serialises
        # Decimal that way), so a numeric correction to it lands here.
        if isinstance(value, (int, float)):
            try:
                return str(Decimal(str(value)))
            except InvalidOperation:
                return str(value)
        return str(value)
    return value


# ---------------------------------------------------------------------------
# Re-validation
# ---------------------------------------------------------------------------


def _prune_computed(model_cls: type[BaseModel], data: Any) -> Any:
    """Strip Pydantic computed fields so a dumped model can be re-validated.

    ``model_dump()`` includes computed properties (``parcel_key``,
    ``cultivable_area_sq_metre``, ``OwnershipShare.decimal_value``, ...), and every
    model in the domain schema sets ``extra="forbid"`` -- so feeding a dump straight
    back to ``model_validate`` fails on the model's *own* output. Rather than
    hard-coding the current list of computed names (which would rot the first time a
    schema gains one), this walks the model's declared fields and prunes by
    introspection, so it stays correct as the ai-engine's schema evolves.
    """
    if not isinstance(data, dict):
        return data

    pruned = {k: v for k, v in data.items() if k not in model_cls.model_computed_fields}

    for name, field in model_cls.model_fields.items():
        if name not in pruned or pruned[name] is None:
            continue
        for nested_cls in _model_types(field.annotation):
            if isinstance(pruned[name], list):
                pruned[name] = [_prune_computed(nested_cls, item) for item in pruned[name]]
            elif isinstance(pruned[name], dict):
                pruned[name] = _prune_computed(nested_cls, pruned[name])
            break  # a field's first BaseModel arm is the only one we can act on
    return pruned


def _model_types(annotation: Any) -> list[type[BaseModel]]:
    """Every ``BaseModel`` subclass reachable one level into a type annotation.

    Handles the three shapes the domain schema actually uses -- ``Model``,
    ``Model | None``, and ``list[Model]`` -- by recursing through generic args rather
    than pattern-matching those three specifically.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    origin = get_origin(annotation)
    if origin is None:
        return []
    found: list[type[BaseModel]] = []
    for arg in get_args(annotation):
        found.extend(_model_types(arg))
    return found


#: Public alias for :func:`_prune_computed`.
#:
#: Any stored dump of an ai-engine model needs this before it can be validated back:
#: ``model_dump()`` includes computed properties and every model in the domain schema
#: sets ``extra="forbid"``, so a model's own output is rejected by its own schema. The
#: succession service re-validates stored ``SuccessionCase`` JSON and hits exactly the
#: same wall (``OwnershipShare.decimal_value``, ``ParcelIdentity.display_key``), so it
#: reuses this rather than growing a second, divergent copy of the same walk.
strip_computed_fields = _prune_computed


def parse_record(artifact_json: dict) -> LandParcelRecord:
    """Rebuild the domain record from a stored ``artifact_json`` blob.

    :raises CorrectionError: when the stored JSON no longer satisfies the engine's
        schema -- which happens legitimately for hand-authored demo rows that were
        never produced by the pipeline, so callers treat it as "cannot revalidate",
        not as data corruption.
    """
    payload = {k: v for k, v in artifact_json.items() if k not in _BACKEND_ONLY_KEYS}
    try:
        return LandParcelRecord.model_validate(_prune_computed(LandParcelRecord, payload))
    except ValidationError as exc:
        # Name the offending fields rather than just counting them: this message is
        # shown to a reviewer whose correction could not be re-validated, and
        # "3 problem(s)" gives them nothing to act on.
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:3]
        )
        raise CorrectionError(f"record does not satisfy the extraction schema — {detail}") from exc


def revalidate(artifact_json: dict, *, policy: ValidationPolicy | None = None) -> list[dict]:
    """Re-run every enabled rule and return the findings as stored-JSON dicts."""
    record = parse_record(artifact_json)
    report = run_all(record, policy or DEFAULT_POLICY)
    return [issue.model_dump(mode="json") for issue in report.issues]


# ---------------------------------------------------------------------------
# The write path
# ---------------------------------------------------------------------------


def refresh_derived_fields(parcel: ParcelRecord) -> None:
    """Recompute everything the queue and the dashboard read from the scores.

    Called after any change to a parcel's findings or scores so the triage band, the
    SLA clock and the issue counters never disagree with ``artifact_json``. Cheap and
    total: it recomputes rather than patching, which is what stops the projection
    from drifting after an unusual sequence of edits.
    """
    issues = parcel.artifact_json.get("validation_issues") or []
    ranks = {"info": 0, "warning": 1, "error": 2, "critical": 3}
    highest = max(issues, key=lambda i: ranks.get(i.get("severity", "info"), 0), default=None)

    parcel.validation_issue_count = len(issues)
    parcel.validation_highest_severity = highest.get("severity") if highest else None

    assessment = assess_priority(
        mismatch_score=parcel.mismatch_score,
        confidence_score=parcel.confidence_score,
        validation_highest_severity=parcel.validation_highest_severity,
        validation_issue_count=parcel.validation_issue_count,
        recommended_action=parcel.recommended_action,
    )
    parcel.priority = assessment.priority.value
    parcel.priority_score = assessment.score
    # The SLA clock runs from ingestion, not from the last edit -- re-basing it on
    # every correction would let a record stay perpetually "on time" by being touched.
    parcel.sla_due_at = sla_due_at(assessment.priority, since=parcel.created_at or datetime.now(UTC))
    parcel.requires_human_review = parcel.validation_highest_severity in {"error", "critical"} or (
        parcel.mismatch_score is not None and parcel.mismatch_score >= 15
    )


def apply_correction(
    parcel: ParcelRecord, *, field_path: str, new_value: Any, policy: ValidationPolicy | None = None
) -> CorrectionResult:
    """Write one corrected value into the parcel's artifact and re-validate it.

    Mutates ``parcel`` in place; the caller owns the transaction and is responsible
    for writing the :class:`~app.models.record.ReviewEvent` that makes the change
    auditable. Splitting it that way keeps this function testable without a session
    and keeps the audit write in the router, where the authenticated identity is.
    """
    # SQLAlchemy tracks JSON columns by identity, not by deep value, so mutating the
    # dict in place would not mark the row dirty. Rebinding a copied dict is what
    # makes the change actually persist -- a classic and silent failure otherwise.
    artifact = dict(parcel.artifact_json)
    issues_before = len(artifact.get("validation_issues") or [])

    previous = _write_path(artifact, field_path, new_value)
    applied = read_path(artifact, field_path)

    revalidated = True
    note: str | None = None
    try:
        artifact["validation_issues"] = revalidate(artifact, policy=policy)
    except CorrectionError as exc:
        # A demo row or a partially-extracted record may not round-trip through the
        # engine's schema. The correction is still applied and audited; we just say
        # so instead of leaving stale findings looking freshly computed.
        revalidated = False
        note = str(exc)

    # Total-area corrections change the number the dashboard filters and sorts on,
    # so the projected column has to follow the artifact rather than wait for a
    # re-extraction that may never come.
    if field_path.replace("$.", "").startswith("total_area"):
        sq_metre = read_path(artifact, "total_area.sq_metre")
        try:
            parcel.total_area_sq_metre = Decimal(str(sq_metre)) if sq_metre is not None else None
        except (InvalidOperation, TypeError):
            pass

    parcel.artifact_json = artifact
    parcel.correction_count = (parcel.correction_count or 0) + 1
    parcel.has_human_corrections = True
    refresh_derived_fields(parcel)

    return CorrectionResult(
        field_path=field_path,
        previous_value=previous,
        new_value=applied,
        issues_before=issues_before,
        issues_after=parcel.validation_issue_count,
        highest_severity_after=parcel.validation_highest_severity,
        revalidated=revalidated,
        revalidation_note=note,
    )
