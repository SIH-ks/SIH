"""Listing, triage, analytics and export behaviour."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.models.enums import Priority
from app.services.triage import assess_priority

# ---------------------------------------------------------------------------
# Triage scoring — pure, so tested directly
# ---------------------------------------------------------------------------


def test_clean_record_sorts_to_the_bottom() -> None:
    assessment = assess_priority(
        mismatch_score=0.5,
        confidence_score=0.96,
        validation_highest_severity="info",
        validation_issue_count=0,
        recommended_action="auto_approve",
    )
    assert assessment.priority is Priority.LOW
    assert "Clean extraction" in assessment.reasons[0]


def test_two_agreeing_signals_are_required_for_critical() -> None:
    """A single maximal signal reaches HIGH; CRITICAL means two systems agree."""
    one_signal = assess_priority(
        mismatch_score=100.0,
        confidence_score=0.95,
        validation_highest_severity="info",
        validation_issue_count=0,
        recommended_action="auto_approve",
    )
    two_signals = assess_priority(
        mismatch_score=100.0,
        confidence_score=0.30,
        validation_highest_severity="critical",
        validation_issue_count=4,
        recommended_action="reject_re_scan",
    )
    assert one_signal.priority is Priority.HIGH
    assert two_signals.priority is Priority.CRITICAL
    assert two_signals.score > one_signal.score


def test_missing_geometry_is_not_penalised() -> None:
    """Absence of evidence must not be scored as evidence of a problem.

    Otherwise every record with no matched cadastral polygon -- which today is every
    real upload -- would sit permanently at the top of every queue.
    """
    unmatched = assess_priority(
        mismatch_score=None,
        confidence_score=0.9,
        validation_highest_severity=None,
        validation_issue_count=0,
        recommended_action="auto_approve",
    )
    matched_clean = assess_priority(
        mismatch_score=0.0,
        confidence_score=0.9,
        validation_highest_severity=None,
        validation_issue_count=0,
        recommended_action="auto_approve",
    )
    assert unmatched.score == matched_clean.score


def test_reasons_are_capped_and_ordered_by_weight() -> None:
    """A reviewer scanning a list will not read a fourth reason."""
    assessment = assess_priority(
        mismatch_score=90.0,
        confidence_score=0.2,
        validation_highest_severity="critical",
        validation_issue_count=9,
        recommended_action="reject_re_scan",
    )
    assert len(assessment.reasons) == 3
    assert "cadastral map" in assessment.reasons[0]


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_list_is_paged_with_a_true_total(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    response = app_client.get("/api/v1/parcels?limit=1", headers=reviewer)
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) <= 1
    assert body["total"] >= 1
    assert response.headers["X-Total-Count"] == str(body["total"])


def test_free_text_search_spans_identifiers(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    hit = app_client.get("/api/v1/parcels?q=Testville", headers=reviewer).json()
    miss = app_client.get("/api/v1/parcels?q=zzzz-no-such-village", headers=reviewer).json()
    assert hit["total"] >= 1
    assert miss["total"] == 0


def test_queue_returns_open_records_worst_first(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    body = app_client.get("/api/v1/parcels/queue?scope=all", headers=reviewer).json()
    scores = [item["priority_score"] for item in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert all(item["review_status"] in {"pending", "in_review", "escalated"} for item in body["items"])


def test_facets_expose_the_jurisdiction_tree(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    body = app_client.get("/api/v1/parcels/facets", headers=reviewer).json()
    assert "Karnataka" in body["tree"]
    assert "Belagavi" in body["tree"]["Karnataka"]


def test_geojson_omits_unmatched_records_but_counts_them(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    """A feature with null coordinates is valid GeoJSON and silently invisible."""
    body = app_client.get("/api/v1/parcels/geojson", headers=reviewer).json()
    assert body["type"] == "FeatureCollection"
    assert all(f["geometry"] is not None for f in body["features"])
    assert body["properties"]["without_geometry"] >= 0


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def test_summary_reports_totals_and_its_own_assumption(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    body = app_client.get("/api/v1/analytics/summary", headers=reviewer).json()
    assert body["total_parcels"] >= 1
    assert body["auto_validated"] + body["needs_review"] + body["flagged"] == body["total_parcels"]
    # The staff-hours figure must never travel without the constant behind it.
    assert body["minutes_saved_per_record_assumption"] > 0


def test_timeseries_includes_empty_days(app_client: TestClient, reviewer: dict) -> None:
    """A sparse series plotted as a line implies throughput across a gap."""
    body = app_client.get("/api/v1/analytics/timeseries?days=7", headers=reviewer).json()
    assert len(body) == 7
    assert [row["date"] for row in body] == sorted(row["date"] for row in body)


def test_district_breakdown_groups_by_jurisdiction(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    body = app_client.get("/api/v1/analytics/districts", headers=reviewer).json()
    assert any(row["district"] == "Belagavi" for row in body)


def test_district_rollup_puts_each_figure_in_its_own_column(
    app_client: TestClient, reviewer: dict, make_parcel
) -> None:
    """Guards a real off-by-one that no type checker could catch.

    Every aggregate in that rollup is a number, so reading the select list by
    position silently reported the overdue *count* as a mean confidence and the
    mean confidence as a mismatch score — numbers in every column, all plausible,
    all wrong. This asserts each value lands in the field that means it.

    It gets its own district because the assertion is on an *average*: sharing the
    Belagavi rows with the rest of the suite would make it fail whenever another
    test corrects an area.
    """
    make_parcel(district="Rollup Test District", village="Rollupville",
                confidence_score=0.62, mismatch_score=22.0, total_area_sq_metre=10000)

    rows = app_client.get("/api/v1/analytics/districts", headers=reviewer).json()
    row = next(r for r in rows if r["district"] == "Rollup Test District")

    assert row["total"] == 1
    assert row["avg_confidence"] == pytest.approx(0.62, abs=0.001), "0-1 fraction, not a count"
    assert row["avg_mismatch"] == pytest.approx(22.0, abs=0.01)
    assert row["total_area_hectares"] == pytest.approx(1.0, abs=0.001)


def test_queue_health_covers_every_priority_band(app_client: TestClient, reviewer: dict) -> None:
    body = app_client.get("/api/v1/analytics/queue-health", headers=reviewer).json()
    assert {b["priority"] for b in body["buckets"]} == {"critical", "high", "normal", "low"}


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


def test_parcel_csv_has_a_bom_and_both_area_units(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    """The BOM is what stops Excel mangling Devanagari and Kannada village names."""
    response = app_client.get("/api/v1/exports/parcels.csv", headers=reviewer)
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")

    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows, "export should contain the seeded parcel"
    assert {"total_area_sq_metre", "total_area_hectare"} <= set(rows[0])


def test_csv_export_honours_the_same_filters_as_the_table(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    """An export covering a different set than the screen discredits the report."""
    response = app_client.get("/api/v1/exports/parcels.csv?q=zzzz-no-such-village", headers=reviewer)
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows == []


def test_verification_report_is_self_contained(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    """It has to stay readable years later on a machine that cannot reach this server."""
    response = app_client.get(f"/api/v1/exports/parcels/{seeded_parcel}/report.html", headers=reviewer)
    assert response.status_code == 200
    html = response.text
    assert "Verification Report" in html
    assert "<link" not in html and "src=" not in html  # nothing fetched from elsewhere


def test_artifact_export_returns_the_stored_json(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    response = app_client.get(f"/api/v1/exports/parcels/{seeded_parcel}/artifact.json", headers=reviewer)
    assert response.status_code == 200
    assert response.json()["parcel_id"] == seeded_parcel


# ---------------------------------------------------------------------------
# System introspection
# ---------------------------------------------------------------------------


def test_rule_catalogue_is_read_from_the_live_registry(app_client: TestClient, reviewer: dict) -> None:
    """A hand-maintained rule list would silently fall behind the engine."""
    body = app_client.get("/api/v1/system/rules", headers=reviewer).json()
    assert len(body) >= 20
    assert any(r["group"] == "Arithmetic consistency" for r in body)
    assert any(r["registered"] for r in body)


def test_status_reports_the_database_actually_in_use(app_client: TestClient, reviewer: dict) -> None:
    body = app_client.get("/api/v1/system/status", headers=reviewer).json()
    assert body["database"]["reachable"] is True
    assert body["auth_enforced"] is True


def test_health_is_public(app_client: TestClient) -> None:
    body = app_client.get("/health").json()
    assert body["status"] == "ok"
