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

## Vision LLM provider

Two interchangeable backends, selected by `ADHIKAR_LLM_PROVIDER` (default `groq`):

| Provider | `ADHIKAR_LLM_PROVIDER` | Credential | Structured output |
|---|---|---|---|
| **Groq** (default) | `groq` | `GROQ_API_KEY` — free, no billing setup: https://console.groq.com/keys | JSON mode + schema-in-prompt + validate-and-repair (up to `ADHIKAR_GROQ_MAX_JSON_REPAIR_ATTEMPTS` retries on a parse/validation failure) |
| **Anthropic** | `anthropic` | `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `ant auth login` | Strict tool use — schema-valid by construction, plus prompt caching |

Groq is the default so the pipeline runs end-to-end on a free key; switch to
Anthropic (`ADHIKAR_LLM_PROVIDER=anthropic` in `.env`) for materially stronger
accuracy on dense multilingual tables once a paid key is available. Neither
credential is ever read, logged, or held by `adhikar` itself — each SDK resolves its
own key from the environment. See `.env.example` for every knob.

## Run the tests

```bash
pytest            # 163 tests (75 of them ownership succession); no network access or API credentials required
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

## Ownership succession & mutation validation (`adhikar.validation.succession`)

A second, cross-document registry, added alongside the 22 rules above rather than
folded into them — these checks compare a *bundle* of documents (an old Record of
Rights, a death certificate, family/heir information, a mutation, an updated Record
of Rights, and any will/relinquishment/partition/settlement/court order) against each
other, which the single-parcel `RuleFunction` signature has no room for. Findings
still come out as ordinary `ValidationIssue`s under codes in the same `RuleCode`
catalogue, scored against the same policy YAML, so the rest of the engine — and
every consumer of it — never needs to know this registry exists separately.

**What it will never conclude.** No rule here decides who inherits, applies
succession law, or reports fraud. There is no `FRAUD` status in
`SuccessionOutcome`, and the strongest finding
(`SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED`) is phrased as a statement about
evidence — *the documents do not establish this* — never as an accusation.

| Rule (code) | Question | Statuses it can return |
|---|---|---|
| S1 `OWNER_IDENTITY_MATCH` (`SUCCESSION_OWNER_IDENTITY_MISMATCH`) | Does the death certificate name the previous recorded owner? | pass / fail / review_required |
| S2 `TRANSITION_AFTER_DEATH` (`SUCCESSION_EVENT_SEQUENCE_INVALID`) | Did the ownership-changing event follow the death? | pass / fail / review_required / warning (`..._RECORD_NOT_UPDATED_AFTER_DEATH`) |
| S3 `PARCEL_MATCH` (`SUCCESSION_PARCEL_MISMATCH`) | Do the old and new records describe the same parcel? | pass / warning (hissa-level ambiguity) / fail / review_required (no shared identifier) |
| S4 `MUTATION_PREDECESSOR_MATCH` (`SUCCESSION_MUTATION_PREDECESSOR_MISMATCH`) | Does the mutation name the previous recorded owner as transferor? | pass / fail / warning |
| S5 `MUTATION_PARCEL_MATCH` (`SUCCESSION_MUTATION_PARCEL_MISMATCH`) | Does the mutation describe the same parcel? | pass / warning / fail |
| S6 `SHARE_AND_AREA_CONSISTENCY` (`SUCCESSION_SHARE_SUM_INCONSISTENT`, `SUCCESSION_AREA_MISMATCH`) | Do shares resolve to unity, and does the area survive the transfer? | pass / warning / fail |
| S7 `HEIRS_IDENTIFIED` (`SUCCESSION_HEIRS_NOT_IDENTIFIED`) | Does anything on file name the deceased's family? | pass / warning |
| S8 `SUCCESSION_EVIDENCE` (`SUCCESSION_EVIDENCE_MISSING`) | Does any submitted document account for the change at all? | pass / warning / review_required |
| S9 `EXCLUSIVE_TRANSFER_EVIDENCE` (`SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED`) | When several heirs are named and the parcel vests in fewer, does a submitted document address it? | pass / warning / review_required |
| S10 `TRANSITION_CHAIN_COMPLETE` (`SUCCESSION_UNEXPLAINED_TRANSITION`) | Does every ownership change across every submitted record have a recorded event behind it? | pass / review_required |
| `DEATH_RECORD_PRESENT` / `MUTATION_RECORD_PRESENT` | Are the documents a succession claim implies actually present? | pass / warning |
| `DOCUMENT_CONSISTENCY` (`SUCCESSION_DOCUMENTS_CONTRADICT`) | Do submitted documents agree with each other (dates, transferees)? | pass / fail |
| `DOCUMENT_LEGIBILITY` / `NAME_MATCH_QUALITY` | Was everything readable, and how exact were the name links it rests on? | pass / warning |

Run `adhikar.validation.registered_succession_rules()` (merged into
`GET /api/v1/system/rules` by the backend) for the live registry.

**Risk scoring** is a plain, itemised sum — never a black box. Each non-clear check
contributes `risk_points(rule_code) × status_multiplier` (fail=1.0, review_required=
0.85, warning=0.45), capped at 100; `risk_points` defaults are in
`adhikar.validation.succession.DEFAULT_RISK_POINTS` and are overridable per rule from
`policies/validation_policy.yaml` (`risk_points:` under any `SUCCESSION_*` code) —
the same mechanism the area/share tolerances already use. Bands: LOW < 15 ≤ MEDIUM <
40 ≤ HIGH < 70 ≤ CRITICAL. `SuccessionReport.risk_contributions` lists every term, so
`risk_score` always decomposes to numbers a reviewer can check.

```python
from adhikar.succession import normalize_case
from adhikar.validation import validate_succession

case, warnings = normalize_case({
    "documents": [
        {"document_type": "jamabandi", "revenue_year": "2019-20",
         "land": {"khasra": "125/2", "khata": "123", "area": 5.0, "area_unit": "hectare"},
         "owners": [{"name": "Ramesh Sharma", "share": "1/1"}]},
        {"document_type": "death_certificate",
         "person": {"name": "Ramesh Sharma"}, "date_of_death": "12/05/2025"},
        {"document_type": "legal_heir_certificate", "deceased": "Ramesh Sharma",
         "heirs": [{"name": "Sita Sharma", "relation": "wife of"},
                   {"name": "Amit Sharma", "relation": "son of"},
                   {"name": "Priya Sharma", "relation": "daughter of"}]},
        {"document_type": "mutation", "status": "sanctioned", "order_date": "02/08/2025",
         "previous_owner": "Ramesh Sharma",
         "new_owners": [{"name": "Amit Sharma", "share": "1/1"}]},
        {"document_type": "updated_jamabandi", "revenue_year": "2025-26",
         "land": {"khasra": "125/2", "khata": "123", "area": 5.0, "area_unit": "hectare"},
         "owners": [{"name": "Amit Sharma", "share": "1/1"}]},
    ]
})
report = validate_succession(case)
print(report.outcome, report.risk_level, report.risk_score)
# review_required high 62.5
print(report.summary_sentence())
```

`case, warnings = normalize_case(...)` is the deterministic path from a raw,
string-valued document payload (dates as printed, shares as printed, areas with an
explicit unit) to a validated `SuccessionCase` — every value goes through the same
normalisers (`parse_record_date`, `parse_share`, the `AreaMeasurement` unit
machinery) the extraction pipeline's own mapping stage uses, and anything that will
not normalise is reported in `warnings` rather than guessed. When a Record of Rights
already went through `process_document`, use `adhikar.succession.snapshot_from_record`
instead — no second extraction pass, no parallel schema.

Name matching (`adhikar.normalize.names`) is deliberately stricter than the
vernacular-vocabulary matcher: it scores a multi-token name on its *worst*-matching
token, not the average, because Indian family names are shared across a household —
scoring on the mean would let a matching surname carry a mismatched given name over
the threshold and link a death certificate to the wrong member of the same family.
Parcel identifiers (`adhikar.normalize.identifiers`) fold separators and leading
zeros (`"0125/2"` = `"125 - 2"` = `"125/2"`) but never collapse a hissa into its
parent survey number — `125` and `125/2` compare as *related*, not equal, and the
rule surfaces that as a warning rather than deciding which the case means.

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
├── llm/            Groq / Anthropic Vision LLM extraction (provider factory) + prompt + wire-to-domain mapper
├── normalize/      Numerals, area parsing, vernacular vocabulary, shares, dates,
│                   name matching (names.py) and parcel-identifier folding (identifiers.py)
├── validation/     Rule registry + 22 rules + succession.py (14 cross-document
│                   ownership-succession checks) + YAML policy loader
├── succession/     Builds a SuccessionCase from a pipeline record, a raw document
│                   payload, or an OCR text layer (death/legal-heir certificates)
├── geo/            Geodesic area, topology, discrepancy scoring
├── pipeline.py     Orchestrates every stage into one ExtractionArtifact
├── cli.py          `adhikar extract` / `adhikar list-rules`
└── config.py       Settings (env-driven), exceptions.py, __init__.py
```
