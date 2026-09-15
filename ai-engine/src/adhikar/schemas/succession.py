"""Ownership succession: the cross-document domain model and its validation report.

Everything else in :mod:`adhikar.schemas` describes *one* record. Succession is the
first thing the engine judges that cannot be judged from one record: it needs the
Jamabandi as it stood, a death certificate, whatever the family filed, the mutation
order, and the Jamabandi as it stands now -- and the finding is almost always about
the *relationship between* those documents rather than about any one of them.

Three design commitments run through this module.

**The system validates documents, not entitlement.** Nothing here encodes who
inherits. There is no "eldest son" rule, no default spousal share, no notion of a
person being *entitled* to anything. :class:`HeirCandidate` is deliberately named:
these are people the submitted paperwork *names*, and the engine's strongest possible
output about them is that the documents do or do not account for a transfer.
:data:`DECISION_SUPPORT_DISCLAIMER` is carried on every report so the limit travels
with the data rather than living in a README.

**Checks are separate from findings.** A :class:`SuccessionCheck` records what was
compared and what was seen -- including the ones that passed, which is what makes the
report readable as evidence rather than as a list of complaints. The subset that
matters is *also* projected into the engine's ordinary
:class:`~adhikar.schemas.validation.ValidationIssue` shape, so the existing reviewer
console, triage scoring and audit trail consume succession findings without knowing
this module exists.

**Every claim points at a document.** :class:`EvidenceRef` is required wherever a
check compares two values, so "Area mismatch" is always displayable as *old
Jamabandi -> 5.00 ha* against *mutation -> 6.20 ha* rather than as an assertion the
reviewer has to take on trust.

Enum values are lower-case, matching every other vocabulary in the package
(:class:`~adhikar.schemas.enums.MutationType`,
:class:`~adhikar.schemas.validation.Severity`); presentation layers supply the
display casing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from fractions import Fraction
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from .enums import MutationStatus, MutationType, RelationType, TenureType
from .land_record import LandParcelRecord, OwnershipShare, PersonName
from .units import AreaMeasurement
from .validation import RuleCode, Severity, ValidationIssue

__all__ = [
    "DECISION_SUPPORT_DISCLAIMER",
    "CheckStatus",
    "DeathRecord",
    "EvidenceRef",
    "HeirCandidate",
    "MutationRecord",
    "OwnershipEntry",
    "OwnershipEvent",
    "OwnershipEventType",
    "ParcelIdentity",
    "RecordSnapshot",
    "RiskContribution",
    "RiskLevel",
    "SuccessionAction",
    "SuccessionCase",
    "SuccessionCheck",
    "SuccessionDocumentType",
    "SuccessionEventType",
    "SuccessionOutcome",
    "SuccessionReport",
    "SupportingDocument",
]

DECISION_SUPPORT_DISCLAIMER = (
    "This is a documentary-consistency assessment, not a determination of legal "
    "entitlement. The system does not decide who inherits, does not apply any "
    "succession law, and does not conclude that a transfer was improper. Findings "
    "identify what the submitted documents do and do not establish; the adjudication "
    "belongs to the revenue authority."
)
"""Carried on every :class:`SuccessionReport`.

Kept in the data rather than only in the UI because the report is exported, printed
and attached to files -- a caveat that exists only on one screen is a caveat that
stops travelling with the conclusion the moment anybody does any of that.
"""


# ======================================================================================
# Document vocabulary
# ======================================================================================


class SuccessionDocumentType(StrEnum):
    """Kinds of paper a succession case is assembled from.

    Membership here says only *what a document is*, never what it proves. The two
    properties below group types by the question they can speak to at all -- a will
    can say who a testator named; whether it is valid, current, or probated is not
    something this system decides.
    """

    JAMABANDI = "jamabandi"
    """Record of Rights as it stood before the transition."""

    UPDATED_JAMABANDI = "updated_jamabandi"
    """Record of Rights as it stands after the transition."""

    DEATH_CERTIFICATE = "death_certificate"
    LEGAL_HEIR_CERTIFICATE = "legal_heir_certificate"

    FAMILY_REGISTER = "family_register"
    """Parivar register / family-details extract naming household members."""

    MUTATION_APPLICATION = "mutation_application"
    MUTATION_ORDER = "mutation_order"
    """The Revenue Officer's order on a mutation (Intekal / Ferfar sanction)."""

    WILL = "will"
    RELINQUISHMENT_DEED = "relinquishment_deed"
    """Release / Haq-tyag deed by which a named person gives up a claim."""

    PARTITION_DEED = "partition_deed"
    FAMILY_SETTLEMENT = "family_settlement"
    COURT_ORDER = "court_order"
    SUCCESSION_CERTIFICATE = "succession_certificate"
    AFFIDAVIT = "affidavit"
    OTHER = "other"
    UNKNOWN = "unknown"

    @property
    def is_record_of_rights(self) -> bool:
        return self in {SuccessionDocumentType.JAMABANDI, SuccessionDocumentType.UPDATED_JAMABANDI}

    @property
    def can_evidence_transition(self) -> bool:
        """Whether this type of document can speak to *why* ownership changed.

        Presence is not proof: a document of one of these types is a place to look
        for an explanation, and the rules check whether it actually names the people
        the record now shows.
        """
        return self in {
            SuccessionDocumentType.MUTATION_ORDER,
            SuccessionDocumentType.MUTATION_APPLICATION,
            SuccessionDocumentType.WILL,
            SuccessionDocumentType.RELINQUISHMENT_DEED,
            SuccessionDocumentType.PARTITION_DEED,
            SuccessionDocumentType.FAMILY_SETTLEMENT,
            SuccessionDocumentType.COURT_ORDER,
            SuccessionDocumentType.SUCCESSION_CERTIFICATE,
        }

    @property
    def can_evidence_exclusive_transfer(self) -> bool:
        """Whether this type can address *why one heir rather than several*.

        A sanctioned mutation order records that a transfer was made; it does not on
        its own record why the other people the file names are absent from it. The
        documents that can speak to that are the ones in which the other parties, a
        testator, or a court say something about the allocation.
        """
        return self in {
            SuccessionDocumentType.WILL,
            SuccessionDocumentType.RELINQUISHMENT_DEED,
            SuccessionDocumentType.PARTITION_DEED,
            SuccessionDocumentType.FAMILY_SETTLEMENT,
            SuccessionDocumentType.COURT_ORDER,
            SuccessionDocumentType.SUCCESSION_CERTIFICATE,
        }

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class EvidenceRef(BaseModel):
    """Where a value a check relied on actually came from.

    The unit of explainability. A finding that cites two of these renders as
    *old Jamabandi -> total_area = 5.00 ha* against *mutation -> area = 6.20 ha*,
    which a reviewer can check against the paper in front of them; a finding without
    them is an assertion.
    """

    model_config = ConfigDict(extra="forbid")

    document_type: SuccessionDocumentType = SuccessionDocumentType.UNKNOWN
    document_id: str | None = None
    """Caller-assigned handle -- a backend ``documents.id``, a file name, a label."""

    document_label: str | None = None
    """Human-readable name for the document, e.g. 'Old Jamabandi (2019-20)'."""

    field_path: str | None = None
    """Path to the field within that document, e.g. ``owners[0].name`` or
    ``date_of_death``. Matches the addressing the reviewer console already uses for
    :class:`~adhikar.schemas.artifact.FieldProvenance`."""

    value: str | None = None
    """The value as the check saw it, after normalisation, rendered for display."""

    raw_value: str | None = None
    """The value as printed, when normalisation changed it. This is what a reviewer
    compares against the scan."""

    def describe(self) -> str:
        label = self.document_label or self.document_type.label
        return f"{label} → {self.field_path or '?'}" + (f" = {self.value}" if self.value else "")


# ======================================================================================
# Parties, parcels and holdings
# ======================================================================================


class ParcelIdentity(BaseModel):
    """The identifiers a document actually carries for the land it is about.

    Deliberately *not* :class:`~adhikar.schemas.land_record.LandParcelRecord`: a death
    certificate carries no parcel at all, a relinquishment deed usually carries only a
    khasra number and a village, and a mutation order carries a subset. Rule S3/S5
    compare whatever two documents have in common and say so when they have nothing.
    """

    model_config = ConfigDict(extra="forbid")

    khasra_number: str | None = None
    khata_number: str | None = None
    khatauni_number: str | None = None
    survey_number: str | None = None
    sub_survey_number: str | None = None

    village: str | None = None
    tehsil: str | None = None
    district: str | None = None
    state: str | None = None

    area: AreaMeasurement | None = None

    @classmethod
    def from_record(cls, record: LandParcelRecord) -> ParcelIdentity:
        """Project a full Record of Rights onto the identifiers succession compares."""
        return cls(
            khasra_number=record.khasra_numbers[0] if record.khasra_numbers else None,
            khata_number=record.khata_number,
            khatauni_number=record.khatauni_number,
            survey_number=record.survey_number,
            sub_survey_number=record.sub_survey_number,
            village=record.jurisdiction.village,
            tehsil=record.jurisdiction.tehsil,
            district=record.jurisdiction.district,
            state=record.jurisdiction.state,
            area=record.total_area,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_key(self) -> str:
        """A short human label, e.g. ``Khasra 125/2 · Angol``."""
        plot = self.khasra_number or self.survey_number or self.khata_number
        parts = [f"Khasra {plot}" if plot else None, self.village, self.district]
        return " · ".join(p for p in parts if p) or "Unidentified parcel"

    @property
    def identifier_fields(self) -> dict[str, str]:
        """Only the identifiers this document actually states, for pairwise comparison.

        Absent identifiers are omitted rather than compared as ``None == None``: two
        documents that both fail to name a village agree on nothing, and a rule that
        counted that as a match would report agreement it never observed.
        """
        candidates = {
            "khasra_number": self.khasra_number,
            "khata_number": self.khata_number,
            "khatauni_number": self.khatauni_number,
            "survey_number": self.survey_number,
            "sub_survey_number": self.sub_survey_number,
            "village": self.village,
            "tehsil": self.tehsil,
            "district": self.district,
            "state": self.state,
        }
        return {k: v for k, v in candidates.items() if v is not None and str(v).strip()}


class OwnershipEntry(BaseModel):
    """One holding: a named person and the share the document gives them.

    ``share=None`` is meaningful and common -- a mutation order frequently names a
    transferee without stating a fraction. Rules distinguish "no share stated" from
    "share stated as 1/1", because only the second is a claim of exclusivity.
    """

    model_config = ConfigDict(extra="forbid")

    name: PersonName
    share: OwnershipShare | None = None
    tenure_type: TenureType = TenureType.UNKNOWN
    serial_number: str | None = None
    source: EvidenceRef | None = None

    @property
    def display_name(self) -> str:
        return str(self.name)

    @property
    def share_text(self) -> str:
        return str(self.share) if self.share else "not stated"


class RecordSnapshot(BaseModel):
    """A Record of Rights as it stood at one point in time.

    The succession chain is a list of these plus the events between them. Modelling
    the record as a *snapshot* rather than as "the current owner" is what lets rule
    S10 detect a transition nothing accounts for: with only a current owner there is
    no earlier state to have transitioned from.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = "Record of Rights"
    document_type: SuccessionDocumentType = SuccessionDocumentType.JAMABANDI
    document_id: str | None = None

    as_of: date | None = None
    """When this snapshot describes the holding."""

    as_of_inferred: bool = False
    """True when :attr:`as_of` was derived from the revenue year rather than read off
    the page as a date.

    Load-bearing, not bookkeeping. A revenue year is a *range*: a record filed under
    ``2025-26`` says nothing finer than "some time in 2025-26", and anchoring it at
    1 January 2025 so it can be ordered would make a mutation dated August 2025 look
    like it followed the record it actually produced. Rules that need a real
    chronology (S2, which asks whether the transfer followed the death) read
    :attr:`stated_as_of` and ignore inferred anchors entirely; rules that need a
    window (S10) read :attr:`window_end`.
    """

    revenue_year: str | None = None
    parcel: ParcelIdentity = Field(default_factory=ParcelIdentity)
    owners: list[OwnershipEntry] = Field(default_factory=list)
    is_legible: bool = True
    """False when the document was submitted but could not be read. The case still
    validates; the illegibility becomes a finding rather than an exception."""

    @classmethod
    def from_record(
        cls,
        record: LandParcelRecord,
        *,
        label: str = "Record of Rights",
        document_type: SuccessionDocumentType = SuccessionDocumentType.JAMABANDI,
        document_id: str | None = None,
        as_of: date | None = None,
        as_of_inferred: bool = False,
    ) -> RecordSnapshot:
        """Build a snapshot from a record the extraction pipeline produced.

        This is the seam between succession validation and the rest of the engine:
        anything ``process_document`` can extract becomes a snapshot without a second
        extraction pass or a parallel schema.
        """
        return cls(
            label=label,
            document_type=document_type,
            document_id=document_id,
            as_of=as_of,
            as_of_inferred=as_of_inferred,
            revenue_year=record.jurisdiction.revenue_year,
            parcel=ParcelIdentity.from_record(record),
            owners=[
                OwnershipEntry(
                    name=owner.name,
                    share=owner.share,
                    tenure_type=owner.tenure_type,
                    serial_number=owner.serial_number,
                    source=EvidenceRef(
                        document_type=document_type,
                        document_id=document_id,
                        document_label=label,
                        field_path=f"owners[{index}].name",
                        value=str(owner.name),
                    ),
                )
                for index, owner in enumerate(record.owners)
            ],
        )

    @property
    def stated_as_of(self) -> date | None:
        """The date printed on the document, or ``None`` when only a year is known."""
        return None if self.as_of_inferred else self.as_of

    @property
    def window_end(self) -> date | None:
        """The latest date this snapshot can be describing.

        For a stated date that is the date itself. For a revenue year it is the end
        of that year -- 31 March of the following calendar year, the convention
        Indian revenue years close on -- so an event dated inside the year counts as
        falling within the window rather than after it.
        """
        if self.as_of is None:
            return None
        return date(self.as_of.year + 1, 3, 31) if self.as_of_inferred else self.as_of

    @property
    def owner_names(self) -> list[str]:
        return [o.display_name for o in self.owners]

    @property
    def total_share(self) -> Fraction:
        return sum((o.share.fraction for o in self.owners if o.share is not None), Fraction(0))

    def evidence(self, field_path: str, value: Any = None) -> EvidenceRef:
        return EvidenceRef(
            document_type=self.document_type,
            document_id=self.document_id,
            document_label=self.label,
            field_path=field_path,
            value=None if value is None else str(value),
        )


class DeathRecord(BaseModel):
    """A death as a submitted document states it.

    ``date_of_death=None`` is tolerated throughout: a certificate whose date cell did
    not survive the scan still establishes *that* the registrar recorded a death, and
    the rules that need the date say so instead of silently skipping.
    """

    model_config = ConfigDict(extra="forbid")

    person: PersonName
    date_of_death: date | None = None
    registration_number: str | None = None
    place: str | None = None
    issuing_authority: str | None = None

    document_type: SuccessionDocumentType = SuccessionDocumentType.DEATH_CERTIFICATE
    document_id: str | None = None
    document_label: str | None = None
    is_legible: bool = True

    def evidence(self, field_path: str, value: Any = None) -> EvidenceRef:
        return EvidenceRef(
            document_type=self.document_type,
            document_id=self.document_id,
            document_label=self.document_label or "Death certificate",
            field_path=field_path,
            value=None if value is None else str(value),
        )


class HeirCandidate(BaseModel):
    """A person the submitted documents name as family of the deceased.

    **Candidate, not heir.** The name is the design: this records that a document
    names somebody in a stated relationship, and nothing about what that person is
    entitled to. ``stated_share`` is only ever populated from a document that itself
    states a share -- the engine never apportions.
    """

    model_config = ConfigDict(extra="forbid")

    name: PersonName
    relation_to_deceased: RelationType = RelationType.UNKNOWN
    deceased_name: str | None = None
    """Which deceased person this relationship is to, when the case has more than one."""

    stated_share: OwnershipShare | None = None
    """Only when a submitted document states one. Never computed."""

    is_minor: bool = False
    is_deceased: bool = False
    source: EvidenceRef | None = None

    @property
    def display_name(self) -> str:
        return str(self.name)

    @property
    def relation_label(self) -> str:
        return self.relation_to_deceased.value.replace("_", " ")


class MutationRecord(BaseModel):
    """A mutation as the mutation paperwork states it.

    Distinct from :class:`~adhikar.schemas.land_record.MutationEntry`, which is a *row
    in a register* read off a Jamabandi. This is the standalone application or order
    submitted as part of the case, and it carries the parcel and the shares that the
    register row does not.
    """

    model_config = ConfigDict(extra="forbid")

    mutation_number: str | None = None
    mutation_type: MutationType = MutationType.UNKNOWN
    status: MutationStatus = MutationStatus.UNKNOWN

    entry_date: date | None = None
    order_date: date | None = None

    parcel: ParcelIdentity = Field(default_factory=ParcelIdentity)
    previous_owners: list[OwnershipEntry] = Field(default_factory=list)
    new_owners: list[OwnershipEntry] = Field(default_factory=list)

    area_transacted: AreaMeasurement | None = None
    basis_reference: str | None = None
    """What the order says it acted on -- a will, a court decree, an application."""

    document_type: SuccessionDocumentType = SuccessionDocumentType.MUTATION_ORDER
    document_id: str | None = None
    document_label: str | None = None
    is_legible: bool = True
    remarks: str | None = None

    @model_validator(mode="after")
    def _order_follows_entry(self) -> Self:
        if self.entry_date and self.order_date and self.order_date < self.entry_date:
            raise ValueError(
                f"order_date {self.order_date} precedes entry_date {self.entry_date}: "
                "an order cannot be dated before the application it decides"
            )
        return self

    @property
    def effective_date(self) -> date | None:
        """The date the change took effect, preferring the order over the entry."""
        return self.order_date or self.entry_date

    @property
    def total_new_share(self) -> Fraction:
        return sum((o.share.fraction for o in self.new_owners if o.share is not None), Fraction(0))

    def evidence(self, field_path: str, value: Any = None) -> EvidenceRef:
        return EvidenceRef(
            document_type=self.document_type,
            document_id=self.document_id,
            document_label=self.document_label
            or (f"Mutation {self.mutation_number}" if self.mutation_number else "Mutation"),
            field_path=field_path,
            value=None if value is None else str(value),
        )


class SupportingDocument(BaseModel):
    """Any other document offered as part of the chain.

    A will, a relinquishment, a partition, a family settlement, a court decree, an
    affidavit. The engine reads three things off it and nothing more: who it names,
    who it says takes what, and which parcel it is about. Whether it is valid,
    registered, stamped, probated or current is outside what a document-consistency
    system can determine, and the report says so rather than implying otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    document_type: SuccessionDocumentType = SuccessionDocumentType.OTHER
    document_id: str | None = None
    label: str | None = None
    issued_on: date | None = None
    reference: str | None = None
    """Registration number, decree citation, sub-registrar's document number."""

    parcel: ParcelIdentity = Field(default_factory=ParcelIdentity)

    executants: list[PersonName] = Field(default_factory=list)
    """Who signed / relinquished / bequeathed. For a relinquishment deed these are
    the people giving up a claim, which is exactly what rule S9 needs to know."""

    beneficiaries: list[OwnershipEntry] = Field(default_factory=list)
    """Who the document names as taking, with a share where it states one."""

    is_legible: bool = True
    summary: str | None = None
    raw_text: str | None = None

    @property
    def display_label(self) -> str:
        return self.label or self.document_type.label

    def evidence(self, field_path: str, value: Any = None) -> EvidenceRef:
        return EvidenceRef(
            document_type=self.document_type,
            document_id=self.document_id,
            document_label=self.display_label,
            field_path=field_path,
            value=None if value is None else str(value),
        )


# ======================================================================================
# The case
# ======================================================================================


class SuccessionCase(BaseModel):
    """Everything submitted about one ownership transition.

    Every collection may be empty. A case with a death certificate and nothing else
    is a legitimate input and produces a report saying precisely which documents are
    missing -- which is more useful to a revenue office than a rejected request.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = "case"
    parcel_key: str | None = None
    """The backend's own identifier for the land, when the case is attached to a
    parcel already in the register."""

    record_snapshots: list[RecordSnapshot] = Field(default_factory=list)
    """Records of Rights across time, oldest first. Two is the usual case (before and
    after); more is what makes an unexplained intermediate transition visible."""

    death_records: list[DeathRecord] = Field(default_factory=list)
    heirs: list[HeirCandidate] = Field(default_factory=list)
    mutations: list[MutationRecord] = Field(default_factory=list)
    supporting_documents: list[SupportingDocument] = Field(default_factory=list)

    submitted_by: str | None = None
    submitted_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _order_snapshots(self) -> Self:
        """Order the chain: declared role first, then date, then submission order.

        Chain rules read consecutive pairs, so this is load-bearing -- and sorting
        here rather than asking callers to means a case assembled from a folder of
        scans in arbitrary filename order still validates correctly.

        **Role outranks date.** ``UPDATED_JAMABANDI`` is the caller stating which
        record is the *after*, and that statement is more reliable than any date
        inference: a record pulled from the register frequently carries no date at
        all, and ordering purely by date would push it behind a dated submission and
        silently invert the very transition the case is about.

        Within one role, dated snapshots come first in date order and undated ones
        keep their submitted position behind them -- an undated record among dated
        ones is most often the current one, and guessing it belongs at the front
        would invent a transition nothing on the paper supports.
        """
        if len(self.record_snapshots) < 2:
            return self

        def key(item: tuple[int, RecordSnapshot]) -> tuple[int, int, date, int]:
            index, snapshot = item
            role = 1 if snapshot.document_type is SuccessionDocumentType.UPDATED_JAMABANDI else 0
            if snapshot.as_of is not None:
                return (role, 0, snapshot.as_of, index)
            return (role, 1, date.max, index)

        self.record_snapshots = [
            snapshot for _, snapshot in sorted(enumerate(self.record_snapshots), key=key)
        ]
        return self

    @property
    def previous_record(self) -> RecordSnapshot | None:
        """The state ownership transitioned *from*."""
        return self.record_snapshots[0] if self.record_snapshots else None

    @property
    def current_record(self) -> RecordSnapshot | None:
        """The state ownership transitioned *to*."""
        return self.record_snapshots[-1] if self.record_snapshots else None

    @property
    def parcel(self) -> ParcelIdentity:
        """Best available parcel identity, preferring the earliest record.

        The old Jamabandi is preferred because it is the document the case is
        *about*: if the new record names a different parcel, that disagreement is a
        finding (rule S3), not a reason to relabel the case.
        """
        for snapshot in self.record_snapshots:
            if snapshot.parcel.identifier_fields:
                return snapshot.parcel
        for mutation in self.mutations:
            if mutation.parcel.identifier_fields:
                return mutation.parcel
        for document in self.supporting_documents:
            if document.parcel.identifier_fields:
                return document.parcel
        return ParcelIdentity()

    @property
    def documents(self) -> list[EvidenceRef]:
        """Every document in the case, as references -- the report's evidence index."""
        refs: list[EvidenceRef] = []
        for snapshot in self.record_snapshots:
            refs.append(
                EvidenceRef(
                    document_type=snapshot.document_type,
                    document_id=snapshot.document_id,
                    document_label=snapshot.label,
                )
            )
        for death in self.death_records:
            refs.append(death.evidence("person.raw", death.person.raw))
        for mutation in self.mutations:
            refs.append(mutation.evidence("mutation_number", mutation.mutation_number))
        for document in self.supporting_documents:
            refs.append(document.evidence("reference", document.reference))
        return refs

    @property
    def illegible_documents(self) -> list[EvidenceRef]:
        """Documents submitted but reported unreadable. An input, not an error."""
        refs: list[EvidenceRef] = []
        refs += [
            s.evidence("$", s.label) for s in self.record_snapshots if not s.is_legible
        ]
        refs += [d.evidence("$", d.person.raw) for d in self.death_records if not d.is_legible]
        refs += [m.evidence("$", m.mutation_number) for m in self.mutations if not m.is_legible]
        refs += [
            d.evidence("$", d.display_label) for d in self.supporting_documents if not d.is_legible
        ]
        return refs


# ======================================================================================
# Ownership events (the timeline the console draws)
# ======================================================================================


class OwnershipEventType(StrEnum):
    """What happened, as the documents record it."""

    RECORD_SNAPSHOT = "record_snapshot"
    """The register showed this holding as at a date. Not a change -- a reading."""

    DEATH = "death"
    SUCCESSION_CLAIM = "succession_claim"
    """Heirs were identified in the submitted paperwork. Names a set of candidates;
    asserts nothing about shares."""

    MUTATION = "mutation"
    WILL = "will"
    RELINQUISHMENT = "relinquishment"
    PARTITION = "partition"
    FAMILY_SETTLEMENT = "family_settlement"
    COURT_ORDER = "court_order"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class EventParty(BaseModel):
    """A person on one side of an ownership event, with the share stated for them."""

    model_config = ConfigDict(extra="forbid")

    name: str
    share: str | None = None
    relation: str | None = None


class OwnershipEvent(BaseModel):
    """One node on the ownership timeline.

    Events are *derived* from the case rather than stored independently, so the
    timeline can never disagree with the documents it was built from -- regenerating
    it is the only way it changes.
    """

    model_config = ConfigDict(extra="forbid")

    sequence: int = 0
    event_type: OwnershipEventType
    event_date: date | None = None
    date_stated: bool = True
    """False when :attr:`event_date` (or the position on the timeline) was inferred
    rather than read off the paper. The console draws these differently: an inferred
    position on a timeline should not look like a recorded one."""

    sort_anchor: date | None = None
    """Where the event sits on the timeline, when that differs from what it displays.

    A record filed under revenue year ``2025-26`` displays as that year and sorts at
    the year's end, so a mutation dated inside the year appears before the record it
    produced rather than after it. Falls back to :attr:`event_date` when unset."""

    parcel_key: str | None = None
    person: str | None = None
    """The single subject, where the event has one (a death)."""

    from_owners: list[EventParty] = Field(default_factory=list)
    to_owners: list[EventParty] = Field(default_factory=list)
    description: str = ""
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @property
    def sort_key(self) -> tuple[int, date, int]:
        """Dated events first in date order, undated ones in submission order."""
        anchor = self.sort_anchor or self.event_date
        return (0, anchor, self.sequence) if anchor else (1, date.max, self.sequence)


# ======================================================================================
# Checks, risk and the report
# ======================================================================================


class CheckStatus(StrEnum):
    """The outcome of one succession check.

    ``REVIEW_REQUIRED`` is the status this system exists to be able to return: the
    documents are internally consistent *and* do not establish what the record
    asserts. Collapsing it into either PASS or FAIL would force the engine to take a
    position it is not entitled to take.
    """

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    REVIEW_REQUIRED = "review_required"
    NOT_APPLICABLE = "not_applicable"
    """The check's precondition was absent -- recorded, never silently omitted, so
    the report is complete evidence of what was and was not examined."""

    @property
    def rank(self) -> int:
        return {"not_applicable": 0, "pass": 1, "warning": 2, "review_required": 3, "fail": 4}[self.value]

    @property
    def is_clear(self) -> bool:
        return self in {CheckStatus.PASS, CheckStatus.NOT_APPLICABLE}

    @property
    def severity(self) -> Severity:
        """How this maps onto the engine's ordinary finding severities.

        ``REVIEW_REQUIRED`` maps to ``WARNING``, not ``ERROR``: the record does not
        contradict itself, so blocking it as if it did would misreport the nature of
        the problem. The report's own ``outcome`` is what routes the case.
        """
        return {
            CheckStatus.FAIL: Severity.ERROR,
            CheckStatus.REVIEW_REQUIRED: Severity.WARNING,
            CheckStatus.WARNING: Severity.WARNING,
            CheckStatus.PASS: Severity.INFO,
            CheckStatus.NOT_APPLICABLE: Severity.INFO,
        }[self]


class SuccessionCheck(BaseModel):
    """One comparison the engine made, and what it saw.

    Passing checks are kept. A reviewer deciding whether to accept a transfer needs
    to know that the parcel identifiers *were* compared and *did* agree; a report
    that lists only problems cannot distinguish "checked and fine" from "not checked".
    """

    model_config = ConfigDict(extra="forbid")

    rule: str
    """Positive-sense name of what was checked, e.g. ``OWNER_IDENTITY_MATCH``. This
    is what the console labels the row with."""

    rule_code: RuleCode
    """The stable catalogue code the finding is filed under. Appears in audits and in
    ``GET /system/rules``, so it must never be renamed."""

    status: CheckStatus
    explanation: str
    """Written for a revenue official: what was compared, what was found, in record
    vocabulary. Never a verdict on entitlement."""

    evidence: list[EvidenceRef] = Field(default_factory=list)
    match_score: float | None = Field(default=None, ge=0.0, le=1.0)
    """Similarity, where the check matched text rather than compared exactly. Carried
    so a fuzzy match is auditable: 'matched at 0.91 against a 0.88 threshold' is
    checkable, 'names matched' is not."""

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    risk_points: float = 0.0
    """This check's contribution to :attr:`SuccessionReport.risk_score`, after the
    status multiplier. Zero for a clear check."""

    remediation: str | None = None
    """The concrete next step for the reviewer, where there is one."""

    def to_issue(self, *, parcel_key: str | None = None) -> ValidationIssue:
        """Project onto the engine's ordinary finding shape.

        This is what lets succession findings flow into the existing reviewer
        console, triage scoring, CSV exports and audit trail without any of them
        knowing that succession validation exists.
        """
        return ValidationIssue(
            rule_code=self.rule_code,
            severity=self.status.severity,
            message=self.explanation,
            json_path=f"$.succession.checks[{self.rule}]",
            parcel_key=parcel_key,
            observed=self.evidence[0].value if self.evidence else None,
            expected=self.evidence[1].value if len(self.evidence) > 1 else None,
            confidence=self.confidence,
            remediation=self.remediation,
            evidence={
                "check": self.rule,
                "status": self.status.value,
                "match_score": self.match_score,
                "sources": [e.describe() for e in self.evidence],
            },
        )


class RiskContribution(BaseModel):
    """One line of the risk score's arithmetic.

    The score is the sum of these and nothing else. A score a reviewer cannot
    decompose is a score they cannot argue with, and this system's findings are meant
    to be argued with.
    """

    model_config = ConfigDict(extra="forbid")

    rule: str
    rule_code: RuleCode
    status: CheckStatus
    base_points: float
    multiplier: float
    points: float
    reason: str


class RiskLevel(StrEnum):
    """Band cut from the risk score. Bands, because a band is an instruction."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}[self.value]


class SuccessionOutcome(StrEnum):
    """The case's overall state. Note what is absent: there is no ``FRAUD``.

    The system has no basis for that conclusion and no mechanism that could reach
    it -- a transfer whose paperwork is incomplete and one that is improper are
    indistinguishable from the documents alone, and conflating them would put a
    machine's guess into a person's land record.
    """

    VALIDATED = "validated"
    """Every check the documents supported came back clear."""

    INCOMPLETE = "incomplete"
    """Nothing contradicts, but documents needed to establish the chain are absent."""

    INCONSISTENT = "inconsistent"
    """Submitted documents disagree with each other on a matter of fact."""

    REVIEW_REQUIRED = "review_required"
    """Internally consistent, but the evidence does not establish what the record
    asserts. The revenue authority decides."""

    @property
    def rank(self) -> int:
        return {"validated": 0, "incomplete": 1, "review_required": 2, "inconsistent": 3}[self.value]


class SuccessionEventType(StrEnum):
    """What kind of transition the case describes, as classified from the documents."""

    OWNER_DEATH_SUCCESSION = "owner_death_succession"
    OWNERSHIP_TRANSITION = "ownership_transition"
    """Ownership changed, with no death recorded in the submitted documents."""

    NO_TRANSITION_DETECTED = "no_transition_detected"
    INSUFFICIENT_DOCUMENTS = "insufficient_documents"


class SuccessionAction(StrEnum):
    """What the system asks a human to do. Its only workflow-bearing output."""

    ACCEPT_RECORD = "accept_record"
    """Every check cleared; the documents support the record as it stands."""

    OBTAIN_ADDITIONAL_DOCUMENTS = "obtain_additional_documents"
    HUMAN_REVIEW = "human_review"
    REFER_TO_REVENUE_AUTHORITY = "refer_to_revenue_authority"
    """Documents contradict each other; resolving that is an adjudication."""


class SuccessionReport(BaseModel):
    """The outcome of validating one succession case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = "case"
    parcel_key: str | None = None
    policy_name: str = "default"

    outcome: SuccessionOutcome = SuccessionOutcome.VALIDATED
    risk_level: RiskLevel = RiskLevel.LOW
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    event_type: SuccessionEventType = SuccessionEventType.NO_TRANSITION_DETECTED
    recommended_action: SuccessionAction = SuccessionAction.ACCEPT_RECORD

    parcel: ParcelIdentity = Field(default_factory=ParcelIdentity)
    previous_owners: list[OwnershipEntry] = Field(default_factory=list)
    current_owners: list[OwnershipEntry] = Field(default_factory=list)

    deceased: list[str] = Field(default_factory=list)
    death_verified: bool = False
    """True only when a submitted death certificate names a person the *previous
    record* recorded as an owner. A certificate for somebody the record never
    mentioned does not verify anything about this parcel."""

    potential_heirs: list[HeirCandidate] = Field(default_factory=list)
    mutations: list[MutationRecord] = Field(default_factory=list)

    checks: list[SuccessionCheck] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    """Plain-language statements of what is unresolved, for the summary panel and the
    printed report. One sentence each, ordered worst-first."""

    findings: list[ValidationIssue] = Field(default_factory=list)
    """The non-clear checks in the engine's ordinary finding shape."""

    risk_contributions: list[RiskContribution] = Field(default_factory=list)
    timeline: list[OwnershipEvent] = Field(default_factory=list)
    evidence_documents: list[EvidenceRef] = Field(default_factory=list)

    disclaimer: str = DECISION_SUPPORT_DISCLAIMER
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def counts_by_status(self) -> dict[str, int]:
        counts = {status.value: 0 for status in CheckStatus}
        for check in self.checks:
            counts[check.status.value] += 1
        return counts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def requires_human_review(self) -> bool:
        """The single boolean the workflow branches on."""
        return self.outcome is not SuccessionOutcome.VALIDATED

    @computed_field  # type: ignore[prop-decorator]
    @property
    def heir_names(self) -> list[str]:
        return [heir.display_name for heir in self.potential_heirs]

    def checks_for(self, code: RuleCode) -> list[SuccessionCheck]:
        return [c for c in self.checks if c.rule_code is code]

    def sorted_checks(self) -> list[SuccessionCheck]:
        """Worst first, then by risk contribution -- the reviewer's reading order."""
        return sorted(self.checks, key=lambda c: (-c.status.rank, -c.risk_points, c.rule))

    def summary_sentence(self) -> str:
        """One paragraph a revenue officer can read without opening the detail.

        Assembled from what the checks actually found, so it cannot drift from them
        the way a separately-authored summary would.
        """
        if self.event_type is SuccessionEventType.INSUFFICIENT_DOCUMENTS:
            return (
                "Not enough documents were submitted to assess an ownership transition "
                "for this parcel."
            )
        if self.event_type is SuccessionEventType.NO_TRANSITION_DETECTED:
            return "No change of recorded ownership was detected between the submitted records."

        parts: list[str] = ["Ownership transition detected."]
        if self.death_verified and self.deceased:
            parts.append(f"Previous owner {', '.join(self.deceased)} is recorded as deceased.")
        elif self.deceased:
            parts.append(
                f"A death certificate was submitted for {', '.join(self.deceased)}, "
                "who could not be matched to the previous recorded owner."
            )

        if len(self.potential_heirs) > 1:
            parts.append(f"{len(self.potential_heirs)} potential heirs are identified.")
        elif len(self.potential_heirs) == 1:
            parts.append(f"One potential heir is identified: {self.potential_heirs[0].display_name}.")

        if self.current_owners:
            holders = ", ".join(f"{o.display_name} ({o.share_text})" for o in self.current_owners)
            parts.append(f"The current record vests the parcel in {holders}.")

        if self.outcome is SuccessionOutcome.VALIDATED:
            parts.append("The submitted documents account for the transition.")
        elif self.outcome is SuccessionOutcome.INCONSISTENT:
            parts.append(
                "Submitted documents disagree with each other; revenue-authority review is required."
            )
        else:
            parts.append(
                "Supporting evidence for the transfer as recorded was not established from the "
                "submitted documents. Human / revenue-authority review is required."
            )
        return " ".join(parts)
