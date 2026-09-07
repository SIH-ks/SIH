"""The discrepancy engine: textual area vs. cadastral polygon, scored.

Geodesic area, never planar-on-degrees
---------------------------------------
Polygon area is computed with `pyproj`'s geodesic (`Geod.geometry_area_perimeter`),
which integrates area on the WGS84 ellipsoid directly from lon/lat. Treating
longitude/latitude degrees as if they were a flat Cartesian plane (a common shortcut)
is wrong by a latitude-dependent factor -- around 6% at 20 degrees N, which alone
exceeds every tolerance this engine uses and would manufacture false mismatches on
every single parcel. There is no planar fallback path in this module for that reason.

Topology
--------
Overlap and gap detection between neighbouring parcels uses Shapely's planar
predicates on a locally projected copy of the geometry (equal-area azimuthal,
centred on the parcel) -- fine at the scale of a village map, and far simpler than
doing exact topology on the ellipsoid, which planar overlap/gap detection does not
need to be.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..config import Settings, get_settings
from ..exceptions import GeometryError
from ..schemas.geo import (
    AreaComparison,
    ConfidenceBreakdown,
    ConfidenceWeights,
    DiscrepancyReport,
    ParcelGeometry,
    TopologyFinding,
    TopologyKind,
)

__all__ = ["ConfidenceInputs", "build_parcel_geometry", "compute_discrepancy", "detect_topology_issues"]


def _geod():  # noqa: ANN202 - pyproj.Geod has no lightweight type stub worth importing for
    try:
        from pyproj import Geod
    except ImportError as exc:
        raise GeometryError(
            "pyproj is required for geodesic area computation; pip install pyproj"
        ) from exc
    return Geod(ellps="WGS84")


def _shapely_geometry(geometry: dict):  # noqa: ANN001, ANN202
    try:
        from shapely.geometry import shape
    except ImportError as exc:
        raise GeometryError("shapely is required for geometry operations; pip install shapely") from exc
    return shape(geometry)


def build_parcel_geometry(
    parcel_key: str,
    geojson_geometry: dict,
    *,
    source,  # noqa: ANN001 - GeometrySource, avoids a redundant import for a keyword-only param
    survey_date=None,  # noqa: ANN001
) -> ParcelGeometry:
    """Construct a :class:`ParcelGeometry`, computing its geodesic area and validity.

    Validity is checked with Shapely (``is_valid``/``explain_validity``) rather than
    assumed -- a self-intersecting or unclosed ring from a poorly digitised cadastral
    layer must not silently produce a plausible-looking area.
    """
    shp = _shapely_geometry(geojson_geometry)
    is_valid = shp.is_valid
    reason = None
    if not is_valid:
        from shapely.validation import explain_validity

        reason = explain_validity(shp)

    area_sq_m = None
    perimeter = None
    if is_valid and not shp.is_empty:
        geod = _geod()
        area_signed, perim = geod.geometry_area_perimeter(shp)
        area_sq_m = Decimal(str(abs(area_signed)))
        perimeter = Decimal(str(perim))

    vertex_count = (
        len(shp.exterior.coords) if shp.geom_type == "Polygon" else sum(len(p.exterior.coords) for p in shp.geoms)
    ) if not shp.is_empty else 0

    return ParcelGeometry(
        parcel_key=parcel_key,
        geometry=geojson_geometry,
        source=source,
        survey_date=survey_date,
        geodesic_area_sq_metre=area_sq_m,
        perimeter_metre=perimeter,
        vertex_count=vertex_count,
        is_valid=is_valid,
        validity_reason=reason,
    )


@dataclass(slots=True)
class ConfidenceInputs:
    ocr: float
    llm_extraction: float
    structural_integrity: float


def compute_discrepancy(
    parcel_key: str,
    *,
    textual_area_sq_metre: Decimal | None,
    geometry: ParcelGeometry | None,
    confidence_inputs: ConfidenceInputs,
    neighbour_geometries: list[ParcelGeometry] | None = None,
    settings: Settings | None = None,
    confidence_weights: ConfidenceWeights | None = None,
) -> DiscrepancyReport:
    """Produce the complete discrepancy report for one parcel.

    :param textual_area_sq_metre: The extracted (and validated) total area.
    :param geometry: The matched cadastral polygon, or ``None`` if no match was found
        -- a real and common outcome (unsurveyed parcels, digitisation backlog), never
        treated as an error.
    :param confidence_inputs: The three non-geometric confidence components; the
        geometric component is computed here from the area comparison.
    :param neighbour_geometries: Adjoining parcels' geometries, for overlap/gap
        detection. Optional -- omitting it just skips :attr:`DiscrepancyReport.topology_findings`.
    """
    settings = settings or get_settings()
    notes: list[str] = []

    if geometry is None:
        area_comparison = AreaComparison(
            textual_area_sq_metre=textual_area_sq_metre,
            geometric_area_sq_metre=None,
            tolerance_relative_applied=Decimal(str(settings.geometry_survey_tolerance)),
            severe_threshold=Decimal(str(settings.geometry_severe_threshold)),
        )
        notes.append("No cadastral geometry could be matched to this parcel.")
        confidence = ConfidenceBreakdown(
            ocr=confidence_inputs.ocr,
            llm_extraction=confidence_inputs.llm_extraction,
            structural_integrity=confidence_inputs.structural_integrity,
            geometric_agreement=0.0,
            weights=confidence_weights or ConfidenceWeights(),
            geometry_available=False,
        )
        return DiscrepancyReport(
            parcel_key=parcel_key,
            geometry_matched=False,
            confidence=confidence,
            area_comparison=area_comparison,
            notes=notes,
        )

    if not geometry.is_valid:
        notes.append(f"Matched geometry is invalid: {geometry.validity_reason}")

    tolerance = Decimal(str(settings.geometry_survey_tolerance)) * geometry.tolerance_multiplier
    area_comparison = AreaComparison(
        textual_area_sq_metre=textual_area_sq_metre,
        geometric_area_sq_metre=geometry.geodesic_area_sq_metre,
        tolerance_relative_applied=tolerance,
        severe_threshold=Decimal(str(settings.geometry_severe_threshold)),
    )

    topology_findings: list[TopologyFinding] = []
    if not geometry.is_valid:
        topology_findings.append(
            TopologyFinding(
                kind=TopologyKind.SELF_INTERSECTION,
                affected_area_sq_metre=Decimal(0),
                affected_fraction_of_parcel=0.0,
                detail=geometry.validity_reason or "geometry failed validity check",
            )
        )
    elif neighbour_geometries:
        topology_findings.extend(detect_topology_issues(geometry, neighbour_geometries))

    confidence = ConfidenceBreakdown(
        ocr=confidence_inputs.ocr,
        llm_extraction=confidence_inputs.llm_extraction,
        structural_integrity=confidence_inputs.structural_integrity,
        geometric_agreement=area_comparison.geometric_agreement,
        weights=confidence_weights or ConfidenceWeights(),
        geometry_available=True,
    )

    return DiscrepancyReport(
        parcel_key=parcel_key,
        geometry_matched=True,
        geometry_source=geometry.source,
        area_comparison=area_comparison,
        topology_findings=topology_findings,
        confidence=confidence,
        notes=notes,
    )


def detect_topology_issues(
    geometry: ParcelGeometry, neighbours: list[ParcelGeometry]
) -> list[TopologyFinding]:
    """Compare one parcel's polygon against its neighbours for overlap or gaps.

    Uses a local equal-area azimuthal projection centred on the parcel's centroid so
    the area figures involved are metric, without needing a full projected-CRS
    pipeline for what is, at village scale, a small planar comparison.
    """
    try:
        import pyproj
        from shapely.ops import transform
    except ImportError as exc:
        raise GeometryError("shapely and pyproj are required for topology checks") from exc

    subject = _shapely_geometry(geometry.geometry)
    if subject.is_empty:
        return []

    centroid = subject.centroid
    local_crs = pyproj.CRS.from_proj4(
        f"+proj=aeqd +lat_0={centroid.y} +lon_0={centroid.x} +datum=WGS84 +units=m"
    )
    to_local = pyproj.Transformer.from_crs("EPSG:4326", local_crs, always_xy=True).transform
    subject_local = transform(to_local, subject)
    subject_area = subject_local.area
    if subject_area <= 0:
        return []

    findings: list[TopologyFinding] = []
    for neighbour in neighbours:
        if neighbour.parcel_key == geometry.parcel_key:
            continue
        neighbour_shape = _shapely_geometry(neighbour.geometry)
        if neighbour_shape.is_empty or not neighbour_shape.is_valid:
            continue
        neighbour_local = transform(to_local, neighbour_shape)

        if subject_local.intersects(neighbour_local):
            intersection = subject_local.intersection(neighbour_local)
            if intersection.area > 0:
                findings.append(
                    TopologyFinding(
                        kind=TopologyKind.OVERLAP,
                        counterpart_parcel_key=neighbour.parcel_key,
                        affected_area_sq_metre=Decimal(str(round(intersection.area, 4))),
                        affected_fraction_of_parcel=round(intersection.area / subject_area, 6),
                        detail=f"Overlaps parcel {neighbour.parcel_key} by {intersection.area:.2f} sq m.",
                    )
                )
                continue

        # No overlap: check for a sliver gap along a shared boundary. A small buffer
        # closes rounding gaps from independent digitisation of a shared line without
        # treating genuinely separated parcels as adjoining.
        gap_probe = subject_local.buffer(0.5).intersection(neighbour_local.buffer(0.5))
        if not gap_probe.is_empty and gap_probe.area > 0:
            gap = subject_local.buffer(0.5).difference(subject_local).intersection(neighbour_local.buffer(0.5))
            if not gap.is_empty and 0 < gap.area:
                findings.append(
                    TopologyFinding(
                        kind=TopologyKind.SLIVER_GAP,
                        counterpart_parcel_key=neighbour.parcel_key,
                        affected_area_sq_metre=Decimal(str(round(gap.area, 4))),
                        affected_fraction_of_parcel=round(gap.area / subject_area, 6),
                        detail=f"Unclaimed gap against parcel {neighbour.parcel_key}.",
                    )
                )

    return findings
