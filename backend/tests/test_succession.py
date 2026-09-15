"""The succession API: assessment, filing, the ownership chain, and the role gates.

These are integration tests over the real app and a real (temporary) database, in the
style of the other backend suites -- no mocking of the engine, so a rule change that
breaks the API surfaces here rather than in a demo.

Two properties get asserted repeatedly on purpose, because they are the ones a future
change is most likely to erode quietly: that filing a case leaves a row in the
*existing* parcel audit trail rather than a private one, and that no response
anywhere concludes a transfer was improper.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------


def _old_jamabandi(**land: Any) -> dict:
    return {
        "document_type": "jamabandi",
        "label": "Old Jamabandi (2019-20)",
        "revenue_year": "2019-20",
        "land": {
            "khasra": "125/2",
            "khata": "123",
            "area": 5.0,
            "area_unit": "hectare",
            "village": "Angol",
            "district": "Belagavi",
            "state": "Karnataka",
            **land,
        },
        "owners": [{"name": "Ramesh Sharma", "share": "1/1"}],
    }


def _updated_jamabandi(owners: list[dict] | None = None) -> dict:
    return {
        "document_type": "updated_jamabandi",
        "label": "Updated Jamabandi (2025-26)",
        "revenue_year": "2025-26",
        "land": {
            "khasra": "125/2",
            "khata": "123",
            "area": 5.0,
            "area_unit": "hectare",
            "village": "Angol",
            "district": "Belagavi",
            "state": "Karnataka",
        },
        "owners": owners
        or [
            {
                "name": "Amit Sharma",
                "relation": "son of",
                "relation_name": "Ramesh Sharma",
                "share": "1/1",
            }
        ],
    }


_DEATH = {
    "document_type": "death_certificate",
    "person": {"name": "Ramesh Sharma"},
    "date_of_death": "12/05/2025",
    "registration_number": "BLG/2025/4471",
}

_HEIRS = {
    "document_type": "legal_heir_certificate",
    "deceased": "Ramesh Sharma",
    "heirs": [
        {"name": "Sita Sharma", "relation": "wife of"},
        {"name": "Amit Sharma", "relation": "son of"},
        {"name": "Priya Sharma", "relation": "daughter of"},
    ],
}

_MUTATION = {
    "document_type": "mutation",
    "number": "MUT/2025/812",
    "type": "virasat",
    "status": "sanctioned",
    "order_date": "02/08/2025",
    "land": {"khasra": "125/2", "khata": "123", "area": 5.0, "area_unit": "hectare", "village": "Angol"},
    "previous_owner": "Ramesh Sharma",
    "new_owners": [{"name": "Amit Sharma", "share": "1/1"}],
}


def _flagged_bundle() -> list[dict]:
    """The reference case: three heirs named, the whole parcel to one of them."""
    return [_old_jamabandi(), _DEATH, _HEIRS, _MUTATION, _updated_jamabandi()]


def _coherent_bundle() -> list[dict]:
    """The counter-case: a relinquishment accounts for the other two heirs."""
    return [
        *_flagged_bundle(),
        {
            "document_type": "relinquishment_deed",
            "label": "Relinquishment deed",
            "reference": "BLG/RD/2025/91",
            "date": "10/07/2025",
            "relinquished_by": ["Sita Sharma", "Priya Sharma"],
            "in_favour_of": [{"name": "Amit Sharma", "share": "1/1"}],
        },
    ]


def _post(client: TestClient, headers: dict, **body: Any):
    return client.post(f"{API}/succession/validate", json=body, headers=headers)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def test_the_reference_case_is_flagged_for_review_not_failed(
    app_client: TestClient, operator: dict
) -> None:
    response = _post(app_client, operator, documents=_flagged_bundle(), persist=False)
    assert response.status_code == 200, response.text
    report = response.json()["report"]

    assert report["outcome"] == "review_required"
    assert report["risk_level"] == "high"
    assert report["event_type"] == "owner_death_succession"
    assert report["recommended_action"] == "human_review"
    assert report["death_verified"] is True
    assert sorted(h["name"] for h in report["potential_heirs"]) == [
        "Amit Sharma",
        "Priya Sharma",
        "Sita Sharma",
    ]


def test_the_reference_case_states_evidence_rather_than_wrongdoing(
    app_client: TestClient, operator: dict
) -> None:
    """The legal-design commitment, asserted against the wire format."""
    report = _post(app_client, operator, documents=_flagged_bundle(), persist=False).json()["report"]
    prose = " ".join(
        [report["summary"], *report["issues"], *(c["explanation"] for c in report["checks"])]
    ).lower()

    for forbidden in ("fraud", "fraudulent", "illegal", "unlawful", "rightful heir", "is entitled"):
        assert forbidden not in prose, f"succession output must not contain {forbidden!r}"
    assert "not a determination of legal entitlement" in report["disclaimer"]
    assert "human" in report["recommended_action"] or "revenue" in report["recommended_action"]


def test_a_coherent_chain_is_validated_and_not_flagged(
    app_client: TestClient, operator: dict
) -> None:
    report = _post(app_client, operator, documents=_coherent_bundle(), persist=False).json()["report"]

    assert report["outcome"] == "validated"
    assert report["risk_score"] == 0.0
    assert report["risk_level"] == "low"
    assert report["recommended_action"] == "accept_record"
    assert report["findings"] == []


def test_every_check_is_reported_including_the_ones_that_passed(
    app_client: TestClient, operator: dict
) -> None:
    report = _post(app_client, operator, documents=_flagged_bundle(), persist=False).json()["report"]
    statuses = {c["status"] for c in report["checks"]}

    assert "pass" in statuses
    assert len(report["checks"]) >= 12
    assert report["counts_by_status"]["pass"] > 0


def test_findings_arrive_in_the_shape_the_console_already_renders(
    app_client: TestClient, operator: dict
) -> None:
    report = _post(app_client, operator, documents=_flagged_bundle(), persist=False).json()["report"]
    finding = report["findings"][0]

    assert set(finding) >= {"rule_code", "severity", "message", "json_path", "confidence"}
    assert finding["severity"] in {"info", "warning", "error", "critical"}


def test_each_finding_points_at_the_documents_behind_it(
    app_client: TestClient, operator: dict
) -> None:
    """Requirement: a finding has to be traceable to a document and a field."""
    documents = [
        _old_jamabandi(),
        _DEATH,
        _HEIRS,
        {**_MUTATION, "land": {**_MUTATION["land"], "area": 6.2}},
        _updated_jamabandi(),
    ]
    report = _post(app_client, operator, documents=documents, persist=False).json()["report"]
    area = next(c for c in report["checks"] if c["rule"] == "AREA_CONSISTENCY" and c["status"] == "fail")

    labels = [e["document_label"] for e in area["evidence"]]
    fields = [e["field_path"] for e in area["evidence"]]
    assert any("Old Jamabandi" in (label or "") for label in labels)
    assert any("Mutation" in (label or "") for label in labels)
    assert all(field for field in fields)


def test_a_bundle_the_engine_could_not_fully_read_reports_how_it_was_read(
    app_client: TestClient, operator: dict
) -> None:
    documents = [_old_jamabandi(), {**_DEATH, "date_of_death": "sometime last year"}]
    body = _post(app_client, operator, documents=documents, persist=False).json()

    assert body["normalization_warnings"]
    assert any("date" in w for w in body["normalization_warnings"])
    # The assessment still happened; it was simply made without that date.
    assert body["report"]["outcome"] in {"validated", "incomplete", "review_required", "inconsistent"}


def test_an_empty_bundle_is_assessed_rather_than_rejected(
    app_client: TestClient, operator: dict
) -> None:
    body = _post(app_client, operator, documents=[], persist=False).json()
    assert body["report"]["event_type"] == "insufficient_documents"
    assert body["persisted"] is False


# ---------------------------------------------------------------------------
# Filing
# ---------------------------------------------------------------------------


def test_filing_a_case_stores_it_with_its_ownership_chain(
    app_client: TestClient, operator: dict
) -> None:
    created = _post(app_client, operator, documents=_flagged_bundle()).json()
    assert created["persisted"] is True

    case = created["case"]
    assert case["case_reference"].startswith("SUC/")
    assert case["outcome"] == "review_required"
    assert case["heir_count"] == 3
    assert case["open_finding_count"] >= 1

    events = app_client.get(f"{API}/succession/cases/{case['id']}/events", headers=operator)
    assert events.status_code == 200
    kinds = [e["event_type"] for e in events.json()]
    assert "death" in kinds
    assert "mutation" in kinds
    assert "record_snapshot" in kinds
    assert [e["sequence"] for e in events.json()] == sorted(e["sequence"] for e in events.json())


def test_a_dry_run_files_nothing(app_client: TestClient, operator: dict) -> None:
    before = app_client.get(f"{API}/succession/cases", headers=operator).json()["total"]
    body = _post(app_client, operator, documents=_flagged_bundle(), persist=False).json()
    after = app_client.get(f"{API}/succession/cases", headers=operator).json()["total"]

    assert body["case"] is None
    assert after == before


def test_a_case_filed_against_a_parcel_lands_in_that_parcel_s_own_audit_trail(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    """Not a private succession log: an officer must get one history per record."""
    before = len(app_client.get(f"{API}/parcels/{seeded_parcel}/events", headers=operator).json())

    response = _post(
        app_client, operator, documents=_flagged_bundle(), parcel_id=seeded_parcel
    )
    assert response.status_code == 200, response.text

    events = app_client.get(f"{API}/parcels/{seeded_parcel}/events", headers=operator).json()
    assert len(events) == before + 1
    assert "Succession case" in events[-1]["note"]
    assert events[-1]["reviewer"] == "operator"
    assert events[-1]["reviewer_role"] == "operator"


def test_an_existing_parcel_supplies_the_previous_record_without_re_keying_it(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    """The pipeline seam: a Jamabandi already extracted is reused as a snapshot."""
    body = _post(
        app_client,
        operator,
        documents=[_DEATH, _HEIRS, _MUTATION, _updated_jamabandi()],
        parcel_id=seeded_parcel,
        persist=False,
    ).json()

    previous = body["report"]["previous_owners"]
    assert [o["name"] for o in previous] == ["Basavaraj Hiremath"]
    # The register's own record is in the chain, labelled as coming from the file.
    labels = [e["document_label"] for e in body["report"]["evidence_documents"]]
    assert "Record of Rights (on file)" in labels


def test_an_unknown_parcel_is_a_422_naming_the_problem(
    app_client: TestClient, operator: dict
) -> None:
    response = _post(
        app_client, operator, documents=_flagged_bundle(), parcel_id=str(uuid.uuid4())
    )
    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


def test_the_case_list_is_paged_and_total_counted(app_client: TestClient, operator: dict) -> None:
    _post(app_client, operator, documents=_flagged_bundle())
    page = app_client.get(f"{API}/succession/cases?limit=1", headers=operator).json()

    assert page["limit"] == 1
    assert len(page["items"]) <= 1
    assert page["total"] >= 1


def test_open_only_excludes_cases_where_every_check_came_back_clear(
    app_client: TestClient, operator: dict
) -> None:
    _post(app_client, operator, documents=_coherent_bundle())
    _post(app_client, operator, documents=_flagged_bundle())

    every = app_client.get(f"{API}/succession/cases?limit=200", headers=operator).json()["items"]
    open_only = app_client.get(
        f"{API}/succession/cases?open_only=true&limit=200", headers=operator
    ).json()["items"]

    assert any(c["outcome"] == "validated" for c in every)
    assert all(c["outcome"] != "validated" for c in open_only)


def test_the_detail_returns_what_was_read_as_well_as_what_was_concluded(
    app_client: TestClient, operator: dict
) -> None:
    case_id = _post(app_client, operator, documents=_flagged_bundle()).json()["case"]["id"]
    detail = app_client.get(f"{API}/succession/cases/{case_id}", headers=operator).json()

    assert detail["report"]["outcome"] == "review_required"
    assert detail["case_json"]["record_snapshots"]  # the bundle as normalised
    assert detail["events"]


def test_explain_decomposes_the_risk_score_into_its_arithmetic(
    app_client: TestClient, operator: dict
) -> None:
    case_id = _post(app_client, operator, documents=_flagged_bundle()).json()["case"]["id"]
    explanation = app_client.get(f"{API}/succession/cases/{case_id}/explain", headers=operator).json()

    contributions = explanation["risk_contributions"]
    assert contributions
    assert round(sum(c["points"] for c in contributions), 2) == explanation["risk_score"]
    for contribution in contributions:
        assert round(contribution["base_points"] * contribution["multiplier"], 2) == contribution["points"]
    assert explanation["disclaimer"]


def test_parcel_history_spans_every_case_raised_against_the_land(
    app_client: TestClient, operator: dict
) -> None:
    key = f"History/{uuid.uuid4().hex[:8]}"
    _post(app_client, operator, documents=_flagged_bundle(), parcel_key=key)
    _post(app_client, operator, documents=_coherent_bundle(), parcel_key=key)

    history = app_client.get(
        f"{API}/succession/history?parcel_key={key}", headers=operator
    ).json()

    assert len(history) >= 8  # both cases' chains, not just one
    dated = [e["event_date"] for e in history if e["event_date"]]
    assert dated == sorted(dated)


def test_the_summary_counts_by_outcome_and_band(app_client: TestClient, operator: dict) -> None:
    _post(app_client, operator, documents=_flagged_bundle())
    summary = app_client.get(f"{API}/succession/summary", headers=operator).json()

    assert summary["total_cases"] >= 1
    assert summary["by_outcome"]
    assert summary["by_risk_level"]
    assert summary["open_cases"] <= summary["total_cases"]


def test_cases_for_a_parcel_drive_the_detail_page_s_panel(
    app_client: TestClient, operator: dict, seeded_parcel: str
) -> None:
    _post(app_client, operator, documents=_flagged_bundle(), parcel_id=seeded_parcel)
    cases = app_client.get(f"{API}/succession/parcels/{seeded_parcel}/cases", headers=operator).json()

    assert cases
    assert all(c["parcel_id"] == seeded_parcel for c in cases)


# ---------------------------------------------------------------------------
# Re-validation and deletion
# ---------------------------------------------------------------------------


def test_revalidating_re_runs_the_engine_without_re_reading_any_document(
    app_client: TestClient, operator: dict
) -> None:
    case_id = _post(app_client, operator, documents=_flagged_bundle()).json()["case"]["id"]
    again = app_client.post(f"{API}/succession/cases/{case_id}/revalidate", headers=operator)

    assert again.status_code == 200, again.text
    body = again.json()
    assert body["outcome"] == "review_required"
    assert body["events"]  # the chain was rewritten, not dropped
    assert body["id"] == case_id


def test_only_an_administrator_can_delete_a_case(
    app_client: TestClient, operator: dict, reviewer: dict, admin: dict
) -> None:
    case_id = _post(app_client, operator, documents=_flagged_bundle()).json()["case"]["id"]

    assert app_client.delete(f"{API}/succession/cases/{case_id}", headers=operator).status_code == 403
    assert app_client.delete(f"{API}/succession/cases/{case_id}", headers=reviewer).status_code == 403
    assert app_client.delete(f"{API}/succession/cases/{case_id}", headers=admin).status_code == 204
    assert app_client.get(f"{API}/succession/cases/{case_id}", headers=admin).status_code == 404


def test_a_missing_case_is_a_404(app_client: TestClient, operator: dict) -> None:
    assert (
        app_client.get(f"{API}/succession/cases/{uuid.uuid4()}", headers=operator).status_code == 404
    )


# ---------------------------------------------------------------------------
# Role gates
# ---------------------------------------------------------------------------


def test_an_auditor_can_read_cases_but_not_file_one(
    app_client: TestClient, auditor: dict, operator: dict
) -> None:
    _post(app_client, operator, documents=_flagged_bundle())

    assert app_client.get(f"{API}/succession/cases", headers=auditor).status_code == 200
    assert _post(app_client, auditor, documents=_flagged_bundle()).status_code == 403


def test_succession_endpoints_require_a_token(app_client: TestClient) -> None:
    assert app_client.get(f"{API}/succession/cases").status_code == 401
    assert app_client.post(f"{API}/succession/validate", json={"documents": []}).status_code == 401


# ---------------------------------------------------------------------------
# The rule catalogue
# ---------------------------------------------------------------------------


def test_the_succession_rules_appear_in_the_live_rule_catalogue(
    app_client: TestClient, operator: dict
) -> None:
    """A rule the engine registers must show up here without anyone editing a list."""
    rules = app_client.get(f"{API}/system/rules", headers=operator).json()
    succession = [r for r in rules if r["group"] == "Ownership succession"]

    assert len(succession) >= 14
    assert all(r["registered"] for r in succession)
    assert {r["code"] for r in succession} >= {
        "SUCCESSION_OWNER_IDENTITY_MISMATCH",
        "SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED",
        "SUCCESSION_UNEXPLAINED_TRANSITION",
    }
    assert not any("FRAUD" in r["code"] for r in rules)


def test_the_existing_parcel_rules_are_untouched_by_the_merge(
    app_client: TestClient, operator: dict
) -> None:
    rules = app_client.get(f"{API}/system/rules", headers=operator).json()
    groups = {r["group"] for r in rules}

    assert "Arithmetic consistency" in groups
    assert "Mutation chain" in groups
    assert any(r["code"] == "AREA_SUM_MISMATCH" and r["registered"] for r in rules)
