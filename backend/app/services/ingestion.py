"""Bridges an uploaded file to the ai-engine pipeline and persists the result.

This is the one place the backend calls into :mod:`adhikar` -- everything upstream
(the router) only ever talks to this service and gets back ORM rows / DTOs, so the
engine's API can change without touching the request-handling layer.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import uuid
from pathlib import Path

from adhikar.exceptions import AdhikarError
from adhikar.pipeline import process_document
from adhikar.preprocessing.loader import load_document
from adhikar.schemas.artifact import ExtractionArtifact
from adhikar.schemas.enums import RecordFormat
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.record import Document, ParcelRecord
from .triage import assess_priority, sla_due_at


class IngestionError(Exception):
    """Raised when extraction fails; carries the underlying AdhikarError for logging."""

    def __init__(self, message: str, *, cause: AdhikarError) -> None:
        super().__init__(message)
        self.cause = cause


_PARCEL_PATH_PREFIX = re.compile(r"^\$\.parcels\[(\d+)\]\.")


def find_duplicate(db: Session, file_bytes: bytes) -> Document | None:
    """Return the already-ingested document with these exact bytes, if any.

    Bulk scanning workflows re-submit the same file constantly -- a re-run of a
    folder sync, an operator retrying after a timeout, the same register scanned
    twice by two clerks. Re-processing a byte-identical scan costs a full OCR + LLM
    pass and produces a second set of parcel rows that somebody then has to reconcile
    against the first. Detecting it by content hash (which the pipeline computes
    anyway) is cheap and exact; detecting it by filename would be neither.
    """
    digest = hashlib.sha256(file_bytes).hexdigest()
    return db.scalar(select(Document).where(Document.sha256 == digest))


def ingest_upload(
    db: Session,
    *,
    file_bytes: bytes,
    file_name: str,
    declared_format: RecordFormat = RecordFormat.UNKNOWN,
    uploaded_by: str | None = None,
) -> tuple[Document, list[ParcelRecord]]:
    """Run the extraction pipeline on an uploaded file and persist the result.

    The original bytes go to a temp file for the pipeline to rasterise (it operates
    on paths, since PDF rendering needs random access), then both the original and
    each rendered page get written to local disk under
    ``settings.local_storage_dir`` -- the zero-setup storage backend this reference
    implementation actually uses. A production deployment would upload to S3/MinIO
    instead (``boto3`` is already a dependency); swapping that in means changing
    this function's storage calls, not its callers or the response shape, since the
    persisted URLs are already opaque strings as far as everything downstream is
    concerned.
    """
    settings = get_settings()
    suffix = Path(file_name).suffix or ".pdf"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    try:
        artifact = process_document(tmp_path, declared_format=declared_format)
        # A second, lightweight load just for the raw page rasters -- the pipeline's
        # own artifact deliberately carries OCR text (PageOcr), never pixel data, so
        # there is no way to get the images the Document Viewer needs out of it
        # directly. Re-decoding a multi-page PDF and rasterising a handful of pages
        # a second time costs a fraction of a second next to the OCR/LLM stages that
        # already ran, so it isn't worth threading pixel data through the artifact
        # schema just to avoid it.
        #
        # No `settings=` here: `load_document` defaults to the ai-engine's own
        # `adhikar.config.Settings` when omitted. The backend's `settings` variable
        # in scope below is a same-named but unrelated class (this module's own
        # `app.core.config.Settings`) -- passing it here would be a type mismatch,
        # not an override.
        loaded = load_document(tmp_path, document_id=artifact.document.document_id)
    except AdhikarError as exc:
        raise IngestionError(f"extraction failed for {file_name}: {exc}", cause=exc) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    page_image_urls = _persist_pages(
        settings.local_storage_dir, sha256=artifact.document.sha256, original_bytes=file_bytes,
        original_suffix=suffix, pages=loaded.pages,
    )

    document = Document(
        id=uuid.uuid4(),
        file_name=artifact.document.file_name,
        sha256=artifact.document.sha256,
        media_type=artifact.document.media_type,
        byte_size=artifact.document.byte_size,
        page_count=artifact.document.page_count,
        declared_record_format=artifact.document.declared_record_format.value,
        declared_state=artifact.document.declared_state,
        source_system=artifact.document.source_system,
        storage_key=f"local/{artifact.document.sha256}{suffix}",
        uploaded_by=uploaded_by,
    )
    db.add(document)
    db.flush()  # assigns document.id for the FK below without committing yet

    parcel_rows = [
        _build_parcel_row(document.id, artifact, index, page_image_urls=page_image_urls)
        for index in range(len(artifact.parcels))
    ]
    db.add_all(parcel_rows)
    db.commit()
    for row in parcel_rows:
        db.refresh(row)

    return document, parcel_rows


def _persist_pages(
    storage_dir: Path, *, sha256: str, original_bytes: bytes, original_suffix: str, pages: list
) -> list[str]:
    """Write the original file and each rendered page PNG to local disk.

    Returns the ``/static/...`` URLs `app.main` serves them under. Keyed by content
    hash rather than document ID so re-uploading the identical scan overwrites the
    same files instead of accumulating duplicates.
    """
    from PIL import Image

    doc_dir = storage_dir / sha256
    doc_dir.mkdir(parents=True, exist_ok=True)

    (doc_dir / f"original{original_suffix}").write_bytes(original_bytes)

    urls: list[str] = []
    for page in pages:
        page_path = doc_dir / f"page-{page.page_index}.png"
        Image.fromarray(page.image).save(page_path, format="PNG")
        urls.append(f"/static/uploads/{sha256}/page-{page.page_index}.png")
    return urls


def _provenance_for_parcel(artifact: ExtractionArtifact, index: int) -> dict[str, dict]:
    """Real per-field bbox/confidence for one parcel, re-keyed relative to it.

    ``artifact.provenance`` is keyed by absolute paths like
    ``"$.parcels[0].owners[0].name.raw_name"``; the frontend only ever looks at one
    parcel at a time, so those get re-keyed to ``"owners[0].name.raw_name"`` here.

    Coverage is only as complete as :mod:`adhikar.llm.mapper` actually records
    today -- currently owner name and total area, not every field (khasra numbers
    and mutation dates aren't instrumented yet). A field with no entry here is the
    honest, correct state for a field the mapper doesn't track provenance for; the
    frontend falls back to a simulated highlight position for those rather than
    guessing at a bounding box that was never actually measured.
    """
    result: dict[str, dict] = {}
    for path, prov in artifact.provenance.items():
        match = _PARCEL_PATH_PREFIX.match(path)
        if match and int(match.group(1)) == index:
            result[path[match.end() :]] = prov.model_dump(mode="json")
    return result


def _build_parcel_row(
    document_id: uuid.UUID, artifact: ExtractionArtifact, index: int, *, page_image_urls: list[str]
) -> ParcelRecord:
    parcel = artifact.parcels[index]
    discrepancy = artifact.discrepancy_for(parcel.parcel_key)

    parcel_issues = [
        issue
        for issue in (artifact.validation.issues if artifact.validation else [])
        if issue.parcel_key == parcel.parcel_key
    ]
    highest = max((i.severity for i in parcel_issues), key=lambda s: s.rank, default=None)

    # Triage at ingestion rather than on read: the queue orders by this score in SQL,
    # and a score computed per-request could not be an ORDER BY.
    assessment = assess_priority(
        mismatch_score=discrepancy.mismatch_score if discrepancy else None,
        confidence_score=discrepancy.confidence_score if discrepancy else None,
        validation_highest_severity=highest.value if highest else None,
        validation_issue_count=len(parcel_issues),
        recommended_action=discrepancy.recommended_action.value if discrepancy else None,
    )

    return ParcelRecord(
        id=uuid.uuid4(),
        document_id=document_id,
        parcel_key=parcel.parcel_key,
        state=parcel.jurisdiction.state,
        district=parcel.jurisdiction.district,
        village=parcel.jurisdiction.village,
        khata_number=parcel.khata_number,
        survey_number=parcel.survey_number,
        total_area_sq_metre=parcel.total_area.sq_metre if parcel.total_area else None,
        record_format=parcel.record_format.value,
        # No cadastral GeoJSON source is configured in this reference deployment,
        # so every real upload honestly has no geometry match -- see
        # ParcelDetail.geometry's docstring. Wiring one means resolving
        # ADHIKAR_GEOMETRY_SOURCE_PATH to a ParcelGeometry per parcel_key and
        # passing it as `geometries_by_parcel_key` to `process_document` above.
        geometry=None,
        mismatch_score=discrepancy.mismatch_score if discrepancy else None,
        confidence_score=discrepancy.confidence_score if discrepancy else None,
        recommended_action=discrepancy.recommended_action.value if discrepancy else None,
        requires_human_review=artifact.requires_human_review,
        artifact_json={
            **parcel.model_dump(mode="json"),
            "provenance": _provenance_for_parcel(artifact, index),
            "validation_issues": [issue.model_dump(mode="json") for issue in parcel_issues],
        },
        page_image_urls=page_image_urls,
        validation_issue_count=len(parcel_issues),
        validation_highest_severity=highest.value if highest else None,
        priority=assessment.priority.value,
        priority_score=assessment.score,
        sla_due_at=sla_due_at(assessment.priority),
    )
