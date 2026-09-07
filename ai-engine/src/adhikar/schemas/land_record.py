"""The canonical land-record domain model.

This is the target schema for extraction and the input to every validation rule.

Two deliberate choices are worth calling out:

**Provenance lives outside the entity.** Wrapping every field in a
``{value, confidence, bbox}`` envelope would triple the size of the JSON schema handed
to the Vision LLM and measurably degrade extraction quality. Instead the domain model
stays clean and a parallel :class:`FieldProvenance` index, keyed by JSON path, records
where each value came from. See :mod:`adhikar.schemas.artifact`.

**Ownership shares are stored as integer numerator/denominator, never as floats.**
A ``1/3`` share written as ``0.333`` breaks the "shares sum to unity" rule for reasons
that have nothing to do with the record. Rational arithmetic makes that rule exact.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from .enums import (
    CultivabilityClass,
    EncumbranceStatus,
    EncumbranceType,
    IrrigationSource,
    LandClassification,
    MutationStatus,
    MutationType,
    RecordFormat,
    RelationType,
    TenureType,
    cultivability_of,
)
from .units import AreaMeasurement, sum_areas

__all__ = [
    "ClassifiedArea",
    "CropEntry",
    "Encumbrance",
    "Jurisdiction",
    "LandParcelRecord",
    "MutationEntry",
    "OwnerRecord",
    "OwnershipShare",
    "PersonName",
    "SubDivision",
]


class Jurisdiction(BaseModel):
    """Where the parcel sits in the revenue hierarchy.

    LGD codes (Local Government Directory, MoPR) are the join key to every other
    government dataset, so they are first-class rather than derived from names --
    village names are neither unique nor stably transliterated.
    """

    model_config = ConfigDict(extra="forbid")

    state: str | None = None
    district: str | None = None
    tehsil: str | None = None
    """Tehsil / Taluka / Mandal / Block, depending on the state."""

    village: str | None = None
    hadbast_number: str | None = None
    """Permanent village settlement number (Punjab/Haryana Jamabandi header)."""

    state_lgd_code: str | None = None
    district_lgd_code: str | None = None
    village_lgd_code: str | None = None

    revenue_year: str | None = None
    """As printed, e.g. ``2023-24``."""

    fasli_year: int | None = Field(default=None, ge=1200, le=1500)
    """Fasli era year (Jamabandi headers). Fasli + 590/591 approximates the CE year."""

    @property
    def is_resolvable(self) -> bool:
        """Whether this is specific enough to look up a cadastral polygon."""
        return bool(self.village_lgd_code) or all([self.state, self.district, self.tehsil, self.village])


class PersonName(BaseModel):
    """A name as printed, plus the relational qualifier that disambiguates it.

    In village records ``Ram Singh s/o Hari Singh`` and ``Ram Singh s/o Mohan Singh``
    are different people and routinely co-occur, so the relation is part of identity,
    not decoration.
    """

    model_config = ConfigDict(extra="forbid")

    raw: str = Field(min_length=1)
    """Verbatim, in the source script. Never overwritten by normalisation."""

    transliterated: str | None = None
    """Latin transliteration for search and cross-dataset matching."""

    relation_type: RelationType = RelationType.UNKNOWN
    relation_name: str | None = None

    @field_validator("raw", "transliterated", "relation_name")
    @classmethod
    def _collapse_whitespace(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v else v

    def __str__(self) -> str:
        if self.relation_name:
            marker = {
                RelationType.SON_OF: "s/o",
                RelationType.DAUGHTER_OF: "d/o",
                RelationType.WIFE_OF: "w/o",
                RelationType.WIDOW_OF: "wd/o",
            }.get(self.relation_type, "r/o")
            return f"{self.raw} {marker} {self.relation_name}"
        return self.raw


class OwnershipShare(BaseModel):
    """A fractional interest, held exactly.

    Records write shares in several notations -- ``1/3``, ``0-05-06`` (biswa-biswansi
    out of a bigha), ``33 paisa``, or the words for "equal share". Whatever the
    notation, it is normalised to an integer ratio here so the sum-to-unity rule is
    exact rather than approximate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)
    raw_text: str | None = None

    @model_validator(mode="after")
    def _not_over_unity(self) -> Self:
        if self.numerator > self.denominator:
            raise ValueError(
                f"share {self.numerator}/{self.denominator} exceeds unity; "
                "an individual holding cannot exceed the whole parcel"
            )
        return self

    @classmethod
    def whole(cls) -> OwnershipShare:
        return cls(numerator=1, denominator=1, raw_text="1/1")

    @classmethod
    def equal_among(cls, count: int, *, raw_text: str | None = None) -> OwnershipShare:
        """Share for one of ``count`` co-owners holding equally."""
        if count < 1:
            raise ValueError("count must be at least 1")
        return cls(numerator=1, denominator=count, raw_text=raw_text or f"1/{count}")

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decimal_value(self) -> Decimal:
        """Share as a decimal, for display and for area apportionment."""
        return (Decimal(self.numerator) / Decimal(self.denominator)).quantize(Decimal("0.000001"))

    def area_of(self, total: AreaMeasurement) -> AreaMeasurement:
        """The area this share represents out of ``total``."""
        return AreaMeasurement(
            sq_metre=total.sq_metre * Decimal(self.numerator) / Decimal(self.denominator),
            unit_system=total.unit_system,
            region_key=total.region_key,
        )

    def __str__(self) -> str:
        return f"{self.numerator}/{self.denominator}"


class OwnerRecord(BaseModel):
    """One person or body recorded against the parcel."""

    model_config = ConfigDict(extra="forbid")

    serial_number: str | None = None
    """The record's own row label, used to link sub-divisions back to owners."""

    name: PersonName
    tenure_type: TenureType = TenureType.UNKNOWN
    share: OwnershipShare | None = None
    khata_number: str | None = None
    """Khata / Khewat / Khatauni number this holder appears under."""

    is_government_body: bool = False
    remarks: str | None = None

    # NOTE: Aadhaar, mobile and bank-account fields are intentionally absent.
    # Land records frequently carry them; they are stripped at ingestion and never
    # persisted. See docs/data-governance.md.

    @property
    def display_name(self) -> str:
        return str(self.name)


class ClassifiedArea(BaseModel):
    """Area carrying a single revenue classification."""

    model_config = ConfigDict(extra="forbid")

    classification: LandClassification
    area: AreaMeasurement
    irrigation_source: IrrigationSource = IrrigationSource.UNKNOWN
    raw_label: str | None = None
    """The vernacular term as printed, before alias resolution."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cultivability(self) -> CultivabilityClass:
        return cultivability_of(self.classification)


class SubDivision(BaseModel):
    """A hissa / sub-survey / sub-division of the parent survey number.

    The area-sum rule the problem statement calls for operates on this collection:
    the sub-division areas must total the parent's area.
    """

    model_config = ConfigDict(extra="forbid")

    sub_division_number: str = Field(min_length=1)
    """As printed, e.g. ``12/1``, ``2A``, ``1-B``."""

    area: AreaMeasurement
    classification: LandClassification = LandClassification.UNKNOWN
    classified_areas: list[ClassifiedArea] = Field(default_factory=list)
    """Populated when the sub-division itself splits across classifications."""

    assessment_amount: Decimal | None = Field(default=None, ge=0)
    """Land revenue / akarni assessed on this sub-division, in rupees."""

    owner_serial_numbers: list[str] = Field(default_factory=list)
    """References into :attr:`LandParcelRecord.owners` by serial number."""

    remarks: str | None = None


class MutationEntry(BaseModel):
    """A recorded change of rights (Intekal / Pheri / Ferfar).

    The mutation chain is the audit trail. Validation checks it for chronological
    order, for status transitions that make sense, and for owners who appear in the
    current holding without any mutation putting them there.
    """

    model_config = ConfigDict(extra="forbid")

    mutation_number: str | None = None
    mutation_type: MutationType = MutationType.UNKNOWN
    status: MutationStatus = MutationStatus.UNKNOWN

    entry_date: date | None = None
    """Date the entry was made in the register."""

    order_date: date | None = None
    """Date the Revenue Officer sanctioned or rejected it."""

    from_parties: list[PersonName] = Field(default_factory=list)
    to_parties: list[PersonName] = Field(default_factory=list)

    area_transacted: AreaMeasurement | None = None
    consideration_amount: Decimal | None = Field(default=None, ge=0)
    """Sale consideration in rupees, where stated."""

    document_reference: str | None = None
    """Registered deed number, or the court decree citation."""

    remarks: str | None = None
    raw_text: str | None = None
    """The full remarks cell, kept verbatim -- mutation columns are dense free text
    and the structured fields above are a lossy read of them."""

    @model_validator(mode="after")
    def _order_follows_entry(self) -> Self:
        if self.entry_date and self.order_date and self.order_date < self.entry_date:
            raise ValueError(
                f"order_date {self.order_date} precedes entry_date {self.entry_date}: "
                "an order cannot be dated before the entry it decides"
            )
        return self


class Encumbrance(BaseModel):
    """A charge, lien or restriction noted against the parcel.

    On a 7/12 extract these live in the "other rights" column; on a Jamabandi they
    appear in the remarks. Either way an *active* encumbrance is the single most
    consequential thing on the record for a buyer or a lender.
    """

    model_config = ConfigDict(extra="forbid")

    encumbrance_type: EncumbranceType = EncumbranceType.UNKNOWN
    status: EncumbranceStatus = EncumbranceStatus.UNKNOWN
    holder_name: str | None = None
    """Bank, society or person in whose favour the charge runs."""

    amount: Decimal | None = Field(default=None, ge=0)
    created_on: date | None = None
    discharged_on: date | None = None
    reference: str | None = None
    remarks: str | None = None
    raw_text: str | None = None

    @model_validator(mode="after")
    def _discharge_implies_status(self) -> Self:
        if self.discharged_on and self.status is EncumbranceStatus.ACTIVE:
            raise ValueError(
                "encumbrance has a discharge date but is marked ACTIVE; "
                "set status to DISCHARGED or clear discharged_on"
            )
        return self

    @property
    def is_live(self) -> bool:
        """Conservative liveness: unknown status counts as live.

        An encumbrance we could not read is a reason for a human to look, not a
        reason to declare the title clean.
        """
        return self.status is not EncumbranceStatus.DISCHARGED


class CropEntry(BaseModel):
    """A row from the crop register (7/12 Part II / Khasra Girdawari)."""

    model_config = ConfigDict(extra="forbid")

    year: str | None = None
    season: str | None = None
    """Kharif / Rabi / Zaid, as printed."""

    crop_name: str | None = None
    area: AreaMeasurement | None = None
    irrigation_source: IrrigationSource = IrrigationSource.UNKNOWN
    remarks: str | None = None


class LandParcelRecord(BaseModel):
    """One parcel's Record of Rights: the unit of extraction and validation."""

    model_config = ConfigDict(extra="forbid")

    record_format: RecordFormat = RecordFormat.UNKNOWN
    jurisdiction: Jurisdiction = Field(default_factory=Jurisdiction)

    # -- identifiers -------------------------------------------------------------------
    khata_number: str | None = None
    """Khata / Khewat -- the ownership-holding identifier."""

    khatauni_number: str | None = None
    """Cultivation-holding identifier (Jamabandi)."""

    khasra_numbers: list[str] = Field(default_factory=list)
    """Field-plot numbers falling under this khata."""

    survey_number: str | None = None
    """Survey / Gat number (7/12 and southern states)."""

    sub_survey_number: str | None = None
    """Hissa number of the survey number itself, where the record is for a hissa."""

    # -- areas --------------------------------------------------------------------------
    total_area: AreaMeasurement | None = None
    """The parcel total as printed. Rules compare derived sums against this, never
    the other way round -- the printed figure is the assertion under test."""

    classified_areas: list[ClassifiedArea] = Field(default_factory=list)
    """Breakup by revenue classification. Should total :attr:`total_area`."""

    sub_divisions: list[SubDivision] = Field(default_factory=list)
    """Should also total :attr:`total_area` -- the headline consistency check."""

    # -- rights ----------------------------------------------------------------------------
    owners: list[OwnerRecord] = Field(default_factory=list)
    mutations: list[MutationEntry] = Field(default_factory=list)
    encumbrances: list[Encumbrance] = Field(default_factory=list)
    crops: list[CropEntry] = Field(default_factory=list)

    # -- revenue -----------------------------------------------------------------------------
    assessment_amount: Decimal | None = Field(default=None, ge=0)
    """Total land revenue / akarni for the parcel, in rupees."""

    water_rate: Decimal | None = Field(default=None, ge=0)
    """Jud / water cess, where separately assessed."""

    other_rights_remarks: str | None = None
    source_page_indices: list[int] = Field(default_factory=list)
    """Pages of the source document this parcel was assembled from."""

    # -- derived views ---------------------------------------------------------------------

    @computed_field  # type: ignore[prop-decorator]
    @property
    def parcel_key(self) -> str:
        """Stable-ish identity for deduplication and cross-referencing.

        Not a primary key: it is only as unique as the identifiers actually printed on
        the scan. The backend assigns a surrogate UUID; this is for human matching and
        for joining to a cadastral polygon.
        """
        parts = [
            self.jurisdiction.village_lgd_code or self.jurisdiction.village or "?",
            self.khata_number or "-",
            self.survey_number or (self.khasra_numbers[0] if self.khasra_numbers else "-"),
            self.sub_survey_number or "",
        ]
        return "/".join(p for p in parts if p)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cultivable_area_sq_metre(self) -> Decimal:
        return sum(
            (ca.area.sq_metre for ca in self.classified_areas if ca.cultivability is CultivabilityClass.CULTIVABLE),
            Decimal(0),
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def non_cultivable_area_sq_metre(self) -> Decimal:
        return sum(
            (
                ca.area.sq_metre
                for ca in self.classified_areas
                if ca.cultivability is CultivabilityClass.NON_CULTIVABLE
            ),
            Decimal(0),
        )

    @property
    def sub_division_area_total(self) -> AreaMeasurement:
        return sum_areas([sd.area for sd in self.sub_divisions])

    @property
    def classified_area_total(self) -> AreaMeasurement:
        return sum_areas([ca.area for ca in self.classified_areas])

    @property
    def total_ownership_share(self) -> Fraction:
        """Sum of recorded shares. Should be exactly 1 for a fully-recorded parcel."""
        return sum((o.share.fraction for o in self.owners if o.share is not None), Fraction(0))

    @property
    def active_encumbrances(self) -> list[Encumbrance]:
        return [e for e in self.encumbrances if e.is_live]

    @property
    def latest_mutation(self) -> MutationEntry | None:
        dated = [m for m in self.mutations if m.entry_date is not None]
        if not dated:
            return None
        return max(dated, key=lambda m: m.entry_date)  # type: ignore[arg-type,return-value]
