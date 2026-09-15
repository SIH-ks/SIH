"""Turning submitted documents into a :class:`~adhikar.schemas.succession.SuccessionCase`.

Interpretation happens **here**, deterministically, and never in whatever produced
the raw values -- the same commitment :mod:`adhikar.llm.mapper` makes for the Vision
LLM's output, for the same reason. A caller (or a model, or an OCR pass) is good at
transcribing ``"12/05/2025"`` and bad at deciding whether that is 12 May or 5
December; a lookup that misses produces ``None`` plus a finding, whereas a transcriber
that guesses produces a confident wrong answer nothing downstream can detect.

So every value that arrives as a string goes through the package's existing
normalisers: :func:`~adhikar.normalize.vocab.parse_record_date` (day-first, as Indian
revenue records are), :func:`~adhikar.normalize.vocab.parse_share` (which recovers
``1/3`` from ``0.3333``), :func:`~adhikar.normalize.vocab.resolve_relation`,
:func:`~adhikar.normalize.vocab.resolve_mutation_type` and
:func:`~adhikar.normalize.vocab.resolve_mutation_status`, and the
:class:`~adhikar.schemas.units.AreaMeasurement` unit machinery -- which refuses to
convert a bigha figure without a region key rather than fabricating an area.

A field that will not normalise is left unset. The succession rules are written to
report an absent value as an absent value, so degrading here is strictly better than
inventing something for them to validate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from ..normalize.numerals import to_ascii_digits
from ..normalize.vocab import (
    parse_record_date,
    parse_share,
    resolve_mutation_status,
    resolve_mutation_type,
    resolve_relation,
)
from ..schemas.enums import MutationStatus, MutationType, RelationType, TenureType
from ..schemas.land_record import LandParcelRecord, PersonName
from ..schemas.succession import (
    DeathRecord,
    EvidenceRef,
    HeirCandidate,
    MutationRecord,
    OwnershipEntry,
    ParcelIdentity,
    RecordSnapshot,
    SuccessionCase,
    SuccessionDocumentType,
    SupportingDocument,
)
from ..schemas.units import AmbiguousUnitError, AreaMeasurement, AreaUnit, UnitConversionError

__all__ = [
    "SUPPORTED_TEXT_DOCUMENTS",
    "TextExtraction",
    "normalize_case",
    "parse_document_text",
    "snapshot_from_record",
]


# ======================================================================================
# Pipeline integration: a Record of Rights the extractor already produced
# ======================================================================================


def snapshot_from_record(
    record: LandParcelRecord,
    *,
    label: str | None = None,
    document_type: SuccessionDocumentType = SuccessionDocumentType.JAMABANDI,
    document_id: str | None = None,
    as_of: date | None = None,
) -> RecordSnapshot:
    """Project an extracted land record onto a succession snapshot.

    This is the seam between succession validation and the rest of the engine: a
    Jamabandi that went through ``process_document`` -- OCR ensemble, table layout,
    Vision LLM, vernacular resolution, unit conversion -- becomes a succession
    document with no second extraction pass and no competing schema. The owners,
    shares and parcel identifiers are the pipeline's own normalised output.

    ``as_of`` falls back to the record's revenue year when the caller does not supply
    a date, since that is the only temporal anchor a Jamabandi page carries.
    """
    inferred = as_of is None
    resolved_as_of = as_of or _year_start(record.jurisdiction.revenue_year)
    return RecordSnapshot.from_record(
        record,
        label=label or _default_label(record, document_type),
        document_type=document_type,
        document_id=document_id,
        as_of=resolved_as_of,
        as_of_inferred=inferred and resolved_as_of is not None,
    )


def _default_label(record: LandParcelRecord, document_type: SuccessionDocumentType) -> str:
    year = record.jurisdiction.revenue_year
    base = document_type.label
    return f"{base} ({year})" if year else base


def _year_start(revenue_year: str | None) -> date | None:
    """First day of a revenue year printed as ``2019-20`` or ``2019``.

    A revenue year is a range, not a date; anchoring a snapshot at its start is a
    convention, and it is recorded as ``date_stated=False`` on the timeline so the
    console never draws an inferred position as though it were printed on the page.
    """
    if not revenue_year:
        return None
    match = re.match(r"\s*(\d{4})", to_ascii_digits(revenue_year))
    if not match:
        return None
    year = int(match.group(1))
    return date(year, 1, 1) if 1800 <= year <= 2200 else None


# ======================================================================================
# Structured payloads
# ======================================================================================


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _person(value: Any, *, default_relation: str | None = None) -> PersonName | None:
    """Build a :class:`PersonName` from a string or a ``{name, relation, ...}`` object.

    Accepting both shapes is not laxity: a legal-heir certificate keyed by a clerk
    gives ``{"name": "Amit Sharma", "relation": "son"}``, while a mutation order's
    transferee list is often just a list of names, and forcing callers to wrap the
    second in the first buys nothing.
    """
    if value is None:
        return None
    if isinstance(value, str):
        raw = _text(value)
        if raw is None:
            return None
        return PersonName(
            raw=raw,
            relation_type=resolve_relation(default_relation).value if default_relation else RelationType.UNKNOWN,
        )
    if not isinstance(value, dict):
        return None

    raw = _text(value.get("name") or value.get("raw") or value.get("raw_name"))
    if raw is None:
        return None
    relation_raw = _text(value.get("relation") or value.get("relation_type") or default_relation)
    relation = resolve_relation(relation_raw)
    return PersonName(
        raw=raw,
        transliterated=_text(value.get("transliterated")),
        relation_type=relation.value,
        relation_name=_text(
            value.get("relation_name") or value.get("father_name") or value.get("husband_name")
        ),
    )


def _area(payload: dict[str, Any] | None, *, warnings: list[str], where: str) -> AreaMeasurement | None:
    """Parse ``{"area": 5.0, "area_unit": "hectare"}`` into a canonical measurement.

    ``area_unit`` defaults to hectare because that is what a modern RoR prints, but a
    bigha value without ``region_key`` is **refused** rather than converted -- the
    unit ranges over a threefold spread between states, and a wrong bigha produces a
    plausible number, which is worse than no number at all.
    """
    if not payload:
        return None
    raw = payload.get("area", payload.get("area_sq_metre"))
    if raw is None:
        return None

    try:
        amount = Decimal(str(to_ascii_digits(str(raw))).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        warnings.append(f"{where}: could not read the area value {raw!r}; it was left unset.")
        return None

    unit_raw = _text(payload.get("area_unit")) or ("sq_metre" if "area_sq_metre" in payload else "hectare")
    try:
        unit = AreaUnit(unit_raw.strip().lower().replace(" ", "_"))
    except ValueError:
        warnings.append(
            f"{where}: unrecognised area unit {unit_raw!r}; the area was left unset rather than assumed."
        )
        return None

    try:
        return AreaMeasurement.from_unit(
            amount, unit, region_key=_text(payload.get("region_key")), raw_text=_text(payload.get("area_text"))
        )
    except (AmbiguousUnitError, UnitConversionError) as exc:
        warnings.append(f"{where}: {exc}. The area was left unset rather than guessed.")
        return None


def _parcel(payload: dict[str, Any] | None, *, warnings: list[str], where: str) -> ParcelIdentity:
    """Read the ``land`` block of a document payload."""
    if not payload:
        return ParcelIdentity()
    return ParcelIdentity(
        khasra_number=_text(payload.get("khasra") or payload.get("khasra_number")),
        khata_number=_text(payload.get("khata") or payload.get("khata_number")),
        khatauni_number=_text(payload.get("khatauni") or payload.get("khatauni_number")),
        survey_number=_text(payload.get("survey") or payload.get("survey_number")),
        sub_survey_number=_text(payload.get("sub_survey") or payload.get("sub_survey_number")),
        village=_text(payload.get("village")),
        tehsil=_text(payload.get("tehsil") or payload.get("taluka")),
        district=_text(payload.get("district")),
        state=_text(payload.get("state")),
        area=_area(payload, warnings=warnings, where=f"{where}.land"),
    )


def _owners(
    raw: Any, *, evidence_for, field_name: str  # noqa: ANN001 - a bound `evidence` method
) -> list[OwnershipEntry]:
    """Read an owner / transferee list, normalising each share deterministically."""
    entries: list[OwnershipEntry] = []
    for index, item in enumerate(raw or []):
        name = _person(item)
        if name is None:
            continue
        share = None
        if isinstance(item, dict):
            share_raw = item.get("share")
            share = parse_share(
                _text(share_raw),
                numerator=_text(item.get("share_numerator")),
                denominator=_text(item.get("share_denominator")),
            )
        entries.append(
            OwnershipEntry(
                name=name,
                share=share,
                tenure_type=TenureType.UNKNOWN
                if isinstance(item, dict) and item.get("is_owner") is False
                else TenureType.OWNER,
                serial_number=_text(item.get("serial_number")) if isinstance(item, dict) else None,
                source=evidence_for(f"{field_name}[{index}].name", str(name)),
            )
        )
    return entries


@dataclass(slots=True)
class _Normalisation:
    """Accumulator for one :func:`normalize_case` run."""

    warnings: list[str] = field(default_factory=list)


def normalize_case(payload: dict[str, Any]) -> tuple[SuccessionCase, list[str]]:
    """Build a validated case from a raw, string-valued document bundle.

    The payload is a ``documents`` list whose entries carry a ``document_type``
    discriminator; everything else about an entry depends on that type. Returns the
    case alongside the warnings raised while interpreting it -- a date that would not
    parse, an area unit nobody recognised -- so the caller can surface *how* a case
    was read as well as what it concluded.

    Unrecognised document types are kept as
    :class:`~adhikar.schemas.succession.SupportingDocument` of type ``other`` rather
    than dropped: a document the engine cannot classify is still a document the
    reviewer should see listed in the evidence index.
    """
    state = _Normalisation()
    snapshots: list[RecordSnapshot] = []
    deaths: list[DeathRecord] = []
    heirs: list[HeirCandidate] = []
    mutations: list[MutationRecord] = []
    supporting: list[SupportingDocument] = []

    for index, raw in enumerate(payload.get("documents") or []):
        if not isinstance(raw, dict):
            state.warnings.append(f"documents[{index}]: not an object; skipped.")
            continue
        kind = _document_type(raw.get("document_type"))
        where = f"documents[{index}]"

        if kind.is_record_of_rights:
            snapshots.append(_record_snapshot(raw, kind, state, where))
        elif kind is SuccessionDocumentType.DEATH_CERTIFICATE:
            record = _death_record(raw, kind, state, where)
            if record is not None:
                deaths.append(record)
        elif kind in {
            SuccessionDocumentType.LEGAL_HEIR_CERTIFICATE,
            SuccessionDocumentType.FAMILY_REGISTER,
        }:
            heirs.extend(_heirs(raw, kind, state, where))
        elif kind in {SuccessionDocumentType.MUTATION_ORDER, SuccessionDocumentType.MUTATION_APPLICATION}:
            mutations.append(_mutation(raw, kind, state, where))
        else:
            supporting.append(_supporting(raw, kind, state, where))

    case = SuccessionCase(
        case_id=_text(payload.get("case_id")) or "case",
        parcel_key=_text(payload.get("parcel_key")),
        record_snapshots=snapshots,
        death_records=deaths,
        heirs=heirs,
        mutations=mutations,
        supporting_documents=supporting,
        submitted_by=_text(payload.get("submitted_by")),
        notes=_text(payload.get("notes")),
    )
    return case, state.warnings


def _document_type(raw: Any) -> SuccessionDocumentType:
    """Resolve the discriminator, tolerating the short forms callers actually send."""
    text = (_text(raw) or "").lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ror": SuccessionDocumentType.JAMABANDI,
        "record_of_rights": SuccessionDocumentType.JAMABANDI,
        "jamabandi": SuccessionDocumentType.JAMABANDI,
        "old_jamabandi": SuccessionDocumentType.JAMABANDI,
        "previous_jamabandi": SuccessionDocumentType.JAMABANDI,
        "updated_ror": SuccessionDocumentType.UPDATED_JAMABANDI,
        "new_jamabandi": SuccessionDocumentType.UPDATED_JAMABANDI,
        "mutation": SuccessionDocumentType.MUTATION_ORDER,
        "intekal": SuccessionDocumentType.MUTATION_ORDER,
        "ferfar": SuccessionDocumentType.MUTATION_ORDER,
        "legal_heir": SuccessionDocumentType.LEGAL_HEIR_CERTIFICATE,
        "heir_certificate": SuccessionDocumentType.LEGAL_HEIR_CERTIFICATE,
        "family_details": SuccessionDocumentType.FAMILY_REGISTER,
        "release_deed": SuccessionDocumentType.RELINQUISHMENT_DEED,
        "relinquishment": SuccessionDocumentType.RELINQUISHMENT_DEED,
        "haq_tyag": SuccessionDocumentType.RELINQUISHMENT_DEED,
        "partition": SuccessionDocumentType.PARTITION_DEED,
        "settlement": SuccessionDocumentType.FAMILY_SETTLEMENT,
        "decree": SuccessionDocumentType.COURT_ORDER,
    }
    if text in aliases:
        return aliases[text]
    try:
        return SuccessionDocumentType(text)
    except ValueError:
        return SuccessionDocumentType.OTHER


def _common(raw: dict[str, Any]) -> tuple[str | None, str | None, bool]:
    return (
        _text(raw.get("document_id")),
        _text(raw.get("label") or raw.get("document_label")),
        bool(raw.get("is_legible", True)),
    )


def _record_snapshot(
    raw: dict[str, Any], kind: SuccessionDocumentType, state: _Normalisation, where: str
) -> RecordSnapshot:
    document_id, label, legible = _common(raw)
    stated = _date(raw.get("as_of") or raw.get("date"), state, f"{where}.as_of")
    from_year = _year_start(_text(raw.get("revenue_year"))) if stated is None else None
    snapshot = RecordSnapshot(
        label=label or kind.label,
        document_type=kind,
        document_id=document_id,
        as_of=stated or from_year,
        as_of_inferred=stated is None and from_year is not None,
        revenue_year=_text(raw.get("revenue_year")),
        parcel=_parcel(raw.get("land") or raw.get("parcel"), warnings=state.warnings, where=where),
        is_legible=legible,
    )
    snapshot.owners = _owners(raw.get("owners"), evidence_for=snapshot.evidence, field_name="owners")
    return snapshot


def _death_record(
    raw: dict[str, Any], kind: SuccessionDocumentType, state: _Normalisation, where: str
) -> DeathRecord | None:
    document_id, label, legible = _common(raw)
    person = _person(raw.get("person") or raw.get("deceased") or raw.get("name"))
    if person is None:
        state.warnings.append(f"{where}: death certificate names no person; skipped.")
        return None
    return DeathRecord(
        person=person,
        date_of_death=_date(
            raw.get("date_of_death") or raw.get("death_date"), state, f"{where}.date_of_death"
        ),
        registration_number=_text(raw.get("registration_number") or raw.get("reference")),
        place=_text(raw.get("place") or raw.get("place_of_death")),
        issuing_authority=_text(raw.get("issuing_authority")),
        document_type=kind,
        document_id=document_id,
        document_label=label,
        is_legible=legible,
    )


def _heirs(
    raw: dict[str, Any], kind: SuccessionDocumentType, state: _Normalisation, where: str
) -> list[HeirCandidate]:
    document_id, label, _ = _common(raw)
    deceased = _text(raw.get("deceased") or raw.get("deceased_name"))
    collected: list[HeirCandidate] = []

    for index, item in enumerate(raw.get("heirs") or raw.get("family_members") or []):
        name = _person(item)
        if name is None:
            state.warnings.append(f"{where}.heirs[{index}]: no name; skipped.")
            continue
        relation_raw = item.get("relation") if isinstance(item, dict) else None
        relation = resolve_relation(_text(relation_raw))
        share = (
            parse_share(_text(item.get("share")))
            if isinstance(item, dict) and item.get("share") is not None
            else None
        )
        collected.append(
            HeirCandidate(
                name=name,
                relation_to_deceased=relation.value,
                deceased_name=deceased or name.relation_name,
                stated_share=share,
                is_minor=bool(item.get("is_minor", False)) if isinstance(item, dict) else False,
                is_deceased=bool(item.get("is_deceased", False)) if isinstance(item, dict) else False,
                source=EvidenceRef(
                    document_type=kind,
                    document_id=document_id,
                    document_label=label or kind.label,
                    field_path=f"heirs[{index}].name",
                    value=str(name),
                    raw_value=_text(relation_raw),
                ),
            )
        )
    return collected


def _mutation(
    raw: dict[str, Any], kind: SuccessionDocumentType, state: _Normalisation, where: str
) -> MutationRecord:
    document_id, label, legible = _common(raw)
    entry = _date(raw.get("entry_date") or raw.get("application_date"), state, f"{where}.entry_date")
    order = _date(raw.get("order_date") or raw.get("date"), state, f"{where}.order_date")
    if entry and order and order < entry:
        # The model refuses this combination outright; downgrading it to a warning
        # and dropping the entry date keeps the rest of the mutation usable, and the
        # date conflict still surfaces as a normalisation warning on the report.
        state.warnings.append(
            f"{where}: order date {order} precedes entry date {entry}; the entry date was dropped "
            "so the rest of the mutation could still be read."
        )
        entry = None

    mutation = MutationRecord(
        mutation_number=_text(raw.get("mutation_number") or raw.get("number")),
        mutation_type=resolve_mutation_type(_text(raw.get("mutation_type") or raw.get("type"))).value
        if raw.get("mutation_type") or raw.get("type")
        else MutationType.UNKNOWN,
        status=resolve_mutation_status(_text(raw.get("status"))).value
        if raw.get("status")
        else MutationStatus.UNKNOWN,
        entry_date=entry,
        order_date=order,
        parcel=_parcel(raw.get("land") or raw.get("parcel"), warnings=state.warnings, where=where),
        area_transacted=_area(
            {"area": raw.get("area_transacted"), "area_unit": raw.get("area_unit")},
            warnings=state.warnings,
            where=f"{where}.area_transacted",
        )
        if raw.get("area_transacted") is not None
        else None,
        basis_reference=_text(raw.get("basis_reference") or raw.get("basis")),
        document_type=kind,
        document_id=document_id,
        document_label=label,
        is_legible=legible,
        remarks=_text(raw.get("remarks")),
    )

    previous = raw.get("previous_owners")
    if previous is None and raw.get("previous_owner") is not None:
        previous = [raw["previous_owner"]]
    mutation.previous_owners = _owners(
        previous, evidence_for=mutation.evidence, field_name="previous_owners"
    )
    mutation.new_owners = _owners(
        raw.get("new_owners") or raw.get("to_owners"),
        evidence_for=mutation.evidence,
        field_name="new_owners",
    )
    return mutation


def _supporting(
    raw: dict[str, Any], kind: SuccessionDocumentType, state: _Normalisation, where: str
) -> SupportingDocument:
    document_id, label, legible = _common(raw)
    document = SupportingDocument(
        document_type=kind,
        document_id=document_id,
        label=label,
        issued_on=_date(raw.get("issued_on") or raw.get("date"), state, f"{where}.issued_on"),
        reference=_text(raw.get("reference") or raw.get("registration_number")),
        parcel=_parcel(raw.get("land") or raw.get("parcel"), warnings=state.warnings, where=where),
        is_legible=legible,
        summary=_text(raw.get("summary")),
        raw_text=_text(raw.get("raw_text")),
    )
    document.executants = [
        person
        for person in (
            _person(item)
            for item in (raw.get("executants") or raw.get("parties") or raw.get("relinquished_by") or [])
        )
        if person is not None
    ]
    document.beneficiaries = _owners(
        raw.get("beneficiaries") or raw.get("in_favour_of"),
        evidence_for=document.evidence,
        field_name="beneficiaries",
    )
    return document


def _date(raw: Any, state: _Normalisation, where: str) -> date | None:
    """Parse a date day-first, recording a warning when it will not parse."""
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    parsed = parse_record_date(_text(raw))
    if parsed is None:
        state.warnings.append(f"{where}: could not read a date from {raw!r}; it was left unset.")
    return parsed


# ======================================================================================
# OCR text layer
# ======================================================================================

SUPPORTED_TEXT_DOCUMENTS: frozenset[SuccessionDocumentType] = frozenset(
    {SuccessionDocumentType.DEATH_CERTIFICATE, SuccessionDocumentType.LEGAL_HEIR_CERTIFICATE}
)
"""Document types :func:`parse_document_text` can read off an OCR text layer.

Both are **form** documents: a fixed set of labelled fields, one value each, no
tabular structure. That is why a deterministic label-and-value pass works on them and
would not work on a Jamabandi, whose meaning is carried by a multi-column grid --
which is exactly the job the OCR + table-layout + Vision-LLM pipeline already does.
Adding a third type here means adding its labels to :data:`_LABELS`, not writing a
new parser.
"""

_LABELS: dict[str, tuple[str, ...]] = {
    "name": ("name of the deceased", "name of deceased", "deceased name", "मृतक का नाम", "name"),
    "date_of_death": ("date of death", "मृत्यु की तिथि", "मृत्यू दिनांक", "date of the death"),
    "registration_number": ("registration no", "registration number", "reg no", "पंजीकरण संख्या"),
    "place": ("place of death", "मृत्यु का स्थान", "place"),
    "issuing_authority": ("issued by", "registrar", "issuing authority"),
}

_HEIR_LABELS: tuple[str, ...] = (
    "wife", "husband", "son", "daughter", "widow", "mother", "father",
    "पत्नी", "पति", "पुत्र", "पुत्री", "विधवा", "मुलगा", "मुलगी",
)

_LINE_SPLIT = re.compile(r"[\r\n]+")
_KEY_VALUE = re.compile(r"^\s*([^:：]{2,40})\s*[:：]\s*(.+?)\s*$")


@dataclass(slots=True)
class TextExtraction:
    """What a labelled-field pass recovered from one document's text layer.

    ``confidence`` is the share of the fields this document type needs that were
    actually found -- reported, never assumed, because a caller acting on a 0.4
    extraction should know it is acting on a 0.4 extraction.
    """

    document_type: SuccessionDocumentType
    fields: dict[str, str]
    heirs: list[tuple[str, str]]
    confidence: float
    unmatched_labels: list[str]

    def as_payload(self, *, document_id: str | None = None, label: str | None = None) -> dict[str, Any]:
        """Render as a :func:`normalize_case` document entry.

        Going back through the normaliser rather than constructing the domain object
        here means an OCR-read certificate and a hand-keyed one are interpreted by
        exactly the same code -- so a date that parses one way through the API cannot
        parse another way through the scanner.
        """
        base: dict[str, Any] = {
            "document_type": self.document_type.value,
            "document_id": document_id,
            "label": label,
        }
        if self.document_type is SuccessionDocumentType.DEATH_CERTIFICATE:
            base.update(
                {
                    "person": {"name": self.fields.get("name")},
                    "date_of_death": self.fields.get("date_of_death"),
                    "registration_number": self.fields.get("registration_number"),
                    "place": self.fields.get("place"),
                    "issuing_authority": self.fields.get("issuing_authority"),
                }
            )
        else:
            base.update(
                {
                    "deceased": self.fields.get("name"),
                    "heirs": [{"name": name, "relation": relation} for relation, name in self.heirs],
                }
            )
        return base


def parse_document_text(
    text: str, document_type: SuccessionDocumentType
) -> TextExtraction:
    """Read labelled fields off a form document's text layer.

    Designed for the output of :func:`adhikar.ocr.ensemble.run_ocr_ensemble` -- join
    the page's line texts with newlines and pass them in -- but it takes any text, so
    it is equally usable on a digital PDF's embedded layer or on a paste.

    Deliberately conservative: a label that is not found leaves its field unset and
    lowers :attr:`TextExtraction.confidence`, rather than falling back to "the longest
    line is probably the name". A missing field is honest; a wrongly-confident one
    puts the wrong person in a land record.

    :raises ValueError: for a document type this pass does not cover -- see
        :data:`SUPPORTED_TEXT_DOCUMENTS` for why a Jamabandi is not one of them.
    """
    if document_type not in SUPPORTED_TEXT_DOCUMENTS:
        raise ValueError(
            f"{document_type.value} has no labelled-field parser; records of rights go through "
            "adhikar.pipeline.process_document, which reads their table structure."
        )

    found: dict[str, str] = {}
    heirs: list[tuple[str, str]] = []

    for line in _LINE_SPLIT.split(text):
        match = _KEY_VALUE.match(line)
        if not match:
            continue
        key, value = match.group(1).strip().lower(), match.group(2).strip()
        if not value:
            continue

        for canonical, labels in _LABELS.items():
            if canonical in found:
                continue
            # Longest label first, so "name of the deceased" wins over the bare
            # "name" fallback on a certificate that carries both.
            if any(label in key for label in sorted(labels, key=len, reverse=True)):
                found[canonical] = value
                break
        else:
            for relation in _HEIR_LABELS:
                if relation in key:
                    heirs.append((relation, value))
                    break

    required = ("name", "date_of_death") if document_type is SuccessionDocumentType.DEATH_CERTIFICATE else ("name",)
    present = sum(1 for key in required if key in found)
    confidence = round(present / len(required), 4)
    if document_type is SuccessionDocumentType.LEGAL_HEIR_CERTIFICATE and not heirs:
        confidence = round(confidence * 0.5, 4)

    return TextExtraction(
        document_type=document_type,
        fields=found,
        heirs=heirs,
        confidence=confidence,
        unmatched_labels=[key for key in required if key not in found],
    )
