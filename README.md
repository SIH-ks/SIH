# Adhikar — Intelligent Land Record Digitization and Validation System

Built for **SIH26018** (Ministry of Rural Development): an automated, data-driven
pipeline that extracts Jamabandi and 7/12 Extract land records from scans, validates
the arithmetic, and cross-references extracted areas against cadastral geometry to
produce a Confidence & Mismatch score.

## Monorepo layout

```
sig/
├── ai-engine/      Python — OCR + Vision-LLM extraction, validation, discrepancy engine
├── backend/        Python/FastAPI — persistence (PostGIS), REST API, review workflow
├── frontend/       Next.js/React — reviewer console, GIS discrepancy map
├── infra/          docker-compose for local Postgres/PostGIS + Redis + MinIO
└── policies/       (inside ai-engine) validation tolerance YAML
```

Each package is independently runnable; the backend imports `ai-engine` as a local
editable dependency (`-e ../ai-engine`) and the frontend talks to the backend over
HTTP only — there is no shared build step.

## Architecture

```
Scan (PDF/image)
   │
   ▼
┌─────────────────────────── ai-engine/adhikar ───────────────────────────┐
│  load → preprocess → OCR ensemble → table-grid detection                │
│                              │                                          │
│                              ▼                                          │
│           Vision LLM (Groq free tier, default | Claude Opus 5)          │
│                              │                                          │
│                              ▼                                          │
│         normalize (numerals/areas/vocab) → map to domain model          │
│                              │                                          │
│                 ┌────────────┴────────────┐                            │
│                 ▼                         ▼                            │
│      validation engine (22 rules)   discrepancy engine (geo)           │
└───────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ExtractionArtifact (JSON)
                              │
                              ▼
              backend/ (FastAPI + PostGIS) — persists, serves REST API
                              │
                              ▼
              frontend/ (Next.js) — reviewer console + MapLibre GIS view
```

## Quick start

### 1. AI engine (extraction + validation, no other services needed)

```bash
cd ai-engine
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
pip install -e .
cp .env.example .env                     # then set GROQ_API_KEY (free: console.groq.com/keys)

pytest                                                 # 72 tests, no network/API calls needed
adhikar extract path/to/scan.pdf --format satbara_7_12 --output artifact.json
adhikar list-rules
```

### 2. Full stack (backend + frontend + Postgres/PostGIS)

```bash
cd infra && docker compose up -d          # Postgres/PostGIS, Redis, MinIO

cd backend
pip install -r requirements.txt           # installs ai-engine too, via -e ../ai-engine
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload             # http://localhost:8000/docs

cd frontend
npm install
cp .env.local.example .env.local
npm run dev                                # http://localhost:3000
```

## What each package actually does

### `ai-engine/` — the extraction and validation core

| Module | Responsibility |
|---|---|
| `adhikar.schemas` | Pydantic v2 domain model, LLM wire contract, validation & discrepancy contracts — the schema everything else is built against |
| `adhikar.preprocessing` | PDF/image loading (`pypdfium2`), deskew/denoise/threshold (`OpenCV`, with a NumPy-only fallback) |
| `adhikar.ocr` | EasyOCR + Tesseract adapters behind one interface, reconciled by IoU-based ensemble merging |
| `adhikar.layout` | Ruled-line table-grid detection via morphological line extraction |
| `adhikar.llm` | Vision LLM extraction behind a provider factory — Groq (free tier, JSON-mode + repair) by default, Anthropic Claude Opus 5 (strict tool use + prompt caching) as the higher-accuracy option |
| `adhikar.normalize` | Deterministic numeral/area/vocabulary normalization — the vernacular-term resolver that keeps classification out of the model's hands |
| `adhikar.validation` | 22 data-driven consistency rules (arithmetic, ownership, mutation chain, encumbrance), parameterized by `policies/validation_policy.yaml` |
| `adhikar.geo` | Geodesic area computation (`pyproj`), topology (overlap/gap) detection, and the Confidence & Mismatch scoring model |
| `adhikar.pipeline` | Orchestrates every stage into one `ExtractionArtifact` |

See [`ai-engine/README.md`](ai-engine/README.md) for the extraction schema, unit
conversion tables, and validation rule reference.

### `backend/` — persistence and API

FastAPI + SQLAlchemy + PostGIS. The full `ExtractionArtifact` is stored as JSONB
(the auditable source of truth); parcel identifiers, geometry, and mismatch/confidence
scores are projected into indexed columns for fast filtering. Every human correction
is recorded as an additive `ReviewEvent` — nothing is overwritten in place, so the
review history stays reconstructable.

### `frontend/` — reviewer console

Next.js App Router + Tailwind + MapLibre. The dashboard lists every extracted parcel
with its mismatch score and recommended action; the parcel detail view renders the
matched cadastral polygon colored by mismatch severity alongside the validation
findings, so a reviewer cross-checks the map and the flagged fields in one view.

## Data governance

Aadhaar, mobile number, and bank-account fields are never extracted or persisted —
this is enforced at the schema level (`LandParcelRecord.owners` has no such field),
not by a downstream filter.
