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
import re
import time
from typing import Any

from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt

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


_SCHEMA_KEY_PRESERVING_CONTAINERS = ("properties", "$defs")
"""Object keys under these are field/type *names*, never schema metadata -- see the
:func:`_compact_schema_for_prompt` docstring for why that distinction is load-bearing."""


def _compact_schema_for_prompt(schema: dict[str, Any]) -> dict[str, Any]:
    """Shrink the JSON Schema before it goes into the prompt as literal tokens.

    ``LlmExtraction.model_json_schema()`` is written for a human reading Pydantic
    docs -- every field carries a ``description`` (often a full sentence) and a
    redundant ``title`` (the field name, re-cased). Embedded verbatim, the full
    schema for this domain model runs to ~4,300 tokens; on Groq's free tier that
    alone eats most of a request's budget before the image or system prompt are
    counted (see the module docstring). ``description``/``title`` exist for
    documentation, not for constraining the model's output shape, so they are
    dropped here -- structurally the schema (types, ``required``, ``enum``, ``$ref``)
    is untouched, and the *actual* :class:`LlmExtraction` class keeps its full
    docstrings for IDE/dev use regardless of what this function does.

    A naive "drop every ``description``/``title`` key at every level" is wrong: a
    ``properties`` (or ``$defs``) object's own keys are field (or type) *names*, not
    metadata, and this schema genuinely has a field called ``description``
    (:attr:`~adhikar.schemas.llm_contract.UnreadableRegion.description`). Filtering
    those keys the same way as metadata keys would silently delete that field from
    the compacted schema -- the model would never be told to produce it, `required`
    would go stale, and every document with an unreadable region would fail
    downstream Pydantic validation against the *real*, uncompacted
    :class:`LlmExtraction` for a reason nothing in the prompt explains. So a
    ``properties``/``$defs`` mapping's immediate keys are always preserved verbatim;
    only their *values* (each itself a schema) are compacted recursively.
    """
    if isinstance(schema, dict):
        result: dict[str, Any] = {}
        for key, value in schema.items():
            if key in ("description", "title"):
                continue
            if key in _SCHEMA_KEY_PRESERVING_CONTAINERS and isinstance(value, dict):
                result[key] = {name: _compact_schema_for_prompt(sub) for name, sub in value.items()}
            else:
                result[key] = _compact_schema_for_prompt(value)
        return result
    if isinstance(schema, list):
        return [_compact_schema_for_prompt(item) for item in schema]
    return schema


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
        compact_schema = _compact_schema_for_prompt(LlmExtraction.model_json_schema())
        # No indent=2: compact JSON is what actually gets tokenized and billed
        # against the free tier's per-minute input budget, and pretty-printing
        # roughly doubles the byte count for whitespace the model doesn't need.
        system_prompt = EXTRACTION_SYSTEM_PROMPT + _JSON_MODE_APPENDIX.format(
            schema=json.dumps(compact_schema, separators=(",", ":"))
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
        repair loop in :meth:`extract`, not here.

        Rate limits get their wait time from Groq's own response headers rather than
        a guessed exponential backoff. This matters concretely on the free tier: its
        per-minute token budget is small enough that one extraction call can consume
        most of it, and the reset window is measured in tens of seconds -- a
        1s/2s/4s exponential backoff never gets there and every retry just fails
        again. ``x-ratelimit-reset-tokens`` (confirmed present on live Groq
        responses; a Go-style duration string like ``"12.342s"`` or ``"130ms"``) or
        the standard ``retry-after`` header give the real number instead.
        """

        def _wait_seconds(retry_state) -> float:  # noqa: ANN001 - tenacity's RetryCallState
            outcome = retry_state.outcome
            exc = outcome.exception() if outcome is not None else None
            header_wait = _retry_after_seconds(exc) if exc is not None else None
            if header_wait is not None:
                return min(header_wait + 0.5, 65.0)  # small safety margin, sane ceiling
            # No usable header (a 5xx or a connection error, not a rate limit):
            # a short exponential backoff is the right shape for those.
            return min(1.0 * (2 ** (retry_state.attempt_number - 1)), 30.0)

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._settings.llm_max_retries + 1),
            wait=_wait_seconds,
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


_GO_DURATION_COMPONENT = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s)")
"""Matches one component of a Go-style duration string. ``ms`` is checked before the
bare ``m``/``s`` alternatives so "130ms" is not misread as "130m" + a stray "s"."""


def _parse_go_duration(text: str) -> float | None:
    """Parse a Go-style duration (``"12.342s"``, ``"130ms"``, ``"1m2.5s"``) to seconds.

    Returns ``None`` for a string with no recognisable component, rather than 0 --
    an unparseable header must fall through to the exponential-backoff default, not
    be read as "wait zero seconds."
    """
    total = 0.0
    matched = False
    for value, unit in _GO_DURATION_COMPONENT.findall(text):
        matched = True
        seconds_per_unit = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}[unit]
        total += float(value) * seconds_per_unit
    return total if matched else None


def _retry_after_seconds(exc: BaseException) -> float | None:
    """Extract a server-authoritative retry delay from a wrapped Groq exception.

    ``exc`` is the :class:`_TransientGroqError` raised in :meth:`_call_with_retry`,
    whose ``__cause__`` is the original ``groq.APIStatusError`` carrying the HTTP
    response. Checks the standard ``retry-after`` header first (seconds, per RFC
    9110), then Groq's own ``x-ratelimit-reset-tokens``. Returns ``None`` when
    neither is present or parseable -- e.g. a connection error has no response at
    all -- so the caller falls back to exponential backoff.
    """
    response = getattr(exc.__cause__, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    retry_after = headers.get("retry-after")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass  # some gateways send an HTTP-date instead of a seconds count here

    return _parse_go_duration(headers.get("x-ratelimit-reset-tokens", ""))
