"""Adhikar -- Intelligent Land Record Digitization and Validation System.

Built for SIH26018 (Ministry of Rural Development): OCR + Vision-LLM extraction,
deterministic arithmetic validation, and geospatial discrepancy scoring for Jamabandi
and 7/12 Extract land records.

The public entry point for most callers is :func:`adhikar.pipeline.process_document`.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
