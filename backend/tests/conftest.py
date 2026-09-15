"""Test fixtures: an isolated in-file SQLite database and pre-authenticated clients.

Each test module gets its own temporary database file rather than sharing one, so a
test that approves a parcel cannot change what a later test sees. A file (not
``:memory:``) because the app's engine is module-level and pooled; an in-memory
SQLite database is per-connection, and the pool would hand different tests different
empty databases.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

DEMO_PASSWORD = "adhikar@2026"

# -- Environment, at conftest *import* time ------------------------------------
# Not in a fixture: `app.core.config.get_settings` is `lru_cache`d and
# `app.db.base` builds the engine at module import. A test module whose own
# imports touch anything under `app.` (several do) would therefore pin the engine
# to the developer's real `.env` database before any fixture had a chance to run
# -- and the suite would quietly exercise, and mutate, the local dev database.
# pytest imports conftest before collecting test modules, so this is the one
# placement that is guaranteed to be early enough.
_TMP_DB = Path(tempfile.mkdtemp(prefix="adhikar-tests-")) / "test.db"
os.environ["ADHIKAR_API_DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["ADHIKAR_API_DATABASE_FALLBACK_TO_SQLITE"] = "false"
os.environ["ADHIKAR_API_REQUIRE_AUTH"] = "true"
os.environ["ADHIKAR_API_SEED_DEMO_USERS"] = "true"
os.environ["ADHIKAR_API_DEMO_USER_PASSWORD"] = DEMO_PASSWORD
os.environ["ADHIKAR_API_ENVIRONMENT"] = "development"


@pytest.fixture(scope="session")
def app_client() -> Iterator[TestClient]:
    from app.db.base import Base
    from app.main import app

    Base.metadata.create_all(bind=_engine())
    with TestClient(app) as client:
        yield client


def _engine():
    from app.db.base import engine

    return engine


def _session() -> Session:
    return sessionmaker(bind=_engine(), future=True)()


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def admin(app_client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(app_client, 'collector')}"}


@pytest.fixture(scope="session")
def reviewer(app_client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(app_client, 'tehsildar')}"}


@pytest.fixture(scope="session")
def operator(app_client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(app_client, 'operator')}"}


@pytest.fixture(scope="session")
def auditor(app_client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(app_client, 'auditor')}"}


@pytest.fixture
def make_parcel(app_client: TestClient):
    """Insert one parcel with overridable fields and hand back its id.

    Needed alongside `seeded_parcel` because the suite shares one database: a test
    that asserts on an *aggregate* (a district rollup, say) cannot use the shared
    Belagavi rows, since earlier tests' corrections move the averages. Giving such
    a test its own district isolates it without resetting the database in between.
    """
    return _insert_parcel


@pytest.fixture
def seeded_parcel(app_client: TestClient) -> str:
    """One parcel written straight through the ORM.

    Inserted directly rather than through the upload endpoint because the extraction
    pipeline needs OCR models and (optionally) a network call to an LLM -- neither
    belongs in a unit test of the review workflow. The row is shaped exactly as
    ``services.ingestion._build_parcel_row`` writes one, including the
    ``validation_issues`` the rule engine folds into ``artifact_json``.
    """
    return _insert_parcel()


def _insert_parcel(
    *,
    state: str = "Karnataka",
    district: str = "Belagavi",
    village: str = "Testville",
    total_area_sq_metre: float = 10000,
    mismatch_score: float | None = 22.0,
    confidence_score: float | None = 0.62,
) -> str:
    from app.models.record import Document, ParcelRecord

    db = _session()
    try:
        document = Document(
            id=uuid.uuid4(),
            file_name="test-jamabandi.pdf",
            sha256=uuid.uuid4().hex * 2,
            media_type="application/pdf",
            byte_size=1024,
            page_count=1,
            declared_record_format="jamabandi",
            storage_key="local/test",
        )
        db.add(document)
        db.flush()

        parcel = ParcelRecord(
            id=uuid.uuid4(),
            document_id=document.id,
            parcel_key=f"{village}/1/100",
            state=state,
            district=district,
            village=village,
            khata_number="1",
            survey_number="100",
            total_area_sq_metre=total_area_sq_metre,
            record_format="jamabandi",
            mismatch_score=mismatch_score,
            confidence_score=confidence_score,
            recommended_action="review_queue",
            requires_human_review=True,
            artifact_json={
                "record_format": "jamabandi",
                "jurisdiction": {"state": state, "district": district, "village": village},
                "khata_number": "1",
                "survey_number": "100",
                "khasra_numbers": ["100"],
                "total_area": {
                    "sq_metre": f"{total_area_sq_metre:.4f}",
                    "unit_system": "metric_ha_are_sqm",
                    "components": {},
                },
                "owners": [
                    {
                        "serial_number": "1",
                        "name": {"raw": "Basavaraj Hiremath", "relation_type": "unknown"},
                        "tenure_type": "unknown",
                    }
                ],
                "provenance": {},
                "validation_issues": [
                    {
                        "rule_code": "SHARE_MISSING",
                        "severity": "warning",
                        "message": "seeded finding",
                        "json_path": "$.owners",
                        "confidence": 1.0,
                    }
                ],
            },
            page_image_urls=[],
            validation_issue_count=1,
            validation_highest_severity="warning",
            priority="high",
            priority_score=40.0,
            created_at=datetime.now(UTC),
        )
        db.add(parcel)
        db.commit()
        return str(parcel.id)
    finally:
        db.close()
