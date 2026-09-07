"""Map the LLM's wire-format extraction onto the domain model, with provenance.

This is where the three normalisation passes -- numerals, areas, vocabulary -- meet
the raw transcription and turn it into typed, validated records. Every value that
makes it into the domain model also gets a :class:`FieldProvenance` entry keyed by its
JSON path, which is what lets the reviewer console point at the exact source text and
LLM confidence behind any field.

Failure policy: a single malformed sub-object (one bad owner row, one bad mutation)
is dropped with a warning rather than failing the whole parcel -- 40 clean owner rows
should not be discarded because row 41 had an impossible value. A parcel that fails to
map at all *is* fatal, since there is nothing left to validate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..normalize.areas import area_from_llm, default_system_for_format
from ..normalize.vocab import (
    is_equal_share_marker,
    parse_record_date,
    parse_share,
    resolve_classification,
    resolve_encumbrance_status,
    resolve_encumbrance_type,
    resolve_irrigation,
    resolve_mutation_status,
    resolve_mutation_type,
    resolve_relation,
    resolve_tenure,
)
from ..schemas.artifact import FieldProvenance
from ..schemas.enums import EncumbranceStatus, ExtractorKind, RecordFormat
from ..schemas.land_record import (
    ClassifiedArea,
    CropEntry,
    Encumbrance,
    Jurisdiction,
    LandParcelRecord,
    MutationEntry,
    OwnerRecord,
    OwnershipShare,
    PersonName,
    SubDivision,
)
from ..schemas.llm_contract import (
    LlmCrop,
    LlmEncumbrance,
    LlmExtraction,
    LlmMutation,
    LlmOwner,
    LlmParcel,
    LlmPerson,
)

__all__ = ["MappingResult", "index_field_confidences", "map_extraction"]


def index_field_confidences(extraction: LlmExtraction) -> dict[str, tuple[float, str | None]]:
    """Build the path -> (confidence, reason) index :func:`map_extraction` expects.

    Separated from ``map_extraction`` itself so a caller who wants to inspect or
    adjust confidences (e.g. discount everything on a low-``overall_confidence``
    page) can do so between indexing and mapping.
    """
    return {fc.field_path: (fc.confidence, fc.reason) for fc in extraction.field_confidences}

_FORMAT_BY_WIRE_VALUE: dict[str, RecordFormat] = {
    "jamabandi": RecordFormat.JAMABANDI,
    "satbara_7_12": RecordFormat.SATBARA,
    "khasra_girdawari": RecordFormat.KHASRA_GIRDAWARI,
    "ror_generic": RecordFormat.ROR_GENERIC,
    "unknown": RecordFormat.UNKNOWN,
}


@dataclass(slots=True)
class MappingResult:
    """Everything one extraction call produced, ready to attach to an artifact."""

    parcels: list[LandParcelRecord] = field(default_factory=list)
    provenance: dict[str, FieldProvenance] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def map_extraction(
    extraction: LlmExtraction,
    *,
    llm_confidence_by_path: dict[str, tuple[float, str | None]] | None = None,
    region_key: str | None = None,
) -> MappingResult:
    """Convert one :class:`LlmExtraction` into domain parcels plus provenance.

    :param llm_confidence_by_path: Pre-indexed ``field_confidences`` from the same
        extraction (path -> (confidence, reason)), built once by the caller and
        passed in so this function stays a pure mapper.
    :param region_key: Bigha-family region, when the deployment or the jurisdiction
        resolves one. Areas that need it and find it absent are recorded as missing,
        not silently dropped -- see :func:`_map_area`.
    """
    confidences = llm_confidence_by_path or {}
    record_format = _FORMAT_BY_WIRE_VALUE.get(extraction.detected_record_format, RecordFormat.UNKNOWN)
    default_system = default_system_for_format(record_format)

    result = MappingResult()
    for i, llm_parcel in enumerate(extraction.parcels):
        path_prefix = f"$.parcels[{i}]"
        try:
            parcel, provenance = _map_parcel(
                llm_parcel,
                record_format=record_format,
                default_system=default_system,
                region_key=region_key,
                path_prefix=path_prefix,
                confidences=confidences,
                warnings=result.warnings,
            )
        except Exception as exc:  # noqa: BLE001 - one bad parcel must not sink the batch
            result.warnings.append(f"{path_prefix}: failed to map parcel, skipped ({exc})")
            continue
        result.parcels.append(parcel)
        result.provenance.update(provenance)

    return result


def _confidence_for(path: str, confidences: dict[str, tuple[float, str | None]]) -> tuple[float, str | None]:
    """Default confidence for a field the model did not flag: high, per the system
    prompt's instruction that only uncertain fields appear in ``field_confidences``."""
    return confidences.get(path, (0.95, None))


def _record_provenance(
    provenance: dict[str, FieldProvenance],
    path: str,
    *,
    raw_text: str | None,
    confidences: dict[str, tuple[float, str | None]],
) -> None:
    if raw_text is None:
        return
    confidence, reason = _confidence_for(path, confidences)
    provenance[path] = FieldProvenance(
        extractor=ExtractorKind.VISION_LLM,
        confidence=confidence,
        raw_text=raw_text,
        reason=reason,
    )


def _map_person(llm_person: LlmPerson) -> PersonName | None:
    if not llm_person.raw_name or not llm_person.raw_name.strip():
        return None
    relation = resolve_relation(llm_person.relation_raw)
    return PersonName(
        raw=llm_person.raw_name,
        transliterated=llm_person.transliterated,
        relation_type=relation.value,
        relation_name=llm_person.relation_name,
    )


def _map_area(
    llm_area,  # noqa: ANN001 - LlmArea | None, kept loose to avoid a long import line
    *,
    default_system,  # noqa: ANN001
    region_key: str | None,
    path: str,
    provenance: dict[str, FieldProvenance],
    confidences: dict[str, tuple[float, str | None]],
    warnings: list[str],
):
    if llm_area is None:
        return None
    try:
        measurement = area_from_llm(llm_area, default_system=default_system, region_key=region_key)
    except Exception as exc:  # noqa: BLE001 - AmbiguousUnitError and parse failures alike
        warnings.append(f"{path}: could not resolve area ({exc})")
        return None
    if measurement is not None and llm_area.raw_text:
        _record_provenance(provenance, path, raw_text=llm_area.raw_text, confidences=confidences)
    return measurement


def _map_owner(
    llm_owner: LlmOwner,
    *,
    path: str,
    provenance: dict[str, FieldProvenance],
    confidences: dict[str, tuple[float, str | None]],
    warnings: list[str],
) -> OwnerRecord | None:
    name = _map_person(llm_owner.name)
    if name is None:
        warnings.append(f"{path}: owner row has no name, skipped")
        return None

    tenure_match = resolve_tenure(llm_owner.tenure_raw)
    if llm_owner.tenure_raw and not tenure_match.resolved:
        warnings.append(f"{path}.tenure_type: unresolved vocabulary {llm_owner.tenure_raw!r}")
    _record_provenance(provenance, f"{path}.name.raw_name", raw_text=llm_owner.name.raw_name, confidences=confidences)
    if llm_owner.tenure_raw:
        _record_provenance(provenance, f"{path}.tenure_type", raw_text=llm_owner.tenure_raw, confidences=confidences)

    share: OwnershipShare | None = None
    if llm_owner.share is not None and not is_equal_share_marker(llm_owner.share.raw_text):
        share = parse_share(
            llm_owner.share.raw_text,
            numerator=llm_owner.share.numerator,
            denominator=llm_owner.share.denominator,
        )
        if share is None and llm_owner.share.raw_text:
            warnings.append(f"{path}.share: could not parse {llm_owner.share.raw_text!r}")

    return OwnerRecord(
        serial_number=llm_owner.serial_number,
        name=name,
        tenure_type=tenure_match.value,
        share=share,
        khata_number=llm_owner.khata_number,
        remarks=llm_owner.remarks,
    )


def _map_mutation(
    llm_mutation: LlmMutation,
    *,
    path: str,
    provenance: dict[str, FieldProvenance],
    confidences: dict[str, tuple[float, str | None]],
    warnings: list[str],
    default_system,  # noqa: ANN001
    region_key: str | None,
) -> MutationEntry | None:
    type_match = resolve_mutation_type(llm_mutation.type_raw)
    status_match = resolve_mutation_status(llm_mutation.status_raw)
    if llm_mutation.type_raw and not type_match.resolved:
        warnings.append(f"{path}.mutation_type: unresolved vocabulary {llm_mutation.type_raw!r}")

    entry_date = parse_record_date(llm_mutation.entry_date_raw)
    order_date = parse_record_date(llm_mutation.order_date_raw)

    from_parties = [p for p in (_map_person(x) for x in llm_mutation.from_parties) if p is not None]
    to_parties = [p for p in (_map_person(x) for x in llm_mutation.to_parties) if p is not None]

    area_transacted = _map_area(
        llm_mutation.area_transacted,
        default_system=default_system,
        region_key=region_key,
        path=f"{path}.area_transacted",
        provenance=provenance,
        confidences=confidences,
        warnings=warnings,
    )

    try:
        return MutationEntry(
            mutation_number=llm_mutation.mutation_number,
            mutation_type=type_match.value,
            status=status_match.value,
            entry_date=entry_date,
            order_date=order_date,
            from_parties=from_parties,
            to_parties=to_parties,
            area_transacted=area_transacted,
            consideration_amount=_parse_money(llm_mutation.consideration_amount),
            document_reference=llm_mutation.document_reference,
            remarks=None,
            raw_text=llm_mutation.raw_text,
        )
    except Exception as exc:  # noqa: BLE001 - e.g. order_date < entry_date model validator
        warnings.append(f"{path}: dropped (validation failed: {exc})")
        return None


def _map_encumbrance(
    llm_enc: LlmEncumbrance,
    *,
    path: str,
    warnings: list[str],
) -> Encumbrance | None:
    type_match = resolve_encumbrance_type(llm_enc.type_raw)
    status_match = resolve_encumbrance_status(llm_enc.status_raw)
    created_on = parse_record_date(llm_enc.created_on_raw)
    discharged_on = parse_record_date(llm_enc.discharged_on_raw)

    # A discharge date with a status the vocabulary resolver did not recognise as
    # DISCHARGED is still evidence of discharge -- prefer the date over an UNKNOWN
    # status so the domain model's own consistency check does not fire spuriously.
    status = status_match.value
    if discharged_on is not None and status is not EncumbranceStatus.DISCHARGED:
        status = EncumbranceStatus.DISCHARGED

    try:
        return Encumbrance(
            encumbrance_type=type_match.value,
            status=status,
            holder_name=llm_enc.holder_name,
            amount=_parse_money(llm_enc.amount),
            created_on=created_on,
            discharged_on=discharged_on,
            reference=llm_enc.reference,
            remarks=None,
            raw_text=llm_enc.raw_text,
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"{path}: dropped (validation failed: {exc})")
        return None


def _map_crop(llm_crop: LlmCrop) -> CropEntry:
    irrigation = resolve_irrigation(llm_crop.irrigation_raw)
    return CropEntry(
        year=llm_crop.year,
        season=llm_crop.season_raw,
        crop_name=llm_crop.crop_name,
        area=area_from_llm(llm_crop.area) if llm_crop.area else None,
        irrigation_source=irrigation.value,
        remarks=llm_crop.remarks,
    )


def _parse_money(raw: str | None) -> Decimal | None:
    from ..normalize.numerals import parse_decimal

    return parse_decimal(raw, repair=True)


def _map_parcel(
    llm_parcel: LlmParcel,
    *,
    record_format: RecordFormat,
    default_system,  # noqa: ANN001
    region_key: str | None,
    path_prefix: str,
    confidences: dict[str, tuple[float, str | None]],
    warnings: list[str],
) -> tuple[LandParcelRecord, dict[str, FieldProvenance]]:
    provenance: dict[str, FieldProvenance] = {}
    j = llm_parcel.jurisdiction
    jurisdiction = Jurisdiction(
        state=j.state,
        district=j.district,
        tehsil=j.tehsil,
        village=j.village,
        hadbast_number=j.hadbast_number,
        revenue_year=j.revenue_year_raw,
        fasli_year=_parse_int_safe(j.fasli_year_raw),
    )

    total_area = _map_area(
        llm_parcel.total_area,
        default_system=default_system,
        region_key=region_key,
        path=f"{path_prefix}.total_area",
        provenance=provenance,
        confidences=confidences,
        warnings=warnings,
    )

    classified_areas: list[ClassifiedArea] = []
    for i, ca in enumerate(llm_parcel.classified_areas):
        area = _map_area(
            ca.area,
            default_system=default_system,
            region_key=region_key,
            path=f"{path_prefix}.classified_areas[{i}].area",
            provenance=provenance,
            confidences=confidences,
            warnings=warnings,
        )
        if area is None:
            warnings.append(f"{path_prefix}.classified_areas[{i}]: no area, skipped")
            continue
        classification = resolve_classification(ca.raw_label)
        if ca.raw_label and not classification.resolved:
            warnings.append(
                f"{path_prefix}.classified_areas[{i}].classification: "
                f"unresolved vocabulary {ca.raw_label!r}"
            )
        irrigation = resolve_irrigation(ca.irrigation_raw)
        classified_areas.append(
            ClassifiedArea(
                classification=classification.value,
                area=area,
                irrigation_source=irrigation.value,
                raw_label=ca.raw_label,
            )
        )

    sub_divisions: list[SubDivision] = []
    for i, sd in enumerate(llm_parcel.sub_divisions):
        area = _map_area(
            sd.area,
            default_system=default_system,
            region_key=region_key,
            path=f"{path_prefix}.sub_divisions[{i}].area",
            provenance=provenance,
            confidences=confidences,
            warnings=warnings,
        )
        if area is None:
            warnings.append(f"{path_prefix}.sub_divisions[{i}]: no area, skipped")
            continue
        classification = resolve_classification(sd.classification_raw)
        sub_divisions.append(
            SubDivision(
                sub_division_number=sd.sub_division_number or f"unnumbered-{i}",
                area=area,
                classification=classification.value,
                assessment_amount=_parse_money(sd.assessment_amount),
                owner_serial_numbers=list(sd.owner_serial_numbers),
                remarks=sd.remarks,
            )
        )

    owners: list[OwnerRecord] = []
    for i, o in enumerate(llm_parcel.owners):
        mapped = _map_owner(
            o,
            path=f"{path_prefix}.owners[{i}]",
            provenance=provenance,
            confidences=confidences,
            warnings=warnings,
        )
        if mapped is not None:
            owners.append(mapped)

    mutations: list[MutationEntry] = []
    for i, m in enumerate(llm_parcel.mutations):
        mapped = _map_mutation(
            m,
            path=f"{path_prefix}.mutations[{i}]",
            provenance=provenance,
            confidences=confidences,
            warnings=warnings,
            default_system=default_system,
            region_key=region_key,
        )
        if mapped is not None:
            mutations.append(mapped)

    encumbrances: list[Encumbrance] = []
    for i, e in enumerate(llm_parcel.encumbrances):
        mapped = _map_encumbrance(e, path=f"{path_prefix}.encumbrances[{i}]", warnings=warnings)
        if mapped is not None:
            encumbrances.append(mapped)

    crops = [_map_crop(c) for c in llm_parcel.crops]

    parcel = LandParcelRecord(
        record_format=record_format,
        jurisdiction=jurisdiction,
        khata_number=llm_parcel.khata_number,
        khatauni_number=llm_parcel.khatauni_number,
        khasra_numbers=list(llm_parcel.khasra_numbers),
        survey_number=llm_parcel.survey_number,
        sub_survey_number=llm_parcel.sub_survey_number,
        total_area=total_area,
        classified_areas=classified_areas,
        sub_divisions=sub_divisions,
        owners=owners,
        mutations=mutations,
        encumbrances=encumbrances,
        crops=crops,
        assessment_amount=_parse_money(llm_parcel.assessment_amount),
        water_rate=_parse_money(llm_parcel.water_rate),
        other_rights_remarks=llm_parcel.other_rights_remarks,
        source_page_indices=list(llm_parcel.source_page_indices),
    )
    return parcel, provenance


def _parse_int_safe(raw: str | None) -> int | None:
    from ..normalize.numerals import parse_int

    return parse_int(raw)
