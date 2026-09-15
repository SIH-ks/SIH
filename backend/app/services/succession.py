"""Assembling, assessing and filing an ownership-succession case.

The second place the backend calls into :mod:`adhikar` (the first being
:mod:`app.services.ingestion`), and it follows the same rule: the router talks only
to this module and gets back ORM rows and DTOs, so the engine's API can move without
touching request handling.

The piece worth understanding is how a case gets its Records of Rights. There are two
routes and they converge:

* **From the register.** ``parcel_id`` / ``current_parcel_id`` name parcels already in
  the database. Their stored ``artifact_json`` is the full output of the OCR + table
  layout + Vision-LLM pipeline, so :func:`adhikar.succession.snapshot_from_record`
  projects it straight onto a succession snapshot -- owners, shares and parcel
  identifiers as the pipeline normalised them, with no second extraction pass.
* **From the submission.** Everything the RoR extraction contract does not cover (a
  death certificate has no table to parse) arrives in ``documents`` as printed
  strings and goes through :func:`adhikar.succession.normalize_case`, which applies
  the same deterministic normalisers the pipeline's own mapping stage uses.

Both produce the same :class:`~adhikar.schemas.succession.SuccessionCase`, and the
rules cannot tell which route a document took.

**Re-validation never re-reads the documents.** ``case_json`` is the normalised
bundle, and re-running the engine over it is what lets a district re-judge yesterday's
cases under today's policy weights without re-scanning anything -- the same separation
``POST /parcels/{id}/revalidate`` makes for the parcel rules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from adhikar.schemas.succession import (
    OwnershipEvent,
    RecordSnapshot,
    SuccessionCase,
    SuccessionDocumentType,
    SuccessionReport,
)
from adhikar.schemas.validation import ValidationPolicy
from adhikar.succession import normalize_case, snapshot_from_record
from adhikar.validation import DEFAULT_POLICY, validate_succession
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..models.record import ParcelRecord
from ..models.succession import OwnershipEventRecord, SuccessionCaseRecord
from .corrections import CorrectionError, parse_record, strip_computed_fields

__all__ = [
    "SuccessionAssembly",
    "SuccessionError",
    "assemble_case",
    "assess",
    "case_from_row",
    "persist_case",
    "report_payload",
    "revalidate_case",
]


class SuccessionError(Exception):
    """A case could not be assembled or re-assessed. Carries a reviewer-readable reason."""


@dataclass(slots=True)
class SuccessionAssembly:
    """A case ready to assess, plus how it was read."""

    case: SuccessionCase
    warnings: list[str]
    """Normalisation warnings -- a date that would not parse, an unrecognised area
    unit. Kept beside the findings because "assessed without a date of death" changes
    what the findings mean."""

    document_ids: list[str]
    parcel: ParcelRecord | None


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _snapshot_from_parcel(
    parcel: ParcelRecord, *, document_type: SuccessionDocumentType, label: str
) -> RecordSnapshot:
    """Project a stored parcel extraction onto a succession snapshot.

    :raises SuccessionError: when the stored artifact no longer satisfies the
        engine's schema. That happens legitimately for hand-authored demo rows that
        the pipeline never produced, so it is reported as "this record cannot be used
        here", not as data corruption.
    """
    try:
        record = parse_record(parcel.artifact_json)
    except CorrectionError as exc:
        raise SuccessionError(
            f"parcel {parcel.parcel_key} cannot be used as a Record of Rights in a "
            f"succession case: {exc}"
        ) from exc

    return snapshot_from_record(
        record,
        label=label,
        document_type=document_type,
        document_id=str(parcel.id),
    )


def assemble_case(
    db: Session,
    *,
    case_id: str,
    documents: list[dict[str, Any]],
    parcel_id: uuid.UUID | None = None,
    current_parcel_id: uuid.UUID | None = None,
    parcel_key: str | None = None,
    notes: str | None = None,
    submitted_by: str | None = None,
) -> SuccessionAssembly:
    """Build one case from register records and submitted documents.

    Register-sourced snapshots are prepended rather than appended so that a caller
    who names ``parcel_id`` and also submits an updated Jamabandi gets the before /
    after order they meant. The engine re-sorts by date anyway where dates exist;
    this only decides the order of snapshots that carry none.
    """
    case, warnings = normalize_case(
        {
            "case_id": case_id,
            "parcel_key": parcel_key,
            "documents": documents,
            "submitted_by": submitted_by,
            "notes": notes,
        }
    )

    register_snapshots: list[RecordSnapshot] = []
    primary: ParcelRecord | None = None
    document_ids: list[str] = []

    for identifier, document_type, label in (
        (parcel_id, SuccessionDocumentType.JAMABANDI, "Record of Rights (on file)"),
        (current_parcel_id, SuccessionDocumentType.UPDATED_JAMABANDI, "Updated Record of Rights (on file)"),
    ):
        if identifier is None:
            continue
        parcel = db.get(ParcelRecord, identifier)
        if parcel is None:
            raise SuccessionError(f"parcel {identifier} does not exist")
        register_snapshots.append(
            _snapshot_from_parcel(parcel, document_type=document_type, label=label)
        )
        document_ids.append(str(parcel.document_id))
        primary = primary or parcel

    document_ids.extend(
        str(entry["document_id"])
        for entry in documents
        if isinstance(entry, dict) and entry.get("document_id")
    )

    resolved_key = parcel_key or (primary.parcel_key if primary else None)
    assembled = case.model_copy(
        update={
            "record_snapshots": [*register_snapshots, *case.record_snapshots],
            "parcel_key": resolved_key,
            "submitted_at": datetime.now(UTC),
        }
    )
    # `model_copy` bypasses validators, and snapshot ordering is one -- the chain
    # rules read consecutive pairs, so re-validating here is what keeps a case
    # assembled from two sources in the same order as one assembled from a payload.
    assembled = SuccessionCase.model_validate(
        strip_computed_fields(SuccessionCase, assembled.model_dump(mode="python"))
    )

    return SuccessionAssembly(
        case=assembled,
        warnings=warnings,
        document_ids=sorted(set(document_ids)),
        parcel=primary,
    )


def assess(case: SuccessionCase, *, policy: ValidationPolicy | None = None) -> SuccessionReport:
    """Run the succession rule engine over one assembled case."""
    return validate_succession(case, policy or DEFAULT_POLICY)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _event_rows(case_id: uuid.UUID, events: list[OwnershipEvent]) -> list[OwnershipEventRecord]:
    return [
        OwnershipEventRecord(
            id=uuid.uuid4(),
            case_id=case_id,
            sequence=event.sequence,
            event_type=event.event_type.value,
            event_date=event.event_date,
            date_stated=event.date_stated,
            parcel_key=event.parcel_key,
            person=event.person,
            from_owners=[p.model_dump(mode="json") for p in event.from_owners],
            to_owners=[p.model_dump(mode="json") for p in event.to_owners],
            description=event.description[:2048],
            evidence=[e.model_dump(mode="json") for e in event.evidence],
        )
        for event in events
    ]


def _project(row: SuccessionCaseRecord, report: SuccessionReport) -> None:
    """Rewrite the scalar columns from the report. Recompute, never patch.

    Total and cheap, for the same reason ``refresh_derived_fields`` is: a projection
    that is patched field-by-field drifts from its source after an unusual sequence
    of edits, and nothing notices until a queue orders wrongly.
    """
    row.outcome = report.outcome.value
    row.risk_level = report.risk_level.value
    row.risk_score = report.risk_score
    row.event_type = report.event_type.value
    row.recommended_action = report.recommended_action.value
    row.death_verified = report.death_verified
    row.heir_count = len(report.potential_heirs)
    row.check_count = len(report.checks)
    row.open_finding_count = len(report.findings)
    row.report_json = report_payload(report)


def persist_case(
    db: Session,
    *,
    assembly: SuccessionAssembly,
    report: SuccessionReport,
    case_reference: str,
    created_by: str | None,
    notes: str | None = None,
) -> SuccessionCaseRecord:
    """File a case and its derived ownership chain. The caller owns the transaction."""
    row = SuccessionCaseRecord(
        id=uuid.uuid4(),
        case_reference=case_reference,
        parcel_id=assembly.parcel.id if assembly.parcel else None,
        parcel_key=assembly.case.parcel_key,
        state=assembly.parcel.state if assembly.parcel else assembly.case.parcel.state,
        district=assembly.parcel.district if assembly.parcel else assembly.case.parcel.district,
        village=assembly.parcel.village if assembly.parcel else assembly.case.parcel.village,
        case_json=assembly.case.model_dump(mode="json"),
        normalization_warnings=list(assembly.warnings),
        document_ids=list(assembly.document_ids),
        notes=notes,
        created_by=created_by,
    )
    _project(row, report)
    db.add(row)
    db.flush()  # assigns row.id for the event FK without committing yet
    db.add_all(_event_rows(row.id, report.timeline))
    return row


def case_from_row(row: SuccessionCaseRecord) -> SuccessionCase:
    """Rebuild the domain case from its stored JSON.

    :raises SuccessionError: when the stored bundle no longer satisfies the engine's
        schema -- which is what a caller sees if a case filed under an older schema
        version is re-validated after a breaking change, and is worth saying plainly
        rather than surfacing as a 500.
    """
    try:
        return SuccessionCase.model_validate(strip_computed_fields(SuccessionCase, row.case_json))
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()[:3]
        )
        raise SuccessionError(f"stored case does not satisfy the engine's schema — {detail}") from exc


def revalidate_case(
    row: SuccessionCaseRecord, *, policy: ValidationPolicy | None = None
) -> SuccessionReport:
    """Re-run the engine over a filed case and rewrite its report, chain and columns.

    Mutates ``row`` in place and replaces its event rows; the caller owns the
    transaction and the audit write. Re-reads nothing: ``case_json`` is the normalised
    bundle, so this re-judges under the current policy without touching a scan.
    """
    report = assess(case_from_row(row), policy=policy)
    _project(row, report)
    # Events are derived output. Replacing the set wholesale is what stops a stale
    # node from a superseded reading surviving into the new chain.
    row.events.clear()
    row.events.extend(_event_rows(row.id, report.timeline))
    return report


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def report_payload(report: SuccessionReport) -> dict[str, Any]:
    """Flatten the engine's report into the shape the console reads.

    The engine's own dump nests names as ``{"raw": ..., "relation_type": ...}``, which
    is right for the domain model and wrong for a table cell. Flattening here, once,
    keeps that formatting decision out of both the ORM and the frontend -- and keeps
    the stored ``report_json`` directly renderable, so an export does not need this
    module to be readable.
    """
    return {
        "case_id": report.case_id,
        "parcel_key": report.parcel_key,
        "policy_name": report.policy_name,
        "outcome": report.outcome.value,
        "risk_level": report.risk_level.value,
        "risk_score": report.risk_score,
        "event_type": report.event_type.value,
        "recommended_action": report.recommended_action.value,
        "summary": report.summary_sentence(),
        "parcel": report.parcel.model_dump(mode="json"),
        "previous_owners": [
            {"name": o.display_name, "share": str(o.share) if o.share else None}
            for o in report.previous_owners
        ],
        "current_owners": [
            {"name": o.display_name, "share": str(o.share) if o.share else None}
            for o in report.current_owners
        ],
        "deceased": list(report.deceased),
        "death_verified": report.death_verified,
        "potential_heirs": [
            {
                "name": heir.display_name,
                "relation": heir.relation_to_deceased.value,
                "stated_share": str(heir.stated_share) if heir.stated_share else None,
                "is_minor": heir.is_minor,
                "source": heir.source.model_dump(mode="json") if heir.source else None,
            }
            for heir in report.potential_heirs
        ],
        "checks": [
            {
                "rule": check.rule,
                "rule_code": check.rule_code.value,
                "status": check.status.value,
                "explanation": check.explanation,
                "evidence": [e.model_dump(mode="json") for e in check.evidence],
                "match_score": check.match_score,
                "confidence": check.confidence,
                "risk_points": check.risk_points,
                "remediation": check.remediation,
            }
            for check in report.sorted_checks()
        ],
        "issues": list(report.issues),
        "findings": [issue.model_dump(mode="json") for issue in report.findings],
        "risk_contributions": [
            {**c.model_dump(mode="json"), "rule_code": c.rule_code.value}
            for c in report.risk_contributions
        ],
        "timeline": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "event_date": event.event_date.isoformat() if event.event_date else None,
                "date_stated": event.date_stated,
                "parcel_key": event.parcel_key,
                "person": event.person,
                "from_owners": [p.model_dump(mode="json") for p in event.from_owners],
                "to_owners": [p.model_dump(mode="json") for p in event.to_owners],
                "description": event.description,
                "evidence": [e.model_dump(mode="json") for e in event.evidence],
            }
            for event in report.timeline
        ],
        "evidence_documents": [e.model_dump(mode="json") for e in report.evidence_documents],
        "disclaimer": report.disclaimer,
        "counts_by_status": report.counts_by_status,
        "duration_ms": report.duration_ms,
        "generated_at": report.generated_at.isoformat(),
    }


def next_case_reference(db: Session, *, district: str | None) -> str:
    """Generate an office-style reference for a case filed without one.

    Sequential within a district and year, because that is how a revenue office
    numbers a file and how somebody later finds it. Derived from a count rather than
    a sequence object so it works identically on SQLite and Postgres; a collision
    under concurrency would produce a duplicate reference, which is why the column is
    indexed but not unique -- a repeated reference is a nuisance a clerk can correct,
    where a rejected filing is work lost.
    """
    year = datetime.now(UTC).year
    prefix = (district or "GEN")[:3].upper()
    existing = (
        db.query(SuccessionCaseRecord)
        .filter(SuccessionCaseRecord.case_reference.like(f"SUC/{prefix}/{year}/%"))
        .count()
    )
    return f"SUC/{prefix}/{year}/{existing + 1:04d}"
