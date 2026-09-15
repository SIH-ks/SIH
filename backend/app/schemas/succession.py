"""API schemas for ownership-succession cases.

Kept beside :mod:`app.schemas.record` and shaped the same way: request/response DTOs
that are free to evolve independently of both the ORM and the ai-engine's domain
model.

One deliberate asymmetry. The *request* is strongly typed only down to the document
level -- each entry is a ``dict`` carrying a ``document_type`` discriminator and
whatever fields that type has. That is not laziness about validation; it is where the
validation belongs. Interpreting ``"12/05/2025"`` as a date, ``"0.3333"`` as a
one-third share and ``"5.0 bigha"`` as an area is
:mod:`adhikar.succession.extraction`'s job, done deterministically and reported on,
and re-implementing a second, weaker version of it in Pydantic field types would give
callers two different answers about what their document said.

The *response* is fully typed, because that is a contract the console reads.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "OwnershipEventResponse",
    "SuccessionCaseDetail",
    "SuccessionCaseSummary",
    "SuccessionCheckResponse",
    "SuccessionRequest",
    "SuccessionValidationResponse",
]


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class SuccessionRequest(BaseModel):
    """A bundle of documents to assess, plus how to attach it to the register."""

    model_config = ConfigDict(extra="forbid")

    case_reference: str | None = Field(
        default=None,
        max_length=128,
        description="Office reference for this case, e.g. 'SUC/BLG/2025/0041'. Generated if omitted.",
    )

    parcel_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "An existing parcel this case concerns. When given, the parcel's stored "
            "extraction is used as the *previous* Record of Rights — so a Jamabandi "
            "that went through the OCR + Vision-LLM pipeline is reused rather than re-keyed."
        ),
    )
    current_parcel_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "An existing parcel holding the *updated* Record of Rights, when the new "
            "Jamabandi was also ingested through /documents/upload."
        ),
    )

    documents: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "Documents in the bundle. Each entry carries a `document_type` "
            "(jamabandi, updated_jamabandi, death_certificate, legal_heir_certificate, "
            "mutation, will, relinquishment_deed, partition_deed, family_settlement, "
            "court_order, …) and the fields that type has. Values may be given exactly "
            "as printed — dates, shares and areas are normalised deterministically by "
            "the engine, which reports anything it could not read."
        ),
    )

    parcel_key: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=2048)

    persist: bool = Field(
        default=True,
        description=(
            "Store the case and its ownership events. Set false to assess a bundle "
            "without filing it — used to check a submission before accepting it."
        ),
    )


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class EvidenceRefResponse(BaseModel):
    """Where a value a check relied on came from. The unit of explainability."""

    model_config = ConfigDict(extra="ignore")

    document_type: str = "unknown"
    document_id: str | None = None
    document_label: str | None = None
    field_path: str | None = None
    value: str | None = None
    raw_value: str | None = None


class SuccessionCheckResponse(BaseModel):
    """One comparison the engine made, and what it saw.

    Passing checks are included. A reviewer deciding whether to accept a transfer
    needs to know the parcel identifiers *were* compared and *did* agree; a response
    carrying only problems cannot distinguish "checked and fine" from "not checked".
    """

    model_config = ConfigDict(extra="ignore")

    rule: str
    rule_code: str
    status: str
    explanation: str
    evidence: list[EvidenceRefResponse] = []
    match_score: float | None = None
    confidence: float = 1.0
    risk_points: float = 0.0
    remediation: str | None = None


class RiskContributionResponse(BaseModel):
    """One line of the risk score's arithmetic. The score is their sum, nothing else."""

    model_config = ConfigDict(extra="ignore")

    rule: str
    rule_code: str
    status: str
    base_points: float
    multiplier: float
    points: float
    reason: str


class EventPartyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    share: str | None = None
    relation: str | None = None


class OwnershipEventResponse(BaseModel):
    """One node of the ownership chain the console draws."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    sequence: int = 0
    event_type: str
    event_date: date | None = None
    date_stated: bool = True
    """False when the position was inferred (from a revenue year, say) rather than
    read off the document. The timeline draws these differently — an inferred
    position must not look like a recorded one."""

    parcel_key: str | None = None
    person: str | None = None
    from_owners: list[EventPartyResponse] = []
    to_owners: list[EventPartyResponse] = []
    description: str = ""
    evidence: list[EvidenceRefResponse] = []


class HeirResponse(BaseModel):
    """A person the documents name as family of the deceased.

    *Candidate*, not heir: this records who the paperwork names and in what stated
    relationship, and nothing about entitlement. ``stated_share`` is populated only
    from a document that itself states a share — the engine never apportions.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    relation: str = "unknown"
    stated_share: str | None = None
    is_minor: bool = False
    source: EvidenceRefResponse | None = None


class OwnerResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    share: str | None = None


class SuccessionReportResponse(BaseModel):
    """The engine's assessment of one case, in full."""

    model_config = ConfigDict(extra="ignore")

    case_id: str
    parcel_key: str | None = None
    policy_name: str = "default"

    outcome: str
    risk_level: str
    risk_score: float
    event_type: str
    recommended_action: str

    summary: str
    """One paragraph assembled from what the checks found, so it cannot drift from
    them the way a separately-authored summary would."""

    parcel: dict[str, Any] = {}
    previous_owners: list[OwnerResponse] = []
    current_owners: list[OwnerResponse] = []

    deceased: list[str] = []
    death_verified: bool = False
    potential_heirs: list[HeirResponse] = []

    checks: list[SuccessionCheckResponse] = []
    issues: list[str] = []
    findings: list[dict[str, Any]] = []
    """The non-clear checks in the engine's ordinary ValidationIssue shape — the same
    structure `parcels/{id}` returns, so the console renders them with the component
    it already has."""

    risk_contributions: list[RiskContributionResponse] = []
    timeline: list[OwnershipEventResponse] = []
    evidence_documents: list[EvidenceRefResponse] = []

    disclaimer: str
    """Carried in the payload, not only in the UI: the report is exported and printed,
    and a caveat that lives on one screen stops travelling with the conclusion the
    moment anybody does either."""

    counts_by_status: dict[str, int] = {}
    duration_ms: float = 0.0
    generated_at: datetime | None = None


class SuccessionCaseSummary(BaseModel):
    """Row shape for the case list and the succession queue."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_reference: str
    parcel_id: uuid.UUID | None = None
    parcel_key: str | None = None
    state: str | None = None
    district: str | None = None
    village: str | None = None

    outcome: str
    risk_level: str
    risk_score: float
    event_type: str
    recommended_action: str
    death_verified: bool
    heir_count: int
    check_count: int
    open_finding_count: int

    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class SuccessionCaseDetail(SuccessionCaseSummary):
    """One case in full: the submitted bundle, the assessment, and the chain."""

    report: SuccessionReportResponse
    case_json: dict[str, Any]
    """The normalised bundle exactly as the engine received it. Returned so a
    reviewer can see what the system *read* from the documents, not only what it
    concluded — the two are different questions and only one of them is a finding."""

    normalization_warnings: list[str] = []
    document_ids: list[str] = []
    notes: str | None = None
    events: list[OwnershipEventResponse] = []


class SuccessionValidationResponse(BaseModel):
    """The result of assessing a bundle, filed or not."""

    report: SuccessionReportResponse
    normalization_warnings: list[str] = []
    persisted: bool
    case: SuccessionCaseDetail | None = None
    """Present only when the bundle was filed. A dry run returns the report alone."""
