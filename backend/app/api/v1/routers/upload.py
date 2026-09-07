"""Upload and extraction endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from adhikar.schemas.enums import RecordFormat

from ....core.config import get_settings
from ....db.base import get_db
from ....schemas.record import DocumentSummary, ParcelSummary, UploadResponse
from ....services.ingestion import IngestionError, ingest_upload

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(..., description="A scanned Jamabandi / 7-12 PDF or image."),
    declared_format: str = Form("unknown"),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Upload a scan, run the full extraction/validation/discrepancy pipeline, and
    persist the result. Returns the parcel rows immediately -- extraction is
    synchronous in this reference implementation; a production deployment would
    enqueue it on the Celery worker declared in ``requirements.txt`` and return a
    202 with a polling location instead.
    """
    settings = get_settings()
    contents = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds the {settings.max_upload_size_mb} MB limit",
        )

    try:
        fmt = RecordFormat(declared_format)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown format {declared_format!r}") from None

    try:
        document, parcels = ingest_upload(
            db,
            file_bytes=contents,
            file_name=file.filename or "upload.pdf",
            declared_format=fmt,
        )
    except IngestionError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_type": type(exc.cause).__name__, "message": str(exc)},
        ) from exc

    return UploadResponse(
        document=DocumentSummary.model_validate(document),
        parcels=[ParcelSummary.model_validate(p) for p in parcels],
    )
