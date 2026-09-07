"""Document ingestion: PDF or image file to a list of page rasters.

PDF rendering uses ``pypdfium2`` rather than ``pdf2image``/Poppler: it is a wheel with
no system binary to install, which matters when the deployment target is a district
NIC server rather than a developer laptop.
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..config import Settings, get_settings
from ..exceptions import DocumentLoadError
from ..schemas.artifact import SourceDocument
from ..schemas.enums import RecordFormat

__all__ = ["LoadedDocument", "LoadedPage", "load_document"]

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
_PDF_SUFFIXES = {".pdf"}


@dataclass(slots=True)
class LoadedPage:
    """One rasterised page."""

    page_index: int
    image: np.ndarray
    """RGB uint8 array, shape ``(height, width, 3)``."""

    dpi: int

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def width(self) -> int:
        return int(self.image.shape[1])


@dataclass(slots=True)
class LoadedDocument:
    """A source file plus its rendered pages."""

    source: SourceDocument
    pages: list[LoadedPage]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_document(
    path: str | Path,
    *,
    document_id: str | None = None,
    declared_format: RecordFormat = RecordFormat.UNKNOWN,
    settings: Settings | None = None,
) -> LoadedDocument:
    """Load and rasterise a scanned land record.

    :param path: A PDF or a single-page image.
    :param document_id: Defaults to the content hash, so re-ingesting the same scan
        produces the same identifier and duplicates are detectable.
    :raises DocumentLoadError: on a missing file, an unsupported type, an encrypted
        or corrupt PDF, or a document with no pages.
    """
    settings = settings or get_settings()
    path = Path(path)

    if not path.is_file():
        raise DocumentLoadError(f"file not found: {path}", context={"path": str(path)})

    suffix = path.suffix.lower()
    checksum = _sha256(path)
    doc_id = document_id or checksum[:16]

    if suffix in _PDF_SUFFIXES:
        pages = _render_pdf(path, settings, doc_id)
        media_type = "application/pdf"
    elif suffix in _IMAGE_SUFFIXES:
        pages = [_load_image(path, settings, doc_id)]
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    else:
        raise DocumentLoadError(
            f"unsupported file type {suffix!r}",
            document_id=doc_id,
            context={"supported": sorted(_PDF_SUFFIXES | _IMAGE_SUFFIXES)},
        )

    if not pages:
        raise DocumentLoadError("document contains no renderable pages", document_id=doc_id)

    source = SourceDocument(
        document_id=doc_id,
        file_name=path.name,
        media_type=media_type,
        sha256=checksum,
        byte_size=path.stat().st_size,
        page_count=len(pages),
        ingested_at=datetime.now(UTC),
        declared_record_format=declared_format,
        declared_state=None,
    )
    return LoadedDocument(source=source, pages=pages)


def _render_pdf(path: Path, settings: Settings, doc_id: str) -> list[LoadedPage]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise DocumentLoadError(
            "pypdfium2 is required to render PDFs; install ai-engine requirements",
            document_id=doc_id,
        ) from exc

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:  # noqa: BLE001 - pdfium raises a variety of native errors
        raise DocumentLoadError(
            f"could not open PDF: {exc}",
            document_id=doc_id,
            context={"hint": "the file may be encrypted or truncated"},
        ) from exc

    scale = settings.render_dpi / 72.0
    pages: list[LoadedPage] = []
    try:
        total = len(pdf)
        if total > settings.max_pages_per_document:
            raise DocumentLoadError(
                f"document has {total} pages, above the configured limit of "
                f"{settings.max_pages_per_document}",
                document_id=doc_id,
                context={"hint": "raise ADHIKAR_MAX_PAGES_PER_DOCUMENT or split the file"},
            )
        for index in range(total):
            page = pdf[index]
            try:
                bitmap = page.render(scale=scale)
                image = np.asarray(bitmap.to_pil().convert("RGB"), dtype=np.uint8)
                pages.append(LoadedPage(page_index=index, image=image, dpi=settings.render_dpi))
            except Exception as exc:  # noqa: BLE001
                raise DocumentLoadError(
                    f"failed to render page: {exc}", document_id=doc_id, page_index=index
                ) from exc
            finally:
                page.close()
    finally:
        pdf.close()

    return pages


def _load_image(path: Path, settings: Settings, doc_id: str) -> LoadedPage:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise DocumentLoadError("Pillow is required to load images", document_id=doc_id) from exc

    try:
        with Image.open(path) as handle:
            # EXIF transpose first: phone photographs of records are routinely stored
            # rotated, and every downstream geometry assumption breaks if we skip it.
            oriented = ImageOps.exif_transpose(handle)
            image = np.asarray(oriented.convert("RGB"), dtype=np.uint8)
    except Exception as exc:  # noqa: BLE001 - Pillow raises many decode error types
        raise DocumentLoadError(f"could not decode image: {exc}", document_id=doc_id) from exc

    return LoadedPage(page_index=0, image=image, dpi=settings.render_dpi)
