"""The review workflow: corrections that actually apply, and status transitions."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_correction_is_applied_to_the_stored_artifact(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    """The behaviour the original implementation was missing entirely.

    Recording a correction in the audit trail without applying it meant the next
    person to open the record still saw the machine's wrong reading, with a note
    attached. This asserts the value is really written.
    """
    response = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/review",
        json={"field_path": "owners[0].name.raw", "new_value": "Basavaraj Hiremath (corrected)"},
        headers=operator,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["applied"] is True

    fresh = app_client.get(f"/api/v1/parcels/{seeded_parcel}", headers=operator).json()
    assert fresh["artifact_json"]["owners"][0]["name"]["raw"] == "Basavaraj Hiremath (corrected)"
    assert fresh["correction_count"] == 1
    assert fresh["has_human_corrections"] is True


def test_correction_reruns_the_rule_engine(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    """A correction must re-judge the record, not leave stale findings in place.

    The seeded row carries one hand-authored finding. After a real correction the
    engine actually runs, so the stored findings are whatever the rules now say --
    the point being that they are *recomputed*, not that any particular count results.
    """
    before = app_client.get(f"/api/v1/parcels/{seeded_parcel}", headers=operator).json()

    response = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/review",
        json={"field_path": "khata_number", "new_value": "77"},
        headers=operator,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["revalidated"] is True, body.get("revalidation_note")

    after = app_client.get(f"/api/v1/parcels/{seeded_parcel}", headers=operator).json()
    assert after["validation_issue_count"] == body["issues_after"]
    assert after["artifact_json"]["khata_number"] == "77"
    # The seeded placeholder finding is gone: these are the engine's own findings now.
    codes = {i["rule_code"] for i in after["artifact_json"]["validation_issues"]}
    assert "seeded finding" not in codes
    assert before["validation_issue_count"] == body["issues_before"]


def test_total_area_correction_updates_the_indexed_projection(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    """The column the dashboard sorts and filters on has to follow the artifact."""
    response = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/review",
        json={"field_path": "total_area.sq_metre", "new_value": "12500"},
        headers=operator,
    )
    assert response.status_code == 201

    fresh = app_client.get(f"/api/v1/parcels/{seeded_parcel}", headers=operator).json()
    assert float(fresh["total_area_sq_metre"]) == 12500.0


def test_unknown_field_path_is_rejected_not_invented(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    """Auto-creating a missing path would let a typo invent an owner on a land record."""
    response = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/review",
        json={"field_path": "owners[7].name.raw", "new_value": "Nobody"},
        headers=operator,
    )
    assert response.status_code == 422
    assert "index 7" in response.json()["detail"]


def test_correction_writes_an_audit_event(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/review",
        json={"field_path": "survey_number", "new_value": "100-A", "note": "matched against scan"},
        headers=operator,
    )
    events = app_client.get(f"/api/v1/parcels/{seeded_parcel}/events", headers=operator).json()

    entry = next(e for e in events if e["field_path"] == "survey_number")
    assert entry["action"] == "corrected"
    assert entry["reviewer"] == "operator"
    assert entry["reviewer_role"] == "operator"
    assert entry["previous_value"]["value"] == "100"
    assert entry["new_value"]["value"] == "100-A"
    assert entry["note"] == "matched against scan"


def test_apply_false_records_intent_without_changing_the_record(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    original = app_client.get(f"/api/v1/parcels/{seeded_parcel}", headers=operator).json()

    response = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/review",
        json={"field_path": "village", "new_value": "Somewhere Else", "apply": False, "note": "needs a second signature"},
        headers=operator,
    )
    assert response.status_code == 201
    assert response.json()["applied"] is False

    after = app_client.get(f"/api/v1/parcels/{seeded_parcel}", headers=operator).json()
    assert after["artifact_json"] == original["artifact_json"]


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def test_reviewer_can_claim_and_approve(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    claimed = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/status", json={"status": "in_review"}, headers=reviewer
    )
    assert claimed.status_code == 200
    assert claimed.json()["review_status"] == "in_review"
    # Claiming assigns: an in-review record owned by nobody is how two officers end
    # up adjudicating the same parcel.
    assert claimed.json()["assigned_to"] == "tehsildar"

    approved = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/status",
        json={"status": "approved", "note": "verified against the register"},
        headers=reviewer,
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["review_status"] == "approved"
    assert body["decided_by"] == "tehsildar"
    assert body["decided_at"] is not None


def test_illegal_transition_is_a_conflict_not_a_silent_noop(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    """Approved -> rejected directly would leave no record of the reversal."""
    app_client.post(f"/api/v1/parcels/{seeded_parcel}/status", json={"status": "in_review"}, headers=reviewer)
    app_client.post(f"/api/v1/parcels/{seeded_parcel}/status", json={"status": "approved"}, headers=reviewer)

    response = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/status", json={"status": "rejected"}, headers=reviewer
    )
    assert response.status_code == 409
    assert "Re-open it into review first" in response.json()["detail"]


def test_repeating_the_current_status_is_a_conflict(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    app_client.post(f"/api/v1/parcels/{seeded_parcel}/status", json={"status": "in_review"}, headers=reviewer)
    repeat = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/status", json={"status": "in_review"}, headers=reviewer
    )
    assert repeat.status_code == 409


def test_assignment_and_release(app_client: TestClient, reviewer: dict, seeded_parcel: str) -> None:
    assigned = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/assign", json={"assignee": "operator"}, headers=reviewer
    )
    assert assigned.json()["assigned_to"] == "operator"

    released = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/assign", json={"assignee": None}, headers=reviewer
    )
    assert released.json()["assigned_to"] is None


def test_bulk_status_reports_every_id_it_skipped(
    app_client: TestClient, reviewer: dict, seeded_parcel: str
) -> None:
    """A bulk action that silently dropped records would be an audit failure."""
    import uuid

    ghost = str(uuid.uuid4())
    response = app_client.post(
        "/api/v1/parcels/bulk/status",
        json={"parcel_ids": [seeded_parcel, ghost], "status": "approved", "note": "batch clearance"},
        headers=reviewer,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_requested"] == 2
    assert seeded_parcel in body["updated"]
    assert any(s["parcel_id"] == ghost and "not found" in s["reason"] for s in body["skipped"])


def test_revalidate_endpoint_recomputes_findings(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    """Needed when the *policy* changes rather than the record."""
    response = app_client.post(f"/api/v1/parcels/{seeded_parcel}/revalidate", headers=operator)
    assert response.status_code == 200
    body = response.json()
    assert body["validation_issue_count"] == len(body["artifact_json"]["validation_issues"])

    events = app_client.get(f"/api/v1/parcels/{seeded_parcel}/events", headers=operator).json()
    assert any(e["action"] == "revalidated" for e in events)
