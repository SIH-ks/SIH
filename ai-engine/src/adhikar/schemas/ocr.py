"""Geometry and OCR primitives shared by the layout, OCR and LLM stages.

All coordinates are **normalised to [0, 1]** against the page they belong to. Scans
arrive at wildly different DPIs (150 dpi phone photos through 600 dpi flatbed TIFFs),
and normalised boxes let a bounding box survive the resize that happens before the
image is handed to the Vision LLM. Pixel coordinates are recoverable at any time via
:meth:`BoundingBox.to_pixels`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ExtractorKind

__all__ = [
    "BoundingBox",
    "OcrLine",
    "OcrToken",
    "PageOcr",
    "ScriptHistogram",
    "TableCell",
    "TableGrid",
]


class BoundingBox(BaseModel):
    """An axis-aligned box in normalised page space, origin at the top-left."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_index: int = Field(ge=0)
    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError(
                f"degenerate box: expected x0<=x1 and y0<=y1, got "
                f"({self.x0}, {self.y0}) -> ({self.x1}, {self.y1})"
            )
        return self

    @classmethod
    def from_pixels(
        cls, page_index: int, x0: float, y0: float, x1: float, y1: float, *, width: int, height: int
    ) -> BoundingBox:
        """Normalise a pixel-space box, clamping to the page.

        OCR engines occasionally return boxes a pixel or two outside the raster;
        clamping is correct here because the overflow is never meaningful.
        """
        if width <= 0 or height <= 0:
            raise ValueError(f"page dimensions must be positive, got {width}x{height}")

        def clamp(v: float) -> float:
            return min(1.0, max(0.0, v))

        return cls(
            page_index=page_index,
            x0=clamp(min(x0, x1) / width),
            y0=clamp(min(y0, y1) / height),
            x1=clamp(max(x0, x1) / width),
            y1=clamp(max(y0, y1) / height),
        )

    def to_pixels(self, *, width: int, height: int) -> tuple[int, int, int, int]:
        """Project back to integer pixel coordinates for cropping."""
        return (
            int(round(self.x0 * width)),
            int(round(self.y0 * height)),
            int(round(self.x1 * width)),
            int(round(self.y1 * height)),
        )

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def intersection_over_union(self, other: BoundingBox) -> float:
        """IoU, used to reconcile the two OCR engines' boxes for the same word."""
        if self.page_index != other.page_index:
            return 0.0
        ix0, iy0 = max(self.x0, other.x0), max(self.y0, other.y0)
        ix1, iy1 = min(self.x1, other.x1), min(self.y1, other.y1)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        intersection = (ix1 - ix0) * (iy1 - iy0)
        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0

    def contains_centre_of(self, other: BoundingBox) -> bool:
        """Whether ``other``'s centre falls inside this box.

        Preferred over full containment when assigning OCR tokens to table cells:
        a word that overruns a ruled line still belongs to the cell it starts in.
        """
        if self.page_index != other.page_index:
            return False
        cx, cy = other.centre
        return self.x0 <= cx <= self.x1 and self.y0 <= cy <= self.y1

    @classmethod
    def hull(cls, boxes: Iterable[BoundingBox]) -> BoundingBox | None:
        """Smallest box enclosing all inputs; ``None`` for an empty iterable."""
        items = list(boxes)
        if not items:
            return None
        page = items[0].page_index
        if any(b.page_index != page for b in items):
            raise ValueError("cannot take the hull of boxes on different pages")
        return cls(
            page_index=page,
            x0=min(b.x0 for b in items),
            y0=min(b.y0 for b in items),
            x1=max(b.x1 for b in items),
            y1=max(b.y1 for b in items),
        )


class OcrToken(BaseModel):
    """A single recognised word, with the engine that produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)
    engine: ExtractorKind
    script: str = "Unknown"
    """Dominant Unicode script name, e.g. ``Devanagari``, ``Latin``, ``Gujarati``."""


class OcrLine(BaseModel):
    """Tokens grouped into a reading-order line."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)
    tokens: tuple[OcrToken, ...] = ()

    @classmethod
    def from_tokens(cls, tokens: Iterable[OcrToken]) -> OcrLine | None:
        """Join tokens left-to-right into a line, or ``None`` if there are none."""
        items = sorted(tokens, key=lambda t: t.bbox.x0)
        if not items:
            return None
        hull = BoundingBox.hull(t.bbox for t in items)
        assert hull is not None  # non-empty by the guard above
        return cls(
            text=" ".join(t.text for t in items).strip(),
            bbox=hull,
            confidence=min(t.confidence for t in items),
            tokens=tuple(items),
        )


class TableCell(BaseModel):
    """One cell of a detected table grid.

    ``row``/``col`` are zero-based indices into the reconstructed grid, not the
    record's own printed column numbers -- mapping grid columns to semantic fields
    is the job of the Vision LLM stage, which sees the header text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    bbox: BoundingBox
    text: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tokens: tuple[OcrToken, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class TableGrid(BaseModel):
    """A reconstructed table: ruled-line intersections plus the text inside them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_index: int = Field(ge=0)
    bbox: BoundingBox
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    cells: tuple[TableCell, ...] = ()
    header_row_indices: tuple[int, ...] = ()
    detection_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    """Fraction of expected grid intersections that were actually found."""

    def cell(self, row: int, col: int) -> TableCell | None:
        for c in self.cells:
            if c.row == row and c.col == col:
                return c
        return None

    def row_cells(self, row: int) -> list[TableCell]:
        return sorted((c for c in self.cells if c.row == row), key=lambda c: c.col)

    def iter_rows(self) -> Iterator[list[TableCell]]:
        for r in range(self.n_rows):
            yield self.row_cells(r)

    def to_markdown(self) -> str:
        """Render as a pipe table.

        This is what gets handed to the Vision LLM alongside the page image: the model
        reads the picture for layout and the text for exact glyphs, which is far more
        reliable on faint Devanagari than either signal alone.
        """
        if self.n_rows == 0 or self.n_cols == 0:
            return ""
        lines: list[str] = []
        for r in range(self.n_rows):
            by_col = {c.col: c for c in self.row_cells(r)}
            values = [
                (by_col[c].text.replace("|", "\\|").replace("\n", " ") if c in by_col else "")
                for c in range(self.n_cols)
            ]
            lines.append("| " + " | ".join(values) + " |")
            if r in self.header_row_indices:
                lines.append("| " + " | ".join(["---"] * self.n_cols) + " |")
        return "\n".join(lines)


class ScriptHistogram(BaseModel):
    """Character counts per Unicode script -- drives OCR language selection."""

    model_config = ConfigDict(extra="forbid")

    counts: dict[str, int] = Field(default_factory=dict)

    @property
    def dominant(self) -> str:
        if not self.counts:
            return "Unknown"
        return max(self.counts.items(), key=lambda kv: kv[1])[0]

    @property
    def is_multilingual(self) -> bool:
        """True when two or more scripts each hold at least 10% of the characters.

        Jamabandi and 7/12 scans are routinely Devanagari + Latin numerals, which is
        exactly the case that defeats a single-language OCR configuration.
        """
        total = sum(self.counts.values())
        if total == 0:
            return False
        significant = [n for n in self.counts.values() if n / total >= 0.10]
        return len(significant) >= 2


class PageOcr(BaseModel):
    """Everything the OCR + layout stages learned about one page."""

    model_config = ConfigDict(extra="forbid")

    page_index: int = Field(ge=0)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    dpi: int = Field(default=300, gt=0)
    rotation_applied_deg: float = 0.0
    """Deskew angle applied during preprocessing; recorded so boxes stay explainable."""

    lines: tuple[OcrLine, ...] = ()
    tables: tuple[TableGrid, ...] = ()
    scripts: ScriptHistogram = Field(default_factory=ScriptHistogram)
    engines_used: tuple[ExtractorKind, ...] = ()

    @property
    def full_text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float:
        """Character-count-weighted mean line confidence.

        Weighting by length stops a single high-confidence stray mark from masking a
        long, badly-read line.
        """
        weighted = sum(line.confidence * max(1, len(line.text)) for line in self.lines)
        total = sum(max(1, len(line.text)) for line in self.lines)
        return weighted / total if total else 0.0

    @property
    def low_confidence_lines(self) -> tuple[OcrLine, ...]:
        return tuple(line for line in self.lines if line.confidence < 0.60)
