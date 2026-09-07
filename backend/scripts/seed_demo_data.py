"""Seed the live database with a realistic, varied set of parcels.

Run this when you want the running app to *show* something without waiting on
real uploads -- e.g. before a demo. It writes real `Document`/`ParcelRecord` rows
through the same ORM the live API reads from, so the dashboard, the traffic-light
column, the gauges, and the map all populate exactly as they would for genuine
extractions. This is a different mechanism from `frontend/src/lib/demoData.ts`:
that file is a client-side fallback used only when the backend is unreachable;
this script populates the backend itself, so the seeded records show up over the
real API regardless of whether the frontend ever falls back to anything.

Usage (from backend/, with the ai-engine on PYTHONPATH):
    python scripts/seed_demo_data.py            # add the seed set
    python scripts/seed_demo_data.py --reset     # wipe existing rows first
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, SessionLocal, engine  # noqa: E402
from app.models.record import Document, ParcelRecord  # noqa: E402


def _plot(lat: float, lon: float, half_side_m: float) -> dict:
    """A small square GeoJSON polygon around a point, sized in metres."""
    import math

    d_lat = half_side_m / 111_320
    d_lon = half_side_m / (111_320 * math.cos(math.radians(lat)))
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - d_lon, lat - d_lat],
                [lon + d_lon, lat - d_lat],
                [lon + d_lon, lat + d_lat],
                [lon - d_lon, lat + d_lat],
                [lon - d_lon, lat - d_lat],
            ]
        ],
    }


@dataclass
class SeedRecord:
    parcel_key: str
    state: str
    district: str
    village: str
    khata_number: str | None
    survey_number: str | None
    total_area_sq_metre: float | None
    mismatch_score: float | None
    confidence_score: float | None
    recommended_action: str | None
    requires_human_review: bool
    validation_highest_severity: str | None
    record_format: str
    owner_name: str | None
    khasra_numbers: list[str]
    mutation_date: str | None
    geometry: dict | None = None
    issues: list[dict] = field(default_factory=list)
    updated_at: datetime | None = None


SEED: list[SeedRecord] = [
    SeedRecord(
        "Belagavi/12/88", "Karnataka", "Belagavi", "Angol", "12", "88", 9420, 4.1, 0.91,
        "auto_approve", False, "info", "jamabandi", "Basavaraj Hiremath", ["88"], "2023-01-19",
        geometry=_plot(15.8497, 74.4977, 48),
        issues=[{
            "rule_code": "ASSESSMENT_DISPROPORTIONATE", "severity": "info",
            "message": "Land revenue per hectare on this sub-division is 2.3x the parcel's other sub-divisions.",
            "json_path": "$.sub_divisions[0].assessment_amount", "confidence": 0.7,
            "remediation": "Consistent with a mixed irrigated/unirrigated split -- worth a glance, not necessarily an error.",
        }],
    ),
    SeedRecord(
        "Madurai/205/77-1", "Tamil Nadu", "Madurai", "Thiruparankundram", "205", "77/1", 3640, 22.0, 0.68,
        "review_queue", True, "error", "ror_generic", "Muthu Selvam", ["77/1", "77/1"], "2020-07-22",
        geometry=_plot(9.8615, 78.0722, 35),
        issues=[
            {"rule_code": "DUPLICATE_KHASRA_NUMBER", "severity": "error",
             "message": "Khasra number 77/1 appears twice on this document, against two different sub-divisions.",
             "json_path": "$.khasra_numbers", "confidence": 0.86,
             "remediation": "Check whether one entry is a re-survey number that should replace, not duplicate, the other."},
            {"rule_code": "SHARE_MISSING", "severity": "warning",
             "message": "Two co-owners are recorded with no share stated for either -- apportionment is undefined.",
             "json_path": "$.owners", "confidence": 1.0,
             "remediation": "Confirm whether the record intends an equal split or ask the reviewer to key it in."},
        ],
    ),
    SeedRecord(
        "Lucknow/501/1200", "Uttar Pradesh", "Lucknow", "Gosainganj", "501", "1200", 15230, 8.0, 0.77,
        "review_queue", True, "error", "jamabandi", "Rajesh Yadav", ["1200"], "2027-01-15",
        geometry=_plot(26.8467, 80.9462, 55),
        issues=[
            {"rule_code": "MUTATION_DATE_IN_FUTURE", "severity": "error",
             "message": "The most recent mutation is dated 15 Jan 2027, which is after today's date.",
             "json_path": "$.mutations[-1].entry_date", "observed": "2027-01-15", "confidence": 0.95,
             "remediation": "Almost always a two-digit-year transcription slip -- verify against the scan."},
            {"rule_code": "MUTATION_OUT_OF_SEQUENCE", "severity": "warning",
             "message": "Mutation entries are not in chronological order in the register.",
             "json_path": "$.mutations", "confidence": 0.8,
             "remediation": "Re-check the entry dates were read from the correct column for each row."},
        ],
    ),
    SeedRecord(
        "Howrah/33/9-2", "West Bengal", "Howrah", "Domjur", "33", "9/2", 2180, None, 0.28,
        "reject_re_scan", True, "critical", "khasra_girdawari", None, ["9/2"], None,
        geometry=None,
        issues=[{
            "rule_code": "NO_OWNERS_RECORDED", "severity": "critical",
            "message": "No owner rows could be extracted from this parcel at all.",
            "json_path": "$.owners", "confidence": 0.9,
            "remediation": "The ownership column is likely obscured or the table grid mis-detected -- re-scan before trusting any other field.",
        }],
    ),
    SeedRecord(
        "Rajkot/88/456", "Gujarat", "Rajkot", "Kotharia", "88", "456", 7300, 6.2, 0.73,
        "review_queue", True, "error", "jamabandi", "Kiritbhai Chauhan", ["456"], "2024-03-11",
        geometry=_plot(22.3039, 70.8022, 42),
        issues=[{
            "rule_code": "CORRECTION_CHANGED_AREA", "severity": "error",
            "message": "A mutation typed as a clerical correction changed the recorded area by 145 sq m -- corrections should not alter area.",
            "json_path": "$.mutations[2]", "observed": "7300", "expected": "7155", "confidence": 0.83,
            "remediation": "Re-classify this mutation or verify the area figures on both sides of the entry.",
        }],
    ),
    SeedRecord(
        "Ludhiana/19/210", "Punjab", "Ludhiana", "Sidhwan Bet", "19", "210", 10120, 11.5, 0.7,
        "review_queue", True, "error", "jamabandi", "Gurpreet Singh", ["210"], "2021-09-09",
        geometry=_plot(30.901, 75.8573, 46),
        issues=[
            {"rule_code": "DUPLICATE_OWNER_SERIAL", "severity": "error",
             "message": "Owner serial number 2 is assigned to two different people on this record.",
             "json_path": "$.owners", "confidence": 0.81,
             "remediation": "One row's serial number was likely misread -- compare both entries against the scan."},
            {"rule_code": "OWNER_WITHOUT_MUTATION_TRAIL", "severity": "warning",
             "message": "The current owner does not appear in any sanctioned mutation's transferee list.",
             "json_path": "$.owners[1]", "confidence": 0.72,
             "remediation": "Either an older mutation wasn't digitized, or this entry predates the mutation register on file."},
        ],
    ),
    SeedRecord(
        "Patna/77/3009", "Bihar", "Patna", "Phulwari Sharif", "77", "3009", 4850, 18.4, 0.66,
        "review_queue", True, "warning", "jamabandi", "Om Prakash Singh", ["3009"], "2019-12-02",
        geometry=_plot(25.5941, 85.1376, 38),
        issues=[
            {"rule_code": "GEOMETRY_SLIVER", "severity": "warning",
             "message": "A 1.2m-wide gap exists between this parcel's polygon and its eastern neighbour, which should share a boundary.",
             "json_path": "$.geometry", "confidence": 0.6,
             "remediation": "Likely a digitisation seam in the source cadastral map rather than a real gap on the ground."},
            {"rule_code": "IDENTIFIER_MISSING", "severity": "warning",
             "message": "No Khatauni number could be read for this parcel, only the Khasra number.",
             "json_path": "$.khatauni_number", "confidence": 1.0,
             "remediation": "Check the cultivation-holding column on the source scan."},
        ],
    ),
    SeedRecord(
        "Indore/145/67", "Madhya Pradesh", "Indore", "Rau", "145", "67", 6800, 2.9, 0.93,
        "auto_approve", False, "info", "jamabandi", "Sunil Malviya", ["67"], "2022-05-30",
        geometry=_plot(22.7196, 75.8577, 41),
        issues=[{
            "rule_code": "UNRESOLVED_VOCABULARY", "severity": "info",
            "message": "The classification term on sub-division 2 did not match any known vernacular alias and was left unclassified.",
            "json_path": "$.sub_divisions[1].classification", "observed": '"Banjar Sailab"', "confidence": 1.0,
            "remediation": "A regional variant not yet in the vocabulary table -- worth adding if this term recurs.",
        }],
    ),
    SeedRecord(
        "Warangal/300/88-3", "Telangana", "Warangal", "Hanamkonda", "300", "88/3", 13400, 100.0, 0.39,
        "field_verification", True, "critical", "ror_generic", "Lakshmi Narayana", ["88/3"], "2017-10-04",
        geometry=_plot(17.9689, 79.5941, 58),
        issues=[{
            "rule_code": "AREA_SUM_EXCEEDS_TOTAL", "severity": "critical",
            "message": "Sub-divisions alone total 15,120 sq m, already exceeding the parcel's printed total of 13,400 sq m.",
            "json_path": "$.sub_divisions", "observed": "15120", "expected": "13400", "confidence": 0.94,
            "remediation": "Not a rounding difference -- re-examine whether a sub-division belongs to a different parent survey number.",
        }],
    ),
    SeedRecord(
        "Bhubaneswar/60/512", "Odisha", "Khordha", "Patrapada", "60", "512", 5590, 31.0, 0.6,
        "review_queue", True, "error", "jamabandi", "Priyanka Mohanty", ["512"], "2023-08-17",
        geometry=_plot(20.2961, 85.8245, 37),
        issues=[
            {"rule_code": "CLASSIFICATION_SPLIT_MISMATCH", "severity": "error",
             "message": "Cultivable + non-cultivable classified areas total 5,910 sq m against a printed parcel total of 5,590 sq m.",
             "json_path": "$.classified_areas", "observed": "5910", "expected": "5590", "confidence": 0.87,
             "remediation": "One classified-area row's figure likely has a transcription error."},
            {"rule_code": "LOW_FIELD_CONFIDENCE", "severity": "warning",
             "message": "The Vision LLM flagged its own reading of the owner's relation name as uncertain (confidence 0.52).",
             "json_path": "$.owners[0].name.relation_name", "confidence": 0.52,
             "remediation": "Cross-check the father's/husband's name against the scan before relying on it."},
        ],
    ),
]


def build_rows(seed: SeedRecord) -> tuple[Document, ParcelRecord]:
    doc_id = uuid.uuid4()
    parcel_id = uuid.uuid4()
    village_slug, khata_slug, survey_slug = seed.parcel_key.replace("/", "-"), seed.khata_number, seed.survey_number

    document = Document(
        id=doc_id,
        file_name=f"{village_slug}-seed.pdf",
        sha256=uuid.uuid4().hex + uuid.uuid4().hex[:32],  # unique placeholder, not a real content hash
        media_type="application/pdf",
        byte_size=0,
        page_count=1,
        declared_record_format=seed.record_format,
        declared_state=seed.state,
        source_system="seed_script",
        storage_key=f"seed/{village_slug}",
    )

    artifact_json = {
        "owners": [{"name": {"raw": seed.owner_name}}] if seed.owner_name else [],
        "khasra_numbers": seed.khasra_numbers,
        "survey_number": seed.survey_number,
        "total_area": {"sq_metre": seed.total_area_sq_metre} if seed.total_area_sq_metre is not None else None,
        "mutations": [{"entry_date": seed.mutation_date}] if seed.mutation_date else [],
        # No `provenance` key: seeded rows have no real OCR behind them, so the
        # Document Viewer correctly falls back to its simulated highlight boxes --
        # same honest behaviour as the frontend's own demo fixtures.
        "validation_issues": seed.issues,
    }

    parcel = ParcelRecord(
        id=parcel_id,
        document_id=doc_id,
        parcel_key=seed.parcel_key,
        state=seed.state,
        district=seed.district,
        village=seed.village,
        khata_number=khata_slug,
        survey_number=survey_slug,
        total_area_sq_metre=seed.total_area_sq_metre,
        record_format=seed.record_format,
        geometry=seed.geometry,
        mismatch_score=seed.mismatch_score,
        confidence_score=seed.confidence_score,
        recommended_action=seed.recommended_action,
        requires_human_review=seed.requires_human_review,
        artifact_json=artifact_json,
        page_image_urls=[],
        validation_issue_count=len(seed.issues),
        validation_highest_severity=seed.validation_highest_severity,
        updated_at=seed.updated_at or datetime.now(UTC),
    )
    return document, parcel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete all existing documents/parcels first")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.reset:
            db.query(ParcelRecord).delete()
            db.query(Document).delete()
            db.commit()
            print("Cleared existing documents and parcels.")

        existing_keys = {row[0] for row in db.query(ParcelRecord.parcel_key).all()}
        added = 0
        for seed in SEED:
            if seed.parcel_key in existing_keys:
                print(f"skip (already present): {seed.parcel_key}")
                continue
            document, parcel = build_rows(seed)
            db.add(document)
            db.add(parcel)
            added += 1
        db.commit()
        print(f"Seeded {added} new parcel(s). Total in DB: {db.query(ParcelRecord).count()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
