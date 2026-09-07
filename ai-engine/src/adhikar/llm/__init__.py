"""Vision-LLM structured extraction.

Two interchangeable backends behind :class:`~adhikar.llm.base.VisionExtractorProtocol`:
:class:`~adhikar.llm.extractor.VisionExtractor` (Anthropic, strict tool use) and
:class:`~adhikar.llm.groq_extractor.GroqVisionExtractor` (Groq, free tier, JSON mode
with validate-and-repair). :func:`build_extractor` selects one from
``settings.llm_provider`` -- callers that don't need to construct a specific backend
should use that rather than importing a provider module directly.
"""

from __future__ import annotations

from .base import ExtractionResult, VisionExtractorProtocol
from .factory import build_extractor

__all__ = ["ExtractionResult", "VisionExtractorProtocol", "build_extractor"]
