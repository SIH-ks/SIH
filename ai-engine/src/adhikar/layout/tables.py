"""Ruled-line table detection and grid reconstruction.

Approach: morphological extraction of long horizontal and vertical strokes from the
binarised page, intersected to recover grid line positions, which become row/column
boundaries. This is the classical approach for *ruled* tables -- and every Jamabandi
and 7/12 template is ruled -- and it is far more reliable here than a learned
table-detection model, which would need training data this project does not have and
would still lose to explicit geometry on a scanned government form with printed
borders.

Cells are populated with OCR tokens by containment (a token belongs to the cell
containing its centre), not by re-running OCR per cell -- token assignment is done
once by the caller (:mod:`adhikar.ocr.ensemble`) after this module returns the grid.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import Settings, get_settings
from ..exceptions import TableDetectionError
from ..schemas.ocr import BoundingBox, OcrToken, TableCell, TableGrid

__all__ = ["GridLines", "assign_tokens_to_grid", "detect_grid_lines", "detect_table_grids"]


@dataclass(slots=True)
class GridLines:
    """Pixel positions of detected ruled lines, in the page's own frame."""

    horizontal_y: list[int]
    vertical_x: list[int]
    bbox_px: tuple[int, int, int, int]
    """(x0, y0, x1, y1) bounding the detected grid."""

    @property
    def n_rows(self) -> int:
        return max(0, len(self.horizontal_y) - 1)

    @property
    def n_cols(self) -> int:
        return max(0, len(self.vertical_x) - 1)


def detect_grid_lines(binary: np.ndarray, *, settings: Settings | None = None) -> list[GridLines]:
    """Find ruled-line grids in a binarised page.

    Returns one :class:`GridLines` per connected grid structure found -- a page with
    a header table and a body table below it yields two. Returns an empty list rather
    than raising when no grid is found (blank pages, or pages that are pure text);
    that is a normal document shape, not an error.
    """
    settings = settings or get_settings()
    try:
        import cv2
    except ImportError as exc:
        raise TableDetectionError("OpenCV is required for table grid detection") from exc

    if binary.ndim != 2:
        raise TableDetectionError(f"expected a 2-D binary image, got shape {binary.shape}")

    # The caller's THRESH_BINARY output has ink (dark) as low values on a light
    # background. Structuring-element erosion needs the foreground (ink) as the high
    # value, so invert before morphology.
    inverted = cv2.bitwise_not(binary)

    height, width = inverted.shape
    h_len = max(15, int(width * settings.table_min_line_length_ratio))
    v_len = max(15, int(height * settings.table_min_line_length_ratio))

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))

    horizontal = cv2.erode(inverted, h_kernel, iterations=1)
    horizontal = cv2.dilate(horizontal, h_kernel, iterations=1)

    vertical = cv2.erode(inverted, v_kernel, iterations=1)
    vertical = cv2.dilate(vertical, v_kernel, iterations=1)

    grid_mask = cv2.bitwise_or(horizontal, vertical)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(grid_mask, connectivity=8)

    grids: list[GridLines] = []
    for label in range(1, n_labels):
        x, y, w, h, area = stats[label]
        if w < h_len or h < v_len or area < (h_len * v_len * 0.02):
            continue  # too small to be a real table region

        region_h = horizontal[y : y + h, x : x + w]
        region_v = vertical[y : y + h, x : x + w]

        h_rows = _line_positions(region_h, axis=0)
        v_cols = _line_positions(region_v, axis=1)

        if len(h_rows) < 2 or len(v_cols) < 2:
            continue  # a single stroke is a border, not a grid

        grids.append(
            GridLines(
                horizontal_y=[y + r for r in h_rows],
                vertical_x=[x + c for c in v_cols],
                bbox_px=(int(x), int(y), int(x + w), int(y + h)),
            )
        )

    return grids


def _line_positions(mask: np.ndarray, *, axis: int) -> list[int]:
    """Cluster a morphology mask's ink into line-centre coordinates.

    ``axis=0`` collapses columns to find horizontal line y-positions; ``axis=1``
    collapses rows to find vertical line x-positions.
    """
    profile = mask.sum(axis=1) if axis == 0 else mask.sum(axis=0)
    ink = np.where(profile > profile.max() * 0.3)[0] if profile.max() > 0 else np.array([], dtype=int)
    if ink.size == 0:
        return []

    positions: list[int] = []
    run_start = ink[0]
    prev = ink[0]
    for value in ink[1:]:
        if value - prev > 3:  # gap: end of one ruled line, start of the next
            positions.append(int((run_start + prev) // 2))
            run_start = value
        prev = value
    positions.append(int((run_start + prev) // 2))
    return positions


def detect_table_grids(
    binary: np.ndarray,
    *,
    page_index: int,
    page_width: int,
    page_height: int,
    settings: Settings | None = None,
) -> list[TableGrid]:
    """Detect ruled tables and return empty (unpopulated) :class:`TableGrid` objects.

    Cell text is filled in afterwards by :func:`assign_tokens_to_grid` using the OCR
    ensemble's tokens; this function only establishes the geometry, which is the part
    a non-text morphological pass can determine reliably.
    """
    settings = settings or get_settings()
    raw_grids = detect_grid_lines(binary, settings=settings)

    tables: list[TableGrid] = []
    for grid in raw_grids:
        cells: list[TableCell] = []
        for row in range(grid.n_rows):
            y0, y1 = grid.horizontal_y[row], grid.horizontal_y[row + 1]
            for col in range(grid.n_cols):
                x0, x1 = grid.vertical_x[col], grid.vertical_x[col + 1]
                if y1 <= y0 or x1 <= x0:
                    continue
                bbox = BoundingBox.from_pixels(
                    page_index, x0, y0, x1, y1, width=page_width, height=page_height
                )
                cells.append(TableCell(row=row, col=col, bbox=bbox))

        expected_intersections = grid.n_rows * grid.n_cols
        detection_confidence = len(cells) / expected_intersections if expected_intersections else 0.0

        hull = BoundingBox.from_pixels(page_index, *grid.bbox_px, width=page_width, height=page_height)
        tables.append(
            TableGrid(
                page_index=page_index,
                bbox=hull,
                n_rows=grid.n_rows,
                n_cols=grid.n_cols,
                cells=tuple(cells),
                header_row_indices=(0,) if grid.n_rows > 0 else (),
                detection_confidence=round(detection_confidence, 4),
            )
        )

    return tables


def assign_tokens_to_grid(grid: TableGrid, tokens: list[OcrToken]) -> TableGrid:
    """Populate cell text from OCR tokens by centre-containment.

    Kept separate from detection so grid geometry can be unit-tested without any OCR
    engine installed, and so the OCR ensemble does not need to import table geometry.
    """
    new_cells: list[TableCell] = []
    for cell in grid.cells:
        owned = [t for t in tokens if cell.bbox.contains_centre_of(t.bbox)]
        if not owned:
            new_cells.append(cell)
            continue
        ordered = sorted(owned, key=lambda t: (round(t.bbox.y0, 3), t.bbox.x0))
        text = " ".join(t.text for t in ordered).strip()
        confidence = sum(t.confidence for t in ordered) / len(ordered)
        new_cells.append(
            cell.model_copy(
                update={"text": text, "confidence": round(confidence, 4), "tokens": tuple(ordered)}
            )
        )

    return grid.model_copy(update={"cells": tuple(new_cells)})
