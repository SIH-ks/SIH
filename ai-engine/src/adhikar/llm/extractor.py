"""Vision-LLM structured extraction: page images -> :class:`LlmExtraction`.

Request shape
-------------
* **Strict tool use** (:func:`~adhikar.llm.schema.build_strict_tool_schema`) with a
  forced ``tool_choice`` guarantees both a single tool call and schema-valid
  arguments -- the model physically cannot return free text or malformed JSON.
* **Prompt caching** on the frozen system prompt: :data:`EXTRACTION_SYSTEM_PROMPT`
  plus the tool definition together form a large, byte-stable prefix, so it is marked
  with ``cache_control`` and reused across every page in a batch. Only the page image
  and its OCR text layer vary per request and sit after the cache breakpoint.
* **Adaptive thinking at configurable effort** -- table geometry disambiguation
  (which column is which sub-division, which row a mutation's parties belong to)
  benefits from reasoning; :attr:`~adhikar.config.Settings.llm_effort` defaults to
  ``high`` for exactly that reason and is turned down for cleaner inputs.
* **Refusal is treated as a real outcome**, not a transport error: it raises
  :class:`~adhikar.exceptions.LlmRefusalError` with the category attached, rather than
  being retried identically (a scan is not going to stop refusing on attempt two).
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import Settings, get_settings
from ..exceptions import LlmExtractionError, LlmRefusalError
from ..schemas.artifact import TokenUsage
from ..schemas.llm_contract import LlmExtraction
from ..schemas.ocr import PageOcr
from .prompts import EXTRACTION_SYSTEM_PROMPT
from .schema import build_strict_tool_schema

__all__ = ["ExtractionResult", "VisionExtractor"]

_TOOL_NAME = "extract_land_record"
_TOOL_SCHEMA = build_strict_tool_schema(
    LlmExtraction,
    tool_name=_TOOL_NAME,
    description=(
        "Record your complete transcription of every parcel on this land record "
        "document, following the schema exactly."
    ),
)

_RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class ExtractionResult:
    """One extraction call's output plus its cost and latency accounting."""

    extraction: LlmExtraction
    token_usage: TokenUsage
    model: str
    effort: str
    duration_ms: float
    stop_reason: str


def _encode_image(image: np.ndarray) -> tuple[str, str]:
    """PNG-encode a raster for the Messages API. Returns (media_type, base64_data)."""
    from PIL import Image
    import io

    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return "image/png", base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def _downscale_if_needed(image: np.ndarray, *, max_edge: int) -> np.ndarray:
    """Shrink an oversized raster before sending it -- tokens scale with pixels, not
    with legibility past the point conjuncts are already resolvable."""
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_edge:
        return image

    from PIL import Image

    scale = max_edge / longest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    resized = Image.fromarray(image).resize(new_size, Image.Resampling.LANCZOS)
    return np.asarray(resized)


class VisionExtractor:
    """Thin, retrying wrapper over one strict-tool-use extraction call."""

    def __init__(self, *, settings: Settings | None = None, client: object | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client  # injected in tests; lazily constructed otherwise

    def _ensure_client(self):  # noqa: ANN202 - anthropic.Anthropic has no light stub here
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise LlmExtractionError(
                "the 'anthropic' package is required for extraction; "
                "pip install anthropic"
            ) from exc
        # Credentials resolve from the environment (ANTHROPIC_API_KEY,
        # ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile) -- never read or
        # logged by this class.
        self._client = anthropic.Anthropic(
            timeout=self._settings.llm_timeout_seconds,
            max_retries=0,  # this class owns retry policy, so the SDK's own is disabled
        )
        return self._client

    def extract(
        self,
        pages: list[np.ndarray],
        *,
        ocr_pages: list[PageOcr] | None = None,
        document_hint: str | None = None,
    ) -> ExtractionResult:
        """Extract structured data from one document's page images.

        :param pages: RGB page rasters, in document order. Multiple pages are sent in
            one call when a parcel's record spans them (e.g. a Jamabandi continuation
            sheet), so the model can resolve references across the boundary.
        :param ocr_pages: The OCR ensemble's read of each page, rendered as a
            supporting text layer. Optional, but materially improves faint-scan
            accuracy -- the model cross-checks its own reading against it.
        :param document_hint: Free text about the document (declared format, state,
            source system) placed before the images, when the caller has it.
        :raises LlmRefusalError: on a policy decline.
        :raises LlmExtractionError: on any other unrecoverable failure.
        """
        if not pages:
            raise LlmExtractionError("extract() requires at least one page image")

        client = self._ensure_client()
        content: list[dict[str, object]] = []

        if document_hint:
            content.append({"type": "text", "text": document_hint})

        for page in pages:
            prepared = _downscale_if_needed(page, max_edge=self._settings.max_image_edge_px)
            media_type, data = _encode_image(prepared)
            content.append(
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
            )

        if ocr_pages:
            ocr_text = _render_ocr_layer(ocr_pages)
            content.append({"type": "text", "text": ocr_text})

        content.append(
            {
                "type": "text",
                "text": f"Call {_TOOL_NAME} now with your complete transcription of this document.",
            }
        )

        system_blocks = [
            {
                "type": "text",
                "text": EXTRACTION_SYSTEM_PROMPT,
                **(
                    {"cache_control": {"type": "ephemeral", "ttl": self._settings.llm_cache_ttl}}
                    if self._settings.llm_enable_prompt_caching
                    else {}
                ),
            }
        ]

        started = time.monotonic()
        response = self._call_with_retry(
            client,
            model=self._settings.llm_model,
            max_tokens=self._settings.llm_max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": content}],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            thinking={"type": "adaptive"},
            output_config={"effort": self._settings.llm_effort},
        )
        duration_ms = (time.monotonic() - started) * 1000

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            raise LlmRefusalError(
                "the model declined to extract this document", category=category
            )

        extraction = self._parse_tool_call(response)
        usage = response.usage
        token_usage = TokenUsage(
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

        return ExtractionResult(
            extraction=extraction,
            token_usage=token_usage,
            model=self._settings.llm_model,
            effort=self._settings.llm_effort,
            duration_ms=round(duration_ms, 2),
            stop_reason=str(response.stop_reason),
        )

    def _parse_tool_call(self, response: object) -> LlmExtraction:
        tool_use_block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use"), None
        )
        if tool_use_block is None:
            raise LlmExtractionError(
                "model response contained no tool_use block",
                context={"stop_reason": getattr(response, "stop_reason", None)},
            )
        try:
            # strict:true guarantees schema-validity, but never skip Pydantic
            # validation here -- see the API-drift note on tool-call JSON escaping;
            # this also gives a single, typed error path for a malformed response.
            return LlmExtraction.model_validate(tool_use_block.input)
        except Exception as exc:  # noqa: BLE001 - normalise every validation failure
            raise LlmExtractionError(
                f"tool call arguments failed schema validation: {exc}",
                context={"raw_input": tool_use_block.input},
            ) from exc

    def _call_with_retry(self, client: object, **kwargs: object) -> object:
        """Retry on transient failures; never retry a refusal or a bad request."""

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._settings.llm_max_retries + 1),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type(_TransientLlmError),
        )
        def _attempt() -> object:
            import anthropic

            try:
                return client.messages.create(**kwargs)
            except anthropic.RateLimitError as exc:
                raise _TransientLlmError(str(exc)) from exc
            except anthropic.APIStatusError as exc:
                if exc.status_code in _RETRYABLE_STATUS_CODES:
                    raise _TransientLlmError(str(exc)) from exc
                raise LlmExtractionError(
                    f"extraction request failed: {exc.message}",
                    context={"status_code": exc.status_code},
                ) from exc
            except anthropic.APIConnectionError as exc:
                raise _TransientLlmError(str(exc)) from exc

        try:
            return _attempt()
        except _TransientLlmError as exc:
            raise LlmExtractionError(
                f"extraction failed after {self._settings.llm_max_retries + 1} attempts: {exc}"
            ) from exc


class _TransientLlmError(Exception):
    """Internal marker for tenacity's retry predicate. Never escapes this module."""


def _render_ocr_layer(pages: list[PageOcr]) -> str:
    """Render the OCR ensemble's reading as a text layer, tables as markdown.

    This is explicitly framed to the model as approximate and secondary (see the
    system prompt's rule 1) -- its purpose is to catch cases where the image is
    ambiguous but the character-level OCR, imperfect as it is, still got the digits
    right.
    """
    parts = ["## OCR text layer (approximate; the image is authoritative on conflict)"]
    for page in pages:
        parts.append(f"\n### Page {page.page_index + 1}")
        if page.tables:
            for i, table in enumerate(page.tables):
                parts.append(f"\nTable {i + 1}:\n{table.to_markdown()}")
        else:
            parts.append(page.full_text)
    return "\n".join(parts)


def load_page_image(path: str | Path) -> np.ndarray:
    """Convenience loader for a single already-rasterised image file (test/demo use)."""
    from PIL import Image

    with Image.open(path) as handle:
        return np.asarray(handle.convert("RGB"))
