# adhikar — the ai-engine

OCR + Vision-LLM extraction, deterministic normalization, arithmetic validation, and
geospatial discrepancy scoring for Jamabandi and 7/12 Extract land records.

## Install

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

Credentials for the Vision LLM resolve through the standard Anthropic SDK chain
(`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or `ant auth login`) — nothing in this
package reads or logs a key directly.

## Run the tests

```bash
pytest            # 65 tests; no network access or API credentials required
pytest --cov=adhikar
```

## Use it

```python
from pathlib import Path
from adhikar.pipeline import process_document
from adhikar.schemas.enums import RecordFormat

artifact = process_document(
    Path("scan.pdf"),
    declared_format=RecordFormat.SATBARA,
)

print(artifact.detected_record_format)
print(artifact.requires_human_review)
for issue in artifact.validation.sorted_issues():
    print(issue.severity, issue.rule_code, issue.message)
```

Or from the CLI:

```bash
adhikar extract scan.pdf --format satbara_7_12 --geometry village_cadastre.geojson -o artifact.json
adhikar list-rules
```

## The extraction schema

The Vision LLM is never asked to classify or compute — only to transcribe (see
`adhikar/llm/prompts.py`). It fills `adhikar.schemas.llm_contract.LlmExtraction`
(delivered via Anthropic's **strict tool use**, so the response is schema-valid by
construction), which `adhikar.llm.mapper` then normalizes and classifies
deterministically into `adhikar.schemas.land_record.LandParcelRecord`:

| Requested field | Where it lives |
|---|---|
| Khata / Khasra / Survey number | `LandParcelRecord.khata_number`, `.khasra_numbers`, `.survey_number`, `.sub_survey_number` |
| Total area (Ha/Are/Sq.M, and every other Indian unit) | `LandParcelRecord.total_area: AreaMeasurement` |
| Land classification (cultivable vs. non-cultivable) | `LandParcelRecord.classified_areas: list[ClassifiedArea]`, each exposing `.cultivability` |
| Ownership / occupant details | `LandParcelRecord.owners: list[OwnerRecord]` (name, tenure, exact rational share) |
| Mutation / encumbrance remarks | `LandParcelRecord.mutations`, `.encumbrances` |

### Units (`adhikar.schemas.units`)

Every area canonicalizes to square metres as `Decimal` — never `float` — because a
0.5 sq m arithmetic mismatch is a real finding, not rounding noise. Conversion
factors are exact rationals derived from the international yard (0.9144 m):

| Unit | Sq. metres |
|---|---|
| 1 hectare | 10,000 |
| 1 are | 100 |
| 1 acre | 4046.8564224 |
| 1 guntha (1/40 acre) | 101.17141056 |
| 1 kanal (1/8 acre) | 505.8570528 |
| 1 marla (1/20 kanal) | 25.29285264 |
| 1 bigha | **region-dependent** — see below |

**Bigha is a family of units, not one unit** — it ranges from ~843 sq m (UP kachcha)
to ~2529 sq m (Bihar), a 3× spread. `AreaMeasurement.from_bigha(...)` requires an
explicit `region_key` and raises `AmbiguousUnitError` otherwise; there is no default
fallback, because a wrong guess is worse than a visible failure. Known regions are in
`BIGHA_REGISTRY` (`up_pucca`, `up_kachcha`, `rajasthan_pucca`, `rajasthan_kachcha`,
`gujarat`, `west_bengal`, `assam`, `bihar`, `punjab_haryana`, `himachal`,
`madhya_pradesh`, `uttarakhand`).

### Vernacular vocabulary resolution

Terms like `चाही`, `Gair Mumkin`, `भोगवटादार वर्ग-1` resolve to controlled enum values
via `adhikar.normalize.vocab` in three tiers: exact match, normalized-exact match
(NFKC + digit/punctuation folding), then fuzzy match (Jaro-Winkler ≥ 0.86) to absorb
single-character OCR slips on long conjuncts. **A term that doesn't resolve becomes
`UNKNOWN` plus an `UNRESOLVED_VOCABULARY`-class finding — never a guessed neighbor.**

## Validation rules (`adhikar.validation`)

Data-driven: every check is a `@rule`-decorated function discovered from a registry,
parameterized by `policies/validation_policy.yaml`. A rule that raises becomes one
`CRITICAL` finding naming the rule — it never silently cancels the rest of the report.

| Rule code | What it checks |
|---|---|
| `AREA_SUM_MISMATCH` | Sum of sub-division areas does not equal the printed total area. |
| `AREA_SUM_EXCEEDS_TOTAL` | Sub-divisions total more than their parent (always an error). |
| `CLASSIFICATION_SPLIT_MISMATCH` | Sum of classified areas does not equal the printed total area. |
| `AREA_COMPONENT_OUT_OF_RANGE` | A printed H-R-Sq.M component exceeds its natural range. |
| `TOTAL_AREA_MISSING` / `TOTAL_AREA_NON_POSITIVE` | No usable total area could be extracted. |
| `ASSESSMENT_DISPROPORTIONATE` | A sub-division's revenue-per-area is a statistical (z-score) outlier among its siblings. |
| `SHARE_SUM_NOT_UNITY` / `SHARE_SUM_EXCEEDS_UNITY` | Recorded ownership shares don't sum to exactly 1. |
| `SHARE_MISSING` | Multiple owners recorded with no shares at all. |
| `NO_OWNERS_RECORDED` | No owner rows extracted. |
| `DUPLICATE_OWNER_SERIAL` / `ORPHAN_OWNER_REFERENCE` | Owner-serial cross-references are inconsistent. |
| `MUTATION_OUT_OF_SEQUENCE` / `MUTATION_DATE_IN_FUTURE` | Mutation chain dates are implausible. |
| `MUTATION_PENDING_UNRESOLVED` | A pending mutation older than the policy's staleness horizon (default 180 days). |
| `MUTATION_AREA_EXCEEDS_PARCEL` | A mutation transacts more area than the parcel has. |
| `CORRECTION_CHANGED_AREA` | A "clerical correction" mutation that nonetheless moves area. |
| `OWNER_WITHOUT_MUTATION_TRAIL` | A current owner with no sanctioned mutation naming them. |
| `ENCUMBRANCE_ACTIVE` / `ENCUMBRANCE_STATUS_UNKNOWN` | Live charges, and charges whose status couldn't be read. |
| `IDENTIFIER_MISSING` / `DUPLICATE_KHASRA_NUMBER` / `JURISDICTION_INCOMPLETE` | Identification and geolocation completeness. |

Run `adhikar list-rules` for the live registry (source of truth over this table).

## The discrepancy engine (`adhikar.geo`)

Cross-references the extracted textual area against a matched cadastral polygon
(GeoJSON `Polygon`/`MultiPolygon`) and produces a `DiscrepancyReport`:

- **Geodesic area**, always — `pyproj`'s `Geod.geometry_area_perimeter` on WGS84, never
  a planar estimate on raw lon/lat degrees (which is wrong by ~6% at 20°N, larger than
  every tolerance this engine uses).
- **Mismatch score (0–100, lower is better)** — the relative area difference rescaled
  against a configurable "severe" threshold (default 10%), escalated by any material
  topology defect (parcel overlap, boundary gap) detected against neighbouring
  polygons.
- **Confidence score (0–1, higher is better)** — a weighted mean of OCR legibility,
  LLM extraction certainty, arithmetic integrity, and geometric agreement, with two
  hard caps: no matched geometry caps confidence at 0.55 (so an unverified record
  never reaches the auto-approve threshold), and any single weak component caps the
  whole composite at its own value (a strong average can never launder one badly
  broken input).
- **Recommended action** — `auto_approve` / `review_queue` / `field_verification` /
  `reject_re_scan`, chosen conservatively: auto-approval requires both high
  confidence *and* a near-exact area match.

```python
from adhikar.geo.discrepancy import build_parcel_geometry, compute_discrepancy, ConfidenceInputs
from adhikar.schemas.geo import GeometrySource

geometry = build_parcel_geometry(
    "village/45/142", geojson_polygon, source=GeometrySource.CADASTRAL_SHAPEFILE
)
report = compute_discrepancy(
    "village/45/142",
    textual_area_sq_metre=parcel.total_area.sq_metre,
    geometry=geometry,
    confidence_inputs=ConfidenceInputs(ocr=0.91, llm_extraction=0.88, structural_integrity=0.95),
)
print(report.headline)
# "village/45/142: mismatch 2.3/100 (within_survey_tolerance), confidence 0.91 -> auto_approve"
```

## Package layout

```
src/adhikar/
├── schemas/        Pydantic domain model, LLM wire contract, validation & geo contracts
├── preprocessing/  PDF/image loading, deskew/denoise/threshold
├── ocr/            EasyOCR + Tesseract adapters, IoU-based ensemble reconciliation
├── layout/         Ruled-line table-grid detection
├── llm/            Strict-tool-use Vision LLM extraction + prompt + wire-to-domain mapper
├── normalize/      Numerals, area parsing, vernacular vocabulary, shares, dates
├── validation/     Rule registry + 22 rules + YAML policy loader
├── geo/            Geodesic area, topology, discrepancy scoring
├── pipeline.py     Orchestrates every stage into one ExtractionArtifact
├── cli.py          `adhikar extract` / `adhikar list-rules`
└── config.py       Settings (env-driven), exceptions.py, __init__.py
```
