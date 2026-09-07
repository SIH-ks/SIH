"""Runtime configuration, sourced from the environment.

Everything tunable lives here so behaviour is reproducible from a recorded settings
snapshot. Nothing in this module reads a secret into a field or logs one -- each
provider SDK resolves its own credential directly from the process environment
(``GROQ_API_KEY`` for Groq; ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` / an
``ant auth login`` profile for Anthropic).

That last point is why this module loads ``.env`` into the *process* environment
via ``python-dotenv`` at import time, in addition to ``pydantic-settings``' own
``env_file`` support below: ``pydantic-settings`` only uses an env file to populate
its own ``ADHIKAR_``-prefixed fields on :class:`Settings` -- it never calls
``os.environ[...] = ...``, so a bare API key sitting in ``.env`` would otherwise be
invisible to the Groq/Anthropic SDKs, which read ``os.environ`` directly. The
``load_dotenv`` call never overwrites a variable already set in the real
environment (``override=False``), so an explicit `export`/CI secret always wins.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .exceptions import ConfigurationError

__all__ = ["Settings", "get_settings"]

# Populate os.environ from .env (ai-engine/.env, then a parent .env) before anything
# below -- or any provider SDK constructed later -- reads a credential. Silent when
# no file is present, which is the normal case in a deployed environment where
# credentials come from the platform instead.
_PACKAGE_ROOT_FOR_DOTENV = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PACKAGE_ROOT_FOR_DOTENV / ".env", override=False)
load_dotenv(_PACKAGE_ROOT_FOR_DOTENV.parent / ".env", override=False)

_PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_ROOT.parent.parent


class Settings(BaseSettings):
    """Engine settings. Every field is overridable by an ``ADHIKAR_``-prefixed env var."""

    model_config = SettingsConfigDict(
        env_prefix="ADHIKAR_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Vision LLM ---------------------------------------------------------------------
    llm_provider: Literal["anthropic", "groq"] = "groq"
    """Which backend :func:`adhikar.llm.factory.build_extractor` constructs.

    ``groq`` runs against Groq's free-tier OpenAI-compatible API (a `GROQ_API_KEY`
    from https://console.groq.com/keys, no billing setup required) -- the default so
    the pipeline is runnable with zero-cost credentials out of the box. ``anthropic``
    is the strict-tool-use path documented in :mod:`adhikar.llm.extractor`, with
    materially stronger accuracy on dense multilingual tables; switch to it for
    production accuracy once a paid key is available."""

    llm_model: str = "claude-opus-5"
    """Extraction model for the ``anthropic`` provider. Opus is the default because a
    misread khasra number is expensive to discover downstream and cheap to avoid here."""

    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    """Reasoning effort (``anthropic`` provider only). Faint multi-column Devanagari
    tables reward `high`; drop to `medium` for clean born-digital PDFs where the table
    structure is unambiguous."""

    llm_max_tokens: int = 32_000
    llm_timeout_seconds: float = 600.0
    llm_max_retries: int = 3

    llm_enable_prompt_caching: bool = True
    """The extraction prompt is a large fixed prefix (schema + few-shot layout guide);
    caching it cuts per-page input cost substantially across a batch. Anthropic only --
    Groq's API has no prompt-caching primitive."""

    llm_cache_ttl: Literal["5m", "1h"] = "1h"
    """1h suits batch ingestion runs, where the same prefix is reused for hours."""

    llm_input_usd_per_mtok: float = 5.00
    llm_output_usd_per_mtok: float = 25.00
    """Rates for cost attribution only (``anthropic`` provider). Update alongside the
    model choice. Groq's free tier is treated as zero-cost -- see
    :class:`~adhikar.llm.groq_extractor.GroqVisionExtractor`."""

    # -- Groq provider ------------------------------------------------------------------
    groq_model: str = "qwen/qwen3.8-27b"
    """A vision-capable model on Groq's free tier, confirmed live against
    ``client.models.list()`` -- each entry's ``input_modalities`` field says whether
    it accepts images (``["text", "image"]``) or text only. Groq's catalog moves
    faster than most providers' (models are added and retired on short notice), so
    if this ID stops resolving, find the current vision-capable one yourself rather
    than guessing from a model name:

    ```python
    import groq
    for m in groq.Groq().models.list().data:
        if "image" in m.input_modalities:
            print(m.id, m.supported_features)
    ```

    then override via ADHIKAR_GROQ_MODEL. Prefer one whose `supported_features`
    includes `json_mode` -- required by :class:`~adhikar.llm.groq_extractor.GroqVisionExtractor`."""

    groq_max_completion_tokens: int = 8_000
    groq_max_json_repair_attempts: int = 2
    """Groq's structured-output guarantee is weaker than Anthropic's strict tool use --
    an open model asked for JSON occasionally emits a trailing comment or truncates.
    On a parse/validation failure the extractor re-prompts with the error attached,
    up to this many extra attempts, before giving up."""

    # -- Rasterisation --------------------------------------------------------------------
    render_dpi: int = Field(default=300, ge=72, le=1200)
    """300 dpi is the floor for reliable Devanagari conjunct recognition. Below ~200
    the matras merge into the headline stroke and both OCR engines degrade sharply."""

    max_image_edge_px: int = Field(default=2400, ge=512)
    """Longest edge sent to the LLM. Larger costs tokens without helping accuracy."""

    max_pages_per_document: int = Field(default=50, ge=1)

    # -- Preprocessing -----------------------------------------------------------------------
    enable_deskew: bool = True
    max_deskew_angle_deg: float = Field(default=15.0, gt=0, le=45)
    """Beyond this the page is misfed rather than skewed; rotating it would be wrong."""

    enable_denoise: bool = True
    enable_adaptive_threshold: bool = True
    """Adaptive rather than global: scans of old registers have strong illumination
    gradients, and a global threshold erases whole columns."""

    # -- OCR ----------------------------------------------------------------------------------
    ocr_languages: list[str] = Field(default_factory=lambda: ["hi", "en"])
    """EasyOCR codes. 'hi' covers Devanagari (Hindi/Marathi); add 'gu', 'te', 'kn',
    'ta', 'bn' per state. Latin is kept alongside for numerals and English headers."""

    tesseract_languages: str = "hin+eng"
    """Tesseract traineddata names, '+'-joined. Add 'mar' for Marathi 7/12."""

    tesseract_cmd: str | None = None
    """Explicit path to the binary when it is not on PATH (typical on Windows)."""

    ocr_min_token_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    """Tokens below this are dropped before assembly -- they are noise, not text."""

    ocr_use_gpu: bool = False
    enable_easyocr: bool = True
    enable_tesseract: bool = True

    # -- Layout --------------------------------------------------------------------------------
    table_min_line_length_ratio: float = Field(default=0.30, ge=0.05, le=1.0)
    """A ruled line must span this fraction of the page to count as a table border."""

    table_cell_padding_px: int = Field(default=2, ge=0)

    # -- Validation ----------------------------------------------------------------------------
    validation_policy_path: Path = _PROJECT_ROOT / "policies" / "validation_policy.yaml"
    default_bigha_region: str | None = None
    """Set per-deployment (e.g. 'up_pucca') when the corpus is single-state. Left
    unset, bigha figures raise rather than being converted on a guess."""

    # -- Discrepancy engine -----------------------------------------------------------------------
    geometry_severe_threshold: float = Field(default=0.10, gt=0, le=1.0)
    """Relative area difference treated as 'severe'; anchors the 0-100 mismatch scale."""

    geometry_survey_tolerance: float = Field(default=0.005, gt=0, le=1.0)
    """Baseline cadastral survey tolerance before the source-accuracy multiplier."""

    auto_approve_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)

    # -- I/O ---------------------------------------------------------------------------------------
    artifact_output_dir: Path = _PROJECT_ROOT / "output"
    geometry_source_path: Path | None = None
    """GeoJSON / shapefile of cadastral polygons for cross-referencing."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    @field_validator("ocr_languages")
    @classmethod
    def _non_empty_languages(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("ocr_languages must name at least one language")
        return v

    @model_validator(mode="after")
    def _at_least_one_ocr_engine(self) -> Settings:
        if not (self.enable_easyocr or self.enable_tesseract):
            raise ConfigurationError(
                "both OCR engines are disabled; the pipeline would have no text source. "
                "Enable ADHIKAR_ENABLE_EASYOCR or ADHIKAR_ENABLE_TESSERACT."
            )
        return self

    @model_validator(mode="after")
    def _tolerance_ordering(self) -> Settings:
        if self.geometry_survey_tolerance >= self.geometry_severe_threshold:
            raise ConfigurationError(
                f"geometry_survey_tolerance ({self.geometry_survey_tolerance}) must be well "
                f"below geometry_severe_threshold ({self.geometry_severe_threshold}); otherwise "
                "every out-of-tolerance parcel scores as severe and the bands carry no signal."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so a mid-run environment change cannot make two stages disagree about
    tolerances. Call ``get_settings.cache_clear()`` in tests that need a fresh read.
    """
    return Settings()
