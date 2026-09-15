"""Authentication and role enforcement.

These tests are the executable statement of the separation of duties the workflow
depends on: an operator may key corrections but may not approve, and an auditor may
read everything but change nothing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import DEMO_PASSWORD


def test_login_returns_token_and_profile(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/v1/auth/login", json={"username": "tehsildar", "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "reviewer"
    assert body["expires_in"] > 0


def test_wrong_password_and_unknown_user_are_indistinguishable(app_client: TestClient) -> None:
    """A different message for each would turn the login form into a username oracle."""
    wrong = app_client.post("/api/v1/auth/login", json={"username": "tehsildar", "password": "nope"})
    missing = app_client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})

    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["detail"] == missing.json()["detail"]


def test_protected_route_rejects_missing_token(app_client: TestClient) -> None:
    assert app_client.get("/api/v1/parcels").status_code == 401


def test_protected_route_rejects_garbage_token(app_client: TestClient) -> None:
    response = app_client.get("/api/v1/parcels", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_operator_may_not_approve(app_client: TestClient, operator: dict, seeded_parcel: str) -> None:
    """The separation-of-duties boundary, asserted end to end."""
    response = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/status", json={"status": "approved"}, headers=operator
    )
    assert response.status_code == 403
    assert "Revenue Inspector" in response.json()["detail"]


def test_auditor_may_read_but_not_write(
    app_client: TestClient, auditor: dict, seeded_parcel: str
) -> None:
    assert app_client.get("/api/v1/parcels", headers=auditor).status_code == 200
    assert app_client.get("/api/v1/audit/events", headers=auditor).status_code == 200

    blocked = app_client.post(
        f"/api/v1/parcels/{seeded_parcel}/review",
        json={"field_path": "khata_number", "new_value": "9"},
        headers=auditor,
    )
    assert blocked.status_code == 403


def test_only_admin_manages_users(app_client: TestClient, reviewer: dict, admin: dict) -> None:
    assert app_client.get("/api/v1/auth/users", headers=reviewer).status_code == 403
    assert app_client.get("/api/v1/auth/users", headers=admin).status_code == 200


def test_deactivated_account_loses_access_immediately(app_client: TestClient, admin: dict) -> None:
    """Role claims are embedded in the token, but active-status is re-read per request.

    That is the whole reason ``_user_from_token`` still touches the database: without
    it, a suspended officer would keep working until their token expired.
    """
    created = app_client.post(
        "/api/v1/auth/users",
        json={
            "username": "temp.clerk",
            "password": "temporary-pass-1",
            "full_name": "Temporary Clerk",
            "role": "operator",
        },
        headers=admin,
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    login = app_client.post(
        "/api/v1/auth/login", json={"username": "temp.clerk", "password": "temporary-pass-1"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert app_client.get("/api/v1/parcels", headers=headers).status_code == 200

    app_client.post(f"/api/v1/auth/users/{user_id}/deactivate", headers=admin)

    assert app_client.get("/api/v1/parcels", headers=headers).status_code == 401
    assert (
        app_client.post(
            "/api/v1/auth/login", json={"username": "temp.clerk", "password": "temporary-pass-1"}
        ).status_code
        == 401
    )


def test_admin_cannot_deactivate_self(app_client: TestClient, admin: dict) -> None:
    me = app_client.get("/api/v1/auth/me", headers=admin).json()
    response = app_client.post(f"/api/v1/auth/users/{me['id']}/deactivate", headers=admin)
    assert response.status_code == 409


def test_roles_endpoint_is_public(app_client: TestClient) -> None:
    """The login screen needs the role vocabulary before any token exists."""
    response = app_client.get("/api/v1/auth/roles")
    assert response.status_code == 200
    assert {r["value"] for r in response.json()} == {"auditor", "operator", "reviewer", "admin"}
