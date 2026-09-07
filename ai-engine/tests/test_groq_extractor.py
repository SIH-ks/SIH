"""The Groq extraction path: JSON-mode request shape and the validate-and-repair loop.

Mirrors the rigor of the Anthropic extractor's own tests but exercises the behaviour
unique to a provider with no strict-schema guarantee: markdown-fence stripping,
re-prompting on a validation failure, and giving up after the configured number of
repair attempts.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from adhikar.config import Settings
from adhikar.exceptions import LlmExtractionError
from adhikar.llm.factory import build_extractor
from adhikar.llm.groq_extractor import (
    GroqVisionExtractor,
    _compact_schema_for_prompt,
    _parse_go_duration,
    _retry_after_seconds,
)

_SAMPLE_EXTRACTION = {
    "detected_record_format": "satbara_7_12",
    "detected_scripts": ["Devanagari"],
    "parcels": [
        {
            "jurisdiction": {
                "state": "Maharashtra",
                "district": None,
                "tehsil": None,
                "village": "Kondhwa",
                "hadbast_number": None,
                "revenue_year_raw": None,
                "fasli_year_raw": None,
            },
            "khata_number": None,
            "khatauni_number": None,
            "khasra_numbers": [],
            "survey_number": "142",
            "sub_survey_number": None,
            "total_area": {
                "raw_text": "0-80-05",
                "hectare": "0",
                "are": "80",
                "sq_metre": "05",
                "acre": None,
                "guntha": None,
                "kanal": None,
                "marla": None,
                "bigha": None,
                "biswa": None,
                "biswansi": None,
            },
            "classified_areas": [],
            "sub_divisions": [],
            "owners": [],
            "mutations": [],
            "encumbrances": [],
            "crops": [],
            "assessment_amount": None,
            "water_rate": None,
            "other_rights_remarks": None,
            "source_page_indices": [0],
        }
    ],
    "field_confidences": [],
    "unreadable_regions": [],
    "overall_confidence": 0.9,
    "notes": None,
}


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeUsage:
    prompt_tokens = 2000
    completion_tokens = 500


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        return next(self._responses)


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(responses)})()


@pytest.fixture
def image() -> np.ndarray:
    return np.zeros((80, 80, 3), dtype=np.uint8)


def test_clean_json_response(image: np.ndarray) -> None:
    fake = _FakeClient([_FakeResponse(json.dumps(_SAMPLE_EXTRACTION))])
    extractor = GroqVisionExtractor(settings=Settings(_env_file=None), client=fake)

    result = extractor.extract([image])

    assert len(result.extraction.parcels) == 1
    assert result.extraction.parcels[0].survey_number == "142"
    assert result.effort == "json_mode(attempts=1)"
    assert result.token_usage.input_tokens == 2000

    kwargs = fake.chat.completions.calls[0]
    assert kwargs["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in kwargs["messages"]] == ["system", "user"]
    assert any(c.get("type") == "image_url" for c in kwargs["messages"][1]["content"])


def test_markdown_fence_is_stripped(image: np.ndarray) -> None:
    fenced = "```json\n" + json.dumps(_SAMPLE_EXTRACTION) + "\n```"
    fake = _FakeClient([_FakeResponse(fenced)])
    extractor = GroqVisionExtractor(settings=Settings(_env_file=None), client=fake)

    result = extractor.extract([image])

    assert len(result.extraction.parcels) == 1


def test_invalid_json_triggers_one_repair_then_succeeds(image: np.ndarray) -> None:
    fake = _FakeClient([_FakeResponse("not json at all {{{"), _FakeResponse(json.dumps(_SAMPLE_EXTRACTION))])
    extractor = GroqVisionExtractor(
        settings=Settings(_env_file=None, groq_max_json_repair_attempts=2), client=fake
    )

    result = extractor.extract([image])

    assert result.effort == "json_mode(attempts=2)"
    assert len(fake.chat.completions.calls) == 2

    second_call_messages = fake.chat.completions.calls[1]["messages"]
    assert len(second_call_messages) == 4  # system, user, assistant(bad), user(repair)
    assert second_call_messages[-1]["role"] == "user"
    assert "did not parse" in second_call_messages[-1]["content"]


def test_exhausting_repair_attempts_raises(image: np.ndarray) -> None:
    fake = _FakeClient([_FakeResponse("bad"), _FakeResponse("still bad"), _FakeResponse("nope")])
    extractor = GroqVisionExtractor(
        settings=Settings(_env_file=None, groq_max_json_repair_attempts=2), client=fake
    )

    with pytest.raises(LlmExtractionError):
        extractor.extract([image])

    assert len(fake.chat.completions.calls) == 3  # 1 initial + 2 repairs


def test_extract_requires_at_least_one_page() -> None:
    extractor = GroqVisionExtractor(settings=Settings(_env_file=None), client=_FakeClient([]))
    with pytest.raises(LlmExtractionError):
        extractor.extract([])


def test_factory_selects_groq_by_default() -> None:
    extractor = build_extractor(Settings(_env_file=None))
    assert isinstance(extractor, GroqVisionExtractor)


def test_factory_selects_anthropic_when_configured() -> None:
    from adhikar.llm.extractor import VisionExtractor

    extractor = build_extractor(Settings(_env_file=None, llm_provider="anthropic"))
    assert isinstance(extractor, VisionExtractor)


# ==========================================================================================
# Schema compaction -- what actually gets billed against the free tier's token budget
# ==========================================================================================


_KEY_PRESERVING_CONTAINERS = ("properties", "$defs")
"""A ``properties``/``$defs`` mapping's own keys are field/type *names*, never
metadata -- the same JSON Schema structural fact `_compact_schema_for_prompt` has to
know. Sharing that one fact with the implementation is unavoidable for this test to
mean anything: without it, the test cannot tell "the `description` metadata key" from
"the field legitimately named `description`" any better than a naive implementation
can -- which is exactly the bug this test exists to catch (see
UnreadableRegion.description)."""


def _find_metadata_keys(node: object) -> set[str]:
    """Collect every ``description``/``title`` key used as *schema metadata*,
    skipping ``properties``/``$defs`` entries' own keys (field/type names)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _KEY_PRESERVING_CONTAINERS and isinstance(value, dict):
                for sub_value in value.values():
                    found |= _find_metadata_keys(sub_value)
                continue
            if key in ("description", "title"):
                found.add(key)
            found |= _find_metadata_keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _find_metadata_keys(item)
    return found


def test_compact_schema_drops_description_and_title_but_keeps_structure() -> None:
    from adhikar.schemas.llm_contract import LlmExtraction

    full = LlmExtraction.model_json_schema()
    assert _find_metadata_keys(full), "fixture assumption failed: the full schema should carry metadata keys"

    compact = _compact_schema_for_prompt(full)
    assert _find_metadata_keys(compact) == set()

    # Structural keys survive untouched -- compaction must not change what the
    # schema actually constrains, only how many tokens describing it costs.
    assert compact["type"] == full["type"]
    assert set(compact["properties"]) == set(full["properties"])
    assert compact["required"] == full["required"]
    assert set(compact["$defs"]) == set(full["$defs"])
    # The legitimately-named `description` property must survive as a property key.
    assert "description" in compact["$defs"]["UnreadableRegion"]["properties"]


def test_compact_schema_is_meaningfully_smaller() -> None:
    from adhikar.schemas.llm_contract import LlmExtraction

    full = LlmExtraction.model_json_schema()
    compact = _compact_schema_for_prompt(full)

    full_size = len(json.dumps(full))
    compact_size = len(json.dumps(compact, separators=(",", ":")))
    # The real-world number that motivated this function: ~17KB down to ~9KB.
    # Asserting "meaningfully smaller" rather than an exact byte count so the test
    # doesn't need updating every time a schema docstring changes by a few words.
    assert compact_size < full_size * 0.6


# ==========================================================================================
# Rate-limit retry: reading the server's own wait time instead of guessing
# ==========================================================================================


class _FakeHeaders(dict):
    """Case-sensitive stand-in is fine here -- Groq's real headers are lower-case
    and every call site below looks them up by their exact lower-case name."""


class _FakeHttpResponse:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = _FakeHeaders(headers)


class _FakeGroqStatusError(Exception):
    """Stands in for groq.APIStatusError: only `.response` is read by our code."""

    def __init__(self, headers: dict[str, str]) -> None:
        super().__init__("rate limited")
        self.response = _FakeHttpResponse(headers)


def _wrapped(headers: dict[str, str]) -> Exception:
    """Build a _TransientGroqError with __cause__ set, matching how
    `_call_with_retry` actually raises it (`raise _TransientGroqError(...) from exc`)."""
    from adhikar.llm.groq_extractor import _TransientGroqError

    cause = _FakeGroqStatusError(headers)
    try:
        raise _TransientGroqError("wrapped") from cause
    except _TransientGroqError as e:
        return e


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"retry-after": "5"}, 5.0),
        ({"x-ratelimit-reset-tokens": "12.342s"}, 12.342),
        ({"x-ratelimit-reset-tokens": "130ms"}, 0.13),
        ({"retry-after": "3", "x-ratelimit-reset-tokens": "99s"}, 3.0),  # standard header wins
        ({}, None),
        ({"x-ratelimit-reset-tokens": "not-a-duration"}, None),
    ],
)
def test_retry_after_seconds_reads_real_header_shapes(
    headers: dict[str, str], expected: float | None
) -> None:
    got = _retry_after_seconds(_wrapped(headers))
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_retry_after_seconds_handles_missing_response() -> None:
    """A connection error has no HTTP response at all -- must not raise."""
    from adhikar.llm.groq_extractor import _TransientGroqError

    try:
        raise _TransientGroqError("wrapped") from ConnectionError("boom")
    except _TransientGroqError as e:
        assert _retry_after_seconds(e) is None
