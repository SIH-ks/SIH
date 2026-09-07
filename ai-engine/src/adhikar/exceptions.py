"""Exception hierarchy.

Two rules govern this module:

**Every failure carries the context needed to act on it.** A bare
``ValueError("bad area")`` in a batch of 5,000 scans is unactionable. Each exception
here carries the document, page and, where relevant, the offending text.

**Recoverable and unrecoverable failures are different types.**
:class:`StageDegradedError` means a stage produced a worse-but-usable result (one OCR
engine missing, no geometry available) and the pipeline continues with a recorded
warning. Everything else aborts the document.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AdhikarError",
    "ConfigurationError",
    "DocumentLoadError",
    "GeometryError",
    "LlmExtractionError",
    "LlmRefusalError",
    "OcrEngineError",
    "PreprocessingError",
    "SchemaMappingError",
    "StageDegradedError",
    "TableDetectionError",
    "ValidationConfigError",
]


class AdhikarError(Exception):
    """Base for every error this package raises."""

    def __init__(
        self,
        message: str,
        *,
        document_id: str | None = None,
        page_index: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.document_id = document_id
        self.page_index = page_index
        self.context = context or {}
        super().__init__(self._render())

    def _render(self) -> str:
        parts = [self.message]
        if self.document_id:
            parts.append(f"document={self.document_id}")
        if self.page_index is not None:
            parts.append(f"page={self.page_index}")
        for key, value in self.context.items():
            parts.append(f"{key}={value!r}")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Structured form, for the API error envelope and for logs."""
        return {
            "error_type": type(self).__name__,
            "message": self.message,
            "document_id": self.document_id,
            "page_index": self.page_index,
            "context": self.context,
        }


class StageDegradedError(AdhikarError):
    """A stage completed with reduced quality rather than failing.

    Never raised to the caller: the pipeline catches it, records it in
    ``ProcessingMetadata.warnings``, and continues. It exists as an exception so
    stages can signal degradation from deep in a call stack without threading a
    status object through every function.
    """


class ConfigurationError(AdhikarError):
    """Settings are missing or internally inconsistent."""


class DocumentLoadError(AdhikarError):
    """The source file could not be opened, decoded or rasterised."""


class PreprocessingError(AdhikarError):
    """Image conditioning failed on a page."""


class OcrEngineError(AdhikarError):
    """An OCR engine failed or is unavailable."""

    def __init__(self, message: str, *, engine: str, **kwargs: Any) -> None:
        self.engine = engine
        super().__init__(message, context={"engine": engine, **kwargs.pop("context", {})}, **kwargs)


class TableDetectionError(AdhikarError):
    """Grid reconstruction failed on a page."""


class LlmExtractionError(AdhikarError):
    """The Vision LLM call failed, or returned something unusable."""


class LlmRefusalError(LlmExtractionError):
    """The model declined the request (``stop_reason == "refusal"``).

    Distinct from a transport failure because retrying identically will not help.
    On land records this would be unusual -- it most often means a scan carried
    unexpected content -- so it is surfaced rather than swallowed.
    """

    def __init__(self, message: str, *, category: str | None = None, **kwargs: Any) -> None:
        self.category = category
        super().__init__(message, context={"refusal_category": category, **kwargs.pop("context", {})}, **kwargs)


class SchemaMappingError(AdhikarError):
    """The LLM's wire output could not be mapped onto the domain model.

    Carries the offending path and raw value so the failure is diagnosable without
    re-running the extraction.
    """

    def __init__(self, message: str, *, field_path: str, raw_value: Any = None, **kwargs: Any) -> None:
        self.field_path = field_path
        self.raw_value = raw_value
        super().__init__(
            message,
            context={"field_path": field_path, "raw_value": raw_value, **kwargs.pop("context", {})},
            **kwargs,
        )


class ValidationConfigError(AdhikarError):
    """A validation policy file is malformed or references an unknown rule."""


class GeometryError(AdhikarError):
    """A parcel polygon is invalid, or an area computation could not be performed."""
