"""Shared request-building helpers used by every Vision LLM provider.

Kept provider-agnostic and dependency-free (no Anthropic or Groq imports) so both
:mod:`adhikar.llm.extractor` and :mod:`adhikar.llm.groq_extractor` build their
requests from the same primitives instead of maintaining parallel copies.
"""

from __future__ import annotations

import base64
import io

import numpy as np

from ..schemas.ocr import PageOcr

__all__ = ["encode_png_base64", "downscale_if_needed", "render_ocr_layer"]


def encode_png_base64(image: np.ndarray) -> str:
    """PNG-encode a raster and return the base64 payload (no data-URL prefix)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def downscale_if_needed(image: np.ndarray, *, max_edge: int) -> np.ndarray:
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


def render_ocr_layer(pages: list[PageOcr]) -> str:
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
