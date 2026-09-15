"""Ownership succession and mutation validation.

Every other rule in this package checks one record against itself. These check a
*bundle* of documents against each other: the Jamabandi as it stood, a death
certificate, whatever the family filed, the mutation order, and the Jamabandi as it
stands now. That is a different input type, so it gets its own registry alongside
:mod:`adhikar.validation.registry` rather than being forced through a signature built
for a single parcel -- but everything downstream is shared. Findings come out as
ordinary :class:`~adhikar.schemas.validation.ValidationIssue` objects under codes in
the same :class:`~adhikar.schemas.validation.RuleCode` catalogue, scored against the
same YAML policy, so the reviewer console, the audit trail and the exports consume
them without a second code path.

What these rules do and do not conclude
---------------------------------------
This is a **document-validation and decision-support** engine. It has no model of
succession law and deliberately carries none: no "eldest son" rule, no default
spousal share, no notion of a person being entitled to anything. There is no rule
here that can return "fraud", and :class:`~adhikar.schemas.succession.SuccessionOutcome`
has no member for it -- a transfer whose paperwork is thin and a transfer that is
improper look identical from the documents alone, and a machine that guessed between
them would be writing a guess into somebody's land record.

The strongest statement the engine makes is
``SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED``, and what that code means is precisely:
*several potential heirs are named in the file, the record vests the parcel in a
subset of them, and no submitted document addresses the allocation.* That is a
statement about the evidence, checkable against the paper, and it routes the case to
a revenue officer rather than resolving it.

The ten checks
--------------
======  ==============================  =====================================================
Rule    Check                           Question
======  ==============================  =====================================================
S1      ``OWNER_IDENTITY_MATCH``        Is the deceased the owner the old record recorded?
S2      ``TRANSITION_AFTER_DEATH``      Did the ownership change follow the death?
S3      ``PARCEL_MATCH``                Do the old and new records describe the same land?
S4      ``MUTATION_PREDECESSOR_MATCH``  Does the mutation name the same person it took from?
S5      ``MUTATION_PARCEL_MATCH``       Does the mutation describe the same land?
S6      ``SHARE_AND_AREA_CONSISTENCY``  Do shares resolve and does the area survive intact?
S7      ``HEIRS_IDENTIFIED``            Does anything on file name the deceased's family?
S8      ``SUCCESSION_EVIDENCE``         Does any document account for the change at all?
S9      ``EXCLUSIVE_TRANSFER_EVIDENCE`` Is a transfer to a subset of the heirs addressed?
S10     ``TRANSITION_CHAIN_COMPLETE``   Does every change between records have an event?
======  ==============================  =====================================================

Four further checks cover the states a real filing arrives in --
``DEATH_RECORD_PRESENT``, ``MUTATION_RECORD_PRESENT``, ``DOCUMENT_CONSISTENCY`` and
``DOCUMENT_LEGIBILITY`` -- so a partial bundle produces a report naming exactly what
is missing instead of an exception.

Every check returns even when it cannot run: ``NOT_APPLICABLE`` is a recorded
outcome, so the report is complete evidence of what was and was not examined.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

from ..normalize.identifiers import IdentifierMatch, compare_identifier
from ..normalize.names import NAME_MATCH_THRESHOLD, NameMatch, match_names, name_similarity
from ..schemas.enums import MutationStatus, MutationType, RelationType
from ..schemas.succession import (
    CheckStatus,
    DeathRecord,
    EventParty,
    EvidenceRef,
    HeirCandidate,
    MutationRecord,
    OwnershipEntry,
    OwnershipEvent,
    OwnershipEventType,
    ParcelIdentity,
    RecordSnapshot,
    RiskContribution,
    RiskLevel,
    SuccessionAction,
    SuccessionCase,
    SuccessionCheck,
    SuccessionDocumentType,
    SuccessionEventType,
    SuccessionOutcome,
    SuccessionReport,
    SupportingDocument,
)
from ..schemas.validation import RuleCode, ValidationPolicy
from .policy import DEFAULT_POLICY

__all__ = [
    "DEFAULT_RISK_POINTS",
    "RISK_BANDS",
    "STATUS_MULTIPLIER",
    "SuccessionContext",
    "build_timeline",
    "registered_succession_rules",
    "succession_rule",
    "validate_documents",
    "validate_succession",
]


# ======================================================================================
# Scoring configuration
# ======================================================================================

DEFAULT_RISK_POINTS: dict[RuleCode, float] = {
    # Contradictions between documents rank highest: they are the findings the
    # engine is most certain about, because both halves are on paper in front of it.
    RuleCode.SUCCESSION_DOCUMENTS_CONTRADICT: 55.0,
    RuleCode.SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED: 55.0,
    RuleCode.SUCCESSION_PARCEL_MISMATCH: 50.0,
    RuleCode.SUCCESSION_UNEXPLAINED_TRANSITION: 50.0,
    RuleCode.SUCCESSION_EVENT_SEQUENCE_INVALID: 45.0,
    RuleCode.SUCCESSION_EVIDENCE_MISSING: 45.0,
    RuleCode.SUCCESSION_OWNER_IDENTITY_MISMATCH: 40.0,
    RuleCode.SUCCESSION_MUTATION_PREDECESSOR_MISMATCH: 35.0,
    RuleCode.SUCCESSION_MUTATION_PARCEL_MISMATCH: 35.0,
    RuleCode.SUCCESSION_AREA_MISMATCH: 30.0,
    RuleCode.SUCCESSION_SHARE_SUM_INCONSISTENT: 25.0,
    RuleCode.SUCCESSION_MUTATION_MISSING: 20.0,
    RuleCode.SUCCESSION_DEATH_RECORD_MISSING: 18.0,
    # A record the office simply has not got round to updating is a backlog item,
    # not a suspicious one, and is weighted as such.
    RuleCode.SUCCESSION_RECORD_NOT_UPDATED_AFTER_DEATH: 15.0,
    RuleCode.SUCCESSION_HEIRS_NOT_IDENTIFIED: 15.0,
    RuleCode.SUCCESSION_DOCUMENT_UNREADABLE: 12.0,
    RuleCode.SUCCESSION_NAME_MATCH_APPROXIMATE: 6.0,
}
"""Base weight each finding carries, before the status multiplier.

Overridable per rule from ``policies/validation_policy.yaml`` via
:attr:`~adhikar.schemas.validation.RuleTolerance.risk_points`; these are the
built-in fallbacks so the engine scores sensibly with no policy file present.
"""

STATUS_MULTIPLIER: dict[CheckStatus, float] = {
    CheckStatus.FAIL: 1.0,
    CheckStatus.REVIEW_REQUIRED: 0.85,
    CheckStatus.WARNING: 0.45,
    CheckStatus.PASS: 0.0,
    CheckStatus.NOT_APPLICABLE: 0.0,
}
"""How much of a rule's weight each outcome carries.

``REVIEW_REQUIRED`` sits just under ``FAIL`` rather than halfway to it: "the
documents do not establish this" is nearly as consequential for a reviewer's
worklist as "the documents contradict each other", and under-weighting it would sink
exactly the cases this feature exists to surface.
"""

RISK_BANDS: tuple[tuple[float, RiskLevel], ...] = (
    (70.0, RiskLevel.CRITICAL),
    (40.0, RiskLevel.HIGH),
    (15.0, RiskLevel.MEDIUM),
)
"""Score at or above which each band applies; anything below the last is ``LOW``.

Cut so that one maximal single finding reaches ``HIGH`` on its own but not
``CRITICAL`` -- reaching the top band takes either a contradiction between documents
or two independent problems agreeing, which is the standard a case should meet
before it jumps a revenue officer's queue.
"""


# ======================================================================================
# Registry
# ======================================================================================

SuccessionRuleFunction = Callable[["SuccessionContext"], Iterable[SuccessionCheck]]


@dataclass(slots=True, frozen=True)
class _RegisteredSuccessionRule:
    name: str
    primary_code: RuleCode
    func: SuccessionRuleFunction
    description: str
    also_emits: tuple[tuple[RuleCode, str], ...] = ()


_REGISTRY: dict[str, _RegisteredSuccessionRule] = {}


def succession_rule(
    name: str,
    primary_code: RuleCode,
    *,
    description: str = "",
    also_emits: dict[RuleCode, str] | None = None,
) -> Callable[[SuccessionRuleFunction], SuccessionRuleFunction]:
    """Register one succession check under its positive-sense name.

    ``primary_code`` is the catalogue code the policy enables or disables the whole
    check by. A rule may still *emit* findings under other codes -- S2 reports either
    an invalid sequence or a record nobody has updated yet -- because those are two
    outcomes of one comparison and separating them into two rules would mean running
    the comparison twice. Those secondary codes are declared in ``also_emits`` so the
    published rule catalogue lists every code the engine can actually produce -- a
    catalogue that showed one of them as unregistered would be telling a reviewer
    that the finding in front of them came from nowhere.

    :raises ValueError: on a duplicate name -- a copy-pasted decorator is a
        programming error, not a runtime condition to absorb quietly.
    """

    def decorator(func: SuccessionRuleFunction) -> SuccessionRuleFunction:
        if name in _REGISTRY:
            raise ValueError(
                f"succession rule {name!r} is already registered by "
                f"{_REGISTRY[name].func.__qualname__}; cannot register {func.__qualname__}"
            )
        _REGISTRY[name] = _RegisteredSuccessionRule(
            name=name,
            primary_code=primary_code,
            func=func,
            description=description,
            also_emits=tuple((also_emits or {}).items()),
        )
        return func

    return decorator


def registered_succession_rules() -> dict[RuleCode, str]:
    """Every registered succession rule's primary code and description.

    Shaped like :func:`adhikar.validation.registry.registered_rules` so the backend's
    ``GET /system/rules`` can merge the two catalogues without special-casing either.
    """
    catalogue: dict[RuleCode, str] = {}
    for entry in _REGISTRY.values():
        catalogue[entry.primary_code] = entry.description
        catalogue.update(entry.also_emits)
    return catalogue


# ======================================================================================
# Derived context
# ======================================================================================


@dataclass(slots=True)
class _DeceasedLink:
    """A death certificate, and the recorded owner it was matched to (or was not)."""

    death: DeathRecord
    owner: OwnershipEntry | None
    match: NameMatch | None

    @property
    def is_recorded_owner(self) -> bool:
        return self.owner is not None


@dataclass(slots=True)
class SuccessionContext:
    """Everything the rules derive once and then share.

    Built before any rule runs, for two reasons. Recomputing "which owners left the
    record" inside six different rules invites the six copies to drift apart, and a
    reviewer reading two findings that disagree about who left has no way to tell
    which one to believe. And name matching is the expensive part of this engine --
    doing it once keeps a fourteen-check report comfortably inside a request.
    """

    case: SuccessionCase
    policy: ValidationPolicy
    name_threshold: float = NAME_MATCH_THRESHOLD

    previous: RecordSnapshot | None = None
    current: RecordSnapshot | None = None
    previous_owners: list[OwnershipEntry] = field(default_factory=list)
    current_owners: list[OwnershipEntry] = field(default_factory=list)

    departed: list[OwnershipEntry] = field(default_factory=list)
    """Owners on the earlier record with no counterpart on the later one."""

    arrived: list[OwnershipEntry] = field(default_factory=list)
    """Owners on the later record with no counterpart on the earlier one."""

    retained: list[tuple[OwnershipEntry, OwnershipEntry]] = field(default_factory=list)
    transition_detected: bool = False
    deceased_links: list[_DeceasedLink] = field(default_factory=list)
    heirs: list[HeirCandidate] = field(default_factory=list)
    approximate_links: list[tuple[str, NameMatch]] = field(default_factory=list)
    """Every cross-document link that rested on a fuzzy rather than exact name match,
    with the context it was made in. Rule S15 reports them so a chain built on
    approximate identity is never presented as if it were built on exact identity."""

    # -- convenience accessors --------------------------------------------------

    @property
    def deceased_owner_links(self) -> list[_DeceasedLink]:
        return [link for link in self.deceased_links if link.is_recorded_owner]

    @property
    def deceased_names(self) -> list[str]:
        return [link.death.person.raw for link in self.deceased_links]

    @property
    def death_verified(self) -> bool:
        return bool(self.deceased_owner_links)

    @property
    def transition_evidence(self) -> list[SupportingDocument]:
        return [d for d in self.case.supporting_documents if d.document_type.can_evidence_transition]

    @property
    def exclusivity_evidence(self) -> list[SupportingDocument]:
        return [
            d
            for d in self.case.supporting_documents
            if d.document_type.can_evidence_exclusive_transfer
        ]

    def risk_points(self, code: RuleCode) -> float:
        """This rule's weight, policy first, built-in default second."""
        configured = self.policy.tolerance_for(code).risk_points
        return configured if configured is not None else DEFAULT_RISK_POINTS.get(code, 20.0)

    def note_approximate(self, context: str, match: NameMatch) -> None:
        if match.is_approximate:
            self.approximate_links.append((context, match))


def _match_owner(name: str, owners: list[OwnershipEntry], threshold: float) -> tuple[OwnershipEntry | None, NameMatch | None]:
    """Best-scoring owner at or above ``threshold``, with the match that justified it."""
    best_owner: OwnershipEntry | None = None
    best_match: NameMatch | None = None
    for owner in owners:
        candidate = match_names(name, owner.name.raw, threshold=threshold)
        if best_match is None or candidate.score > best_match.score:
            best_owner, best_match = owner, candidate
    if best_match is not None and best_match.matched:
        return best_owner, best_match
    return None, best_match


def _diff_owners(
    before: list[OwnershipEntry], after: list[OwnershipEntry], threshold: float
) -> tuple[list[OwnershipEntry], list[OwnershipEntry], list[tuple[OwnershipEntry, OwnershipEntry]]]:
    """Who left, who arrived, and who stayed, matching names tolerantly.

    Pairing is by best available match rather than by position: registers renumber
    owner serials freely between revenue years, and comparing row *n* to row *n*
    would report a transition every time somebody was inserted alphabetically.
    """
    unmatched_after = list(after)
    retained: list[tuple[OwnershipEntry, OwnershipEntry]] = []
    departed: list[OwnershipEntry] = []

    for owner in before:
        partner, match = _match_owner(owner.name.raw, unmatched_after, threshold)
        if partner is not None and match is not None and match.matched:
            retained.append((owner, partner))
            unmatched_after.remove(partner)
        else:
            departed.append(owner)

    return departed, unmatched_after, retained


def _collect_heirs(
    case: SuccessionCase,
    deceased_names: list[str],
    recorded_owners: list[str],
    threshold: float,
) -> list[HeirCandidate]:
    """Every person the submitted documents name as family of the deceased.

    Four sources, in order of directness: an explicit legal-heir or family document;
    the relation qualifier printed beside an owner name on any record
    (``Amit Sharma s/o Ramesh Sharma`` names Amit as a son on the face of the
    register); the same qualifier on a mutation's transferees; and the executants of
    a relinquishment, partition or settlement deed, who are by construction people
    the filing itself treats as having a claim.

    Nothing here decides anyone is an heir. It collects who the paperwork names, so
    rule S9 can ask whether the record accounts for all of them.
    """
    collected: dict[str, HeirCandidate] = {}
    inheriting_relations = {
        RelationType.SON_OF,
        RelationType.DAUGHTER_OF,
        RelationType.WIFE_OF,
        RelationType.WIDOW_OF,
        RelationType.HEIR_OF,
    }

    def add(candidate: HeirCandidate) -> None:
        key = candidate.name.raw.strip().casefold()
        if not key:
            return
        existing = collected.get(key)
        if existing is None:
            collected[key] = candidate
            return
        # A later source only ever adds detail; it never overwrites a stated relation
        # with UNKNOWN or a stated share with nothing.
        if existing.relation_to_deceased is RelationType.UNKNOWN:
            existing.relation_to_deceased = candidate.relation_to_deceased
        if existing.stated_share is None:
            existing.stated_share = candidate.stated_share
        if existing.source is None:
            existing.source = candidate.source

    for heir in case.heirs:
        add(heir.model_copy(deep=True))

    def from_relation(entry: OwnershipEntry, source: EvidenceRef | None) -> None:
        relation = entry.name.relation_type
        related_to = entry.name.relation_name
        if relation not in inheriting_relations or not related_to:
            return
        if not any(
            name_similarity(related_to, deceased) >= threshold for deceased in deceased_names
        ):
            return
        add(
            HeirCandidate(
                name=entry.name,
                relation_to_deceased=relation,
                deceased_name=related_to,
                source=source or entry.source,
            )
        )

    for snapshot in case.record_snapshots:
        for index, owner in enumerate(snapshot.owners):
            from_relation(owner, snapshot.evidence(f"owners[{index}].name", owner.display_name))

    for mutation in case.mutations:
        for index, owner in enumerate(mutation.new_owners):
            from_relation(owner, mutation.evidence(f"new_owners[{index}].name", owner.display_name))

    connected_names = [*deceased_names, *recorded_owners]
    for document in case.supporting_documents:
        if not document.document_type.can_evidence_exclusive_transfer:
            continue
        # Only from a deed that is demonstrably about *this* family: one naming the
        # deceased or a recorded owner of this parcel among its parties. Without that
        # test, an unrelated will sitting in the same bundle would enrol its testator
        # as a potential heir here and then be counted as explaining his own absence
        # from the record -- a check the bundle could satisfy by containing noise.
        parties = [*(e.raw for e in document.executants), *(b.name.raw for b in document.beneficiaries)]
        if not any(
            name_similarity(party, known) >= threshold
            for party in parties
            for known in connected_names
        ):
            continue
        for index, person in enumerate(document.executants):
            add(
                HeirCandidate(
                    name=person,
                    relation_to_deceased=person.relation_type,
                    deceased_name=person.relation_name,
                    source=document.evidence(f"executants[{index}]", str(person)),
                )
            )

    return list(collected.values())


def build_context(case: SuccessionCase, policy: ValidationPolicy) -> SuccessionContext:
    """Derive everything the rules share from the raw case."""
    threshold = NAME_MATCH_THRESHOLD
    ctx = SuccessionContext(case=case, policy=policy, name_threshold=threshold)

    ctx.previous = case.previous_record
    ctx.current = case.current_record
    if ctx.previous is not None and ctx.current is not None and ctx.previous is ctx.current:
        # One record submitted: there is a holding but no before/after to compare.
        ctx.current = None

    ctx.previous_owners = list(ctx.previous.owners) if ctx.previous else []
    ctx.current_owners = list(ctx.current.owners) if ctx.current else []

    if ctx.previous is not None and ctx.current is not None:
        ctx.departed, ctx.arrived, ctx.retained = _diff_owners(
            ctx.previous_owners, ctx.current_owners, threshold
        )
        share_changed = any(
            before.share != after.share for before, after in ctx.retained
        )
        ctx.transition_detected = bool(ctx.departed or ctx.arrived or share_changed)
    elif case.mutations:
        # No "after" record was submitted, but a mutation that names transferees is
        # itself an assertion that ownership changed -- the checks that can run on a
        # mutation alone should still run.
        ctx.transition_detected = any(m.new_owners for m in case.mutations)

    for death in case.death_records:
        owner, match = _match_owner(death.person.raw, ctx.previous_owners, threshold)
        ctx.deceased_links.append(_DeceasedLink(death=death, owner=owner, match=match))
        if match is not None:
            ctx.note_approximate(
                f"death certificate for '{death.person.raw}' linked to recorded owner", match
            )

    ctx.heirs = _collect_heirs(
        case,
        [link.death.person.raw for link in ctx.deceased_links],
        [o.name.raw for o in (*ctx.previous_owners, *ctx.current_owners)],
        threshold,
    )
    return ctx


# ======================================================================================
# Small shared helpers
# ======================================================================================


def _check(
    *,
    rule: str,
    code: RuleCode,
    status: CheckStatus,
    explanation: str,
    evidence: list[EvidenceRef] | None = None,
    match_score: float | None = None,
    confidence: float = 1.0,
    remediation: str | None = None,
) -> SuccessionCheck:
    return SuccessionCheck(
        rule=rule,
        rule_code=code,
        status=status,
        explanation=explanation,
        evidence=evidence or [],
        match_score=match_score,
        confidence=confidence,
        remediation=remediation,
    )


def _not_applicable(rule: str, code: RuleCode, why: str) -> SuccessionCheck:
    return _check(rule=rule, code=code, status=CheckStatus.NOT_APPLICABLE, explanation=why)


def _compare_parcels(left: ParcelIdentity, right: ParcelIdentity) -> list[IdentifierMatch]:
    """Every identifier the two documents both state, compared."""
    comparisons: list[IdentifierMatch] = []
    shared = set(left.identifier_fields) & set(right.identifier_fields)
    for name in sorted(shared):
        comparison = compare_identifier(
            name, left.identifier_fields[name], right.identifier_fields[name]
        )
        if comparison is not None:
            comparisons.append(comparison)
    return comparisons


def _areas_agree(
    left: Decimal, right: Decimal, policy: ValidationPolicy, code: RuleCode
) -> tuple[bool, Decimal, Decimal]:
    """Whether two areas agree within the policy's tolerance for ``code``.

    Returns the absolute and relative difference alongside the verdict so the
    explanation can quote the numbers a reviewer would check, rather than asserting
    agreement or disagreement without showing the margin.
    """
    tolerance = policy.tolerance_for(code)
    absolute = abs(left - right)
    base = max(abs(left), abs(right), Decimal(1))
    relative = absolute / base
    allowed_absolute = tolerance.absolute_sq_metre or Decimal("1.0")
    allowed_relative = tolerance.relative or Decimal("0.005")
    return (absolute <= allowed_absolute or relative <= allowed_relative), absolute, relative


def _names(entries: list[OwnershipEntry]) -> str:
    return ", ".join(e.display_name for e in entries) or "—"


# ======================================================================================
# S1 — Is the deceased the person the old record recorded as owner?
# ======================================================================================


@succession_rule(
    "OWNER_IDENTITY_MATCH",
    RuleCode.SUCCESSION_OWNER_IDENTITY_MISMATCH,
    description="Whether the person named on the death certificate is the owner the previous record recorded.",
)
def _s1_owner_identity(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "OWNER_IDENTITY_MATCH"
    code = RuleCode.SUCCESSION_OWNER_IDENTITY_MISMATCH

    if not ctx.case.death_records:
        yield _not_applicable(rule, code, "No death certificate was submitted with this case.")
        return

    if not ctx.previous_owners:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.REVIEW_REQUIRED,
            explanation=(
                "A death certificate was submitted, but no previous Record of Rights was "
                "provided to check the name against."
            ),
            evidence=[link.death.evidence("person.raw", link.death.person.raw) for link in ctx.deceased_links],
            remediation="Attach the Jamabandi / RoR as it stood before the transition.",
        )
        return

    for link in ctx.deceased_links:
        death_evidence = link.death.evidence("person.raw", link.death.person.raw)
        if link.owner is not None and link.match is not None:
            owner_evidence = link.owner.source or EvidenceRef(
                document_type=ctx.previous.document_type if ctx.previous else SuccessionDocumentType.JAMABANDI,
                document_label=ctx.previous.label if ctx.previous else "Previous record",
                field_path="owners[].name",
                value=link.owner.display_name,
            )
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.PASS,
                explanation=(
                    f"The death certificate names {link.death.person.raw}, who the previous record "
                    f"recorded as owner ({link.owner.display_name}). {link.match.describe()}."
                ),
                evidence=[death_evidence, owner_evidence],
                match_score=link.match.score,
                confidence=1.0 if link.match.is_exact else 0.85,
            )
        else:
            score = link.match.score if link.match else 0.0
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.FAIL,
                explanation=(
                    f"The death certificate names {link.death.person.raw}, who does not appear as an "
                    f"owner on the previous record (recorded owners: {_names(ctx.previous_owners)}). "
                    f"Closest name similarity was {score:.2f}, below the {ctx.name_threshold:.2f} "
                    "threshold at which the engine will link two names."
                ),
                evidence=[death_evidence],
                match_score=score,
                remediation=(
                    "Confirm the certificate relates to this parcel's recorded owner; a namesake in "
                    "the same village is common and is not the same person."
                ),
            )


# ======================================================================================
# S2 — Did the ownership change follow the death?
# ======================================================================================


@succession_rule(
    "TRANSITION_AFTER_DEATH",
    RuleCode.SUCCESSION_EVENT_SEQUENCE_INVALID,
    description="Whether the recorded ownership change is dated after the death it follows.",
    also_emits={
        RuleCode.SUCCESSION_RECORD_NOT_UPDATED_AFTER_DEATH: (
            "A death is recorded but the register still shows the deceased as the holder."
        )
    },
)
def _s2_transition_after_death(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "TRANSITION_AFTER_DEATH"
    code = RuleCode.SUCCESSION_EVENT_SEQUENCE_INVALID

    linked = ctx.deceased_owner_links
    if not linked:
        yield _not_applicable(
            rule, code, "No death certificate was matched to a previously recorded owner."
        )
        return

    if not ctx.transition_detected:
        holder_still_listed = [
            link for link in linked
            if any(
                name_similarity(link.death.person.raw, owner.name.raw) >= ctx.name_threshold
                for owner in (ctx.current_owners or ctx.previous_owners)
            )
        ]
        if holder_still_listed:
            names = ", ".join(link.death.person.raw for link in holder_still_listed)
            yield _check(
                rule=rule,
                code=RuleCode.SUCCESSION_RECORD_NOT_UPDATED_AFTER_DEATH,
                status=CheckStatus.WARNING,
                explanation=(
                    f"{names} is recorded as deceased, but the register still shows the same holder. "
                    "No mutation updating the record was found in the submitted documents."
                ),
                evidence=[link.death.evidence("date_of_death", link.death.date_of_death) for link in holder_still_listed],
                remediation="Check the village mutation register for a pending inheritance entry on this khata.",
            )
        else:
            yield _not_applicable(rule, code, "No ownership change was detected between the submitted records.")
        return

    transition_dates: list[tuple[date, EvidenceRef]] = []
    for mutation in ctx.case.mutations:
        if mutation.effective_date:
            transition_dates.append(
                (mutation.effective_date, mutation.evidence("order_date", mutation.effective_date))
            )
    # `stated_as_of`, not `as_of`: a snapshot anchored at the start of its revenue
    # year carries no real chronology, and ordering a death against an inferred
    # anchor would report every mid-year succession as dated before the death.
    if ctx.current is not None and ctx.current.stated_as_of:
        stated = ctx.current.stated_as_of
        transition_dates.append((stated, ctx.current.evidence("as_of", stated)))

    death_dates = [(link.death.date_of_death, link.death) for link in linked if link.death.date_of_death]

    if not death_dates or not transition_dates:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.REVIEW_REQUIRED,
            explanation=(
                "An ownership change and a death are both recorded, but the documents do not carry "
                "enough dates to establish which came first."
                + ("" if death_dates else " No date of death was read from the certificate.")
                + (
                    ""
                    if transition_dates
                    else " No date was read from the mutation, and the updated record is dated only "
                    "by revenue year, which is a range rather than a date."
                )
            ),
            evidence=[link.death.evidence("date_of_death", link.death.date_of_death) for link in linked],
            confidence=0.7,
            remediation="Supply the mutation order date and the registrar's date of death.",
        )
        return

    for death_date, death in death_dates:
        for transition_date, evidence in transition_dates:
            if transition_date < death_date:
                yield _check(
                    rule=rule,
                    code=code,
                    status=CheckStatus.FAIL,
                    explanation=(
                        f"An ownership-changing event is dated {transition_date}, before the recorded "
                        f"death of {death.person.raw} on {death_date}. A succession cannot precede the "
                        "death it follows; one of the two dates is wrong, or the transfer was not a succession."
                    ),
                    evidence=[death.evidence("date_of_death", death_date), evidence],
                    remediation="Verify both dates against the source documents before acting on either.",
                )
                return

    earliest = min(transition_dates, key=lambda item: item[0])
    latest_death = max(death_dates, key=lambda item: item[0])
    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.PASS,
        explanation=(
            f"The ownership change is dated {earliest[0]}, after the recorded death of "
            f"{latest_death[1].person.raw} on {latest_death[0]}."
        ),
        evidence=[latest_death[1].evidence("date_of_death", latest_death[0]), earliest[1]],
    )


# ======================================================================================
# S3 — Do the old and new records describe the same land?
# ======================================================================================


@succession_rule(
    "PARCEL_MATCH",
    RuleCode.SUCCESSION_PARCEL_MISMATCH,
    description="Whether the previous and current Records of Rights identify the same parcel.",
)
def _s3_parcel_match(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "PARCEL_MATCH"
    code = RuleCode.SUCCESSION_PARCEL_MISMATCH

    if ctx.previous is None or ctx.current is None:
        yield _not_applicable(
            rule, code, "Both a previous and a current Record of Rights are needed to compare parcels."
        )
        return

    yield from _parcel_comparison_check(
        ctx,
        rule=rule,
        code=code,
        left=ctx.previous.parcel,
        right=ctx.current.parcel,
        left_label=ctx.previous.label,
        right_label=ctx.current.label,
        left_evidence=ctx.previous.evidence,
        right_evidence=ctx.current.evidence,
    )


def _parcel_comparison_check(
    ctx: SuccessionContext,
    *,
    rule: str,
    code: RuleCode,
    left: ParcelIdentity,
    right: ParcelIdentity,
    left_label: str,
    right_label: str,
    left_evidence,  # noqa: ANN001 - a bound `evidence` method on either document model
    right_evidence,  # noqa: ANN001
) -> Iterable[SuccessionCheck]:
    """Shared body of S3 and S5: compare two documents' parcel identifiers."""
    comparisons = _compare_parcels(left, right)

    if not comparisons:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.REVIEW_REQUIRED,
            explanation=(
                f"{left_label} and {right_label} state no identifier in common, so the engine cannot "
                "establish that they describe the same land."
            ),
            evidence=[
                left_evidence("parcel", left.display_key),
                right_evidence("parcel", right.display_key),
            ],
            confidence=0.8,
            remediation="Confirm the khasra / khata number on both documents.",
        )
        return

    conflicts = [c for c in comparisons if not c.equal and not c.related]
    related = [c for c in comparisons if not c.equal and c.related]
    agreed = [c for c in comparisons if c.equal]

    if conflicts:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.FAIL,
            explanation=(
                f"{left_label} and {right_label} describe different land: "
                + "; ".join(c.describe() for c in conflicts)
                + (f". They agree on {', '.join(c.field for c in agreed)}." if agreed else ".")
            ),
            evidence=[
                left_evidence(c.field, c.left) for c in conflicts
            ] + [right_evidence(c.field, c.right) for c in conflicts],
            remediation="Re-read the identifier cells on both scans; a succession case must concern one parcel.",
        )
        return

    if related:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.WARNING,
            explanation=(
                f"{left_label} and {right_label} refer to the same survey number at different levels of "
                "sub-division: " + "; ".join(c.describe() for c in related)
                + ". This is routine shorthand in some districts and a genuine mismatch in others."
            ),
            evidence=[left_evidence(c.field, c.left) for c in related]
            + [right_evidence(c.field, c.right) for c in related],
            confidence=0.7,
            remediation="Confirm whether the transfer concerns the whole survey number or the hissa.",
        )
        return

    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.PASS,
        explanation=(
            f"{left_label} and {right_label} agree on "
            + ", ".join(f"{c.field} ({c.left})" for c in agreed)
            + "."
        ),
        evidence=[left_evidence(c.field, c.left) for c in agreed[:3]]
        + [right_evidence(c.field, c.right) for c in agreed[:3]],
    )


# ======================================================================================
# S4 — Does the mutation name the same person it took from?
# ======================================================================================


@succession_rule(
    "MUTATION_PREDECESSOR_MATCH",
    RuleCode.SUCCESSION_MUTATION_PREDECESSOR_MISMATCH,
    description="Whether the mutation's transferor is the owner the previous record recorded.",
)
def _s4_mutation_predecessor(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "MUTATION_PREDECESSOR_MATCH"
    code = RuleCode.SUCCESSION_MUTATION_PREDECESSOR_MISMATCH

    if not ctx.case.mutations:
        yield _not_applicable(rule, code, "No mutation record was submitted with this case.")
        return
    if not ctx.previous_owners:
        yield _not_applicable(
            rule, code, "No previous Record of Rights was submitted to compare the transferor against."
        )
        return

    for mutation in ctx.case.mutations:
        label = mutation.document_label or f"Mutation {mutation.mutation_number or '(unnumbered)'}"
        if not mutation.previous_owners:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.WARNING,
                explanation=(
                    f"{label} does not name the person the parcel was transferred from, so it cannot "
                    f"be tied to the previous recorded owner ({_names(ctx.previous_owners)})."
                ),
                evidence=[mutation.evidence("previous_owners", "not stated")],
                confidence=0.85,
                remediation="Obtain the full mutation order; the transferor is a required entry on it.",
            )
            continue

        for index, party in enumerate(mutation.previous_owners):
            owner, match = _match_owner(party.name.raw, ctx.previous_owners, ctx.name_threshold)
            if owner is not None and match is not None:
                ctx.note_approximate(f"{label} transferor linked to recorded owner", match)
                yield _check(
                    rule=rule,
                    code=code,
                    status=CheckStatus.PASS,
                    explanation=(
                        f"{label} records the transfer as coming from {party.display_name}, "
                        f"who the previous record recorded as owner. {match.describe()}."
                    ),
                    evidence=[
                        mutation.evidence(f"previous_owners[{index}].name", party.display_name),
                        owner.source
                        or EvidenceRef(field_path="owners[].name", value=owner.display_name),
                    ],
                    match_score=match.score,
                    confidence=1.0 if match.is_exact else 0.85,
                )
            else:
                yield _check(
                    rule=rule,
                    code=code,
                    status=CheckStatus.FAIL,
                    explanation=(
                        f"{label} records the transfer as coming from {party.display_name}, who is not "
                        f"an owner on the previous record ({_names(ctx.previous_owners)})."
                    ),
                    evidence=[mutation.evidence(f"previous_owners[{index}].name", party.display_name)],
                    match_score=match.score if match else 0.0,
                    remediation="Check whether the mutation belongs to a different khata.",
                )


# ======================================================================================
# S5 — Does the mutation describe the same land?
# ======================================================================================


@succession_rule(
    "MUTATION_PARCEL_MATCH",
    RuleCode.SUCCESSION_MUTATION_PARCEL_MISMATCH,
    description="Whether the mutation record identifies the same parcel as the Records of Rights.",
)
def _s5_mutation_parcel(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "MUTATION_PARCEL_MATCH"
    code = RuleCode.SUCCESSION_MUTATION_PARCEL_MISMATCH

    if not ctx.case.mutations:
        yield _not_applicable(rule, code, "No mutation record was submitted with this case.")
        return

    reference = ctx.previous if ctx.previous is not None else ctx.current
    if reference is None or not reference.parcel.identifier_fields:
        yield _not_applicable(
            rule, code, "No Record of Rights with parcel identifiers was submitted to compare against."
        )
        return

    for mutation in ctx.case.mutations:
        label = mutation.document_label or f"Mutation {mutation.mutation_number or '(unnumbered)'}"
        if not mutation.parcel.identifier_fields:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.WARNING,
                explanation=f"{label} does not state a khasra, khata or survey number for the land it transfers.",
                evidence=[mutation.evidence("parcel", "not stated")],
                confidence=0.85,
                remediation="Obtain the mutation order page carrying the land description.",
            )
            continue

        yield from _parcel_comparison_check(
            ctx,
            rule=rule,
            code=code,
            left=reference.parcel,
            right=mutation.parcel,
            left_label=reference.label,
            right_label=label,
            left_evidence=reference.evidence,
            right_evidence=mutation.evidence,
        )


# ======================================================================================
# S6 — Do shares resolve, and does the area survive the transfer intact?
# ======================================================================================


@succession_rule(
    "SHARE_AND_AREA_CONSISTENCY",
    RuleCode.SUCCESSION_SHARE_SUM_INCONSISTENT,
    description="Whether recorded shares resolve to the whole parcel and the area is unchanged by the transfer.",
    also_emits={
        RuleCode.SUCCESSION_AREA_MISMATCH: (
            "The area on the updated record or the mutation differs from the previous record."
        )
    },
)
def _s6_shares_and_area(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    yield from _share_checks(ctx)
    yield from _area_checks(ctx)


def _share_checks(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "SHARE_SUM_CONSISTENCY"
    code = RuleCode.SUCCESSION_SHARE_SUM_INCONSISTENT

    holdings: list[tuple[str, list[OwnershipEntry], EvidenceRef]] = []
    if ctx.current is not None and ctx.current_owners:
        holdings.append(
            (ctx.current.label, ctx.current_owners, ctx.current.evidence("owners[].share"))
        )
    for mutation in ctx.case.mutations:
        if mutation.new_owners:
            label = mutation.document_label or f"Mutation {mutation.mutation_number or '(unnumbered)'}"
            holdings.append((label, mutation.new_owners, mutation.evidence("new_owners[].share")))

    if not holdings:
        yield _not_applicable(rule, code, "No document states a post-transfer holding.")
        return

    for label, entries, evidence in holdings:
        stated = [e for e in entries if e.share is not None]
        if not stated:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.WARNING if len(entries) > 1 else CheckStatus.PASS,
                explanation=(
                    f"{label} names {len(entries)} holder(s) without stating a share for any of them."
                    + (
                        " With more than one holder, the apportionment between them is undefined."
                        if len(entries) > 1
                        else " With a single holder this is unambiguous."
                    )
                ),
                evidence=[evidence],
                confidence=0.9,
                remediation=(
                    "Obtain the share column from the updated record."
                    if len(entries) > 1
                    else None
                ),
            )
            continue

        total = sum((e.share.fraction for e in stated), Fraction(0))
        missing = len(entries) - len(stated)
        if total == 1 and missing == 0:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.PASS,
                explanation=(
                    f"{label}: the recorded shares sum to exactly the whole parcel "
                    f"({' + '.join(str(e.share) for e in stated)})."
                ),
                evidence=[evidence],
            )
        elif total > 1:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.FAIL,
                explanation=(
                    f"{label}: the recorded shares sum to {total}, which is more than the whole parcel."
                ),
                evidence=[evidence],
                remediation="Re-read the share column; holdings cannot total more than unity.",
            )
        else:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.WARNING,
                explanation=(
                    f"{label}: the recorded shares sum to {total}, leaving {1 - total} of the parcel "
                    "unaccounted for"
                    + (f", and {missing} holder(s) have no share stated." if missing else ".")
                ),
                evidence=[evidence],
                confidence=0.9,
                remediation="Confirm whether a co-sharer is missing from the record.",
            )


def _area_checks(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "AREA_CONSISTENCY"
    code = RuleCode.SUCCESSION_AREA_MISMATCH

    reference = ctx.previous
    if reference is None or reference.parcel.area is None:
        yield _not_applicable(rule, code, "The previous record states no total area to compare against.")
        return

    base = reference.parcel.area
    compared = 0

    candidates: list[tuple[str, Decimal, EvidenceRef]] = []
    if ctx.current is not None and ctx.current.parcel.area is not None:
        candidates.append(
            (
                ctx.current.label,
                ctx.current.parcel.area.sq_metre,
                ctx.current.evidence("total_area", ctx.current.parcel.area.format_native()),
            )
        )
    for mutation in ctx.case.mutations:
        label = mutation.document_label or f"Mutation {mutation.mutation_number or '(unnumbered)'}"
        area = mutation.parcel.area or mutation.area_transacted
        if area is not None:
            candidates.append((label, area.sq_metre, mutation.evidence("area", area.format_native())))

    for label, value, evidence in candidates:
        compared += 1
        agrees, absolute, relative = _areas_agree(base.sq_metre, value, ctx.policy, code)
        base_evidence = reference.evidence("total_area", base.format_native())
        if agrees:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.PASS,
                explanation=(
                    f"{reference.label} and {label} state the same area "
                    f"({base.format_native()}), within tolerance."
                ),
                evidence=[base_evidence, evidence],
            )
        elif value > base.sq_metre:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.FAIL,
                explanation=(
                    f"{label} states an area of {value} sq m against {base.sq_metre} sq m on "
                    f"{reference.label} — {absolute} sq m ({relative:.2%}) more. A succession cannot "
                    "enlarge the parcel it transfers."
                ),
                evidence=[base_evidence, evidence],
                remediation="Check both area cells against the scans, and whether a second khasra was merged in.",
            )
        else:
            yield _check(
                rule=rule,
                code=code,
                status=CheckStatus.WARNING,
                explanation=(
                    f"{label} states an area of {value} sq m against {base.sq_metre} sq m on "
                    f"{reference.label} — {absolute} sq m ({relative:.2%}) less. This is consistent with "
                    "a partial transfer, and with a misread area cell."
                ),
                evidence=[base_evidence, evidence],
                confidence=0.85,
                remediation="Confirm whether only part of the parcel was transferred.",
            )

    if compared == 0:
        yield _not_applicable(rule, code, "No other document states an area to compare.")


# ======================================================================================
# S7 — Does anything on file name the deceased's family?
# ======================================================================================


@succession_rule(
    "HEIRS_IDENTIFIED",
    RuleCode.SUCCESSION_HEIRS_NOT_IDENTIFIED,
    description="Whether the submitted documents name any family member of the deceased.",
)
def _s7_heirs_identified(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "HEIRS_IDENTIFIED"
    code = RuleCode.SUCCESSION_HEIRS_NOT_IDENTIFIED

    if not ctx.deceased_links and not ctx.transition_detected:
        yield _not_applicable(rule, code, "No death and no ownership change were detected.")
        return

    if not ctx.deceased_links:
        yield _not_applicable(rule, code, "No death certificate was submitted, so there is no deceased to relate heirs to.")
        return

    if ctx.heirs:
        described = ", ".join(
            f"{heir.display_name} ({heir.relation_label})" if heir.relation_to_deceased is not RelationType.UNKNOWN
            else heir.display_name
            for heir in ctx.heirs
        )
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation=(
                f"{len(ctx.heirs)} potential heir(s) are named in the submitted documents: {described}. "
                "This is who the paperwork names, not a determination of entitlement."
            ),
            evidence=[heir.source for heir in ctx.heirs if heir.source is not None][:5],
        )
        return

    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.WARNING,
        explanation=(
            "No family member of the deceased is named anywhere in the submitted documents, so the "
            "engine cannot tell whether the recorded transfer accounts for everyone with a claim."
        ),
        evidence=[link.death.evidence("person.raw", link.death.person.raw) for link in ctx.deceased_links],
        remediation="Obtain the legal-heir certificate or the family register extract for the deceased.",
    )


# ======================================================================================
# S8 — Does any document account for the change at all?
# ======================================================================================


@succession_rule(
    "SUCCESSION_EVIDENCE",
    RuleCode.SUCCESSION_EVIDENCE_MISSING,
    description="Whether any submitted document explains the recorded change of ownership.",
)
def _s8_succession_evidence(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "SUCCESSION_EVIDENCE"
    code = RuleCode.SUCCESSION_EVIDENCE_MISSING

    if not ctx.transition_detected:
        yield _not_applicable(rule, code, "No ownership change was detected between the submitted records.")
        return

    sanctioned = [m for m in ctx.case.mutations if m.status is MutationStatus.SANCTIONED]
    unsanctioned = [m for m in ctx.case.mutations if m.status is not MutationStatus.SANCTIONED]
    supporting = ctx.transition_evidence

    if sanctioned or supporting:
        named = [
            *(
                (m.document_label or f"Mutation {m.mutation_number or '(unnumbered)'}")
                for m in sanctioned
            ),
            *(d.display_label for d in supporting),
        ]
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation=(
                "The change of ownership is accounted for by " + ", ".join(named) + ". "
                "Whether those documents are themselves valid, registered or current is outside "
                "what this check establishes."
            ),
            evidence=[m.evidence("status", m.status.value) for m in sanctioned]
            + [d.evidence("reference", d.reference) for d in supporting],
        )
        return

    if unsanctioned:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.WARNING,
            explanation=(
                "The only document offered for the change of ownership is a mutation that is not "
                "recorded as sanctioned ("
                + ", ".join(f"{m.mutation_number or 'unnumbered'}: {m.status.value}" for m in unsanctioned)
                + "). The register has been updated ahead of the order."
            ),
            evidence=[m.evidence("status", m.status.value) for m in unsanctioned],
            remediation="Obtain the sanctioned mutation order before treating the transfer as recorded.",
        )
        return

    # REVIEW_REQUIRED, not FAIL: an absent explanation is not a contradiction
    # between two documents -- there is only the one comparison an absent mutation
    # cannot supply a second side of. FAIL is reserved for cases where two
    # submitted documents actively disagree (see DOCUMENT_CONSISTENCY); routing a
    # bare evidence gap through it would report "nothing was filed" as "the
    # paperwork disagrees with itself", which is a different -- and false -- claim.
    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.REVIEW_REQUIRED,
        explanation=(
            f"Ownership changed from {_names(ctx.previous_owners)} to {_names(ctx.current_owners)}, "
            "and no submitted document — mutation order, will, relinquishment, partition, family "
            "settlement or court order — accounts for the change. This is a gap in the evidence, "
            "not a finding that the transfer was improper."
        ),
        evidence=[
            e for e in (
                ctx.previous.evidence("owners", _names(ctx.previous_owners)) if ctx.previous else None,
                ctx.current.evidence("owners", _names(ctx.current_owners)) if ctx.current else None,
            ) if e is not None
        ],
        remediation="Obtain the mutation order or transfer deed that produced this entry.",
    )


# ======================================================================================
# S9 — Is a transfer to a subset of the named heirs addressed by anything on file?
# ======================================================================================


@succession_rule(
    "EXCLUSIVE_TRANSFER_EVIDENCE",
    RuleCode.SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED,
    description=(
        "Whether a transfer to fewer than all the named potential heirs is addressed by a submitted "
        "document. Reports what the evidence does or does not establish; never that a transfer is improper."
    ),
)
def _s9_exclusive_transfer(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "EXCLUSIVE_TRANSFER_EVIDENCE"
    code = RuleCode.SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED

    if not ctx.transition_detected or not ctx.deceased_owner_links:
        yield _not_applicable(rule, code, "No death-related ownership change was detected.")
        return
    if len(ctx.heirs) <= 1:
        yield _not_applicable(
            rule, code, "Fewer than two potential heirs are named, so there is no allocation between them to explain."
        )
        return

    recipients = ctx.current_owners or [o for m in ctx.case.mutations for o in m.new_owners]
    if not recipients:
        yield _not_applicable(rule, code, "No post-transfer holding was stated to compare against the heirs.")
        return

    recipient_names = [r.name.raw for r in recipients]
    excluded = [
        heir
        for heir in ctx.heirs
        if not any(
            name_similarity(heir.name.raw, name) >= ctx.name_threshold for name in recipient_names
        )
    ]

    if not excluded:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation=(
                f"Every potential heir named in the documents ({', '.join(h.display_name for h in ctx.heirs)}) "
                "appears on the record after the transfer."
            ),
            evidence=[
                ctx.current.evidence("owners", _names(recipients))
                if ctx.current
                else EvidenceRef(field_path="new_owners", value=_names(recipients))
            ],
        )
        return

    excluded_names = ", ".join(h.display_name for h in excluded)
    holders = ", ".join(f"{r.display_name} ({r.share_text})" for r in recipients)
    holding_evidence = (
        ctx.current.evidence("owners", holders)
        if ctx.current is not None
        else EvidenceRef(field_path="new_owners", value=holders)
    )
    heir_evidence = [h.source for h in excluded if h.source is not None][:3]

    corroborating = _corroborating_documents(ctx, recipient_names, excluded)
    if corroborating.covers_all:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation=(
                f"The record vests the parcel in {holders}, and {excluded_names} "
                f"{'is' if len(excluded) == 1 else 'are'} named as a party to "
                + ", ".join(d.display_label for d in corroborating.documents)
                + ", which addresses the allocation. Whether that document is valid, registered or "
                "current is not something this check establishes."
            ),
            evidence=[holding_evidence, *heir_evidence]
            + [d.evidence("executants", d.display_label) for d in corroborating.documents],
            confidence=0.9,
            remediation="Verify the deed's registration particulars before acting on it.",
        )
        return

    if corroborating.documents:
        uncovered = ", ".join(h.display_name for h in corroborating.uncovered)
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.WARNING,
            explanation=(
                f"The record vests the parcel in {holders}. "
                + ", ".join(d.display_label for d in corroborating.documents)
                + f" addresses the transfer, but does not name {uncovered}, who "
                f"{'is' if len(corroborating.uncovered) == 1 else 'are'} also identified as a "
                "potential heir in the submitted documents."
            ),
            evidence=[holding_evidence, *heir_evidence]
            + [d.evidence("beneficiaries", d.display_label) for d in corroborating.documents],
            remediation=f"Obtain a relinquishment, settlement or order covering {uncovered}.",
        )
        return

    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.REVIEW_REQUIRED,
        explanation=(
            f"{len(ctx.heirs)} potential heirs are identified "
            f"({', '.join(h.display_name for h in ctx.heirs)}), and the current record transfers the "
            f"parcel to {holders}. No submitted document — will, relinquishment, partition, family "
            f"settlement, succession certificate or court order — explains the absence of "
            f"{excluded_names}. This is a statement about the evidence on file, not a finding that "
            "the transfer was improper; the revenue authority decides."
        ),
        evidence=[holding_evidence, *heir_evidence],
        remediation=(
            "Refer to the Revenue Officer for verification of the succession, and request any "
            "relinquishment, settlement or court order relied on."
        ),
    )


@dataclass(slots=True)
class _Corroboration:
    documents: list[SupportingDocument]
    uncovered: list[HeirCandidate]

    @property
    def covers_all(self) -> bool:
        return bool(self.documents) and not self.uncovered


def _corroborating_documents(
    ctx: SuccessionContext, recipient_names: list[str], excluded: list[HeirCandidate]
) -> _Corroboration:
    """Documents that speak to the allocation, and which excluded heirs they leave out.

    A document counts as speaking to the allocation only if it actually names one of
    the people the record now shows -- either as a beneficiary, or as the counterparty
    whose relinquishment the transfer rests on. A deed in the bundle that names nobody
    on the current record explains nothing about it, and treating mere presence as
    corroboration would make the check trivially satisfiable by attaching paperwork.
    """
    relevant: list[SupportingDocument] = []
    covered: set[str] = set()

    for document in ctx.exclusivity_evidence:
        beneficiary_names = [b.name.raw for b in document.beneficiaries]
        executant_names = [e.raw for e in document.executants]
        names_a_recipient = any(
            name_similarity(candidate, recipient) >= ctx.name_threshold
            for candidate in [*beneficiary_names, *executant_names]
            for recipient in recipient_names
        )
        names_an_excluded_heir = any(
            name_similarity(candidate, heir.name.raw) >= ctx.name_threshold
            for candidate in [*beneficiary_names, *executant_names]
            for heir in excluded
        )
        if not (names_a_recipient or names_an_excluded_heir):
            continue

        relevant.append(document)
        for heir in excluded:
            if any(
                name_similarity(candidate, heir.name.raw) >= ctx.name_threshold
                for candidate in [*beneficiary_names, *executant_names]
            ):
                covered.add(heir.name.raw.strip().casefold())

    uncovered = [h for h in excluded if h.name.raw.strip().casefold() not in covered]
    return _Corroboration(documents=relevant, uncovered=uncovered)


# ======================================================================================
# S10 — Does every change between consecutive records have an event behind it?
# ======================================================================================


@succession_rule(
    "TRANSITION_CHAIN_COMPLETE",
    RuleCode.SUCCESSION_UNEXPLAINED_TRANSITION,
    description="Whether every change of holder between consecutive records is accounted for by a recorded event.",
)
def _s10_chain_complete(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "TRANSITION_CHAIN_COMPLETE"
    code = RuleCode.SUCCESSION_UNEXPLAINED_TRANSITION

    snapshots = ctx.case.record_snapshots
    if len(snapshots) < 2:
        yield _not_applicable(
            rule, code, "At least two Records of Rights are needed to trace a chain of ownership."
        )
        return

    unexplained: list[str] = []
    evidence: list[EvidenceRef] = []
    explained = 0

    for earlier, later in zip(snapshots, snapshots[1:], strict=False):
        departed, arrived, _ = _diff_owners(earlier.owners, later.owners, ctx.name_threshold)
        if not departed and not arrived:
            continue

        if _event_explains(ctx, earlier, later, departed, arrived):
            explained += 1
            continue

        window = _window_label(earlier, later)
        unexplained.append(
            f"{window}: {_names(departed) if departed else 'no one'} → "
            f"{_names(arrived) if arrived else 'no one'}"
        )
        evidence.append(earlier.evidence("owners", _names(earlier.owners)))
        evidence.append(later.evidence("owners", _names(later.owners)))

    if unexplained:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.REVIEW_REQUIRED,
            explanation=(
                f"{len(unexplained)} ownership transition(s) appear in the register with no "
                "corresponding event in the submitted documents — "
                + "; ".join(unexplained)
                + ". An unexplained transition is a gap in the evidence, which may equally be a "
                "missing document as anything else."
            ),
            evidence=evidence[:6],
            remediation="Retrieve the mutation register entries covering these revenue years.",
        )
        return

    if explained:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation=(
                f"Each of the {explained} ownership change(s) across the {len(snapshots)} submitted "
                "records is accounted for by a mutation or a recorded death in the documents."
            ),
            evidence=[s.evidence("owners", _names(s.owners)) for s in snapshots][:4],
        )
        return

    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.PASS,
        explanation=f"The {len(snapshots)} submitted records show the same holders throughout.",
        evidence=[s.evidence("owners", _names(s.owners)) for s in snapshots][:4],
    )


def _window_label(earlier: RecordSnapshot, later: RecordSnapshot) -> str:
    left = earlier.revenue_year or (earlier.as_of.isoformat() if earlier.as_of else earlier.label)
    right = later.revenue_year or (later.as_of.isoformat() if later.as_of else later.label)
    return f"{left} → {right}"


def _event_explains(
    ctx: SuccessionContext,
    earlier: RecordSnapshot,
    later: RecordSnapshot,
    departed: list[OwnershipEntry],
    arrived: list[OwnershipEntry],
) -> bool:
    """Whether any submitted event accounts for this particular step in the chain.

    A mutation qualifies when it names at least one arriving holder as a transferee
    *and* falls inside the window between the two records (an undated mutation is
    allowed, since many orders reach the file without a legible date -- the
    alternative would be to report every such case as an unexplained transition,
    which would drown the ones that are).

    A death qualifies only in combination with some transition document: a death
    certificate alone explains why a holder left, never why a particular person
    arrived. That distinction is the whole substance of rule S9.
    """
    arrived_names = [a.name.raw for a in arrived]
    departed_names = [d.name.raw for d in departed]

    for mutation in ctx.case.mutations:
        when = mutation.effective_date
        if when is not None:
            if earlier.as_of and when < earlier.as_of:
                continue
            # `window_end`, not `as_of`: the later record is often dated only by
            # revenue year, and a mutation ordered in August of that year is inside
            # the window that produced it, not after it.
            if later.window_end and when > later.window_end:
                continue
        names_arrival = any(
            name_similarity(owner.name.raw, name) >= ctx.name_threshold
            for owner in mutation.new_owners
            for name in arrived_names
        )
        names_departure = any(
            name_similarity(owner.name.raw, name) >= ctx.name_threshold
            for owner in mutation.previous_owners
            for name in departed_names
        )
        if names_arrival or (names_departure and not arrived_names):
            return True

    death_of_departed = any(
        name_similarity(link.death.person.raw, name) >= ctx.name_threshold
        for link in ctx.deceased_links
        for name in departed_names
    )
    if death_of_departed and not arrived_names:
        return True
    if death_of_departed and ctx.transition_evidence:
        for document in ctx.transition_evidence:
            if any(
                name_similarity(b.name.raw, name) >= ctx.name_threshold
                for b in document.beneficiaries
                for name in arrived_names
            ):
                return True
    return False


# ======================================================================================
# Completeness and contradiction checks
# ======================================================================================


@succession_rule(
    "DEATH_RECORD_PRESENT",
    RuleCode.SUCCESSION_DEATH_RECORD_MISSING,
    description="Whether a death certificate was submitted for a transfer the documents treat as inheritance.",
)
def _s11_death_record_present(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "DEATH_RECORD_PRESENT"
    code = RuleCode.SUCCESSION_DEATH_RECORD_MISSING

    if ctx.case.death_records:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation=(
                f"{len(ctx.case.death_records)} death certificate(s) were submitted: "
                + ", ".join(d.person.raw for d in ctx.case.death_records)
                + "."
            ),
            evidence=[d.evidence("person.raw", d.person.raw) for d in ctx.case.death_records],
        )
        return

    inheritance_claimed = [
        m for m in ctx.case.mutations if m.mutation_type in {MutationType.INHERITANCE, MutationType.WILL}
    ]
    if not inheritance_claimed and not ctx.case.heirs:
        yield _not_applicable(
            rule, code, "Nothing in the submitted documents presents this transfer as a succession."
        )
        return

    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.WARNING,
        explanation=(
            "The submitted documents present this transfer as a succession"
            + (
                f" (mutation recorded as {inheritance_claimed[0].mutation_type.value})"
                if inheritance_claimed
                else " (heir details were filed)"
            )
            + ", but no death certificate was submitted."
        ),
        evidence=[m.evidence("mutation_type", m.mutation_type.value) for m in inheritance_claimed],
        remediation="Obtain the registrar's death certificate for the previous recorded owner.",
    )


@succession_rule(
    "MUTATION_RECORD_PRESENT",
    RuleCode.SUCCESSION_MUTATION_MISSING,
    description="Whether a mutation record accompanies a change of holder in the register.",
)
def _s12_mutation_present(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "MUTATION_RECORD_PRESENT"
    code = RuleCode.SUCCESSION_MUTATION_MISSING

    if ctx.case.mutations:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation=f"{len(ctx.case.mutations)} mutation record(s) were submitted with this case.",
            evidence=[m.evidence("mutation_number", m.mutation_number) for m in ctx.case.mutations],
        )
        return

    if not ctx.transition_detected:
        yield _not_applicable(rule, code, "No ownership change was detected, so no mutation is expected.")
        return

    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.WARNING,
        explanation=(
            "The register shows a change of holder but no mutation application or order was submitted, "
            "so there is nothing on file recording who ordered the change or on what basis."
        ),
        evidence=[
            e for e in (
                ctx.previous.evidence("owners", _names(ctx.previous_owners)) if ctx.previous else None,
                ctx.current.evidence("owners", _names(ctx.current_owners)) if ctx.current else None,
            ) if e is not None
        ],
        remediation="Retrieve the mutation (Intekal / Ferfar) entry for this khata.",
    )


@succession_rule(
    "DOCUMENT_CONSISTENCY",
    RuleCode.SUCCESSION_DOCUMENTS_CONTRADICT,
    description="Whether the submitted documents agree with each other on dates and on who takes the parcel.",
)
def _s13_documents_agree(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "DOCUMENT_CONSISTENCY"
    code = RuleCode.SUCCESSION_DOCUMENTS_CONTRADICT
    contradictions: list[tuple[str, list[EvidenceRef]]] = []

    # Two certificates for one person with different dates of death.
    for index, first in enumerate(ctx.case.death_records):
        for second in ctx.case.death_records[index + 1 :]:
            if (
                first.date_of_death
                and second.date_of_death
                and first.date_of_death != second.date_of_death
                and name_similarity(first.person.raw, second.person.raw) >= ctx.name_threshold
            ):
                contradictions.append(
                    (
                        f"two documents give different dates of death for {first.person.raw} "
                        f"({first.date_of_death} and {second.date_of_death})",
                        [
                            first.evidence("date_of_death", first.date_of_death),
                            second.evidence("date_of_death", second.date_of_death),
                        ],
                    )
                )

    # The mutation and the updated register name different transferees.
    if ctx.current_owners:
        current_names = [o.name.raw for o in ctx.current_owners]
        for mutation in ctx.case.mutations:
            if not mutation.new_owners:
                continue
            unmatched = [
                o
                for o in mutation.new_owners
                if not any(
                    name_similarity(o.name.raw, name) >= ctx.name_threshold for name in current_names
                )
            ]
            if unmatched and len(unmatched) == len(mutation.new_owners):
                label = mutation.document_label or f"Mutation {mutation.mutation_number or '(unnumbered)'}"
                contradictions.append(
                    (
                        f"{label} transfers to {_names(mutation.new_owners)}, but the updated record "
                        f"shows {_names(ctx.current_owners)}",
                        [
                            mutation.evidence("new_owners", _names(mutation.new_owners)),
                            ctx.current.evidence("owners", _names(ctx.current_owners))
                            if ctx.current
                            else EvidenceRef(field_path="owners", value=_names(ctx.current_owners)),
                        ],
                    )
                )

        # A will or court order naming beneficiaries the record does not show.
        for document in ctx.exclusivity_evidence:
            if not document.beneficiaries:
                continue
            unmatched = [
                b
                for b in document.beneficiaries
                if not any(
                    name_similarity(b.name.raw, name) >= ctx.name_threshold for name in current_names
                )
            ]
            if unmatched and len(unmatched) == len(document.beneficiaries):
                contradictions.append(
                    (
                        f"{document.display_label} names {_names(document.beneficiaries)} as taking the "
                        f"parcel, but the record shows {_names(ctx.current_owners)}",
                        [
                            document.evidence("beneficiaries", _names(document.beneficiaries)),
                            ctx.current.evidence("owners", _names(ctx.current_owners))
                            if ctx.current
                            else EvidenceRef(field_path="owners", value=_names(ctx.current_owners)),
                        ],
                    )
                )

    if not contradictions:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation="The submitted documents agree on dates and on who the parcel passed to.",
        )
        return

    for description, evidence in contradictions:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.FAIL,
            explanation=(
                f"Submitted documents contradict each other: {description}. Both cannot be correct; "
                "which one is, is an adjudication rather than a reading."
            ),
            evidence=evidence,
            remediation="Refer to the Revenue Officer; the contradiction cannot be resolved from the documents.",
        )


@succession_rule(
    "DOCUMENT_LEGIBILITY",
    RuleCode.SUCCESSION_DOCUMENT_UNREADABLE,
    description="Whether any submitted document was reported as unreadable.",
)
def _s14_legibility(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "DOCUMENT_LEGIBILITY"
    code = RuleCode.SUCCESSION_DOCUMENT_UNREADABLE

    illegible = ctx.case.illegible_documents
    if not illegible:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation="Every submitted document was readable.",
        )
        return

    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.WARNING,
        explanation=(
            f"{len(illegible)} submitted document(s) could not be read: "
            + "; ".join(ref.describe() for ref in illegible)
            + ". Every check that would have used them was evaluated without them, so this report is "
            "weaker evidence than it would otherwise be."
        ),
        evidence=illegible,
        remediation="Re-scan the affected documents at a higher resolution.",
    )


@succession_rule(
    "NAME_MATCH_QUALITY",
    RuleCode.SUCCESSION_NAME_MATCH_APPROXIMATE,
    description="Whether any cross-document link in this case rests on an approximate name match.",
)
def _s15_name_match_quality(ctx: SuccessionContext) -> Iterable[SuccessionCheck]:
    rule = "NAME_MATCH_QUALITY"
    code = RuleCode.SUCCESSION_NAME_MATCH_APPROXIMATE

    if not ctx.approximate_links:
        yield _check(
            rule=rule,
            code=code,
            status=CheckStatus.PASS,
            explanation="Every cross-document link in this case rests on an exact name match.",
        )
        return

    described = "; ".join(f"{context} — {match.describe()}" for context, match in ctx.approximate_links)
    yield _check(
        rule=rule,
        code=code,
        status=CheckStatus.WARNING,
        explanation=(
            f"{len(ctx.approximate_links)} link(s) in this chain rest on an approximate rather than "
            f"exact name match: {described}. The conclusions above are only as sound as those links."
        ),
        match_score=min(match.score for _, match in ctx.approximate_links),
        confidence=0.8,
        remediation="Confirm the spellings against the source documents before relying on the chain.",
    )


# ======================================================================================
# Timeline
# ======================================================================================


def _party(entry: OwnershipEntry) -> EventParty:
    return EventParty(
        name=entry.display_name,
        share=str(entry.share) if entry.share else None,
        relation=(
            entry.name.relation_type.value
            if entry.name.relation_type is not RelationType.UNKNOWN
            else None
        ),
    )


def build_timeline(case: SuccessionCase, ctx: SuccessionContext) -> list[OwnershipEvent]:
    """Derive the ownership event chain the console draws.

    Built from the case rather than stored beside it, so the timeline cannot come to
    disagree with the documents it depicts -- regenerating it is the only way it
    changes. Undated events keep their submission order and are marked
    ``date_stated=False`` so the console can draw an inferred position differently
    from a recorded one.
    """
    events: list[OwnershipEvent] = []
    parcel_key = case.parcel_key or case.parcel.display_key

    for index, snapshot in enumerate(case.record_snapshots):
        # A snapshot with no date at all -- the common real-world case for a
        # register-sourced "previous Record of Rights", which carries no revenue
        # year -- has no `window_end` to anchor it either. Falling back to the
        # generic undated-event rule (`date.max`, pushed to the end) would draw the
        # *baseline* ownership state as though it were the most recent thing on the
        # parcel, which is backwards. `case.record_snapshots` is already ordered
        # oldest-first by `_order_snapshots`, so a synthetic anchor that preserves
        # that position -- placed before every dated event, tie-broken by chain
        # order for more than one undated snapshot -- is the honest fallback: it
        # asserts nothing about *when*, only asserts what the case's own ordering
        # already established about *before/after*.
        anchor = snapshot.window_end
        if anchor is None:
            anchor = date.min + timedelta(days=index)
        events.append(
            OwnershipEvent(
                event_type=OwnershipEventType.RECORD_SNAPSHOT,
                event_date=snapshot.as_of,
                sort_anchor=anchor,
                date_stated=snapshot.as_of is not None and not snapshot.as_of_inferred,
                parcel_key=parcel_key,
                to_owners=[_party(o) for o in snapshot.owners],
                description=(
                    f"{snapshot.label}"
                    + (f" ({snapshot.revenue_year})" if snapshot.revenue_year else "")
                    + f" records {_names(snapshot.owners)}."
                ),
                evidence=[snapshot.evidence("owners", _names(snapshot.owners))],
            )
        )

    for link in ctx.deceased_links:
        death = link.death
        events.append(
            OwnershipEvent(
                event_type=OwnershipEventType.DEATH,
                event_date=death.date_of_death,
                date_stated=death.date_of_death is not None,
                parcel_key=parcel_key,
                person=death.person.raw,
                from_owners=[_party(link.owner)] if link.owner else [],
                description=(
                    f"{death.person.raw} recorded as deceased"
                    + (f" on {death.date_of_death}" if death.date_of_death else "")
                    + (
                        "; matched to the previously recorded owner."
                        if link.is_recorded_owner
                        else "; not matched to any recorded owner of this parcel."
                    )
                ),
                evidence=[death.evidence("date_of_death", death.date_of_death)],
            )
        )

    if ctx.heirs and ctx.deceased_links:
        events.append(
            OwnershipEvent(
                event_type=OwnershipEventType.SUCCESSION_CLAIM,
                event_date=None,
                # Undated on the paper, but it belongs with the death it arises from
                # rather than adrift at the end of the timeline.
                sort_anchor=next(
                    (link.death.date_of_death for link in ctx.deceased_links if link.death.date_of_death),
                    None,
                ),
                date_stated=False,
                parcel_key=parcel_key,
                person=ctx.deceased_names[0] if ctx.deceased_names else None,
                to_owners=[
                    EventParty(
                        name=heir.display_name,
                        share=str(heir.stated_share) if heir.stated_share else None,
                        relation=(
                            heir.relation_to_deceased.value
                            if heir.relation_to_deceased is not RelationType.UNKNOWN
                            else None
                        ),
                    )
                    for heir in ctx.heirs
                ],
                description=(
                    f"{len(ctx.heirs)} potential heir(s) named in the submitted documents. "
                    "Named, not adjudicated: this asserts nothing about entitlement or share."
                ),
                evidence=[h.source for h in ctx.heirs if h.source is not None][:4],
            )
        )

    for document in case.supporting_documents:
        events.append(
            OwnershipEvent(
                event_type=_EVENT_TYPE_BY_DOCUMENT.get(document.document_type, OwnershipEventType.OTHER),
                event_date=document.issued_on,
                date_stated=document.issued_on is not None,
                parcel_key=parcel_key,
                from_owners=[
                    EventParty(name=str(person)) for person in document.executants
                ],
                to_owners=[_party(b) for b in document.beneficiaries],
                description=(
                    f"{document.display_label}"
                    + (f" ({document.reference})" if document.reference else "")
                    + (
                        f" — executed by {', '.join(str(p) for p in document.executants)}"
                        if document.executants
                        else ""
                    )
                    + (
                        f"; names {_names(document.beneficiaries)}"
                        if document.beneficiaries
                        else ""
                    )
                    + "."
                ),
                evidence=[document.evidence("reference", document.reference)],
            )
        )

    for mutation in case.mutations:
        events.append(
            OwnershipEvent(
                event_type=OwnershipEventType.MUTATION,
                event_date=mutation.effective_date,
                date_stated=mutation.effective_date is not None,
                parcel_key=mutation.parcel.display_key if mutation.parcel.identifier_fields else parcel_key,
                from_owners=[_party(o) for o in mutation.previous_owners],
                to_owners=[_party(o) for o in mutation.new_owners],
                description=(
                    f"Mutation {mutation.mutation_number or '(unnumbered)'}"
                    + f" — {mutation.mutation_type.value}, {mutation.status.value}"
                    + (
                        f"; transfers from {_names(mutation.previous_owners)}"
                        if mutation.previous_owners
                        else ""
                    )
                    + (f" to {_names(mutation.new_owners)}" if mutation.new_owners else "")
                    + "."
                ),
                evidence=[mutation.evidence("status", mutation.status.value)],
            )
        )

    ordered = sorted(events, key=lambda e: e.sort_key)
    for index, event in enumerate(ordered):
        event.sequence = index
    return ordered


_EVENT_TYPE_BY_DOCUMENT: dict[SuccessionDocumentType, OwnershipEventType] = {
    SuccessionDocumentType.WILL: OwnershipEventType.WILL,
    SuccessionDocumentType.RELINQUISHMENT_DEED: OwnershipEventType.RELINQUISHMENT,
    SuccessionDocumentType.PARTITION_DEED: OwnershipEventType.PARTITION,
    SuccessionDocumentType.FAMILY_SETTLEMENT: OwnershipEventType.FAMILY_SETTLEMENT,
    SuccessionDocumentType.COURT_ORDER: OwnershipEventType.COURT_ORDER,
    SuccessionDocumentType.SUCCESSION_CERTIFICATE: OwnershipEventType.COURT_ORDER,
}


# ======================================================================================
# Scoring and assembly
# ======================================================================================


def _score(checks: list[SuccessionCheck], ctx: SuccessionContext) -> tuple[float, list[RiskContribution]]:
    """Sum every non-clear check's weighted contribution, capped at 100.

    A plain sum rather than a blend: the point of the score is that a reviewer can
    decompose it, and any aggregation cleverer than addition stops being explainable
    the moment two findings interact. The cap is applied to the total only, so each
    contribution still reports the points it actually carried.
    """
    contributions: list[RiskContribution] = []
    total = 0.0

    for check in checks:
        multiplier = STATUS_MULTIPLIER[check.status]
        if multiplier == 0.0:
            continue
        base = ctx.risk_points(check.rule_code)
        points = round(base * multiplier, 2)
        check.risk_points = points
        total += points
        contributions.append(
            RiskContribution(
                rule=check.rule,
                rule_code=check.rule_code,
                status=check.status,
                base_points=base,
                multiplier=multiplier,
                points=points,
                reason=check.explanation,
            )
        )

    contributions.sort(key=lambda c: -c.points)
    return round(min(total, 100.0), 2), contributions


def _band(score: float) -> RiskLevel:
    for threshold, level in RISK_BANDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


def _outcome(checks: list[SuccessionCheck]) -> SuccessionOutcome:
    """Worst status wins, mapped onto the four outcomes.

    ``FAIL`` means documents disagree on a matter of fact -- ``INCONSISTENT``.
    ``REVIEW_REQUIRED`` means they are consistent and do not establish the record.
    A ``WARNING`` is an evidence gap, so ``INCOMPLETE``.
    """
    worst = max((c.status for c in checks), key=lambda s: s.rank, default=CheckStatus.PASS)
    return {
        CheckStatus.FAIL: SuccessionOutcome.INCONSISTENT,
        CheckStatus.REVIEW_REQUIRED: SuccessionOutcome.REVIEW_REQUIRED,
        CheckStatus.WARNING: SuccessionOutcome.INCOMPLETE,
        CheckStatus.PASS: SuccessionOutcome.VALIDATED,
        CheckStatus.NOT_APPLICABLE: SuccessionOutcome.VALIDATED,
    }[worst]


_ACTION_BY_OUTCOME: dict[SuccessionOutcome, SuccessionAction] = {
    SuccessionOutcome.VALIDATED: SuccessionAction.ACCEPT_RECORD,
    SuccessionOutcome.INCOMPLETE: SuccessionAction.OBTAIN_ADDITIONAL_DOCUMENTS,
    SuccessionOutcome.REVIEW_REQUIRED: SuccessionAction.HUMAN_REVIEW,
    SuccessionOutcome.INCONSISTENT: SuccessionAction.REFER_TO_REVENUE_AUTHORITY,
}


def _classify_event(ctx: SuccessionContext) -> SuccessionEventType:
    if not ctx.case.record_snapshots and not ctx.case.mutations:
        return SuccessionEventType.INSUFFICIENT_DOCUMENTS
    if not ctx.transition_detected:
        return SuccessionEventType.NO_TRANSITION_DETECTED
    if ctx.deceased_owner_links:
        return SuccessionEventType.OWNER_DEATH_SUCCESSION
    return SuccessionEventType.OWNERSHIP_TRANSITION


def _issue_sentences(checks: list[SuccessionCheck], ctx: SuccessionContext) -> list[str]:
    """One plain-language sentence per unresolved matter, worst first.

    Distinct from the checks themselves: a check explains what was compared, and
    these are what a Tehsildar would write in the file. Derived from the checks so
    the two can never tell different stories.
    """
    sentences: list[str] = []
    ordered = sorted(
        (c for c in checks if not c.status.is_clear),
        key=lambda c: (-c.status.rank, -c.risk_points),
    )
    for check in ordered:
        if check.rule_code is RuleCode.SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED:
            sentences.append(f"{len(ctx.heirs)} potential heirs are identified in the documents.")
            holders = _names(ctx.current_owners) or "a single successor"
            sentences.append(f"The current record transfers the parcel to {holders}.")
            sentences.append(
                "Supporting evidence for the transfer as recorded was not found and requires verification."
            )
        else:
            sentences.append(check.explanation.split(". ")[0].rstrip(".") + ".")
    # Preserve order while removing repeats: two checks can legitimately reach the
    # same one-line summary, and printing it twice makes the report look padded.
    seen: set[str] = set()
    return [s for s in sentences if not (s in seen or seen.add(s))]


def validate_succession(
    case: SuccessionCase, policy: ValidationPolicy | None = None
) -> SuccessionReport:
    """Run every enabled succession check over one case.

    A rule the policy disables is simply not run; a rule that raises is converted
    into a single ``FAIL`` naming the rule that broke, exactly as
    :func:`adhikar.validation.registry.run_all` does -- a bug in one check must never
    silently cancel the other thirteen on the same case.
    """
    policy = policy or DEFAULT_POLICY
    started = time.monotonic()
    ctx = build_context(case, policy)

    checks: list[SuccessionCheck] = []
    for entry in _REGISTRY.values():
        if not policy.is_enabled(entry.primary_code):
            continue
        try:
            checks.extend(entry.func(ctx))
        except Exception as exc:  # noqa: BLE001 - one broken rule must not sink the report
            checks.append(
                _check(
                    rule=entry.name,
                    code=entry.primary_code,
                    status=CheckStatus.FAIL,
                    explanation=f"Succession check {entry.name} raised an internal error: {exc}",
                    remediation="Report this to the engineering team; the case could not be fully checked.",
                )
            )

    # NAME_MATCH_QUALITY reports the approximate links the earlier rules recorded
    # while running, so it has to evaluate after them. It does, because `_REGISTRY`
    # preserves decoration order and that rule is declared last in this module --
    # which is why its position here is load-bearing rather than cosmetic.
    risk_score, contributions = _score(checks, ctx)
    outcome = _outcome(checks)
    parcel = case.parcel

    report = SuccessionReport(
        case_id=case.case_id,
        parcel_key=case.parcel_key or (parcel.display_key if parcel.identifier_fields else None),
        policy_name=policy.name,
        outcome=outcome,
        risk_level=_band(risk_score),
        risk_score=risk_score,
        event_type=_classify_event(ctx),
        recommended_action=_ACTION_BY_OUTCOME[outcome],
        parcel=parcel,
        previous_owners=ctx.previous_owners,
        current_owners=ctx.current_owners,
        deceased=ctx.deceased_names,
        death_verified=ctx.death_verified,
        potential_heirs=ctx.heirs,
        mutations=list(case.mutations),
        checks=checks,
        issues=_issue_sentences(checks, ctx),
        findings=[
            check.to_issue(parcel_key=case.parcel_key)
            for check in checks
            if not check.status.is_clear
        ],
        risk_contributions=contributions,
        timeline=build_timeline(case, ctx),
        evidence_documents=case.documents,
        duration_ms=round((time.monotonic() - started) * 1000, 3),
    )
    return report


def validate_documents(
    *,
    previous_land_record: RecordSnapshot | None = None,
    death_certificate: DeathRecord | list[DeathRecord] | None = None,
    heir_information: list[HeirCandidate] | None = None,
    will_document: SupportingDocument | list[SupportingDocument] | None = None,
    mutation_record: MutationRecord | list[MutationRecord] | None = None,
    current_land_record: RecordSnapshot | None = None,
    case_id: str = "case",
    parcel_key: str | None = None,
    policy: ValidationPolicy | None = None,
) -> SuccessionReport:
    """Document-shaped convenience wrapper around :func:`validate_succession`.

    Assembles a :class:`~adhikar.schemas.succession.SuccessionCase` from the six
    things a revenue clerk actually has in front of them and validates it. Every
    argument is optional: a bundle missing the mutation, or the death certificate, or
    both, is a legitimate input and produces a report naming what is absent.
    """

    def listify(value):  # noqa: ANN001, ANN202 - accepts one item or many of one type
        if value is None:
            return []
        return list(value) if isinstance(value, list) else [value]

    snapshots = [s for s in (previous_land_record, current_land_record) if s is not None]
    case = SuccessionCase(
        case_id=case_id,
        parcel_key=parcel_key,
        record_snapshots=snapshots,
        death_records=listify(death_certificate),
        heirs=list(heir_information or []),
        mutations=listify(mutation_record),
        supporting_documents=listify(will_document),
    )
    return validate_succession(case, policy)
