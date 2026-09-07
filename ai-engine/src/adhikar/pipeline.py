"""The end-to-end pipeline: scan file in, :class:`ExtractionArtifact` out.

Stage order and why it is fixed:

``load -> preprocess -> OCR ensemble -> table layout -> Vision LLM -> normalise/map
-> validate -> discrepancy``

The OCR ensemble and table layout run *before* the LLM call, even though the LLM does
its own reading from the image, because their output becomes the text layer in the
prompt (see :mod:`adhikar.llm.extractor`) -- the model reads the picture and
cross-checks it against an independent character-level pass, which is materially more
accurate on faint or low-contrast scans than either signal alone. Validation and the
discrepancy engine run last and never influence extraction, so their findings stay a
trustworthy check on the extraction rather than a self-fulfilling one.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings, get_settings
from .exceptions import AdhikarError, StageDegradedError
from .geo.discrepancy import ConfidenceInputs, compute_discrepancy
from .layout.tables import assign_tokens_to_grid, detect_table_grids
from .llm.base import VisionExtractorProtocol
from .llm.factory import build_extractor
from .llm.bbox_attribution import attach_bboxes
from .llm.mapper import index_field_confidences, map_extraction
from .ocr.ensemble import run_ocr_ensemble
from .preprocessing.enhance import prepare_page
from .preprocessing.loader import load_document
from .schemas.artifact import ExtractionArtifact, ProcessingMetadata
from .schemas.enums import RecordFormat
from .schemas.geo import DiscrepancyReport, ParcelGeometry
from .schemas.ocr import PageOcr
from .schemas.validation import RuleCode, ValidationReport
from .validation.registry import run_all as run_validation

__all__ = ["process_document"]


def process_document(
    path: str | Path,
    *,
    settings: Settings | None = None,
    declared_format: RecordFormat = RecordFormat.UNKNOWN,
    geometries_by_parcel_key: dict[str, ParcelGeometry] | None = None,
    neighbour_geometries_by_parcel_key: dict[str, list[ParcelGeometry]] | None = None,
    extractor: VisionExtractorProtocol | None = None,
) -> ExtractionArtifact:
    """Run the full pipeline over one scanned document.

    :param geometries_by_parcel_key: Cadastral polygons to cross-reference against,
        keyed by :attr:`LandParcelRecord.parcel_key`. Omit entirely to skip the
        discrepancy engine -- every parcel then simply has no geometry match, which
        is reported honestly (see :data:`~adhikar.schemas.geo.NO_GEOMETRY_CONFIDENCE_CAP`)
        rather than being silently absent.
    :param extractor: Injected for testing; otherwise built by
        :func:`adhikar.llm.factory.build_extractor` from ``settings.llm_provider``.
    :raises AdhikarError: (or a subclass) on any stage failure that is not a
        recorded, non-fatal degradation.
    """
    settings = settings or get_settings()
    metadata = ProcessingMetadata(policy_name="default")

    t0 = time.monotonic()
    loaded = load_document(path, declared_format=declared_format, settings=settings)
    metadata.record_stage("load", (time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    prepared_pages = [
        prepare_page(p.image, page_index=p.page_index, dpi=p.dpi, settings=settings) for p in loaded.pages
    ]
    metadata.record_stage("preprocess", (time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    page_ocr_results: list[PageOcr] = []
    for prepared in prepared_pages:
        ensemble_result = run_ocr_ensemble(
            prepared.rgb, page_index=prepared.page_index, dpi=prepared.dpi, settings=settings
        )
        page = ensemble_result.page
        if ensemble_result.degradation is not None:
            metadata.warnings.append(str(ensemble_result.degradation))

        try:
            grids = detect_table_grids(
                prepared.binary,
                page_index=prepared.page_index,
                page_width=prepared.width,
                page_height=prepared.height,
                settings=settings,
            )
            all_tokens = [t for line in page.lines for t in line.tokens]
            populated_grids = tuple(assign_tokens_to_grid(g, all_tokens) for g in grids)
            page = page.model_copy(update={"tables": populated_grids})
        except AdhikarError as exc:
            metadata.warnings.append(f"table detection degraded on page {prepared.page_index}: {exc}")

        page_ocr_results.append(page)
        metadata.ocr_engines = list({*metadata.ocr_engines, *page.engines_used})
    metadata.record_stage("ocr_layout", (time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    vision_extractor = extractor or build_extractor(settings)
    document_hint = (
        f"Declared record format: {loaded.source.declared_record_format.value}. "
        f"File: {loaded.source.file_name}."
    )
    extraction_result = vision_extractor.extract(
        [p.rgb for p in prepared_pages],
        ocr_pages=page_ocr_results,
        document_hint=document_hint,
    )
    metadata.record_stage("llm_extraction", (time.monotonic() - t0) * 1000)
    metadata.llm_model = extraction_result.model
    metadata.llm_effort = extraction_result.effort
    metadata.token_usage = extraction_result.token_usage

    t0 = time.monotonic()
    confidences = index_field_confidences(extraction_result.extraction)
    mapping = map_extraction(
        extraction_result.extraction,
        llm_confidence_by_path=confidences,
        region_key=settings.default_bigha_region,
    )
    metadata.warnings.extend(mapping.warnings)
    # The LLM never reports pixel coordinates -- this recovers them after the fact
    # by fuzzy-matching each field's transcribed text against the OCR ensemble's
    # own line boxes, so the reviewer console can point at a field's real source
    # location instead of simulating one. See the module docstring for why a
    # low-confidence match is left unset rather than guessed.
    mapping.provenance = attach_bboxes(mapping.provenance, page_ocr_results)
    metadata.record_stage("normalize_map", (time.monotonic() - t0) * 1000)

    detected_format = _wire_format_to_enum(extraction_result.extraction.detected_record_format)

    t0 = time.monotonic()
    policy = _load_policy_safely(settings, metadata)
    metadata.policy_name = policy.name

    all_issues = []
    evaluated_codes: set[RuleCode] = set()
    skipped_codes: set[RuleCode] = set()
    for parcel in mapping.parcels:
        report = run_validation(parcel, policy)
        all_issues.extend(report.issues)
        evaluated_codes.update(report.rules_evaluated)
        skipped_codes.update(report.rules_skipped)

    validation_report = ValidationReport(
        policy_name=policy.name,
        issues=all_issues,
        rules_evaluated=sorted(evaluated_codes, key=str),
        rules_skipped=sorted(skipped_codes, key=str),
    )
    metadata.record_stage("validate", (time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    discrepancies: list[DiscrepancyReport] = []
    if geometries_by_parcel_key is not None:
        mean_ocr_confidence = (
            sum(p.mean_confidence for p in page_ocr_results) / len(page_ocr_results)
            if page_ocr_results
            else 0.0
        )
        for parcel in mapping.parcels:
            key = parcel.parcel_key
            geometry = geometries_by_parcel_key.get(key)
            neighbours = (neighbour_geometries_by_parcel_key or {}).get(key, [])
            parcel_validation_score = _integrity_score_for(parcel, all_issues)
            llm_field_confidence = _mean_llm_confidence(mapping, parcel)
            report = compute_discrepancy(
                key,
                textual_area_sq_metre=parcel.total_area.sq_metre if parcel.total_area else None,
                geometry=geometry,
                confidence_inputs=ConfidenceInputs(
                    ocr=mean_ocr_confidence,
                    llm_extraction=llm_field_confidence,
                    structural_integrity=parcel_validation_score,
                ),
                neighbour_geometries=neighbours,
                settings=settings,
            )
            discrepancies.append(report)
    metadata.record_stage("discrepancy", (time.monotonic() - t0) * 1000)

    metadata.completed_at = datetime.now(UTC)

    return ExtractionArtifact(
        document=loaded.source,
        detected_record_format=detected_format,
        parcels=mapping.parcels,
        provenance=mapping.provenance,
        pages=page_ocr_results,
        validation=validation_report,
        discrepancies=discrepancies,
        processing=metadata,
        llm_notes=extraction_result.extraction.notes,
        unreadable_regions=[r.model_dump() for r in extraction_result.extraction.unreadable_regions],
    )


def _wire_format_to_enum(value: str) -> RecordFormat:
    return {
        "jamabandi": RecordFormat.JAMABANDI,
        "satbara_7_12": RecordFormat.SATBARA,
        "khasra_girdawari": RecordFormat.KHASRA_GIRDAWARI,
        "ror_generic": RecordFormat.ROR_GENERIC,
    }.get(value, RecordFormat.UNKNOWN)


def _load_policy_safely(settings: Settings, metadata: ProcessingMetadata):  # noqa: ANN202
    from .validation.policy import DEFAULT_POLICY, load_policy

    if not settings.validation_policy_path.is_file():
        metadata.warnings.append(
            f"validation policy file not found at {settings.validation_policy_path}; using built-in defaults"
        )
        return DEFAULT_POLICY
    try:
        return load_policy(settings.validation_policy_path)
    except AdhikarError as exc:
        metadata.warnings.append(f"failed to load validation policy, using built-in defaults: {exc}")
        return DEFAULT_POLICY


def _integrity_score_for(parcel, issues) -> float:  # noqa: ANN001
    """A parcel-scoped integrity score, for feeding the discrepancy engine.

    ``ValidationReport.integrity_score`` operates on a whole report; this filters to
    the one parcel's issues and reuses the same scoring so the two numbers agree.
    """
    parcel_key = parcel.parcel_key
    scoped = [i for i in issues if i.parcel_key == parcel_key]
    return ValidationReport(issues=scoped).integrity_score


def _mean_llm_confidence(mapping, parcel) -> float:  # noqa: ANN001
    """Mean provenance confidence for fields belonging to one parcel."""
    prefix = None
    # parcel index is not tracked on the domain object; match by identity via the
    # mapping's parcel list order instead, which is stable within one mapping call.
    try:
        index = mapping.parcels.index(parcel)
    except ValueError:
        return 0.8
    prefix = f"$.parcels[{index}]"
    scoped = [p.confidence for path, p in mapping.provenance.items() if path.startswith(prefix)]
    return sum(scoped) / len(scoped) if scoped else 0.8
