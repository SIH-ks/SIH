"""Bridges an uploaded file to the ai-engine pipeline and persists the result.

This is the one place the backend calls into :mod:`adhikar` -- everything upstream
(the router) only ever talks to this service and gets back ORM rows / DTOs, so the
engine's API can change without touching the request-handling layer.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from adhikar.exceptions import AdhikarError
from adhikar.pipeline import process_document
from adhikar.schemas.artifact import ExtractionArtifact
from adhikar.schemas.enums import RecordFormat
from sqlalchemy.orm import Session

from ..models.record import Document, ParcelRecord


class IngestionError(Exception):
    """Raised when extraction fails; carries the underlying AdhikarError for logging."""

    def __init__(self, message: str, *, cause: AdhikarError) -> None:
        super().__init__(message)
        self.cause = cause


def ingest_upload(
    db: Session,
    *,
    file_bytes: bytes,
    file_name: str,
    declared_format: RecordFormat = RecordFormat.UNKNOWN,
    uploaded_by: str | None = None,
    storage_key_prefix: str = "scans",
) -> tuple[Document, list[ParcelRecord]]:
    """Run the extraction pipeline on an uploaded file and persist the result.

    The original bytes are written to a temp file for the pipeline to rasterise (it
    operates on paths, since PDF rendering libraries need random access) and then --
    in a production deployment -- uploaded to object storage under
    ``storage_key_prefix``; that upload call is elided here and left as an integration
    point (``boto3`` is already a backend dependency) so this module stays testable
    without live cloud credentials.
    """
    suffix = Path(file_name).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    try:
        artifact = process_document(tmp_path, declared_format=declared_format)
    except AdhikarError as exc:
        raise IngestionError(f"extraction failed for {file_name}: {exc}", cause=exc) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    storage_key = f"{storage_key_prefix}/{artifact.document.sha256}{suffix}"

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
        storage_key=storage_key,
        uploaded_by=uploaded_by,
    )
    db.add(document)
    db.flush()  # assigns document.id for the FK below without committing yet

    parcel_rows = [_build_parcel_row(document.id, artifact, index) for index in range(len(artifact.parcels))]
    db.add_all(parcel_rows)
    db.commit()
    for row in parcel_rows:
        db.refresh(row)

    return document, parcel_rows


def _build_parcel_row(document_id: uuid.UUID, artifact: ExtractionArtifact, index: int) -> ParcelRecord:
    parcel = artifact.parcels[index]
    discrepancy = artifact.discrepancy_for(parcel.parcel_key)

    parcel_issues = [
        issue
        for issue in (artifact.validation.issues if artifact.validation else [])
        if issue.parcel_key == parcel.parcel_key
    ]
    highest = max((i.severity for i in parcel_issues), key=lambda s: s.rank, default=None)

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
        mismatch_score=discrepancy.mismatch_score if discrepancy else None,
        confidence_score=discrepancy.confidence_score if discrepancy else None,
        recommended_action=discrepancy.recommended_action.value if discrepancy else None,
        requires_human_review=artifact.requires_human_review,
        artifact_json=parcel.model_dump(mode="json"),
        validation_issue_count=len(parcel_issues),
        validation_highest_severity=highest.value if highest else None,
    )
