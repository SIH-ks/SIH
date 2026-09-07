"""Selects a Vision LLM extractor implementation from settings.

The one place that needs to know provider choice exists -- :mod:`adhikar.pipeline`
calls :func:`build_extractor` and works only against
:class:`~adhikar.llm.base.VisionExtractorProtocol` from then on, so adding a third
backend means adding one branch here, never touching the orchestrator.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..exceptions import ConfigurationError
from .base import VisionExtractorProtocol

__all__ = ["build_extractor"]


def build_extractor(settings: Settings | None = None) -> VisionExtractorProtocol:
    """Construct the extractor named by ``settings.llm_provider``.

    :raises ConfigurationError: for a provider name outside the ones this factory
        knows -- unreachable in practice since :attr:`Settings.llm_provider` is a
        closed ``Literal``, but guarded explicitly rather than falling through.
    """
    settings = settings or get_settings()
    if settings.llm_provider == "groq":
        from .groq_extractor import GroqVisionExtractor

        return GroqVisionExtractor(settings=settings)
    if settings.llm_provider == "anthropic":
        from .extractor import VisionExtractor

        return VisionExtractor(settings=settings)
    raise ConfigurationError(  # pragma: no cover - unreachable via the Literal type
        f"unknown llm_provider {settings.llm_provider!r}; expected 'anthropic' or 'groq'"
    )
