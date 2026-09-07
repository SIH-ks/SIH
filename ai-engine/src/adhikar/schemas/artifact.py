"""The top-level extraction artifact: everything one document produced.

This is the object that is persisted, shipped to the frontend, and diffed when a
reviewer edits a value. It is designed to be **self-contained and re-auditable** --
given only the artifact, you can answer "where did this number come from, how sure
were we, and what did the checks say" without re-running anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from .enums import ExtractorKind, RecordFormat
from .geo import DiscrepancyReport
from .land_record import LandParcelRecord
from .ocr import BoundingBox, PageOcr
from .validation import ValidationReport

__all__ = [
    "SCHEMA_VERSION",
    "ExtractionArtifact",
    "FieldProvenance",
    "ProcessingMetadata",
    "SourceDocument",
    "TokenUsage",
]

SCHEMA_VERSION = "1.0.0"
"""Bumped on any breaking change to the artifact shape. Persisted with every record so
stored artifacts remain interpretable after the schema moves on.
"""


class SourceDocument(BaseModel):
    """Identity and integrity of the scan that was processed."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    file_name: str
    media_type: str = "application/pdf"

    sha256: str = Field(min_length=64, max_length=64)
    """Content hash. The join key for deduplication, and the tamper check: a stored
    artifact whose hash no longer matches its source is not evidence of anything."""

    byte_size: int = Field(ge=0)
    page_count: int = Field(ge=0)
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    declared_record_format: RecordFormat = RecordFormat.UNKNOWN
    """What the uploader said it was, before detection ran."""

    declared_state: str | None = None
    source_system: str | None = None
    """Originating portal, e.g. 'Bhulekh-UP', 'MahaBhumi', 'Jamabandi-HR'."""


class FieldProvenance(BaseModel):
    """Where one extracted value came from.

    Keyed by JSON path in :attr:`ExtractionArtifact.provenance`. Keeping this beside
    the domain model rather than inside it means the LLM's output schema stays small
    while every value stays traceable to a pixel region and an engine.
    """

    model_config = ConfigDict(extra="forbid")

    extractor: ExtractorKind
    confidence: float = Field(ge=0.0, le=1.0)
    raw_text: str | None = None
    """The source text before normalisation. This is what a reviewer compares against."""

    bbox: BoundingBox | None = None
    """Where on the page it was read, for click-to-source in the console."""

    alternatives: list[str] = Field(default_factory=list)
    """Runner-up readings, when the engines disagreed. Populated by the OCR ensemble."""

    reason: str | None = None
    """Why confidence is below 1.0."""

    corrected_by: str | None = None
    """Reviewer identity, when :attr:`extractor` is ``HUMAN_REVIEW``."""

    corrected_at: datetime | None = None


class TokenUsage(BaseModel):
    """LLM token accounting, for cost attribution per document."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cache_hit_ratio(self) -> float:
        """Share of input tokens served from cache.

        Watched in production: the extraction prompt is a large fixed prefix, so a
        ratio that collapses toward zero means something volatile leaked into it.
        """
        total = self.input_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens
        return round(self.cache_read_input_tokens / total, 4) if total else 0.0

    def estimated_cost_usd(self, *, input_per_mtok: float, output_per_mtok: float) -> float:
        """Cost estimate at the given rates. Cached reads bill at ~10% of input."""
        return round(
            (self.input_tokens / 1e6) * input_per_mtok
            + (self.cache_creation_input_tokens / 1e6) * input_per_mtok * 1.25
            + (self.cache_read_input_tokens / 1e6) * input_per_mtok * 0.10
            + (self.output_tokens / 1e6) * output_per_mtok,
            6,
        )

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
        )


class ProcessingMetadata(BaseModel):
    """How this artifact was produced. Reproducibility record."""

    model_config = ConfigDict(extra="forbid")

    engine_version: str = SCHEMA_VERSION
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    stage_durations_ms: dict[str, float] = Field(default_factory=dict)
    """Per-stage wall time: ``load``, ``preprocess``, ``ocr``, ``layout``, ``llm``,
    ``normalize``, ``validate``, ``discrepancy``."""

    ocr_engines: list[ExtractorKind] = Field(default_factory=list)
    llm_model: str | None = None
    llm_effort: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    policy_name: str = "default"

    warnings: list[str] = Field(default_factory=list)
    """Non-fatal degradations, e.g. 'Tesseract unavailable; ran EasyOCR only'."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_duration_ms(self) -> float:
        return round(sum(self.stage_durations_ms.values()), 2)

    def record_stage(self, name: str, duration_ms: float) -> None:
        self.stage_durations_ms[name] = round(duration_ms, 2)


class ExtractionArtifact(BaseModel):
    """One processed document, end to end."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    document: SourceDocument
    detected_record_format: RecordFormat = RecordFormat.UNKNOWN

    parcels: list[LandParcelRecord] = Field(default_factory=list)

    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    """JSON path -> provenance. Paths address :attr:`parcels`, e.g.
    ``$.parcels[0].sub_divisions[1].area``."""

    pages: list[PageOcr] = Field(default_factory=list)
    validation: ValidationReport | None = None
    discrepancies: list[DiscrepancyReport] = Field(default_factory=list)
    processing: ProcessingMetadata = Field(default_factory=ProcessingMetadata)

    llm_notes: str | None = None
    unreadable_regions: list[dict[str, Any]] = Field(default_factory=list)

    # -- aggregate views -------------------------------------------------------------

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mean_ocr_confidence(self) -> float:
        if not self.pages:
            return 0.0
        return round(sum(p.mean_confidence for p in self.pages) / len(self.pages), 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mean_field_confidence(self) -> float:
        """Mean confidence across every provenance entry."""
        if not self.provenance:
            return 0.0
        return round(sum(p.confidence for p in self.provenance.values()) / len(self.provenance), 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_area_sq_metre(self) -> Decimal:
        return sum(
            (p.total_area.sq_metre for p in self.parcels if p.total_area is not None),
            Decimal(0),
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def requires_human_review(self) -> bool:
        """The single boolean the ingestion workflow branches on."""
        if self.validation is not None and self.validation.is_blocking:
            return True
        return any(d.recommended_action.value != "auto_approve" for d in self.discrepancies)

    def provenance_for(self, json_path: str) -> FieldProvenance | None:
        return self.provenance.get(json_path)

    def low_confidence_paths(self, threshold: float = 0.60) -> list[str]:
        """Paths a reviewer should check first."""
        return sorted(p for p, prov in self.provenance.items() if prov.confidence < threshold)

    def discrepancy_for(self, parcel_key: str) -> DiscrepancyReport | None:
        return next((d for d in self.discrepancies if d.parcel_key == parcel_key), None)
