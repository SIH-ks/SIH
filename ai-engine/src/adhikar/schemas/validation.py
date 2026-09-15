"""Validation contract: rule identifiers, findings, tolerances and the report.

The engine is *data-driven* in two senses:

1. Rules are registered functions discovered from a registry, not an if-ladder, so
   adding a rule is adding a function (see :mod:`adhikar.validation.rules`).
2. Every threshold a rule uses comes from :class:`ValidationPolicy`, loaded from
   ``policies/validation_policy.yaml``. A revenue department that surveys to a
   different tolerance changes the YAML, not the code.

Findings are addressed by **JSON path** into the extraction artifact. That is what
lets the reviewer console jump from a finding straight to the offending cell, and it
keeps findings meaningful when the record is re-extracted.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

__all__ = [
    "RuleCode",
    "RuleTolerance",
    "Severity",
    "ValidationIssue",
    "ValidationPolicy",
    "ValidationReport",
]


class Severity(StrEnum):
    """How much a finding should block downstream use of the record."""

    INFO = "info"
    """Worth recording; does not affect trust."""

    WARNING = "warning"
    """Plausible but unverified -- surface to the reviewer, allow the record through."""

    ERROR = "error"
    """The record contradicts itself. Requires human adjudication before use."""

    CRITICAL = "critical"
    """Structural failure -- extraction is unusable, or the record cannot be trusted
    for any downstream purpose (e.g. total area is zero, or shares exceed unity)."""

    @property
    def rank(self) -> int:
        return {"info": 0, "warning": 1, "error": 2, "critical": 3}[self.value]


class RuleCode(StrEnum):
    """Stable identifiers for every check. Never renumber -- these appear in audits."""

    # -- arithmetic consistency ------------------------------------------------------
    AREA_SUM_MISMATCH = "AREA_SUM_MISMATCH"
    """Sum of sub-division areas != printed total area."""

    AREA_SUM_EXCEEDS_TOTAL = "AREA_SUM_EXCEEDS_TOTAL"
    """Sub-divisions total more than the parent. Always an error, never rounding."""

    CLASSIFICATION_SPLIT_MISMATCH = "CLASSIFICATION_SPLIT_MISMATCH"
    """Cultivable + non-cultivable != total area."""

    AREA_COMPONENT_OUT_OF_RANGE = "AREA_COMPONENT_OUT_OF_RANGE"
    """An H-R-Sq.M component exceeds its natural range (are > 99, sq m > 99)."""

    TOTAL_AREA_MISSING = "TOTAL_AREA_MISSING"
    TOTAL_AREA_NON_POSITIVE = "TOTAL_AREA_NON_POSITIVE"

    ASSESSMENT_DISPROPORTIONATE = "ASSESSMENT_DISPROPORTIONATE"
    """A sub-division's revenue per unit area is a statistical outlier against its
    siblings -- a classic signature of a transcription error in either column."""

    # -- ownership ----------------------------------------------------------------------
    SHARE_SUM_NOT_UNITY = "SHARE_SUM_NOT_UNITY"
    SHARE_SUM_EXCEEDS_UNITY = "SHARE_SUM_EXCEEDS_UNITY"
    SHARE_MISSING = "SHARE_MISSING"
    """Multiple co-owners recorded with no shares stated -- apportionment undefined."""

    NO_OWNERS_RECORDED = "NO_OWNERS_RECORDED"
    DUPLICATE_OWNER_SERIAL = "DUPLICATE_OWNER_SERIAL"
    ORPHAN_OWNER_REFERENCE = "ORPHAN_OWNER_REFERENCE"
    """A sub-division references an owner serial that no owner row carries."""

    # -- mutation chain ------------------------------------------------------------------
    MUTATION_OUT_OF_SEQUENCE = "MUTATION_OUT_OF_SEQUENCE"
    MUTATION_DATE_IN_FUTURE = "MUTATION_DATE_IN_FUTURE"
    MUTATION_PENDING_UNRESOLVED = "MUTATION_PENDING_UNRESOLVED"
    """A pending mutation older than the policy's staleness horizon."""

    MUTATION_AREA_EXCEEDS_PARCEL = "MUTATION_AREA_EXCEEDS_PARCEL"
    OWNER_WITHOUT_MUTATION_TRAIL = "OWNER_WITHOUT_MUTATION_TRAIL"
    """A current owner who appears in no sanctioned mutation's ``to_parties``."""

    CORRECTION_CHANGED_AREA = "CORRECTION_CHANGED_AREA"
    """A mutation typed as a clerical correction that nonetheless moves area."""

    # -- ownership succession (cross-document; see adhikar.validation.succession) ---------
    # These are the only rules in the catalogue that judge a *relationship between
    # documents* rather than one record's internal consistency. Every one of them is
    # phrased as a statement about evidence, never about entitlement: the engine has
    # no basis to decide who inherits and deliberately carries no code that says so.
    SUCCESSION_OWNER_IDENTITY_MISMATCH = "SUCCESSION_OWNER_IDENTITY_MISMATCH"
    """The death certificate names somebody the previous record did not record as owner."""

    SUCCESSION_NAME_MATCH_APPROXIMATE = "SUCCESSION_NAME_MATCH_APPROXIMATE"
    """Two documents were linked on a fuzzy name match, not an exact one. Recorded
    explicitly so a chain that rests on an OCR-tolerant comparison says so."""

    SUCCESSION_EVENT_SEQUENCE_INVALID = "SUCCESSION_EVENT_SEQUENCE_INVALID"
    """An ownership-changing event is dated before the death it is said to follow."""

    SUCCESSION_RECORD_NOT_UPDATED_AFTER_DEATH = "SUCCESSION_RECORD_NOT_UPDATED_AFTER_DEATH"
    """A death is recorded but the register still shows the deceased as holder."""

    SUCCESSION_DEATH_RECORD_MISSING = "SUCCESSION_DEATH_RECORD_MISSING"
    SUCCESSION_MUTATION_MISSING = "SUCCESSION_MUTATION_MISSING"

    SUCCESSION_PARCEL_MISMATCH = "SUCCESSION_PARCEL_MISMATCH"
    """The before and after records identify different land."""

    SUCCESSION_MUTATION_PREDECESSOR_MISMATCH = "SUCCESSION_MUTATION_PREDECESSOR_MISMATCH"
    SUCCESSION_MUTATION_PARCEL_MISMATCH = "SUCCESSION_MUTATION_PARCEL_MISMATCH"

    SUCCESSION_SHARE_SUM_INCONSISTENT = "SUCCESSION_SHARE_SUM_INCONSISTENT"
    SUCCESSION_AREA_MISMATCH = "SUCCESSION_AREA_MISMATCH"

    SUCCESSION_HEIRS_NOT_IDENTIFIED = "SUCCESSION_HEIRS_NOT_IDENTIFIED"
    """No family member of the deceased is named anywhere in the submitted documents."""

    SUCCESSION_EVIDENCE_MISSING = "SUCCESSION_EVIDENCE_MISSING"
    """Ownership changed and no submitted document accounts for the change."""

    SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED = "SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED"
    """Several potential heirs are named and the record vests the whole parcel in a
    subset of them, with nothing on file addressing the allocation. Not an allegation:
    the finding is that the evidence is silent, and that is what it says."""

    SUCCESSION_UNEXPLAINED_TRANSITION = "SUCCESSION_UNEXPLAINED_TRANSITION"
    """Consecutive records show different holders with no event between them."""

    SUCCESSION_DOCUMENTS_CONTRADICT = "SUCCESSION_DOCUMENTS_CONTRADICT"
    SUCCESSION_DOCUMENT_UNREADABLE = "SUCCESSION_DOCUMENT_UNREADABLE"

    # -- encumbrance -----------------------------------------------------------------------
    ENCUMBRANCE_ACTIVE = "ENCUMBRANCE_ACTIVE"
    """Informational by default: a live charge exists. Consequential for buyers."""

    ENCUMBRANCE_STATUS_UNKNOWN = "ENCUMBRANCE_STATUS_UNKNOWN"

    # -- identifiers -------------------------------------------------------------------------
    IDENTIFIER_MISSING = "IDENTIFIER_MISSING"
    DUPLICATE_KHASRA_NUMBER = "DUPLICATE_KHASRA_NUMBER"
    JURISDICTION_INCOMPLETE = "JURISDICTION_INCOMPLETE"

    # -- extraction quality ---------------------------------------------------------------------
    LOW_OCR_CONFIDENCE = "LOW_OCR_CONFIDENCE"
    LOW_FIELD_CONFIDENCE = "LOW_FIELD_CONFIDENCE"
    UNRESOLVED_VOCABULARY = "UNRESOLVED_VOCABULARY"
    """A vernacular term that no alias resolved -- classification fell back to UNKNOWN."""

    TABLE_STRUCTURE_DEGRADED = "TABLE_STRUCTURE_DEGRADED"
    """Grid detection found materially fewer intersections than the layout implies."""

    # -- geospatial (discrepancy engine) -----------------------------------------------------------
    GEOMETRY_AREA_MISMATCH = "GEOMETRY_AREA_MISMATCH"
    GEOMETRY_NOT_FOUND = "GEOMETRY_NOT_FOUND"
    GEOMETRY_INVALID = "GEOMETRY_INVALID"
    GEOMETRY_OVERLAP = "GEOMETRY_OVERLAP"
    """This parcel's polygon overlaps a neighbouring parcel's -- an encroachment or a
    survey error, and the highest-value finding the system produces."""

    GEOMETRY_SLIVER = "GEOMETRY_SLIVER"
    """A gap between adjoining parcels that should share a boundary."""


class RuleTolerance(BaseModel):
    """Per-rule thresholds. Loaded from YAML; every field is optional."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    severity: Severity | None = None
    """Overrides the rule's built-in severity when set."""

    absolute_sq_metre: Decimal | None = None
    """Absolute area tolerance, in square metres."""

    relative: Decimal | None = None
    """Relative tolerance as a fraction, e.g. ``0.005`` for 0.5%."""

    min_confidence: float | None = None
    z_score_threshold: float | None = None
    max_age_days: int | None = None

    risk_points: float | None = Field(default=None, ge=0.0, le=100.0)
    """Weight this rule carries in the succession risk score (0-100).

    Only the succession rules read it. It lives in the policy rather than in code
    for the same reason the area tolerances do: how heavily an unexplained transfer
    should rank against a parcel mismatch is a departmental judgement, and a score
    nobody can re-weight without a code change is a score nobody can calibrate.
    """

    note: str = ""


class ValidationPolicy(BaseModel):
    """The complete tolerance configuration for a validation run."""

    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    description: str = ""
    state: str | None = None
    """Set when the policy is state-specific; surfaced in the report for audit."""

    default_absolute_sq_metre: Decimal = Decimal("1.0")
    default_relative: Decimal = Decimal("0.005")
    default_min_confidence: float = 0.60

    rules: dict[RuleCode, RuleTolerance] = Field(default_factory=dict)

    def tolerance_for(self, code: RuleCode) -> RuleTolerance:
        """Tolerance for a rule, backfilled from the policy defaults."""
        configured = self.rules.get(code, RuleTolerance())
        return RuleTolerance(
            enabled=configured.enabled,
            severity=configured.severity,
            absolute_sq_metre=(
                configured.absolute_sq_metre
                if configured.absolute_sq_metre is not None
                else self.default_absolute_sq_metre
            ),
            relative=configured.relative if configured.relative is not None else self.default_relative,
            min_confidence=(
                configured.min_confidence
                if configured.min_confidence is not None
                else self.default_min_confidence
            ),
            z_score_threshold=configured.z_score_threshold,
            max_age_days=configured.max_age_days,
            risk_points=configured.risk_points,
            note=configured.note,
        )

    def is_enabled(self, code: RuleCode) -> bool:
        return self.rules.get(code, RuleTolerance()).enabled


class ValidationIssue(BaseModel):
    """A single finding, addressed to a location in the artifact."""

    model_config = ConfigDict(extra="forbid")

    rule_code: RuleCode
    severity: Severity
    message: str
    """Written for a revenue official, not a developer: state what is wrong with the
    record, in record vocabulary, with the numbers that make it checkable."""

    json_path: str = "$"
    """RFC 9535-style path into the artifact, e.g. ``$.parcels[0].sub_divisions[2].area``."""

    parcel_key: str | None = None
    observed: Any = None
    expected: Any = None
    delta: Decimal | None = None
    """Signed difference where the rule is numeric: observed - expected."""

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    """How sure the engine is that this finding is real, not an extraction artefact.
    An area mismatch on a page that OCR'd at 0.4 confidence is probably a misread
    digit, and this field is how the reviewer queue knows to sort it differently."""

    remediation: str | None = None
    """The concrete next step, e.g. 'Re-examine the Hissa 2 area cell on page 1'."""

    evidence: dict[str, Any] = Field(default_factory=dict)
    """Rule-specific supporting numbers, rendered verbatim in the console."""


class ValidationReport(BaseModel):
    """The outcome of a validation run over one artifact."""

    model_config = ConfigDict(extra="forbid")

    policy_name: str = "default"
    issues: list[ValidationIssue] = Field(default_factory=list)
    rules_evaluated: list[RuleCode] = Field(default_factory=list)
    rules_skipped: list[RuleCode] = Field(default_factory=list)
    """Disabled by policy, or inapplicable because required fields were absent."""

    duration_ms: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def counts_by_severity(self) -> dict[str, int]:
        counter = Counter(issue.severity.value for issue in self.issues)
        return {s.value: counter.get(s.value, 0) for s in Severity}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def highest_severity(self) -> Severity | None:
        return max((i.severity for i in self.issues), key=lambda s: s.rank, default=None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_blocking(self) -> bool:
        """Whether the record should be withheld from automated downstream use."""
        return any(i.severity.rank >= Severity.ERROR.rank for i in self.issues)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def integrity_score(self) -> float:
        """A 0-1 summary of internal consistency.

        Each finding subtracts a severity-weighted penalty, scaled by the engine's own
        confidence in that finding, from a perfect score. It is a triage aid for
        ordering a review queue -- it is deliberately not a probability, and nothing
        downstream should treat it as one.
        """
        penalty = 0.0
        weights = {Severity.INFO: 0.0, Severity.WARNING: 0.04, Severity.ERROR: 0.15, Severity.CRITICAL: 0.40}
        for issue in self.issues:
            penalty += weights[issue.severity] * issue.confidence
        return round(max(0.0, 1.0 - penalty), 4)

    def issues_for(self, code: RuleCode) -> list[ValidationIssue]:
        return [i for i in self.issues if i.rule_code is code]

    def sorted_issues(self) -> list[ValidationIssue]:
        """Most severe first, then most confident -- the reviewer queue order."""
        return sorted(self.issues, key=lambda i: (-i.severity.rank, -i.confidence, i.json_path))
