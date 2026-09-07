"""The provider-agnostic extractor contract.

Every Vision LLM backend (Anthropic, Groq, ...) implements this one method with this
one return shape. :func:`adhikar.llm.factory.build_extractor` is the only place that
knows which concrete class a given :class:`~adhikar.config.Settings` selects --
:mod:`adhikar.pipeline` calls through this protocol and never imports a provider
module directly, so adding a third provider never touches the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..schemas.artifact import TokenUsage
from ..schemas.llm_contract import LlmExtraction
from ..schemas.ocr import PageOcr

import numpy as np

__all__ = ["ExtractionResult", "VisionExtractorProtocol"]


@dataclass(slots=True)
class ExtractionResult:
    """One extraction call's output plus its cost and latency accounting.

    Shared verbatim across providers -- ``model``/``effort`` are populated with
    whatever the provider's own vocabulary is (Groq has no ``effort`` concept, so it
    carries a fixed descriptive string instead of a fabricated value).
    """

    extraction: LlmExtraction
    token_usage: TokenUsage
    model: str
    effort: str
    duration_ms: float
    stop_reason: str


class VisionExtractorProtocol(Protocol):
    """What :mod:`adhikar.pipeline` requires from any Vision LLM backend."""

    def extract(
        self,
        pages: list[np.ndarray],
        *,
        ocr_pages: list[PageOcr] | None = None,
        document_hint: str | None = None,
    ) -> ExtractionResult: ...
