"""Discrepancy-engine contract: textual area vs. cadastral polygon.

The question this answers is the one that actually matters to a Tehsildar: *does the
area written on the paper match the shape on the map?* Everything here is built to
make that answer auditable -- each score decomposes into named components with the
numbers that produced them, so a finding can be defended in a hearing rather than
attributed to a model.

Scoring model
-------------
**Mismatch score (0-100, lower is better)** is a linear map of the relative area
difference onto the band the policy calls "severe":

    mismatch = min(100, 100 * relative_delta / severe_threshold)

With the default 10% severe threshold, a score of 50 means the record is 5% off its
polygon. It is a *ratio restated on a fixed scale*, not a learned quantity -- which is
precisely why it can be explained to a non-technical adjudicator.

**Confidence score (0-1, higher is better)** is a weighted mean of four independently
measured components (OCR legibility, LLM extraction certainty, internal arithmetic
integrity, geometric agreement), followed by two hard caps: missing geometry caps
confidence at :data:`NO_GEOMETRY_CONFIDENCE_CAP`, and any single component below
:data:`COMPONENT_FLOOR` caps the composite at that component's value. The caps exist
so a strong average can never launder one badly broken input.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

__all__ = [
    "COMPONENT_FLOOR",
    "NO_GEOMETRY_CONFIDENCE_CAP",
    "AreaComparison",
    "ConfidenceBreakdown",
    "ConfidenceWeights",
    "DiscrepancyReport",
    "GeometrySource",
    "MismatchBand",
    "ParcelGeometry",
    "RecommendedAction",
    "TopologyFinding",
    "TopologyKind",
]

NO_GEOMETRY_CONFIDENCE_CAP: float = 0.55
"""Ceiling on composite confidence when no polygon could be matched.

A record whose text we read perfectly but whose shape we never saw is, by
construction, only half-verified. Capping below the auto-approve threshold means such
records always reach a human.
"""

COMPONENT_FLOOR: float = 0.35
"""Below this, a single component caps the whole composite at its own value."""


class GeometrySource(StrEnum):
    """Where a parcel polygon came from. Provenance drives the tolerance applied."""

    CADASTRAL_SHAPEFILE = "cadastral_shapefile"
    """Digitised village map (Bhu-Naksha / DILRMP cadastral layer)."""

    BHU_NAKSHA = "bhu_naksha"
    DRONE_SURVEY = "drone_survey"
    """SVAMITVA drone orthophoto survey -- the highest-accuracy source available."""

    DGPS_SURVEY = "dgps_survey"
    ETS_SURVEY = "ets_survey"
    """Electronic Total Station ground survey."""

    MOCK = "mock"
    """Synthetic fixture. Never valid in production; the engine flags it explicitly."""

    UNKNOWN = "unknown"


_SOURCE_TOLERANCE_MULTIPLIER: dict[GeometrySource, Decimal] = {
    # Digitised legacy village maps carry real georeferencing error; drone and DGPS
    # survey products do not, so the same absolute delta means different things.
    GeometrySource.DRONE_SURVEY: Decimal("0.6"),
    GeometrySource.DGPS_SURVEY: Decimal("0.6"),
    GeometrySource.ETS_SURVEY: Decimal("0.8"),
    GeometrySource.CADASTRAL_SHAPEFILE: Decimal("1.0"),
    GeometrySource.BHU_NAKSHA: Decimal("1.0"),
    GeometrySource.MOCK: Decimal("1.0"),
    GeometrySource.UNKNOWN: Decimal("1.5"),
}


class MismatchBand(StrEnum):
    """Interpretation bands for the area difference."""

    EXACT = "exact"
    """Within 0.1% -- indistinguishable from a rounding difference."""

    WITHIN_SURVEY_TOLERANCE = "within_survey_tolerance"
    """Explainable by normal cadastral survey error."""

    MINOR = "minor"
    """Beyond survey tolerance but small; typically a digit or unit transcription slip."""

    MATERIAL = "material"
    """Large enough to change the parcel's value or its revenue assessment."""

    SEVERE = "severe"
    """The text and the map describe different pieces of land."""

    UNDETERMINED = "undetermined"
    """No geometry, or no textual area, to compare."""


class RecommendedAction(StrEnum):
    """What the system asks a human to do. The only output that drives workflow."""

    AUTO_APPROVE = "auto_approve"
    REVIEW_QUEUE = "review_queue"
    """Desk review by a revenue clerk against the scan."""

    FIELD_VERIFICATION = "field_verification"
    """Send a surveyor. Reserved for material geometric disagreement."""

    REJECT_RE_SCAN = "reject_re_scan"
    """Extraction quality is too poor to adjudicate; re-scan the document."""


class TopologyKind(StrEnum):
    OVERLAP = "overlap"
    """Two parcels claim the same ground -- encroachment or double-allotment."""

    SLIVER_GAP = "sliver_gap"
    """Unclaimed gap between parcels that should share a boundary."""

    SELF_INTERSECTION = "self_intersection"
    NOT_CLOSED = "not_closed"
    DEGENERATE = "degenerate"
    """Zero or near-zero area ring."""


class ParcelGeometry(BaseModel):
    """A cadastral polygon plus the metadata needed to judge how much to trust it."""

    model_config = ConfigDict(extra="forbid")

    parcel_key: str
    geometry: dict[str, Any]
    """RFC 7946 GeoJSON geometry -- ``Polygon`` or ``MultiPolygon``."""

    crs: str = "EPSG:4326"
    source: GeometrySource = GeometrySource.UNKNOWN
    survey_date: date | None = None

    geodesic_area_sq_metre: Decimal | None = Field(default=None, ge=0)
    """Ellipsoidal area on the WGS84 spheroid.

    Computed with a geodesic method, never by treating degrees as a planar unit --
    at 20 degrees N a naive planar area is wrong by roughly 6%, which is larger than
    every tolerance in this system and would manufacture mismatches everywhere.
    """

    perimeter_metre: Decimal | None = Field(default=None, ge=0)
    vertex_count: int = Field(default=0, ge=0)
    is_valid: bool = True
    validity_reason: str | None = None

    @model_validator(mode="after")
    def _geometry_shape(self) -> Self:
        geom_type = self.geometry.get("type")
        if geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"parcel geometry must be Polygon or MultiPolygon, got {geom_type!r}; "
                "point and line geometries cannot carry an area"
            )
        return self

    @property
    def tolerance_multiplier(self) -> Decimal:
        """How much to widen the area tolerance, given the source's accuracy."""
        return _SOURCE_TOLERANCE_MULTIPLIER.get(self.source, Decimal("1.0"))


class AreaComparison(BaseModel):
    """The textual-vs-geometric area comparison for one parcel."""

    model_config = ConfigDict(extra="forbid")

    textual_area_sq_metre: Decimal | None = Field(default=None, ge=0)
    """From the record, as extracted."""

    geometric_area_sq_metre: Decimal | None = Field(default=None, ge=0)
    """From the polygon, geodesically."""

    tolerance_relative_applied: Decimal = Decimal("0.005")
    """Effective relative tolerance after the source multiplier."""

    severe_threshold: Decimal = Decimal("0.10")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def absolute_delta_sq_metre(self) -> Decimal | None:
        if self.textual_area_sq_metre is None or self.geometric_area_sq_metre is None:
            return None
        return self.textual_area_sq_metre - self.geometric_area_sq_metre

    @computed_field  # type: ignore[prop-decorator]
    @property
    def relative_delta(self) -> Decimal | None:
        """Absolute difference over the geometric area.

        The polygon is the denominator because it is the measured quantity; the
        written area is the claim being tested against it.
        """
        delta = self.absolute_delta_sq_metre
        if delta is None:
            return None
        if not self.geometric_area_sq_metre:
            return None if self.textual_area_sq_metre in (None, 0) else Decimal(1)
        return abs(delta) / self.geometric_area_sq_metre

    @computed_field  # type: ignore[prop-decorator]
    @property
    def band(self) -> MismatchBand:
        rel = self.relative_delta
        if rel is None:
            return MismatchBand.UNDETERMINED
        if rel <= Decimal("0.001"):
            return MismatchBand.EXACT
        if rel <= self.tolerance_relative_applied:
            return MismatchBand.WITHIN_SURVEY_TOLERANCE
        if rel <= self.severe_threshold / 5:
            return MismatchBand.MINOR
        if rel <= self.severe_threshold:
            return MismatchBand.MATERIAL
        return MismatchBand.SEVERE

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mismatch_score(self) -> float:
        """0-100, lower is better. See the module docstring for the mapping."""
        rel = self.relative_delta
        if rel is None:
            return 0.0
        if self.severe_threshold <= 0:  # pragma: no cover - guarded by policy schema
            return 100.0
        return round(min(100.0, float(rel / self.severe_threshold) * 100.0), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def within_tolerance(self) -> bool:
        rel = self.relative_delta
        return rel is not None and rel <= self.tolerance_relative_applied

    @property
    def geometric_agreement(self) -> float:
        """0-1 confidence component derived from the area agreement."""
        rel = self.relative_delta
        if rel is None:
            return 0.0
        return round(max(0.0, 1.0 - float(rel / self.severe_threshold)), 4)


class TopologyFinding(BaseModel):
    """A geometric defect between this parcel and its neighbours, or within itself."""

    model_config = ConfigDict(extra="forbid")

    kind: TopologyKind
    counterpart_parcel_key: str | None = None
    """The other parcel, for OVERLAP and SLIVER_GAP."""

    affected_area_sq_metre: Decimal = Field(default=Decimal(0), ge=0)
    affected_fraction_of_parcel: float = Field(default=0.0, ge=0.0)
    detail: str = ""

    @property
    def is_material(self) -> bool:
        """Above 1 sq m and 0.1% of the parcel.

        Both conditions are needed: digitisation noise produces sub-square-metre
        overlaps on almost every shared boundary, and reporting those would bury the
        genuine encroachments.
        """
        return self.affected_area_sq_metre > 1 and self.affected_fraction_of_parcel > 0.001


class ConfidenceWeights(BaseModel):
    """Weights for the composite confidence. Must sum to 1."""

    model_config = ConfigDict(extra="forbid")

    ocr: float = Field(default=0.25, ge=0.0, le=1.0)
    llm_extraction: float = Field(default=0.25, ge=0.0, le=1.0)
    structural_integrity: float = Field(default=0.25, ge=0.0, le=1.0)
    geometric_agreement: float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _sums_to_one(self) -> Self:
        total = self.ocr + self.llm_extraction + self.structural_integrity + self.geometric_agreement
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"confidence weights must sum to 1.0, got {total:.6f}")
        return self


class ConfidenceBreakdown(BaseModel):
    """The four measured components and the composite they produce.

    Kept decomposed on purpose: "confidence 0.62" is not actionable, but "OCR 0.91,
    extraction 0.88, integrity 0.95, geometry 0.15" tells the reviewer to go look at
    the map, not the scan.
    """

    model_config = ConfigDict(extra="forbid")

    ocr: float = Field(ge=0.0, le=1.0)
    """Character-weighted mean OCR confidence over the pages this parcel came from."""

    llm_extraction: float = Field(ge=0.0, le=1.0)
    """The Vision LLM's own per-field certainty, averaged over populated fields."""

    structural_integrity: float = Field(ge=0.0, le=1.0)
    """The arithmetic validation integrity score."""

    geometric_agreement: float = Field(ge=0.0, le=1.0)
    """From :attr:`AreaComparison.geometric_agreement`."""

    weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)
    geometry_available: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def composite(self) -> float:
        """Weighted mean, then the two hard caps described in the module docstring."""
        w = self.weights
        score = (
            self.ocr * w.ocr
            + self.llm_extraction * w.llm_extraction
            + self.structural_integrity * w.structural_integrity
            + self.geometric_agreement * w.geometric_agreement
        )
        components = (self.ocr, self.llm_extraction, self.structural_integrity)
        if self.geometry_available:
            components += (self.geometric_agreement,)
        weakest = min(components)
        if weakest < COMPONENT_FLOOR:
            score = min(score, weakest)
        if not self.geometry_available:
            score = min(score, NO_GEOMETRY_CONFIDENCE_CAP)
        return round(max(0.0, min(1.0, score)), 4)

    @property
    def weakest_component(self) -> str:
        candidates = {
            "ocr": self.ocr,
            "llm_extraction": self.llm_extraction,
            "structural_integrity": self.structural_integrity,
        }
        if self.geometry_available:
            candidates["geometric_agreement"] = self.geometric_agreement
        return min(candidates.items(), key=lambda kv: kv[1])[0]


class DiscrepancyReport(BaseModel):
    """The discrepancy engine's complete output for one parcel."""

    model_config = ConfigDict(extra="forbid")

    parcel_key: str
    geometry_matched: bool = False
    geometry_source: GeometrySource = GeometrySource.UNKNOWN
    area_comparison: AreaComparison = Field(default_factory=AreaComparison)
    topology_findings: list[TopologyFinding] = Field(default_factory=list)
    confidence: ConfidenceBreakdown
    notes: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mismatch_score(self) -> float:
        """Area mismatch, escalated by any material topology defect.

        A parcel whose written area matches its polygon exactly can still be in
        serious trouble if that polygon overlaps its neighbour, so the topology
        penalty is added rather than averaged in.
        """
        base = self.area_comparison.mismatch_score
        topology_penalty = sum(
            min(40.0, f.affected_fraction_of_parcel * 100.0)
            for f in self.topology_findings
            if f.is_material
        )
        return round(min(100.0, base + topology_penalty), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def confidence_score(self) -> float:
        return self.confidence.composite

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recommended_action(self) -> RecommendedAction:
        """Route the record. Thresholds are deliberately conservative.

        Auto-approval requires *both* high confidence and a near-exact area match:
        this system proposes, and a revenue officer disposes.
        """
        if self.confidence.ocr < 0.45 or self.confidence.llm_extraction < 0.45:
            return RecommendedAction.REJECT_RE_SCAN
        if any(f.is_material for f in self.topology_findings):
            return RecommendedAction.FIELD_VERIFICATION
        band = self.area_comparison.band
        if band in (MismatchBand.MATERIAL, MismatchBand.SEVERE):
            return RecommendedAction.FIELD_VERIFICATION
        if self.confidence_score >= 0.85 and band in (
            MismatchBand.EXACT,
            MismatchBand.WITHIN_SURVEY_TOLERANCE,
        ):
            return RecommendedAction.AUTO_APPROVE
        return RecommendedAction.REVIEW_QUEUE

    @property
    def headline(self) -> str:
        """One-line summary for the console list view."""
        return (
            f"{self.parcel_key}: mismatch {self.mismatch_score:.1f}/100 "
            f"({self.area_comparison.band.value}), confidence {self.confidence_score:.2f} "
            f"-> {self.recommended_action.value}"
        )
