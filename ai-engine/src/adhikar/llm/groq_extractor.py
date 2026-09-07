"""Vision-LLM structured extraction via Groq's free-tier OpenAI-compatible API.

Groq is the zero-cost path -- a `GROQ_API_KEY` from
https://console.groq.com/keys needs no billing setup, which is why
:attr:`~adhikar.config.Settings.llm_provider` defaults to it. The tradeoff against
:class:`~adhikar.llm.extractor.VisionExtractor` (Anthropic) is in how structured
output is enforced:

**Strict tool use vs. JSON-mode-and-repair.** Anthropic's ``strict: true`` tool
schema makes malformed output physically impossible. Groq's vision-capable models
don't uniformly support tool calling alongside image input, so this extractor uses
JSON mode (``response_format: {"type": "json_object"}``) with the full JSON Schema
embedded in the prompt instead, and treats "the model didn't quite comply" as an
*expected* failure mode rather than an edge case: a parse or validation failure
re-prompts with the exact error attached, up to
:attr:`~adhikar.config.Settings.groq_max_json_repair_attempts` extra tries, before
raising. This recovers most of strict tool use's reliability without requiring the
provider to support it.

No prompt caching: Groq's API has no caching primitive equivalent to Anthropic's
``cache_control``, so every call pays full price for the system prompt. At Groq's
free-tier rate limits this is a non-issue in practice.
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import numpy as np

from ..config import Settings, get_settings
from ..exceptions import LlmExtractionError
from ..schemas.artifact import TokenUsage
from ..schemas.llm_contract import LlmExtraction
from ..schemas.ocr import PageOcr
from .base import ExtractionResult
from .prompts import EXTRACTION_SYSTEM_PROMPT
from .rendering import downscale_if_needed, encode_png_base64, render_ocr_layer

__all__ = ["GroqVisionExtractor"]

_RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}

_JSON_MODE_APPENDIX = """

## Output format

You do not have a tool to call. Respond with **one JSON object and nothing else** --
no markdown code fences, no commentary before or after it. The object must validate
against this JSON Schema exactly: every property listed under a "required" array
must be present (use `null` for a field you have no value for -- never omit it).

```json
{schema}
```
"""


def _strip_code_fence(text: str) -> str:
    """Remove a ```json ... ``` wrapper some open models add despite being asked
    not to. A no-op on already-bare JSON."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


class GroqVisionExtractor:
    """Vision extraction against Groq's OpenAI-compatible chat completions API."""

    def __init__(self, *, settings: Settings | None = None, client: object | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client  # injected in tests; lazily constructed otherwise

    def _ensure_client(self):  # noqa: ANN202 - groq.Groq has no light stub here
        if self._client is not None:
            return self._client
        try:
            import groq
        except ImportError as exc:
            raise LlmExtractionError(
                "the 'groq' package is required for the groq provider; pip install groq"
            ) from exc
        # Credentials resolve from GROQ_API_KEY -- never read or logged by this class.
        self._client = groq.Groq(
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

        Same contract as :meth:`adhikar.llm.extractor.VisionExtractor.extract` --
        see that docstring for the parameter semantics.

        :raises LlmExtractionError: on an unrecoverable transport failure, or when
            the model's output still fails schema validation after every repair
            attempt.
        """
        if not pages:
            raise LlmExtractionError("extract() requires at least one page image")

        client = self._ensure_client()
        schema = LlmExtraction.model_json_schema()
        system_prompt = EXTRACTION_SYSTEM_PROMPT + _JSON_MODE_APPENDIX.format(
            schema=json.dumps(schema, indent=2)
        )

        content: list[dict[str, Any]] = []
        if document_hint:
            content.append({"type": "text", "text": document_hint})

        for page in pages:
            prepared = downscale_if_needed(page, max_edge=self._settings.max_image_edge_px)
            data_url = f"data:image/png;base64,{encode_png_base64(prepared)}"
            content.append({"type": "image_url", "image_url": {"url": data_url}})

        if ocr_pages:
            content.append({"type": "text", "text": render_ocr_layer(ocr_pages)})

        content.append({"type": "text", "text": "Return the JSON object now."})

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]

        started = time.monotonic()
        total_usage = TokenUsage()
        max_attempts = 1 + self._settings.groq_max_json_repair_attempts

        for attempt in range(max_attempts):
            response = self._call_with_retry(
                client,
                model=self._settings.groq_model,
                max_completion_tokens=self._settings.groq_max_completion_tokens,
                response_format={"type": "json_object"},
                messages=messages,
            )
            usage = getattr(response, "usage", None)
            total_usage = total_usage + TokenUsage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )

            raw_text = response.choices[0].message.content or ""
            cleaned = _strip_code_fence(raw_text)

            try:
                parsed = json.loads(cleaned)
                extraction = LlmExtraction.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                if attempt < max_attempts - 1:
                    # Feed the exact failure back so the repair prompt targets the
                    # actual problem rather than asking the model to guess again.
                    messages.append({"role": "assistant", "content": raw_text})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"That response did not parse as valid JSON against the schema. "
                                f"Error: {exc}\n\n"
                                "Return ONLY the corrected JSON object -- no markdown fence, "
                                "no commentary."
                            ),
                        }
                    )
                    continue
                raise LlmExtractionError(
                    f"Groq response failed schema validation after {max_attempts} attempt(s): {exc}",
                    context={"raw_response": raw_text[:2000]},
                ) from exc

            duration_ms = (time.monotonic() - started) * 1000
            return ExtractionResult(
                extraction=extraction,
                token_usage=total_usage,
                model=self._settings.groq_model,
                effort=f"json_mode(attempts={attempt + 1})",
                duration_ms=round(duration_ms, 2),
                stop_reason=str(getattr(response.choices[0], "finish_reason", "stop")),
            )

        raise LlmExtractionError("unreachable: the repair loop above always returns or raises")  # pragma: no cover

    def _call_with_retry(self, client: object, **kwargs: object) -> object:
        """Retry on transient failures only; a validation failure is handled by the
        repair loop in :meth:`extract`, not here."""

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._settings.llm_max_retries + 1),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type(_TransientGroqError),
        )
        def _attempt() -> object:
            import groq

            try:
                return client.chat.completions.create(**kwargs)
            except groq.RateLimitError as exc:
                raise _TransientGroqError(str(exc)) from exc
            except groq.APIStatusError as exc:
                if exc.status_code in _RETRYABLE_STATUS_CODES:
                    raise _TransientGroqError(str(exc)) from exc
                raise LlmExtractionError(
                    f"Groq extraction request failed: {exc.message}",
                    context={"status_code": exc.status_code},
                ) from exc
            except groq.APIConnectionError as exc:
                raise _TransientGroqError(str(exc)) from exc

        try:
            return _attempt()
        except _TransientGroqError as exc:
            raise LlmExtractionError(
                f"Groq extraction failed after {self._settings.llm_max_retries + 1} attempts: {exc}"
            ) from exc


class _TransientGroqError(Exception):
    """Internal marker for tenacity's retry predicate. Never escapes this module."""
