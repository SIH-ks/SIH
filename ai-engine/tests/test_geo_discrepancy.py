"""The geospatial discrepancy engine: geodesic area, mismatch scoring, topology."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from adhikar.geo.discrepancy import ConfidenceInputs, build_parcel_geometry, compute_discrepancy, detect_topology_issues
from adhikar.schemas.geo import GeometrySource, MismatchBand, RecommendedAction

shapely = pytest.importorskip("shapely")
pyproj = pytest.importorskip("pyproj")


def _square_polygon(lat: float, lon: float, half_side_m: float, *, offset_m: float = 0.0) -> dict:
    dlat = half_side_m / 111_320
    dlon = half_side_m / (111_320 * math.cos(math.radians(lat)))
    doff = offset_m / (111_320 * math.cos(math.radians(lat)))
    lon = lon + doff
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - dlon, lat - dlat],
                [lon + dlon, lat - dlat],
                [lon + dlon, lat + dlat],
                [lon - dlon, lat + dlat],
                [lon - dlon, lat - dlat],
            ]
        ],
    }


@pytest.fixture
def good_confidence() -> ConfidenceInputs:
    return ConfidenceInputs(ocr=0.9, llm_extraction=0.9, structural_integrity=0.95)


def test_geodesic_area_is_close_to_planar_estimate_at_low_latitude() -> None:
    # _square_polygon(lat, lon, half_side_m) yields a square of side 2*half_side_m,
    # so half_side_m=40 is an 80m x 80m square: ~6400 sq m. This confirms the
    # geodesic path returns a value in the right ballpark (not a units bug), with a
    # wide band since geodesic and planar estimates genuinely differ by a small amount.
    poly = _square_polygon(18.5, 73.9, 40)
    geom = build_parcel_geometry("P1", poly, source=GeometrySource.CADASTRAL_SHAPEFILE)
    assert geom.is_valid
    assert geom.geodesic_area_sq_metre is not None
    assert 6_200 < float(geom.geodesic_area_sq_metre) < 6_600


def test_exact_match_auto_approves(good_confidence: ConfidenceInputs) -> None:
    poly = _square_polygon(18.5, 73.9, 40)
    geom = build_parcel_geometry("P1", poly, source=GeometrySource.CADASTRAL_SHAPEFILE)
    report = compute_discrepancy(
        "P1",
        textual_area_sq_metre=geom.geodesic_area_sq_metre,
        geometry=geom,
        confidence_inputs=good_confidence,
    )
    assert report.area_comparison.band is MismatchBand.EXACT
    assert report.recommended_action is RecommendedAction.AUTO_APPROVE


def test_severe_mismatch_routes_to_field_verification(good_confidence: ConfidenceInputs) -> None:
    poly = _square_polygon(18.5, 73.9, 40)
    geom = build_parcel_geometry("P1", poly, source=GeometrySource.CADASTRAL_SHAPEFILE)
    textual = geom.geodesic_area_sq_metre * Decimal("1.15")
    report = compute_discrepancy(
        "P1", textual_area_sq_metre=textual, geometry=geom, confidence_inputs=good_confidence
    )
    assert report.area_comparison.band is MismatchBand.SEVERE
    assert report.recommended_action is RecommendedAction.FIELD_VERIFICATION
    assert report.mismatch_score == 100.0


def test_missing_geometry_caps_confidence(good_confidence: ConfidenceInputs) -> None:
    report = compute_discrepancy(
        "P2", textual_area_sq_metre=Decimal(8000), geometry=None, confidence_inputs=good_confidence
    )
    assert report.confidence_score <= 0.55
    assert report.area_comparison.band is MismatchBand.UNDETERMINED


def test_weak_component_floors_the_composite() -> None:
    poly = _square_polygon(18.5, 73.9, 40)
    geom = build_parcel_geometry("P1", poly, source=GeometrySource.CADASTRAL_SHAPEFILE)
    weak = ConfidenceInputs(ocr=0.2, llm_extraction=0.9, structural_integrity=0.95)
    report = compute_discrepancy(
        "P1", textual_area_sq_metre=geom.geodesic_area_sq_metre, geometry=geom, confidence_inputs=weak
    )
    assert report.confidence_score == pytest.approx(0.2, abs=1e-9)
    assert report.confidence.weakest_component == "ocr"


def test_overlap_detected_between_neighbours() -> None:
    poly_a = _square_polygon(18.5, 73.9, 40)
    poly_b = _square_polygon(18.5, 73.9, 40, offset_m=40)  # shifted by half its width -> overlaps
    geom_a = build_parcel_geometry("A", poly_a, source=GeometrySource.CADASTRAL_SHAPEFILE)
    geom_b = build_parcel_geometry("B", poly_b, source=GeometrySource.CADASTRAL_SHAPEFILE)

    findings = detect_topology_issues(geom_a, [geom_b])
    assert any(f.kind.value == "overlap" and f.counterpart_parcel_key == "B" for f in findings)
    overlap = next(f for f in findings if f.kind.value == "overlap")
    assert overlap.is_material


def test_no_overlap_for_distant_parcels() -> None:
    poly_a = _square_polygon(18.5, 73.9, 40)
    poly_b = _square_polygon(18.5, 73.9, 40, offset_m=1000)  # far away
    geom_a = build_parcel_geometry("A", poly_a, source=GeometrySource.CADASTRAL_SHAPEFILE)
    geom_b = build_parcel_geometry("B", poly_b, source=GeometrySource.CADASTRAL_SHAPEFILE)

    findings = detect_topology_issues(geom_a, [geom_b])
    assert not any(f.kind.value == "overlap" for f in findings)


def test_source_accuracy_widens_tolerance(good_confidence: ConfidenceInputs) -> None:
    """A cadastral-shapefile-sourced polygon tolerates more area drift than a
    drone survey polygon of the same nominal mismatch, per the source multiplier."""
    poly = _square_polygon(18.5, 73.9, 40)
    geom_cadastral = build_parcel_geometry("P1", poly, source=GeometrySource.CADASTRAL_SHAPEFILE)
    geom_drone = build_parcel_geometry("P1", poly, source=GeometrySource.DRONE_SURVEY)

    # A drift right at the cadastral tolerance boundary
    textual = geom_cadastral.geodesic_area_sq_metre * Decimal("1.006")

    report_cadastral = compute_discrepancy(
        "P1", textual_area_sq_metre=textual, geometry=geom_cadastral, confidence_inputs=good_confidence
    )
    report_drone = compute_discrepancy(
        "P1", textual_area_sq_metre=textual, geometry=geom_drone, confidence_inputs=good_confidence
    )
    assert report_cadastral.area_comparison.tolerance_relative_applied > report_drone.area_comparison.tolerance_relative_applied
