# Adhikar — Architecture & How It Works

**Adhikar** ("Intelligent Land Record Digitization and Validation System") is a system built for **SIH26018** (Smart India Hackathon, Ministry of Rural Development). It extracts structured data from scanned Indian land records (Jamabandi and 7/12 Extract formats), validates the extracted data for arithmetic and logical consistency, and cross-checks parcel areas against cadastral map geometry — producing a **Confidence & Mismatch score** that flags records for human review by a Tehsildar.

## What the repo contains

It's a monorepo with four independently runnable parts:

```
sig/
├── ai-engine/   Python — OCR + Vision-LLM extraction, validation, discrepancy engine
├── backend/     Python/FastAPI — persistence (PostGIS), REST API, review workflow
├── frontend/    Next.js/React — reviewer console with a GIS discrepancy map
└── infra/       docker-compose.yml — Postgres/PostGIS + Redis + MinIO
```

`backend` installs `ai-engine` as an editable local dependency. `frontend` only ever talks to `backend` over HTTP — there's no shared build step between them.

## End-to-end flow

```
Scan (PDF/image)
  → load → preprocess → OCR ensemble → table-grid detection
  → Vision LLM (strict tool use)
  → normalize (numerals/areas/vocab) → map to domain model
  → validation engine (22 rules)  +  geo discrepancy engine
  → ExtractionArtifact (JSON)
  → backend (FastAPI + PostGIS) persists it, serves it via REST
  → frontend (Next.js) reviewer console + MapLibre GIS view
```

This is implemented as a fixed pipeline in `ai-engine/src/adhikar/pipeline.py` (`process_document()`). OCR deliberately runs *before* the LLM call: its text becomes a supplementary text layer in the vision prompt, so the model can cross-check its own image reading against an independent OCR pass. Validation and the discrepancy check run last and never feed back into extraction — that separation is what makes them a trustworthy check rather than a self-fulfilling one.

## `ai-engine/` — extraction & validation core

| Module | Responsibility |
|---|---|
| `adhikar.schemas` | Pydantic v2 domain model (`land_record.py`), the LLM wire contract, the artifact/provenance format, validation/geo contracts |
| `adhikar.preprocessing` | PDF/image loading (`pypdfium2`), deskew/denoise/threshold (OpenCV) |
| `adhikar.ocr` | EasyOCR + Tesseract behind one interface, merged via IoU-based ensembling |
| `adhikar.layout` | Ruled-line table-grid detection (morphological line extraction) |
| `adhikar.llm` | Vision-LLM structured extraction (see below) |
| `adhikar.normalize` | Deterministic numeral/area/vocabulary normalization — keeps classification decisions out of the model |
| `adhikar.validation` | 22 data-driven rules (arithmetic, ownership, mutation chain, encumbrance), parameterized by `policies/validation_policy.yaml` |
| `adhikar.geo` | Geodesic area via pyproj/WGS84 (avoids the ~6% error of planar lon/lat math), topology checks (overlap/gap) via Shapely, and the Confidence & Mismatch score |
| `adhikar.pipeline` | Orchestrates every stage into one `ExtractionArtifact` |

**CLI**: `ai-engine/src/adhikar/cli.py`, a Typer app (`adhikar extract <file> --format ... --output ...`, `adhikar list-rules`). It's a thin wrapper around `process_document()` — the same call path the backend uses.

**Domain model** (`schemas/land_record.py`): `LandParcelRecord`, `Jurisdiction` (state/district/tehsil/village + LGD codes, fasli year), `PersonName` (name plus a relational qualifier, since same-named people are common in village records), `OwnershipShare` (stored as an exact `Fraction`, never a float, so "shares sum to unity" checks are exact rather than approximate).

Provenance (`{value, confidence, bbox}` per field) is kept in a separate index keyed by JSON path rather than wrapped around every field — this keeps the schema handed to the LLM small, which matters for extraction quality.

**Data governance**: Aadhaar, mobile number, and bank-account fields are never extracted or persisted — enforced at the schema level (no such field exists on `LandParcelRecord.owners`), not filtered out downstream.

### `ai-engine/src/adhikar/llm/` — the vision extraction subsystem

- **`base.py`** — the provider-agnostic contract: an `ExtractionResult` dataclass shared across providers, and a `VisionExtractorProtocol` that any backend must implement. Intent (per its docstring): a future `adhikar.llm.factory.build_extractor` should be the only place that knows which concrete extractor class a given `Settings` selects, so the pipeline never imports a provider module directly.
- **`extractor.py`** — `VisionExtractor`, the Anthropic (Claude) implementation:
  - Builds a **strict tool-use** schema around the `LlmExtraction` model and forces `tool_choice` so the model can't return free text or malformed JSON.
  - Applies **prompt caching** to the large, byte-stable system prompt, since it's reused per page across a batch.
  - Uses **adaptive thinking effort** (`low`/`medium`/`high`/`xhigh`/`max`, default `high`) — table geometry disambiguation benefits from reasoning.
  - Treats a model **refusal** as a distinct outcome (`LlmRefusalError`), not something to retry.
  - Retries transient failures (429/5xx/connection errors) via `tenacity`, but never retries a refusal or a bad request.
  - Renders the OCR ensemble output as a secondary text layer, explicitly framed to the model as "approximate — the image is authoritative on conflict."
- **`mapper.py`** — maps the raw LLM wire format onto the domain model, running the normalizers and building the provenance index. A malformed sub-object (e.g. one bad owner row) is dropped with a warning; a parcel that fails to map entirely is fatal.
- **`schema.py`** — builds the strict Anthropic tool-use JSON schema from the Pydantic models.
- **`prompts.py`** — the frozen extraction system prompt.

**Known in-progress gap**: `config.py` already defines `llm_provider: Literal["anthropic", "groq"] = "groq"` and Groq-specific settings, and points at `adhikar.llm.factory.build_extractor` / `adhikar.llm.groq_extractor.GroqVisionExtractor` — but neither `factory.py` nor `groq_extractor.py` exist yet, and `pipeline.py` still hardcodes the Anthropic `VisionExtractor()` directly. `base.py` looks like the first step of this refactor (defining the provider-agnostic protocol); the factory/dispatch layer and the Groq implementation itself are not built yet.

## `backend/` — persistence & API

FastAPI + SQLAlchemy + PostGIS (`geoalchemy2`). Entry point `backend/app/main.py`, with a global exception handler that converts engine errors into structured 422 responses.

- **`Document`** — one uploaded scan (hash, media type, page count, declared format, object-storage key).
- **`ParcelRecord`** — the queryable projection of one extracted parcel. The full extraction artifact is stored verbatim as `artifact_json` (JSONB, the auditable source of truth); identifiers, PostGIS geometry, mismatch/confidence scores, and review flags are also projected into indexed columns for fast filtering. Both are rewritten together on re-extraction so they can't drift apart.
- **`ReviewEvent`** — an append-only audit trail of human corrections; nothing is overwritten in place.
- **`ingestion.py`** — the single bridge point between backend and ai-engine: writes uploaded bytes to a temp file, calls `process_document()`, builds the `Document`/`ParcelRecord` rows.
- **Routers**: `POST /documents/upload` (runs extraction synchronously today; a documented future step is to enqueue via Celery and return 202), `GET /parcels` (filterable/paginated), `GET /parcels/{id}`, `POST /parcels/{id}/review` (records a `ReviewEvent` without mutating `artifact_json` in place).

## `frontend/` — reviewer console

Next.js (App Router) + Tailwind + MapLibre GL. A dashboard lists extracted parcels with their mismatch score and recommended action; a detail view renders the matched cadastral polygon (colored by mismatch severity) next to the validation findings for side-by-side review.

`lib/api.ts` has a demo-data fallback: if the backend is unreachable, read paths fall back to bundled fixtures so the UI can be demoed without the full stack running. Write paths (submitting a correction) never fall back — a correction that can't persist fails loudly instead of silently succeeding against fake data.

## `infra/`

`docker-compose.yml` brings up Postgres/PostGIS, Redis, and MinIO for local full-stack development.

## Tech stack

- **ai-engine**: Python ≥3.11, Pydantic v2, Typer/Rich CLI, Anthropic SDK (Claude) for vision extraction, `tenacity` for retries, EasyOCR + Tesseract, OpenCV/NumPy, `pypdfium2`, Shapely + pyproj, `ruff`/`mypy`, `pytest`.
- **backend**: FastAPI, SQLAlchemy, `geoalchemy2`, Alembic, `prometheus-fastapi-instrumentator`; boto3 and Celery are present as dependencies for planned object-storage/async-worker support.
- **frontend**: Next.js, React, TypeScript, Tailwind CSS, MapLibre GL.
- **infra**: Docker Compose (Postgres/PostGIS, Redis, MinIO).

## Quick start

```bash
# ai-engine (extraction CLI)
cd ai-engine && pip install -r requirements.txt && pip install -e .
adhikar extract path/to/scan.pdf --format satbara_7_12 --output artifact.json
adhikar list-rules

# infra
cd infra && docker compose up -d

# backend
cd backend && pip install -r requirements.txt && alembic upgrade head && uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev
```
