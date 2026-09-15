"""Document ingestion: single and batch upload, plus the document register."""

from __future__ import annotations

import time
import uuid

from adhikar.schemas.enums import RecordFormat
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....core.config import get_settings
from ....core.logging import get_logger
from ....db.base import get_db
from ....models.record import Document, ParcelRecord
from ....schemas.record import (
    BatchUploadResponse,
    DocumentSummary,
    Page,
    ParcelSummary,
    UploadResponse,
)
from ....services.ingestion import IngestionError, find_duplicate, ingest_upload
from ...deps import CurrentUser, require_admin, require_operator

router = APIRouter(prefix="/documents", tags=["documents"])
logger = get_logger("adhikar.ingest")


def _ingest_one(
    db: Session, *, contents: bytes, filename: str, declared_format: RecordFormat, actor: CurrentUser
) -> UploadResponse:
    """Ingest one file, or return the existing document if these bytes are already in.

    Shared by the single and batch endpoints so both dedupe identically -- a batch
    that re-processed duplicates the single upload skips would be a silent
    inconsistency between two ways of doing the same thing.
    """
    started = time.perf_counter()

    if (existing := find_duplicate(db, contents)) is not None:
        parcels = db.scalars(select(ParcelRecord).where(ParcelRecord.document_id == existing.id)).all()
        logger.info("upload_deduplicated", file=filename, document_id=str(existing.id))
        return UploadResponse(
            document=DocumentSummary.model_validate(existing),
            parcels=[ParcelSummary.model_validate(p) for p in parcels],
            warnings=[
                f"This scan was already ingested on {existing.ingested_at:%d %b %Y} as "
                f"'{existing.file_name}'. The existing extraction is shown; nothing was re-processed."
            ],
            duplicate_of=existing.id,
        )

    document, parcels = ingest_upload(
        db,
        file_bytes=contents,
        file_name=filename,
        declared_format=declared_format,
        uploaded_by=actor.username,
    )
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    logger.info("upload_ingested", file=filename, parcels=len(parcels), duration_ms=elapsed)

    warnings: list[str] = []
    if not parcels:
        warnings.append(
            "No parcel could be assembled from this scan. The page may be blank, "
            "rotated beyond correction, or of a record format the extractor does not recognise."
        )
    return UploadResponse(
        document=DocumentSummary.model_validate(document),
        parcels=[ParcelSummary.model_validate(p) for p in parcels],
        warnings=warnings,
        processing_ms=elapsed,
    )


def _read_and_check(contents: bytes, filename: str) -> None:
    settings = get_settings()
    if len(contents) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{filename} exceeds the {settings.max_upload_size_mb} MB limit",
        )
    if not contents:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{filename} is empty")


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(..., description="A scanned Jamabandi / 7-12 PDF or image."),
    declared_format: str = Form("unknown"),
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Upload a scan, run the full extraction/validation/discrepancy pipeline, and
    persist the result. Returns the parcel rows immediately -- extraction is
    synchronous in this reference implementation; a production deployment would
    enqueue it on the Celery worker declared in ``requirements.txt`` and return a
    202 with a polling location instead.
    """
    contents = await file.read()
    filename = file.filename or "upload.pdf"
    _read_and_check(contents, filename)

    try:
        fmt = RecordFormat(declared_format)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown format {declared_format!r}"
        ) from None

    try:
        return _ingest_one(db, contents=contents, filename=filename, declared_format=fmt, actor=actor)
    except IngestionError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_type": type(exc.cause).__name__, "message": str(exc)},
        ) from exc


@router.post("/batch-upload", response_model=BatchUploadResponse, status_code=status.HTTP_201_CREATED)
async def batch_upload(
    files: list[UploadFile] = File(..., description="Up to `max_batch_upload_files` scans."),
    declared_format: str = Form("unknown"),
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
) -> BatchUploadResponse:
    """Ingest a folder of scans in one request.

    This is how the work actually arrives: a taluk office digitises a bound register
    as two hundred images, not as two hundred separate visits to an upload form.

    Failures are per-file and never abort the batch. One corrupt scan in a folder of
    two hundred must not discard the other hundred and ninety-nine -- so each file is
    committed on its own and the response reports exactly which ones did not make it
    and why, which is also the list an operator needs in order to re-scan.
    """
    settings = get_settings()
    if len(files) > settings.max_batch_upload_files:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"batch is limited to {settings.max_batch_upload_files} files; received {len(files)}",
        )

    try:
        fmt = RecordFormat(declared_format)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown format {declared_format!r}"
        ) from None

    results: list[UploadResponse] = []
    failures: list[dict] = []

    for upload in files:
        filename = upload.filename or "upload.pdf"
        try:
            contents = await upload.read()
            _read_and_check(contents, filename)
            results.append(
                _ingest_one(db, contents=contents, filename=filename, declared_format=fmt, actor=actor)
            )
        except HTTPException as exc:
            failures.append({"file_name": filename, "reason": str(exc.detail)})
        except IngestionError as exc:
            failures.append({"file_name": filename, "reason": str(exc), "error_type": type(exc.cause).__name__})
        except Exception as exc:  # noqa: BLE001 - one bad scan must not sink the batch
            logger.exception("batch_file_failed", file=filename)
            db.rollback()
            failures.append({"file_name": filename, "reason": f"unexpected error: {exc}"})

    logger.info("batch_upload_complete", succeeded=len(results), failed=len(failures))
    return BatchUploadResponse(
        results=results, failures=failures, succeeded=len(results), failed=len(failures)
    )


@router.get("", response_model=Page[DocumentSummary])
def list_documents(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_operator),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[DocumentSummary]:
    """The document register: what has been ingested, by whom, and when.

    Distinct from the parcel list because one scan can yield several parcels (or
    none). An operator chasing "did my batch go through?" is asking about documents;
    a reviewer working the queue is asking about parcels.
    """
    total = db.scalar(select(func.count(Document.id))) or 0
    rows = db.scalars(
        select(Document).order_by(Document.ingested_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[DocumentSummary](
        items=[DocumentSummary.model_validate(d) for d in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{document_id}", response_model=DocumentSummary)
def get_document(
    document_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(require_operator)
) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_document(
    document_id: uuid.UUID, _: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> None:
    """Delete a document and every parcel extracted from it. Administrator only.

    Cascades to the parcels and their audit trails -- see the note on
    ``parcels.delete_parcel`` about retention obligations.
    """
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    db.delete(document)
    db.commit()
