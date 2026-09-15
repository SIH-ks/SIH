"""Seed the live database with a realistic, varied corpus of land records.

Run this when you want the running app to *show* something without waiting on real
uploads -- before a demo, or to populate the dashboard, queue, map and analytics
views in one step. It writes real `Document` / `ParcelRecord` / `ReviewEvent` rows
through the same ORM the live API reads from.

**The validation findings on these records are not hand-written.** Each seed entry is
assembled into a genuine :class:`~adhikar.schemas.land_record.LandParcelRecord` --
with the arithmetic, ownership shares, duplicate identifiers and out-of-sequence
mutations that actually make a record inconsistent -- and then run through the same
22-rule engine the pipeline uses. What the console displays is therefore real engine
output over synthetic inputs, not a fixture pretending to be one. If a rule's
behaviour changes, this data changes with it; if a seeded record stops producing the
finding it was written to produce, that is a real regression and the script says so.

What stays synthetic, and is labelled as such: OCR/LLM confidence, the cadastral
mismatch score (no cadastral source is wired in this deployment), and the rendered
"scan" image. Those come from stages that cannot be faked offline.

This is a different mechanism from `frontend/src/lib/demoData.ts`: that file is a
client-side fallback used only when the backend is unreachable; this populates the
backend itself.

Usage (from backend/, with the ai-engine importable):
    python scripts/seed_demo_data.py             # add any missing seed records
    python scripts/seed_demo_data.py --reset     # wipe existing rows first
    python scripts/seed_demo_data.py --verify    # assert every intended rule fired
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adhikar.schemas.enums import (  # noqa: E402
    EncumbranceStatus,
    EncumbranceType,
    LandClassification,
    MutationStatus,
    MutationType,
    RecordFormat,
    RelationType,
    TenureType,
)
from adhikar.schemas.land_record import (  # noqa: E402
    ClassifiedArea,
    Encumbrance,
    Jurisdiction,
    LandParcelRecord,
    MutationEntry,
    OwnerRecord,
    OwnershipShare,
    PersonName,
    SubDivision,
)
from adhikar.schemas.units import AreaMeasurement  # noqa: E402
from adhikar.validation import DEFAULT_POLICY, run_all  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base, SessionLocal, engine  # noqa: E402
from app.models.enums import Priority, ReviewAction, ReviewStatus  # noqa: E402
from app.models.record import Document, ParcelRecord, ReviewEvent  # noqa: E402
from app.models.succession import (  # noqa: E402
    OwnershipEventRecord,
    SuccessionCaseRecord,
)
from app.services.triage import assess_priority, sla_due_at  # noqa: E402

_PAGE_SIZE = (1275, 1650)  # 8.5x11in @150dpi, matches DocumentViewer's aspect-[8.5/11]
_FONT_DIR = Path(r"C:\Windows\Fonts")

_RNG_SEED = 20260910
"""Fixed so a re-seed produces the same corpus. A demo whose numbers move between
runs is a demo nobody can rehearse against."""


# ---------------------------------------------------------------------------
# Synthetic scan rendering (labelled synthetic; there is no OCR behind it)
# ---------------------------------------------------------------------------


def _fonts() -> dict:
    from PIL import ImageFont

    def _load(name: str, size: int):
        path = _FONT_DIR / name
        return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size)

    return {
        "title": _load("timesbd.ttf", 34),
        "label": _load("times.ttf", 18),
        "value": _load("timesbd.ttf", 24),
        "small": _load("times.ttf", 15),
    }


def _render_mock_scan(seed: SeedRecord) -> bytes:
    """A synthetic 'scanned page' standing in for a real upload.

    A plausible Jamabandi / 7-12-style form with this record's own fields printed on
    it, so the Document Viewer shows a real (if fabricated) image instead of its
    CSS-drawn placeholder. No OCR or bbox provenance behind it -- the same honest
    limitation as any other seeded row.
    """
    import io

    from PIL import Image, ImageDraw

    rng = random.Random(seed.parcel_key)  # stable per-parcel "paper grain"
    w, h = _PAGE_SIZE
    font = _fonts()
    img = Image.new("RGB", (w, h), (253, 252, 248))
    draw = ImageDraw.Draw(img)

    margin = 70
    draw.rectangle([margin, margin, w - margin, h - margin], outline=(70, 70, 70), width=3)
    draw.rectangle([margin + 8, margin + 8, w - margin - 8, h - margin - 8], outline=(160, 160, 160), width=1)

    title = {
        "jamabandi": "JAMABANDI \u2014 RECORD OF RIGHTS",
        "satbara_7_12": "SATBARA (7/12) EXTRACT",
        "ror_generic": "RECORD OF RIGHTS",
        "khasra_girdawari": "KHASRA GIRDAWARI",
    }.get(seed.record_format, "RECORD OF RIGHTS")
    draw.text((w / 2, margin + 50), title, font=font["title"], fill=(30, 30, 30), anchor="mm")
    draw.text((w / 2, margin + 90), f"{seed.state}, India", font=font["small"], fill=(90, 90, 90), anchor="mm")
    draw.line([margin + 40, margin + 115, w - margin - 40, margin + 115], fill=(120, 120, 120), width=2)

    owner = seed.owners[0][0] if seed.owners else "\u2014"
    rows = [
        ("Village", seed.village),
        ("District", seed.district),
        ("Khata Number", seed.khata_number or "\u2014"),
        ("Survey / Khasra No.", seed.survey_number or "\u2014"),
        ("Owner Name", owner),
        ("Total Area (sq. m)", f"{seed.total_area_sq_metre:,.0f}" if seed.total_area_sq_metre else "\u2014"),
        ("Last Mutation Date", seed.mutations[-1][0] if seed.mutations else "\u2014"),
    ]
    y = margin + 160
    row_h = 70
    for label, value in rows:
        draw.text((margin + 40, y), label.upper(), font=font["label"], fill=(120, 120, 120))
        draw.text((margin + 40, y + 26), str(value), font=font["value"], fill=(25, 25, 25))
        draw.line([margin + 40, y + row_h - 12, w - margin - 40, y + row_h - 12], fill=(210, 210, 210), width=1)
        y += row_h

    # Decorative ledger rows below, to fill out the page like a real dense form
    y += 30
    for _ in range(9):
        bar_w = rng.randint(int((w - 2 * margin) * 0.35), int((w - 2 * margin) * 0.8))
        draw.rectangle([margin + 40, y, margin + 40 + bar_w, y + 14], fill=(225, 225, 220))
        y += 34

    # Light paper grain so it doesn't read as a vector graphic
    for _ in range(1200):
        x, y_ = rng.randint(margin, w - margin), rng.randint(margin, h - margin)
        shade = rng.randint(210, 245)
        draw.point((x, y_), fill=(shade, shade, shade))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


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


# ---------------------------------------------------------------------------
# Seed corpus
# ---------------------------------------------------------------------------


@dataclass
class SeedRecord:
    """One record described in domain terms, from which a real parcel is assembled.

    Owners, sub-divisions and mutations are given as plain tuples rather than fully
    constructed Pydantic objects purely for legibility: the table below is meant to
    be readable as a list of land records, and the defects each one carries should be
    visible at a glance in the data itself, not buried in constructor calls.
    """

    parcel_key: str
    state: str
    district: str
    village: str
    khata_number: str | None
    survey_number: str | None
    total_area_sq_metre: float | None
    record_format: str

    # -- synthetic pipeline scores (OCR/geo stages cannot run offline) -------------
    mismatch_score: float | None
    confidence_score: float | None
    recommended_action: str | None

    #: (name, relation_name, serial, share_numerator, share_denominator | None)
    owners: list[tuple] = field(default_factory=list)
    #: (number, area_sq_metre, classification, owner_serials)
    sub_divisions: list[tuple] = field(default_factory=list)
    #: (classification, area_sq_metre)
    classified_areas: list[tuple] = field(default_factory=list)
    #: (entry_date, mutation_type, status, from_party, to_party|[to_parties], area | None)
    mutations: list[tuple] = field(default_factory=list)
    #: (encumbrance_type, status, holder, amount)
    encumbrances: list[tuple] = field(default_factory=list)

    khasra_numbers: list[str] = field(default_factory=list)
    khatauni_number: str | None = None
    geometry: dict | None = None

    expect_rules: list[str] = field(default_factory=list)
    """Rule codes this record was constructed to trigger. ``--verify`` asserts each
    one actually fires -- so a seed record that silently stops demonstrating its
    defect (because a rule or a tolerance changed) is caught here rather than
    discovered mid-demo."""

    note: str = ""
    """What this record is for, in one line. Printed by ``--verify``."""


_M = lambda v: AreaMeasurement(sq_metre=Decimal(str(v)))  # noqa: E731 - a table-local shorthand

_TEHSILS: dict[str, str] = {
    "Belagavi": "Belagavi", "Indore": "Indore", "Nashik": "Dindori", "Coimbatore": "Sulur",
    "Warangal": "Hanamkonda", "Khordha": "Bhubaneswar", "Jaipur": "Sanganer", "Madurai": "Madurai South",
    "Ludhiana": "Jagraon", "Howrah": "Domjur", "Kamrup": "Rangia", "Nagpur": "Kamptee",
    "Lucknow": "Mohanlalganj", "Rajkot": "Rajkot", "Patna": "Phulwari Sharif", "Varanasi": "Varanasi",
    "Thrissur": "Thrissur", "Raipur": "Abhanpur", "Rangareddy": "Shamshabad", "Amritsar": "Ajnala",
    "Mysuru": "Nanjangud", "Cuttack": "Salepur",
}
"""Taluk/tehsil per district. Not decoration: `Jurisdiction.is_resolvable` -- and so
the JURISDICTION_INCOMPLETE rule -- requires state, district, tehsil *and* village
together, because a village name alone is not unique within a state. Ranchi is
deliberately absent so exactly one seeded record demonstrates that rule firing."""


SEED: list[SeedRecord] = [
    # -- clean records: what the majority of a real corpus looks like ---------------
    SeedRecord(
        "Belagavi/12/88", "Karnataka", "Belagavi", "Angol", "12", "88", 9420, "jamabandi",
        4.1, 0.91, "auto_approve",
        owners=[("Basavaraj Hiremath", "Shivappa Hiremath", "1", 1, 1)],
        sub_divisions=[("88/1", 5420, LandClassification.IRRIGATED, ["1"]),
                       ("88/2", 4000, LandClassification.UNIRRIGATED, ["1"])],
        classified_areas=[(LandClassification.IRRIGATED, 5420), (LandClassification.UNIRRIGATED, 4000)],
        mutations=[("2019-06-02", MutationType.INHERITANCE, MutationStatus.SANCTIONED,
                    "Shivappa Hiremath", "Basavaraj Hiremath", None),
                   ("2023-01-19", MutationType.CORRECTION, MutationStatus.SANCTIONED, None, None, None)],
        khasra_numbers=["88"], geometry=_plot(15.8497, 74.4977, 48),
        note="Internally consistent single-owner holding — the auto-approve path.",
    ),
    SeedRecord(
        "Indore/145/67", "Madhya Pradesh", "Indore", "Rau", "145", "67", 6800, "jamabandi",
        2.9, 0.93, "auto_approve",
        owners=[("Sunil Malviya", "Ramesh Malviya", "1", 1, 2), ("Meena Malviya", "Sunil Malviya", "2", 1, 2)],
        sub_divisions=[("67/1", 3400, LandClassification.IRRIGATED, ["1"]),
                       ("67/2", 3400, LandClassification.IRRIGATED, ["2"])],
        classified_areas=[(LandClassification.IRRIGATED, 6800)],
        mutations=[("2022-05-30", MutationType.PARTITION, MutationStatus.SANCTIONED,
                    "Ramesh Malviya", ["Sunil Malviya", "Meena Malviya"], 3400)],
        khasra_numbers=["67"], geometry=_plot(22.7196, 75.8577, 41),
        note="Two co-owners with shares summing to unity — clean partition.",
    ),
    SeedRecord(
        "Nashik/61/402", "Maharashtra", "Nashik", "Dindori", "61", "402", 12800, "satbara_7_12",
        1.4, 0.94, "auto_approve",
        owners=[("Vasant Pawar", "Dattatray Pawar", "1", 1, 1)],
        sub_divisions=[("402/A", 8800, LandClassification.IRRIGATED, ["1"]),
                       ("402/B", 4000, LandClassification.CULTIVABLE_WASTE, ["1"])],
        classified_areas=[(LandClassification.IRRIGATED, 8800), (LandClassification.CULTIVABLE_WASTE, 4000)],
        mutations=[("2021-11-08", MutationType.SALE, MutationStatus.SANCTIONED,
                    "Dattatray Pawar", "Vasant Pawar", 12800)],
        khasra_numbers=["402"], geometry=_plot(20.2006, 73.7898, 62),
        note="Clean 7/12 extract from a well-maintained register.",
    ),
    SeedRecord(
        "Coimbatore/34/512", "Tamil Nadu", "Coimbatore", "Sulur", "34", "512", 5100, "ror_generic",
        3.3, 0.89, "auto_approve",
        owners=[("Karthikeyan R", "Ramasamy", "1", 1, 1)],
        sub_divisions=[("512", 5100, LandClassification.IRRIGATED, ["1"])],
        classified_areas=[(LandClassification.IRRIGATED, 5100)],
        mutations=[("2020-02-14", MutationType.SALE, MutationStatus.SANCTIONED, "Ramasamy", "Karthikeyan R", 5100)],
        khasra_numbers=["512"], geometry=_plot(11.0246, 77.1256, 36),
        note="Clean record, single sub-division.",
    ),

    # -- arithmetic defects ---------------------------------------------------------
    SeedRecord(
        "Warangal/300/88-3", "Telangana", "Warangal", "Hanamkonda", "300", "88/3", 13400, "ror_generic",
        100.0, 0.39, "field_verification",
        owners=[("Lakshmi Narayana", "Venkataiah", "1", 1, 1)],
        # 8,200 + 6,920 = 15,120 against a printed total of 13,400.
        sub_divisions=[("88/3A", 8200, LandClassification.IRRIGATED, ["1"]),
                       ("88/3B", 6920, LandClassification.UNIRRIGATED, ["1"])],
        mutations=[("2017-10-04", MutationType.SALE, MutationStatus.SANCTIONED, "Venkataiah", "Lakshmi Narayana", 13400)],
        khasra_numbers=["88/3"], geometry=_plot(17.9689, 79.5941, 58),
        expect_rules=["AREA_SUM_EXCEEDS_TOTAL"],
        note="Sub-divisions total more than the parent parcel — never a rounding error.",
    ),
    SeedRecord(
        "Bhubaneswar/60/512", "Odisha", "Khordha", "Patrapada", "60", "512", 5590, "jamabandi",
        31.0, 0.60, "review_queue",
        owners=[("Priyanka Mohanty", "Bijay Mohanty", "1", 1, 1)],
        sub_divisions=[("512/1", 5590, LandClassification.IRRIGATED, ["1"])],
        # Classified areas total 5,910 against a printed 5,590.
        classified_areas=[(LandClassification.IRRIGATED, 3600), (LandClassification.NON_CULTIVABLE, 2310)],
        mutations=[("2023-08-17", MutationType.INHERITANCE, MutationStatus.SANCTIONED,
                    "Bijay Mohanty", "Priyanka Mohanty", None)],
        khasra_numbers=["512"], geometry=_plot(20.2961, 85.8245, 37),
        expect_rules=["CLASSIFICATION_SPLIT_MISMATCH"],
        note="Cultivable + non-cultivable breakup contradicts the printed total.",
    ),
    SeedRecord(
        "Jaipur/210/1145", "Rajasthan", "Jaipur", "Sanganer", "210", "1145", 18600, "jamabandi",
        9.7, 0.71, "review_queue",
        owners=[("Mahendra Sharma", "Gopal Sharma", "1", 1, 1)],
        # 9,000 + 9,000 = 18,000 against 18,600: a 600 sq m shortfall, well past tolerance.
        sub_divisions=[("1145/1", 9000, LandClassification.UNIRRIGATED, ["1"]),
                       ("1145/2", 9000, LandClassification.UNIRRIGATED, ["1"])],
        mutations=[("2018-03-21", MutationType.SALE, MutationStatus.SANCTIONED, "Gopal Sharma", "Mahendra Sharma", 18600)],
        khasra_numbers=["1145"], geometry=_plot(26.8189, 75.7861, 68),
        expect_rules=["AREA_SUM_MISMATCH"],
        note="Sub-divisions fall short of the printed total by more than survey tolerance.",
    ),

    # -- ownership defects ------------------------------------------------------------
    SeedRecord(
        "Madurai/205/77-1", "Tamil Nadu", "Madurai", "Thiruparankundram", "205", "77/1", 3640, "ror_generic",
        22.0, 0.68, "review_queue",
        owners=[("Muthu Selvam", "Selvam", "1", None, None), ("Ananthi Selvam", "Muthu Selvam", "2", None, None)],
        sub_divisions=[("77/1", 3640, LandClassification.IRRIGATED, ["1", "2"])],
        mutations=[("2020-07-22", MutationType.INHERITANCE, MutationStatus.SANCTIONED, "Selvam", "Muthu Selvam", None)],
        khasra_numbers=["77/1", "77/1"],  # the same plot number entered twice
        geometry=_plot(9.8615, 78.0722, 35),
        expect_rules=["DUPLICATE_KHASRA_NUMBER", "SHARE_MISSING"],
        note="Two co-owners with no shares stated, and a duplicated khasra number.",
    ),
    SeedRecord(
        "Ludhiana/19/210", "Punjab", "Ludhiana", "Sidhwan Bet", "19", "210", 10120, "jamabandi",
        11.5, 0.70, "review_queue",
        owners=[("Gurpreet Singh", "Harbans Singh", "1", 1, 2),
                ("Jaswinder Kaur", "Harbans Singh", "2", 1, 4),
                ("Manjit Singh", "Harbans Singh", "2", 1, 4)],  # serial 2 used twice
        sub_divisions=[("210", 10120, LandClassification.IRRIGATED, ["1", "2"])],
        mutations=[("2021-09-09", MutationType.INHERITANCE, MutationStatus.SANCTIONED,
                    "Harbans Singh", "Gurpreet Singh", None)],
        khasra_numbers=["210"], geometry=_plot(30.9010, 75.8573, 46),
        expect_rules=["DUPLICATE_OWNER_SERIAL"],
        note="Two people share owner serial 2 — one row's serial was misread.",
    ),
    SeedRecord(
        "Howrah/33/9-2", "West Bengal", "Howrah", "Domjur", "33", "9/2", 2180, "khasra_girdawari",
        None, 0.28, "reject_re_scan",
        owners=[],  # the ownership column could not be read at all
        sub_divisions=[("9/2", 2180, LandClassification.UNKNOWN, [])],
        khasra_numbers=["9/2"], geometry=None,
        expect_rules=["NO_OWNERS_RECORDED"],
        note="Ownership column illegible — the record is unusable until re-scanned.",
    ),
    SeedRecord(
        "Kamrup/44/781", "Assam", "Kamrup", "Rangia", "44", "781", 4300, "ror_generic",
        14.2, 0.64, "review_queue",
        owners=[("Nabajyoti Das", "Bhaben Das", "1", 2, 3), ("Rupali Das", "Bhaben Das", "2", 2, 3)],
        sub_divisions=[("781", 4300, LandClassification.IRRIGATED, ["1", "2"])],
        mutations=[("2019-04-30", MutationType.INHERITANCE, MutationStatus.SANCTIONED, "Bhaben Das", "Nabajyoti Das", None)],
        khasra_numbers=["781"], geometry=_plot(26.4525, 91.6250, 33),
        expect_rules=["SHARE_SUM_EXCEEDS_UNITY"],
        note="Recorded shares total 4/3 — more land is apportioned than exists.",
    ),
    SeedRecord(
        "Nagpur/88/1330", "Maharashtra", "Nagpur", "Kamptee", "88", "1330", 7700, "satbara_7_12",
        6.8, 0.75, "review_queue",
        owners=[("Sanjay Wankhede", "Arun Wankhede", "1", 1, 1)],
        # References owner serial 4, which no owner row carries.
        sub_divisions=[("1330/1", 4700, LandClassification.IRRIGATED, ["1"]),
                       ("1330/2", 3000, LandClassification.UNIRRIGATED, ["4"])],
        mutations=[("2022-01-11", MutationType.SALE, MutationStatus.SANCTIONED, "Arun Wankhede", "Sanjay Wankhede", 7700)],
        khasra_numbers=["1330"], geometry=_plot(21.2181, 79.1980, 44),
        expect_rules=["ORPHAN_OWNER_REFERENCE"],
        note="A sub-division is booked to an owner serial that appears nowhere on the record.",
    ),

    # -- mutation-chain defects -----------------------------------------------------
    SeedRecord(
        "Lucknow/501/1200", "Uttar Pradesh", "Lucknow", "Gosainganj", "501", "1200", 15230, "jamabandi",
        8.0, 0.77, "review_queue",
        owners=[("Rajesh Yadav", "Ram Naresh Yadav", "1", 1, 1)],
        sub_divisions=[("1200", 15230, LandClassification.IRRIGATED, ["1"])],
        mutations=[("2024-05-02", MutationType.SALE, MutationStatus.SANCTIONED, "Ram Naresh Yadav", "Rajesh Yadav", 15230),
                   ("2020-08-13", MutationType.CORRECTION, MutationStatus.SANCTIONED, None, None, None),
                   (_future_date := (date.today() + timedelta(days=380)).isoformat(),
                    MutationType.CORRECTION, MutationStatus.SANCTIONED, None, None, None)],
        khasra_numbers=["1200"], geometry=_plot(26.8467, 80.9462, 55),
        expect_rules=["MUTATION_DATE_IN_FUTURE", "MUTATION_OUT_OF_SEQUENCE"],
        note="A mutation dated in the future, and entries out of chronological order.",
    ),
    SeedRecord(
        "Rajkot/88/456", "Gujarat", "Rajkot", "Kotharia", "88", "456", 7300, "jamabandi",
        6.2, 0.73, "review_queue",
        owners=[("Kiritbhai Chauhan", "Bhagwanji Chauhan", "1", 1, 1)],
        sub_divisions=[("456", 7300, LandClassification.IRRIGATED, ["1"])],
        # A "clerical correction" that nonetheless moves 145 sq m of area.
        mutations=[("2020-02-03", MutationType.SALE, MutationStatus.SANCTIONED,
                    "Bhagwanji Chauhan", "Kiritbhai Chauhan", 7300),
                   ("2024-03-11", MutationType.CORRECTION, MutationStatus.SANCTIONED, None, None, 145)],
        khasra_numbers=["456"], geometry=_plot(22.3039, 70.8022, 42),
        expect_rules=["CORRECTION_CHANGED_AREA"],
        note="A mutation typed as a clerical correction changed the recorded area.",
    ),
    SeedRecord(
        "Patna/77/3009", "Bihar", "Patna", "Phulwari Sharif", "77", "3009", 4850, "jamabandi",
        18.4, 0.66, "review_queue",
        owners=[("Om Prakash Singh", "Ramashish Singh", "1", 1, 1)],
        sub_divisions=[("3009", 4850, LandClassification.UNIRRIGATED, ["1"])],
        # Pending since 2019 — well past any staleness horizon.
        mutations=[("2019-12-02", MutationType.SALE, MutationStatus.PENDING, "Ramashish Singh", "Om Prakash Singh", 4850)],
        khasra_numbers=["3009"], khatauni_number=None, geometry=_plot(25.5941, 85.1376, 38),
        expect_rules=["MUTATION_PENDING_UNRESOLVED"],
        note="A sale mutation still un-sanctioned years after entry.",
    ),
    SeedRecord(
        "Varanasi/128/640", "Uttar Pradesh", "Varanasi", "Ramnagar", "128", "640", 3120, "jamabandi",
        12.9, 0.69, "review_queue",
        owners=[("Shyam Sundar Tiwari", "Kashi Nath Tiwari", "1", 1, 1)],
        sub_divisions=[("640", 3120, LandClassification.IRRIGATED, ["1"])],
        # A mutation moving more area than the parcel contains.
        mutations=[("2021-07-19", MutationType.SALE, MutationStatus.SANCTIONED,
                    "Kashi Nath Tiwari", "Shyam Sundar Tiwari", 4800)],
        khasra_numbers=["640"], geometry=_plot(25.2677, 83.0180, 31),
        expect_rules=["MUTATION_AREA_EXCEEDS_PARCEL"],
        note="A transfer of more land than the parcel holds.",
    ),

    # -- encumbrance and identifier issues -------------------------------------------
    SeedRecord(
        "Thrissur/72/318", "Kerala", "Thrissur", "Ollur", "72", "318", 2450, "ror_generic",
        5.5, 0.83, "review_queue",
        owners=[("Joseph Mathew", "Mathew Chacko", "1", 1, 1)],
        sub_divisions=[("318", 2450, LandClassification.IRRIGATED, ["1"])],
        mutations=[("2023-03-04", MutationType.MORTGAGE, MutationStatus.SANCTIONED, None, None, None)],
        encumbrances=[(EncumbranceType.BANK_CHARGE, EncumbranceStatus.ACTIVE, "Kerala Gramin Bank", 850000)],
        khasra_numbers=["318"], geometry=_plot(10.5276, 76.2144, 28),
        expect_rules=["ENCUMBRANCE_ACTIVE"],
        note="A live bank charge — consequential for any buyer, informational for the register.",
    ),
    SeedRecord(
        "Raipur/55/2201", "Chhattisgarh", "Raipur", "Abhanpur", None, None, 8900, "khasra_girdawari",
        None, 0.51, "field_verification",
        owners=[("Dinesh Sahu", "Ganesh Sahu", "1", 1, 1)],
        sub_divisions=[("2201", 8900, LandClassification.UNIRRIGATED, ["1"])],
        khasra_numbers=[], geometry=None,
        expect_rules=["IDENTIFIER_MISSING"],
        note="Neither khata nor survey number could be read — the record cannot be located.",
    ),
    SeedRecord(
        "Unknown/-/9981", "Jharkhand", "Ranchi", None, None, "9981", 6100, "khasra_girdawari",
        None, 0.44, "field_verification",
        owners=[("Birsa Munda Trust", None, "1", 1, 1)],
        sub_divisions=[("9981", 6100, LandClassification.FOREST, ["1"])],
        khasra_numbers=["9981"], geometry=None,
        expect_rules=["JURISDICTION_INCOMPLETE"],
        note="No village could be resolved — the parcel cannot be placed on a map.",
    ),

    # -- more volume, so the dashboard and district rollups have something to say -----
    SeedRecord(
        "Hyderabad/410/77", "Telangana", "Rangareddy", "Shamshabad", "410", "77", 22400, "ror_generic",
        2.2, 0.90, "auto_approve",
        owners=[("Syed Abdul Rahman", "Syed Ismail", "1", 1, 1)],
        sub_divisions=[("77/1", 12400, LandClassification.IRRIGATED, ["1"]),
                       ("77/2", 10000, LandClassification.RESIDENTIAL, ["1"])],
        classified_areas=[(LandClassification.IRRIGATED, 12400), (LandClassification.RESIDENTIAL, 10000)],
        mutations=[("2023-09-27", MutationType.SALE, MutationStatus.SANCTIONED, "Syed Ismail", "Syed Abdul Rahman", 22400)],
        khasra_numbers=["77"], geometry=_plot(17.2403, 78.4294, 84),
        note="Peri-urban holding with a residential conversion — clean.",
    ),
    SeedRecord(
        "Amritsar/7/64", "Punjab", "Amritsar", "Ajnala", "7", "64", 16200, "jamabandi",
        3.9, 0.87, "auto_approve",
        owners=[("Balwinder Singh", "Sucha Singh", "1", 3, 4), ("Rajwinder Kaur", "Sucha Singh", "2", 1, 4)],
        sub_divisions=[("64/1", 12150, LandClassification.IRRIGATED, ["1"]),
                       ("64/2", 4050, LandClassification.IRRIGATED, ["2"])],
        classified_areas=[(LandClassification.IRRIGATED, 16200)],
        mutations=[("2020-12-01", MutationType.PARTITION, MutationStatus.SANCTIONED,
                    "Sucha Singh", ["Balwinder Singh", "Rajwinder Kaur"], 12150)],
        khasra_numbers=["64"], geometry=_plot(31.8400, 74.7600, 72),
        note="Unequal but valid 3/4 : 1/4 split.",
    ),
    SeedRecord(
        "Belagavi/12/89", "Karnataka", "Belagavi", "Angol", "12", "89", 4180, "jamabandi",
        7.1, 0.81, "review_queue",
        owners=[("Shantabai Patil", "Ganpati Patil", "1", 1, 3),
                ("Ravi Patil", "Ganpati Patil", "2", 1, 3)],
        sub_divisions=[("89", 4180, LandClassification.UNIRRIGATED, ["1", "2"])],
        mutations=[("2022-08-14", MutationType.INHERITANCE, MutationStatus.SANCTIONED, "Ganpati Patil", "Shantabai Patil", None)],
        khasra_numbers=["89"], geometry=_plot(15.8512, 74.4991, 32),
        expect_rules=["SHARE_SUM_NOT_UNITY"],
        note="Shares total 2/3 — a third of the holding is unaccounted for.",
    ),
    SeedRecord(
        "Cuttack/91/1408", "Odisha", "Cuttack", "Salepur", "91", "1408", 3350, "jamabandi",
        4.6, 0.86, "auto_approve",
        owners=[("Jagannath Behera", "Sarat Behera", "1", 1, 1)],
        sub_divisions=[("1408", 3350, LandClassification.IRRIGATED, ["1"])],
        classified_areas=[(LandClassification.IRRIGATED, 3350)],
        mutations=[("2021-04-06", MutationType.SALE, MutationStatus.SANCTIONED, "Sarat Behera", "Jagannath Behera", 3350)],
        khasra_numbers=["1408"], geometry=_plot(20.5600, 86.0500, 29),
        note="Clean smallholding.",
    ),
    SeedRecord(
        "Mysuru/23/155", "Karnataka", "Mysuru", "Nanjangud", "23", "155", 11700, "jamabandi",
        58.0, 0.55, "field_verification",
        owners=[("Devaraju Gowda", "Mahadevappa", "1", 1, 1)],
        sub_divisions=[("155/1", 6700, LandClassification.IRRIGATED, ["1"]),
                       ("155/2", 5000, LandClassification.UNIRRIGATED, ["1"])],
        mutations=[("2016-05-18", MutationType.SALE, MutationStatus.SANCTIONED, "Mahadevappa", "Devaraju Gowda", 11700)],
        encumbrances=[(EncumbranceType.LIS_PENDENS, EncumbranceStatus.ACTIVE, "Civil Court, Nanjangud", None)],
        khasra_numbers=["155"], geometry=_plot(12.1200, 76.6800, 52),
        expect_rules=["ENCUMBRANCE_ACTIVE"],
        note="Under litigation and badly disagreeing with the cadastral map — the escalation case.",
    ),

    # -- the two holdings the succession demo cases are raised against ---------------
    # Both are internally consistent as *records*: the whole point is that the
    # succession question is invisible to the per-parcel rules and only appears once
    # a second document is put beside them.
    SeedRecord(
        "Belagavi/123/125-2", "Karnataka", "Belagavi", "Angol", "123", "125/2", 50000, "jamabandi",
        3.8, 0.90, "auto_approve",
        owners=[("Ramesh Sharma", "Mohanlal Sharma", "1", 1, 1)],
        sub_divisions=[("125/2", 50000, LandClassification.IRRIGATED, ["1"])],
        classified_areas=[(LandClassification.IRRIGATED, 50000)],
        mutations=[("2011-03-21", MutationType.INHERITANCE, MutationStatus.SANCTIONED,
                    "Mohanlal Sharma", "Ramesh Sharma", 50000)],
        khasra_numbers=["125/2"], geometry=_plot(15.8360, 74.5040, 112),
        note="Ramesh Sharma's holding — the record the flagged succession case starts from.",
    ),
    SeedRecord(
        "Nashik/77/318", "Maharashtra", "Nashik", "Ganeshgaon", "77", "318", 32000, "satbara_7_12",
        2.6, 0.92, "auto_approve",
        owners=[("Vasantrao Deshmukh", "Tukaram Deshmukh", "1", 1, 1)],
        sub_divisions=[("318", 32000, LandClassification.IRRIGATED, ["1"])],
        classified_areas=[(LandClassification.IRRIGATED, 32000)],
        mutations=[("2009-09-14", MutationType.INHERITANCE, MutationStatus.SANCTIONED,
                    "Tukaram Deshmukh", "Vasantrao Deshmukh", 32000)],
        khasra_numbers=["318"], geometry=_plot(20.0100, 73.7600, 89),
        note="Vasantrao Deshmukh's holding — the record the coherent succession case starts from.",
    ),
]


# ---------------------------------------------------------------------------
# Succession demo cases
# ---------------------------------------------------------------------------
# Assembled and assessed through `app.services.succession` — the same code path the
# API uses — so what the console shows is real engine output over synthetic
# documents, exactly as the parcel findings above are. Neither case is a fixture: if
# a succession rule or a risk weight changes, these change with it, and `--verify`
# fails if one stops demonstrating what it was written to demonstrate.


@dataclass
class SuccessionSeed:
    """One succession case, described as the documents a revenue office would hold."""

    label: str
    parcel_key: str
    """The seeded parcel this case is raised against. Its stored extraction supplies
    the *previous* Record of Rights, so the demo exercises the real seam between the
    extraction pipeline and succession validation rather than re-keying the record."""

    documents: list[dict]
    expect_outcome: str
    expect_risk_level: str
    expect_rules: list[str] = field(default_factory=list)
    note: str = ""


def _ror(*, label: str, year: str, khasra: str, khata: str, hectares: float,
         village: str, district: str, state: str, tehsil: str, owners: list[dict]) -> dict:
    return {
        "document_type": "updated_jamabandi",
        "label": label,
        "revenue_year": year,
        "land": {
            "khasra": khasra, "khata": khata, "area": hectares, "area_unit": "hectare",
            "village": village, "tehsil": tehsil, "district": district, "state": state,
        },
        "owners": owners,
    }


SUCCESSION_SEED: list[SuccessionSeed] = [
    SuccessionSeed(
        label="Ramesh Sharma — exclusive transfer to one of three named heirs",
        parcel_key="Belagavi/123/125-2",
        documents=[
            {
                "document_type": "death_certificate",
                "label": "Death certificate — Ramesh Sharma",
                "person": {"name": "Ramesh Sharma"},
                "date_of_death": "12/05/2025",
                "registration_number": "BLG/D/2025/4471",
                "issuing_authority": "Registrar of Births and Deaths, Belagavi",
            },
            {
                "document_type": "legal_heir_certificate",
                "label": "Legal heir certificate",
                "deceased": "Ramesh Sharma",
                "heirs": [
                    {"name": "Sita Sharma", "relation": "wife of"},
                    {"name": "Amit Sharma", "relation": "son of"},
                    {"name": "Priya Sharma", "relation": "daughter of"},
                ],
            },
            {
                "document_type": "mutation",
                "label": "Mutation order MUT/2025/812",
                "number": "MUT/2025/812",
                "type": "virasat",
                "status": "sanctioned",
                "order_date": "02/08/2025",
                "land": {"khasra": "125/2", "khata": "123", "area": 5.0,
                         "area_unit": "hectare", "village": "Angol"},
                "previous_owner": "Ramesh Sharma",
                "new_owners": [{"name": "Amit Sharma", "share": "1/1"}],
            },
            _ror(
                label="Updated Jamabandi (2025-26)", year="2025-26", khasra="125/2", khata="123",
                hectares=5.0, village="Angol", tehsil="Belagavi", district="Belagavi",
                state="Karnataka",
                owners=[{"name": "Amit Sharma", "relation": "son of",
                         "relation_name": "Ramesh Sharma", "share": "1/1"}],
            ),
        ],
        expect_outcome="review_required",
        expect_risk_level="high",
        expect_rules=["SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED"],
        note=(
            "Three heirs are named and the whole parcel is recorded against one of them, "
            "with nothing on file addressing the other two. The system reports that the "
            "evidence is silent and asks for review — it does not conclude anything."
        ),
    ),
    SuccessionSeed(
        label="Vasantrao Deshmukh — succession with a relinquishment on file",
        parcel_key="Nashik/77/318",
        documents=[
            {
                "document_type": "death_certificate",
                "label": "Death certificate — Vasantrao Deshmukh",
                "person": {"name": "Vasantrao Deshmukh"},
                "date_of_death": "03/02/2024",
                "registration_number": "NSK/D/2024/1180",
                "issuing_authority": "Registrar of Births and Deaths, Nashik",
            },
            {
                "document_type": "legal_heir_certificate",
                "label": "Legal heir certificate",
                "deceased": "Vasantrao Deshmukh",
                "heirs": [
                    {"name": "Shalini Deshmukh", "relation": "wife of"},
                    {"name": "Nitin Deshmukh", "relation": "son of"},
                ],
            },
            {
                "document_type": "relinquishment_deed",
                "label": "Relinquishment deed NSK/RD/2024/312",
                "reference": "NSK/RD/2024/312",
                "date": "19/04/2024",
                "land": {"khasra": "318", "khata": "77", "village": "Ganeshgaon"},
                "relinquished_by": ["Shalini Deshmukh"],
                "in_favour_of": [{"name": "Nitin Deshmukh", "share": "1/1"}],
            },
            {
                "document_type": "mutation",
                "label": "Mutation order FER/2024/455",
                "number": "FER/2024/455",
                "type": "varsa",
                "status": "sanctioned",
                "order_date": "28/06/2024",
                "land": {"khasra": "318", "khata": "77", "area": 3.2,
                         "area_unit": "hectare", "village": "Ganeshgaon"},
                "previous_owner": "Vasantrao Deshmukh",
                "new_owners": [{"name": "Nitin Deshmukh", "share": "1/1"}],
            },
            _ror(
                label="Updated 7/12 extract (2024-25)", year="2024-25", khasra="318", khata="77",
                hectares=3.2, village="Ganeshgaon", tehsil="Dindori", district="Nashik",
                state="Maharashtra",
                owners=[{"name": "Nitin Deshmukh", "relation": "son of",
                         "relation_name": "Vasantrao Deshmukh", "share": "1/1"}],
            ),
        ],
        expect_outcome="validated",
        expect_risk_level="low",
        note=(
            "The counter-case. Same shape of transfer, but the other heir's "
            "relinquishment is on file, so every check clears and nothing is flagged. "
            "A system that flagged this one too would be useless in a real district."
        ),
    ),
]


def seed_succession_cases(db, *, verify: bool) -> tuple[int, list[str]]:
    """File the succession demo cases through the service the API itself uses.

    Returns how many were filed and any that stopped producing their intended
    outcome. Runs after the parcels are committed, because each case reads its
    previous Record of Rights out of a seeded parcel row.
    """
    from app.services.succession import assemble_case, assess, persist_case

    problems: list[str] = []
    added = 0

    for seed in SUCCESSION_SEED:
        parcel = (
            db.query(ParcelRecord).filter(ParcelRecord.parcel_key == seed.parcel_key).one_or_none()
        )
        if parcel is None:
            problems.append(f"{seed.label}: parcel {seed.parcel_key} is not in the database")
            continue

        reference = f"SUC/{(parcel.district or 'GEN')[:3].upper()}/2025/{added + 1:04d}"
        if (
            db.query(SuccessionCaseRecord)
            .filter(SuccessionCaseRecord.case_reference == reference)
            .count()
        ):
            print(f"skip (already present): {reference}")
            continue

        assembly = assemble_case(
            db,
            case_id=reference,
            documents=seed.documents,
            parcel_id=parcel.id,
            parcel_key=parcel.parcel_key,
            notes=seed.note,
            submitted_by="operator",
        )
        report = assess(assembly.case)

        fired = sorted({issue.rule_code.value for issue in report.findings})
        missing = [code for code in seed.expect_rules if code not in fired]
        if missing:
            problems.append(f"{seed.label}: expected {missing} but the engine fired {fired}")
        if report.outcome.value != seed.expect_outcome:
            problems.append(
                f"{seed.label}: expected outcome {seed.expect_outcome}, got {report.outcome.value}"
            )
        if report.risk_level.value != seed.expect_risk_level:
            problems.append(
                f"{seed.label}: expected risk {seed.expect_risk_level}, got {report.risk_level.value}"
            )

        persist_case(
            db,
            assembly=assembly,
            report=report,
            case_reference=reference,
            created_by="operator",
            notes=seed.note,
        )
        added += 1

        if verify:
            mark = "!!" if (missing or report.outcome.value != seed.expect_outcome) else "ok"
            print(f"  [{mark}] {reference:<22} {report.outcome.value} / {report.risk_level.value} "
                  f"({report.risk_score}) — {', '.join(fired) or 'no findings'}")
            print(f"       {seed.note}")

    db.commit()
    return added, problems


# ---------------------------------------------------------------------------
# Assembly: seed spec -> real domain record -> real validation findings
# ---------------------------------------------------------------------------


def _build_record(seed: SeedRecord) -> LandParcelRecord:
    """Assemble a genuine ``LandParcelRecord`` from one seed row."""
    owners = [
        OwnerRecord(
            serial_number=serial,
            name=PersonName(
                raw=name,
                relation_type=RelationType.SON_OF if relation else RelationType.UNKNOWN,
                relation_name=relation,
            ),
            tenure_type=TenureType.OWNER,
            share=OwnershipShare(numerator=num, denominator=den) if num is not None and den else None,
        )
        for name, relation, serial, num, den in seed.owners
    ]

    sub_divisions = [
        SubDivision(
            sub_division_number=number,
            area=_M(area),
            classification=classification,
            owner_serial_numbers=list(serials),
        )
        for number, area, classification, serials in seed.sub_divisions
    ]

    classified = [
        ClassifiedArea(classification=classification, area=_M(area))
        for classification, area in seed.classified_areas
    ]

    mutations = [
        MutationEntry(
            entry_date=date.fromisoformat(entry_date),
            mutation_type=mutation_type,
            status=mutation_status,
            from_parties=[PersonName(raw=from_party)] if from_party else [],
            # A transfer can name several transferees (a partition among heirs), and
            # OWNER_WITHOUT_MUTATION_TRAIL checks every current owner against this
            # list -- so a co-owned parcel whose mutation names only one of them is
            # genuinely an incomplete trail, not a modelling shortcut.
            to_parties=[
                PersonName(raw=party)
                for party in (to_party if isinstance(to_party, list) else [to_party])
                if party
            ],
            area_transacted=_M(area) if area is not None else None,
        )
        for entry_date, mutation_type, mutation_status, from_party, to_party, area in seed.mutations
    ]

    encumbrances = [
        Encumbrance(
            encumbrance_type=enc_type,
            status=enc_status,
            holder_name=holder,
            amount=Decimal(str(amount)) if amount is not None else None,
        )
        for enc_type, enc_status, holder, amount in seed.encumbrances
    ]

    return LandParcelRecord(
        record_format=RecordFormat(seed.record_format),
        jurisdiction=Jurisdiction(
            state=seed.state,
            district=seed.district,
            tehsil=_TEHSILS.get(seed.district or ""),
            village=seed.village,
        ),
        khata_number=seed.khata_number,
        khatauni_number=seed.khatauni_number,
        khasra_numbers=list(seed.khasra_numbers),
        survey_number=seed.survey_number,
        total_area=_M(seed.total_area_sq_metre) if seed.total_area_sq_metre is not None else None,
        classified_areas=classified,
        sub_divisions=sub_divisions,
        owners=owners,
        mutations=mutations,
        encumbrances=encumbrances,
        source_page_indices=[0],
    )


_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}


def build_rows(seed: SeedRecord, *, rng: random.Random) -> tuple[Document, ParcelRecord, list[ReviewEvent], list[str]]:
    """Build the ORM rows for one seed entry, and report which rules actually fired."""
    doc_id = uuid.uuid4()
    parcel_id = uuid.uuid4()
    slug = seed.parcel_key.replace("/", "-")

    record = _build_record(seed)
    report = run_all(record, DEFAULT_POLICY, parcel_key=seed.parcel_key)
    issues = [issue.model_dump(mode="json") for issue in report.issues]
    fired = sorted({issue["rule_code"] for issue in issues})
    highest = max(issues, key=lambda i: _SEVERITY_RANK.get(i["severity"], 0), default=None)
    highest_severity = highest["severity"] if highest else None

    artifact_json = {
        **record.model_dump(mode="json"),
        # No `provenance` key: the rendered scan below has no real OCR behind it, so
        # the Document Viewer shows the image but skips per-field highlight boxes --
        # the same honest behaviour as the frontend's own demo fixtures.
        "provenance": {},
        "validation_issues": issues,
    }

    settings = get_settings()
    settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{parcel_id}.jpg"
    (settings.local_storage_dir / image_name).write_bytes(_render_mock_scan(seed))

    document = Document(
        id=doc_id,
        file_name=f"{slug}-seed.pdf",
        sha256=uuid.uuid4().hex + uuid.uuid4().hex[:32],  # unique placeholder, not a real content hash
        media_type="application/pdf",
        byte_size=0,
        page_count=1,
        declared_record_format=seed.record_format,
        declared_state=seed.state,
        source_system="seed_script",
        storage_key=f"seed/{slug}",
        uploaded_by="operator",
    )

    assessment = assess_priority(
        mismatch_score=seed.mismatch_score,
        confidence_score=seed.confidence_score,
        validation_highest_severity=highest_severity,
        validation_issue_count=len(issues),
        recommended_action=seed.recommended_action,
    )

    # Spread ingestion across a trailing month so the analytics time series has a
    # shape rather than a single spike on the day the seed was run.
    created_at = datetime.now(UTC) - timedelta(days=rng.randint(0, 27), hours=rng.randint(0, 23))
    status, assigned_to, decided_by, decided_at, note = _workflow_state(assessment.priority, created_at, rng)

    parcel = ParcelRecord(
        id=parcel_id,
        document_id=doc_id,
        parcel_key=seed.parcel_key,
        state=seed.state,
        district=seed.district,
        village=seed.village,
        khata_number=seed.khata_number,
        survey_number=seed.survey_number,
        total_area_sq_metre=seed.total_area_sq_metre,
        record_format=seed.record_format,
        geometry=seed.geometry,
        mismatch_score=seed.mismatch_score,
        confidence_score=seed.confidence_score,
        recommended_action=seed.recommended_action,
        requires_human_review=highest_severity in {"error", "critical"}
        or (seed.mismatch_score is not None and seed.mismatch_score >= 15),
        artifact_json=artifact_json,
        page_image_urls=[f"/static/uploads/{image_name}"],
        validation_issue_count=len(issues),
        validation_highest_severity=highest_severity,
        priority=assessment.priority.value,
        priority_score=assessment.score,
        review_status=status.value,
        assigned_to=assigned_to,
        assigned_at=created_at + timedelta(hours=6) if assigned_to else None,
        sla_due_at=sla_due_at(assessment.priority, since=created_at),
        decided_by=decided_by,
        decided_at=decided_at,
        decision_note=note,
        created_at=created_at,
        updated_at=decided_at or created_at,
    )

    return document, parcel, _events_for(parcel, rng), fired


def _workflow_state(
    priority: Priority, created_at: datetime, rng: random.Random
) -> tuple[ReviewStatus, str | None, str | None, datetime | None, str | None]:
    """Give each seeded record a plausible position in the workflow.

    Weighted so the corpus shows every state a demo needs to display -- a decided
    backlog, live work in progress, an escalation, and an unclaimed pool -- rather
    than uniformly random states that would leave some views empty.
    """
    roll = rng.random()
    if priority is Priority.LOW and roll < 0.75:
        decided = created_at + timedelta(hours=rng.randint(2, 40))
        return ReviewStatus.APPROVED, "tehsildar", "tehsildar", decided, "Consistent on all checks; entered into the register."
    if roll < 0.18:
        decided = created_at + timedelta(hours=rng.randint(6, 90))
        return ReviewStatus.APPROVED, "tehsildar", "tehsildar", decided, "Verified against the village register."
    if roll < 0.28:
        decided = created_at + timedelta(hours=rng.randint(6, 90))
        return ReviewStatus.REJECTED, "tehsildar", "tehsildar", decided, "Scan illegible in the ownership column — re-scan requested."
    if roll < 0.40:
        return ReviewStatus.ESCALATED, "tehsildar", None, None, None
    if roll < 0.62:
        return ReviewStatus.IN_REVIEW, "tehsildar", None, None, None
    return ReviewStatus.PENDING, None, None, None, None


def _events_for(parcel: ParcelRecord, rng: random.Random) -> list[ReviewEvent]:
    """An audit trail consistent with the state the record ended up in.

    Written so the audit page, the reviewer-throughput chart and the per-record
    timeline all have real rows to display. Every event a decided record shows is
    one that must have happened for it to be in that state -- an audit trail with
    invented entries would undermine the exact property it exists to demonstrate.
    """
    events: list[ReviewEvent] = []
    base = parcel.created_at

    def _add(action: ReviewAction, *, at: datetime, reviewer: str, role: str, **kwargs) -> None:
        events.append(
            ReviewEvent(
                id=uuid.uuid4(),
                parcel_id=parcel.id,
                action=action.value,
                reviewer=reviewer,
                reviewer_role=role,
                created_at=at,
                field_path=kwargs.pop("field_path", "$"),
                previous_value={"value": kwargs.pop("previous", None)},
                new_value={"value": kwargs.pop("new", None)},
                note=kwargs.pop("note", None),
                source_ip="10.12.4.%d" % rng.randint(2, 250),
            )
        )

    if parcel.assigned_to:
        _add(
            ReviewAction.ASSIGNED,
            at=base + timedelta(hours=6),
            reviewer="collector",
            role="admin",
            new=parcel.assigned_to,
            note="Routed by district triage.",
        )

    # A correction on roughly a third of the flagged records, keyed by the operator.
    if parcel.validation_issue_count and rng.random() < 0.35:
        _add(
            ReviewAction.CORRECTED,
            at=base + timedelta(hours=rng.randint(8, 30)),
            reviewer="operator",
            role="operator",
            field_path="owners[0].name.raw",
            previous=(parcel.artifact_json.get("owners") or [{}])[0].get("name", {}).get("raw"),
            new=(parcel.artifact_json.get("owners") or [{}])[0].get("name", {}).get("raw"),
            note="Spelling verified against the scan; no change required.",
        )
        parcel.correction_count = 1
        parcel.has_human_corrections = True

    if parcel.review_status in {ReviewStatus.IN_REVIEW.value, ReviewStatus.ESCALATED.value}:
        _add(
            ReviewAction.STATUS_CHANGED,
            at=base + timedelta(hours=rng.randint(10, 48)),
            reviewer="tehsildar",
            role="reviewer",
            previous="pending",
            new=parcel.review_status,
            note="Escalated: contradiction cannot be resolved from the document alone."
            if parcel.review_status == ReviewStatus.ESCALATED.value
            else None,
        )

    if parcel.decided_at:
        _add(
            ReviewAction.STATUS_CHANGED,
            at=parcel.decided_at,
            reviewer=parcel.decided_by or "tehsildar",
            role="reviewer",
            previous="in_review",
            new=parcel.review_status,
            note=parcel.decision_note,
        )

    return events


# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete all existing documents/parcels first")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="assert every record's `expect_rules` actually fired, and print what did",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    rng = random.Random(_RNG_SEED)
    db = SessionLocal()
    try:
        if args.reset:
            # Children first: succession cases reference parcels, and ownership
            # events reference cases.
            db.query(OwnershipEventRecord).delete()
            db.query(SuccessionCaseRecord).delete()
            db.query(ReviewEvent).delete()
            db.query(ParcelRecord).delete()
            db.query(Document).delete()
            db.commit()
            print("Cleared existing documents, parcels, review events and succession cases.")

        existing_keys = {row[0] for row in db.query(ParcelRecord.parcel_key).all()}
        added = 0
        problems: list[str] = []

        for seed in SEED:
            if seed.parcel_key in existing_keys:
                print(f"skip (already present): {seed.parcel_key}")
                continue

            document, parcel, events, fired = build_rows(seed, rng=rng)
            missing = [code for code in seed.expect_rules if code not in fired]
            if missing:
                problems.append(f"{seed.parcel_key}: expected {missing} but the engine fired {fired}")

            if args.verify:
                mark = "!!" if missing else "ok"
                print(f"  [{mark}] {seed.parcel_key:<24} {', '.join(fired) or '(no findings)'}")
                if seed.note:
                    print(f"       {seed.note}")

            db.add(document)
            db.add(parcel)
            for event in events:
                db.add(event)
            added += 1

        db.commit()
        print(f"\nSeeded {added} new parcel(s). Total in DB: {db.query(ParcelRecord).count()}")
        print(f"Audit events in DB: {db.query(ReviewEvent).count()}")

        # After the commit above: each succession case reads its previous Record of
        # Rights out of a seeded parcel row, so the parcels have to be durable first.
        if args.verify:
            print("\nSuccession cases:")
        cases_added, case_problems = seed_succession_cases(db, verify=args.verify)
        problems.extend(case_problems)
        print(f"Seeded {cases_added} succession case(s). "
              f"Total in DB: {db.query(SuccessionCaseRecord).count()} "
              f"({db.query(OwnershipEventRecord).count()} ownership events)")

        if problems:
            # A seed record that stopped demonstrating its defect is a regression in
            # the rule engine, not a cosmetic issue -- so it fails the run loudly.
            print("\nSeed records that no longer produce their intended finding:")
            for problem in problems:
                print(f"  - {problem}")
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
