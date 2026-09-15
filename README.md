# Adhikar — Intelligent Land Record Digitization and Validation System

Built for **SIH26018** (Ministry of Rural Development). Scanned Jamabandi and 7/12
Extract pages are read by an OCR + Vision-LLM pipeline, checked against 22 consistency
rules and the cadastral map, then queued for a revenue officer **worst-first**. Every
correction is applied to the record *and* written to an audit trail that cannot be
edited in place.

A second, cross-document engine (**Ownership Succession & Mutation Validation** — see
[below](#ownership-succession--mutation-validation)) checks whether a recorded
ownership transition — an owner's death followed by a mutation — is actually
*supported by the documents on file*, without ever deciding who legally inherits.

The point of the system is the second half of that sentence. Extraction is table
stakes; what a revenue department actually needs is a defensible answer to *"who
changed this figure, when, and what did it say before?"* — for every field of every
record, years later.

---

## Quick start (two commands, no Docker)

```bash
# 1. API — SQLite, four demo accounts provisioned on first boot
cd backend
pip install -r requirements.txt          # installs ai-engine too, via -e ../ai-engine
python scripts/seed_demo_data.py --reset # 26 records + 2 succession cases, real engine findings
uvicorn app.main:app --reload            # http://localhost:8000/docs

# 2. Console
cd frontend
npm install
npm run dev                              # http://localhost:3000
```

Sign in with any of the four evaluation accounts (listed on the login screen):

| Username | Role | Can |
|---|---|---|
| `collector` | District Administrator | Everything, plus user management |
| `tehsildar` | Revenue Inspector | Approve, reject, escalate, assign |
| `operator` | Data Entry Operator | Upload and correct — **cannot approve** |
| `auditor` | Auditor | Read everything, change nothing |

Password for all four: `adhikar@2026`. They exist only because
`ADHIKAR_API_SEED_DEMO_USERS` defaults to true; set it to `false` for anything real.

**Nothing else is required to run this.** The database defaults to a bundled SQLite
file, and if you *do* point it at Postgres and Postgres is down, the API falls back to
SQLite and says so loudly at `/health` and in the console's status pill — because a
demo machine without Docker should still boot a working system, and a silent
substitution would be worse than a crash.

---

## What is actually here

### The review workflow (the part that makes it a system, not a viewer)

```
   upload ──▶ extract ──▶ validate ──▶ triage ──▶ QUEUE ──▶ decision ──▶ register
                                          │                    │
                                          │                    ├── approved
                    priority + SLA clock ─┘                    ├── rejected (re-scan)
                                                               └── escalated
```

* **Corrections are applied and re-validated.** A reviewer who fixes a mis-read
  sub-division area sees `AREA_SUM_MISMATCH` clear in the same response — because the
  API writes the value into `artifact_json` and then re-runs the entire rule engine
  against the corrected record. Letting a human edit a field *without* re-checking the
  arithmetic would be worse than not letting them edit at all: the stale green tick
  would carry the reviewer's authority.
* **Separation of duties is enforced, not described.** An operator may key corrections
  all day and still cannot put a record into the register. Sign in as `operator` and
  the Approve button is gone; call the endpoint directly and it answers 403.
* **The queue explains itself.** Records are ordered by a triage score computed from
  the pipeline's own outputs (`backend/app/services/triage.py`) — a small, pure,
  explainable function, not a learned ranker, so a Tehsildar asked why a record is at
  the top of their list is owed a sentence and gets one.
* **The audit trail is append-only and readable by the auditor role.** An audit trail
  only the people being audited can read is not one.

### The console

| Route | What it is for |
|---|---|
| `/` | Command dashboard — throughput, adjudication mix, backlog shape, what to look at next |
| `/queue` | The prioritised worklist, with scope tabs (my work / unclaimed pool / my district / all) |
| `/records` | Full grid: filter, sort, page, bulk-approve, export. Filters live in the URL, so a filtered view is a link |
| `/parcels/[id]` | Split-screen: source scan beside every extracted field, with workflow controls, findings and the record's own timeline |
| `/map` | Every matched cadastral polygon on one map, colourable by mismatch / status / priority |
| `/analytics` | District comparison and the rule-frequency report |
| `/audit` | Department-wide trail of every human action |
| `/succession` | Ownership-succession cases, worst-risk first — see [below](#ownership-succession--mutation-validation) |
| `/rules` | What each of the 22 + 14 checks does, and the tolerance it was judged against |
| `/upload` | Single or batch ingestion with per-file outcomes |
| `/admin` | Accounts, the permission matrix, and deployment status |

Ctrl/Cmd-K jumps to any page or straight to a parcel by village, khata or survey
number. Light, dark and follow-the-system themes.

---

## Ownership Succession & Mutation Validation

**The problem.** A parcel is recorded in the name of a family head. He dies. A
mutation later shows the whole parcel transferred to one of his children. Is that
transition *supported by the documents on file* — or did the office just extend a
green tick to a record nobody actually checked?

**What the system does about it — and does not.** This is a document-validation and
decision-support engine, not a legal judge. It never decides who inherits, never
applies succession law, and never concludes that a transfer was improper — there is
no `FRAUD` status anywhere in it, on purpose. What it does is compare documents:
does the death certificate name the recorded owner; do the old and new records
describe the same parcel; does the area survive the transfer; are the deceased's
heirs named anywhere in the file; and — the case this feature exists to catch — when
several heirs are named and the whole parcel goes to one of them, does *any*
submitted document (a will, a relinquishment, a partition, a family settlement, a
court order) actually address that. If nothing does, the system says exactly that —
and asks for human review — rather than guessing.

### The reference case

```
Old Jamabandi:  Ramesh Sharma, Khasra 125/2, 5.00 ha
Death:          Ramesh Sharma, 12/05/2025
Family:         Sita Sharma (wife), Amit Sharma (son), Priya Sharma (daughter)
Mutation:       Amit Sharma — 100%
```

```
Ownership transition detected. Previous owner Ramesh Sharma is recorded as
deceased. 3 potential heirs are identified. The current record vests the parcel
in Amit Sharma (1/1). Supporting evidence for the transfer as recorded was not
established from the submitted documents. Human / revenue-authority review is
required.
```

`outcome: review_required`, `risk_level: high` (46.75/100) — not `validated`,
and nowhere does it say Amit is or is not the rightful owner. Add a relinquishment
deed by which Sita and Priya give up their claim, and the same bundle comes back
`validated`, `risk_level: low` (0) — the counter-case a real district needs just as
much as the flagged one. Both are seeded and demonstrable (see Quick start above);
`ai-engine/README.md` has the ten checks (S1–S10) and the risk-scoring formula in full.

### Architecture: one engine, extended, not duplicated

Ownership succession is not a bolt-on service — it runs through the same three
packages, the same registration pattern, and the same policy file as the 22
single-record rules:

| Layer | What was added |
|---|---|
| `ai-engine/adhikar.schemas.succession` | The cross-document domain model — `SuccessionCase`, `RecordSnapshot`, `DeathRecord`, `HeirCandidate`, `MutationRecord`, `SupportingDocument` — and the `SuccessionReport` it produces |
| `ai-engine/adhikar.validation.succession` | 14 registered checks (S1–S10 plus four completeness/consistency checks), the same `@rule`-style registry pattern as `validation/rules.py`, scored against the *same* `ValidationPolicy` YAML |
| `ai-engine/adhikar.normalize.names` / `.identifiers` | Name matching tolerant of honorifics, OCR slips and word order (worst-token-wins, so a shared surname can never carry a mismatched given name over the line) — and parcel-identifier folding (`"0125/2"` = `"125/2"`) |
| `ai-engine/adhikar.succession` | Turns a pipeline-extracted `LandParcelRecord` *or* a raw document payload into a `SuccessionCase`, through the same deterministic normalisers (`parse_record_date`, `parse_share`, the area-unit machinery) the extraction pipeline already uses |
| `backend/app.models.succession` | `succession_cases` (the filed assessment) and `ownership_events` (the derived, queryable event chain) — two additive tables, [Alembic `0003`](backend/alembic/versions/0003_succession_cases.py) |
| `backend/app.services.succession` | Assembles a case (reusing a parcel's own extraction as the *previous* Record of Rights when one is on file), runs the engine, projects the result into queryable columns |
| `backend/app.api.v1.routers.succession` | `POST /succession/validate`, the case list/detail/explain endpoints, `GET /succession/history` (a parcel's ownership events across every case) — see the API example below |
| `frontend/components/succession/*` | The ownership timeline (previous owner → death → potential heirs → mutation → current owner), the per-check evidence list, and the risk-score breakdown; a compact panel on the existing parcel page, plus its own `/succession` queue |

The existing 22 rules, the review workflow, the audit trail and every current
endpoint are unchanged — this is four new files inside `ai-engine/adhikar/`, one new
service + router + two tables in the backend, and a components folder + two routes in
the frontend, all additive.

### Example: `POST /api/v1/succession/validate`

```json
{
  "case_reference": "SUC/BLG/2025/0041",
  "documents": [
    { "document_type": "jamabandi", "revenue_year": "2019-20",
      "land": { "khasra": "125/2", "khata": "123", "area": 5.0, "area_unit": "hectare", "village": "Angol" },
      "owners": [{ "name": "Ramesh Sharma", "share": "1/1" }] },
    { "document_type": "death_certificate",
      "person": { "name": "Ramesh Sharma" }, "date_of_death": "12/05/2025" },
    { "document_type": "legal_heir_certificate", "deceased": "Ramesh Sharma",
      "heirs": [{ "name": "Sita Sharma", "relation": "wife of" },
                { "name": "Amit Sharma", "relation": "son of" },
                { "name": "Priya Sharma", "relation": "daughter of" }] },
    { "document_type": "mutation", "status": "sanctioned", "order_date": "02/08/2025",
      "previous_owner": "Ramesh Sharma",
      "new_owners": [{ "name": "Amit Sharma", "share": "1/1" }] },
    { "document_type": "updated_jamabandi", "revenue_year": "2025-26",
      "land": { "khasra": "125/2", "khata": "123", "area": 5.0, "area_unit": "hectare", "village": "Angol" },
      "owners": [{ "name": "Amit Sharma", "relation": "son of", "relation_name": "Ramesh Sharma", "share": "1/1" }] }
  ]
}
```

returns (trimmed):

```json
{
  "persisted": true,
  "report": {
    "outcome": "review_required",
    "risk_level": "high",
    "risk_score": 46.75,
    "event_type": "owner_death_succession",
    "recommended_action": "human_review",
    "death_verified": true,
    "potential_heirs": [
      { "name": "Sita Sharma", "relation": "wife_of" },
      { "name": "Amit Sharma", "relation": "son_of" },
      { "name": "Priya Sharma", "relation": "daughter_of" }
    ],
    "checks": [
      { "rule": "OWNER_IDENTITY_MATCH", "status": "pass",
        "explanation": "The death certificate names Ramesh Sharma, who the previous record recorded as owner." },
      { "rule": "PARCEL_MATCH", "status": "pass",
        "explanation": "Old Jamabandi (2019-20) and Updated Jamabandi (2025-26) agree on khasra_number (125/2), khata_number (123)." },
      { "rule": "EXCLUSIVE_TRANSFER_EVIDENCE", "status": "review_required",
        "explanation": "3 potential heirs are identified ... and the current record transfers the parcel to Amit Sharma (1/1). No submitted document ... explains the absence of Sita Sharma, Priya Sharma." }
    ],
    "disclaimer": "This is a documentary-consistency assessment, not a determination of legal entitlement. The system does not decide who inherits ..."
  },
  "case": { "id": "…", "case_reference": "SUC/BLG/2025/0041", "outcome": "review_required" }
}
```

Set `"persist": false` to assess a bundle without filing it — what a clerk uses to
check a submission before accepting it, and what the demo cases above and the tests
run against. `GET /api/v1/succession/cases/{id}/explain` decomposes `risk_score`
into the exact per-check arithmetic that produced it.

---

## Monorepo layout

```
sig/
├── ai-engine/      Python — OCR + Vision-LLM extraction, validation, discrepancy engine
├── backend/        Python/FastAPI — auth, workflow, persistence, analytics, exports
├── frontend/       Next.js/React — the reviewer console
└── infra/          docker-compose for Postgres/PostGIS + Redis + MinIO (optional)
```

Each package is independently runnable; the backend imports `ai-engine` as a local
editable dependency and the frontend talks to the backend over HTTP only.

### Architecture

```
Scan (PDF/image)
   │
   ▼
┌─────────────────────────── ai-engine/adhikar ───────────────────────────┐
│  load → preprocess → OCR ensemble → table-grid detection                │
│                              │                                          │
│                              ▼                                          │
│           Vision LLM (Groq free tier, default | Claude Opus 5)           │
│                              │                                          │
│                              ▼                                          │
│         normalize (numerals/areas/vocab) → map to domain model          │
│                              │                                          │
│                 ┌────────────┴────────────┐                             │
│                 ▼                         ▼                             │
│      validation engine (22 rules)   discrepancy engine (geo)            │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ExtractionArtifact (JSON)
                              │
                              ▼
   backend/ — JWT auth + RBAC · triage · review workflow · audit trail
              analytics (in SQL) · CSV / GeoJSON / report exports
                              │
                              ▼
   frontend/ — reviewer console, httpOnly session, MapLibre GIS view
```

---

## What each package does

### `ai-engine/` — the extraction and validation core

| Module | Responsibility |
|---|---|
| `adhikar.schemas` | Pydantic v2 domain model, LLM wire contract, validation & discrepancy contracts |
| `adhikar.preprocessing` | PDF/image loading (`pypdfium2`), deskew/denoise/threshold (OpenCV, NumPy fallback) |
| `adhikar.ocr` | EasyOCR + Tesseract behind one interface, reconciled by IoU-based ensemble merging |
| `adhikar.layout` | Ruled-line table-grid detection via morphological line extraction |
| `adhikar.llm` | Vision-LLM extraction behind a provider factory — Groq (free tier) by default, Claude Opus 5 for higher accuracy |
| `adhikar.normalize` | Deterministic numeral/area/vocabulary normalization — classification never left to the model |
| `adhikar.validation` | 22 data-driven rules, parameterized by `policies/validation_policy.yaml` |
| `adhikar.validation.succession` | Ownership-succession & mutation validation — 14 cross-document checks, same policy file |
| `adhikar.succession` | Assembles a `SuccessionCase` from a pipeline record or a raw document payload |
| `adhikar.geo` | Geodesic area (`pyproj`), topology detection, Confidence & Mismatch scoring |
| `adhikar.pipeline` | Orchestrates every stage into one `ExtractionArtifact` |

See [`ai-engine/README.md`](ai-engine/README.md) for the extraction schema, unit
conversion tables, and the validation rule reference — including the succession rules.

### `backend/` — auth, workflow, persistence, reporting

FastAPI + SQLAlchemy, portable between SQLite and Postgres/PostGIS. The full
`ExtractionArtifact` is stored as JSONB (the auditable source of truth); parcel
identifiers, geometry and scores are projected into indexed columns for fast
filtering. Notable modules:

| Module | Responsibility |
|---|---|
| `app.core.security` / `app.api.deps` | Argon2 password hashing, JWT issue/verify, the four-role hierarchy. The **only** place identity arrives over HTTP |
| `app.services.triage` | Priority score, band, SLA clock — and the reasons, returned alongside |
| `app.services.corrections` | Applies a correction to the artifact and re-runs the rule engine |
| `app.services.analytics` | Every dashboard figure, computed in SQL across the whole corpus |
| `app.services.succession` | Assembles, assesses and files ownership-succession cases; re-validates without re-reading documents |
| `app.api.v1.routers.exports` | Streaming CSV (UTF-8 BOM, so Excel does not mangle village names), GeoJSON, and a printable, self-contained verification report |
| `app.api.v1.routers.succession` | Submit/assess/file a succession bundle, the case list & queue, the ownership-event history |
| `app.db.dev_schema` | Dev-only: adds columns an existing SQLite file is missing, which `create_all()` cannot |

```bash
cd backend && pytest        # 70 tests: RBAC, the correction/re-validation loop,
                            # triage scoring, paging, exports, rule catalogue,
                            # and the succession API (27 of the 70)
```

### `frontend/` — the reviewer console

Next.js App Router + Tailwind + MapLibre. Two things worth knowing:

* **The session token never enters client JavaScript.** `/api/session` exchanges
  credentials server-side and stores the JWT in an httpOnly cookie; browser requests
  go through a same-origin proxy that attaches it. A second, readable cookie carries
  display identity only, so the UI can grey out actions the role cannot perform —
  presentation, never authorization, which the API enforces independently.
* **The chart palette is validated, not chosen by eye.** Series hues are assigned in
  a fixed order checked for colour-vision separation; status colours are a separate,
  reserved set and always ship with an icon and a word, so no meaning is ever carried
  by colour alone.

---

## Data governance

Aadhaar numbers, mobile numbers and bank-account details are **never extracted or
persisted** — there is no field for them in `LandParcelRecord`. That is enforced by
the Pydantic model the LLM's output is validated against, not by a downstream filter
that could be misconfigured or switched off.

## Before any real deployment

* `ADHIKAR_API_SEED_DEMO_USERS=false` — remove the four evaluation accounts.
* Rotate `ADHIKAR_API_JWT_SECRET`; the default is a known string.
* Point `ADHIKAR_API_DATABASE_URL` at Postgres/PostGIS and set
  `ADHIKAR_API_DATABASE_FALLBACK_TO_SQLITE=false`.
* Run `alembic upgrade head` rather than relying on the development
  `create_all()` path.
