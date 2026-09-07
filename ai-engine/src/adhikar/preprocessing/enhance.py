"""Image conditioning: deskew, denoise, binarise.

Ordering matters and is not arbitrary:

1. **Grayscale** -- colour carries no information on a monochrome register scan.
2. **Deskew** -- before binarisation, so the rotation interpolates smooth gradients
   rather than hard black/white edges (which produces stair-stepped strokes).
3. **Denoise** -- before thresholding, so speckle does not become permanent ink.
4. **Adaptive threshold** -- last, and adaptive rather than global: bound registers
   photographed under one lamp have a strong illumination gradient across the gutter,
   and a global threshold erases the darker half of the page outright.

Deskew angle is returned rather than hidden, because every bounding box the OCR stage
produces is in the rotated frame and the artifact records the rotation so boxes stay
explainable against the original scan.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import Settings, get_settings
from ..exceptions import PreprocessingError

__all__ = ["PreparedPage", "prepare_page"]


@dataclass(slots=True)
class PreparedPage:
    """Conditioned rasters for one page, plus what was done to produce them."""

    page_index: int

    rgb: np.ndarray
    """Deskewed RGB. This is what the Vision LLM sees -- models read the original
    greyscale far better than a binarised image, which destroys stroke weight."""

    grayscale: np.ndarray
    binary: np.ndarray
    """Binarised, for morphological table-line detection only."""

    rotation_deg: float
    dpi: int
    notes: list[str]

    @property
    def height(self) -> int:
        return int(self.grayscale.shape[0])

    @property
    def width(self) -> int:
        return int(self.grayscale.shape[1])


def prepare_page(
    image: np.ndarray,
    *,
    page_index: int = 0,
    dpi: int = 300,
    settings: Settings | None = None,
) -> PreparedPage:
    """Condition one page raster.

    Degrades gracefully: if OpenCV is unavailable, the page passes through with a
    NumPy-only greyscale and threshold and a note recording the degradation. OCR
    quality drops, but the pipeline still produces a result rather than failing the
    whole batch on a missing wheel.

    :raises PreprocessingError: if the input is not an HxWx3 or HxW uint8 array.
    """
    settings = settings or get_settings()
    notes: list[str] = []

    if image.ndim not in (2, 3):
        raise PreprocessingError(
            f"expected a 2-D or 3-D array, got shape {image.shape}", page_index=page_index
        )
    if image.size == 0:
        raise PreprocessingError("page raster is empty", page_index=page_index)

    try:
        import cv2
    except ImportError:
        notes.append("OpenCV unavailable: deskew and denoise skipped, using a global threshold")
        return _prepare_without_cv2(image, page_index=page_index, dpi=dpi, notes=notes)

    rgb = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    rotation = 0.0
    if settings.enable_deskew:
        rotation = _estimate_skew(gray, settings, cv2)
        if abs(rotation) > 0.1:
            rgb = _rotate(rgb, rotation, cv2, border=(255, 255, 255))
            gray = _rotate(gray, rotation, cv2, border=255)
            notes.append(f"deskewed by {rotation:+.2f} deg")
        elif rotation == 0.0:
            notes.append("no reliable skew estimate; left unrotated")

    if settings.enable_denoise:
        # Median blur removes salt-and-pepper scanner speckle without softening the
        # thin horizontal headline stroke that Devanagari recognition depends on --
        # a Gaussian blur at this radius visibly damages it.
        gray = cv2.medianBlur(gray, 3)

    if settings.enable_adaptive_threshold:
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=35, C=11
        )
    else:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return PreparedPage(
        page_index=page_index,
        rgb=rgb,
        grayscale=gray,
        binary=binary,
        rotation_deg=rotation,
        dpi=dpi,
        notes=notes,
    )


def _estimate_skew(gray: np.ndarray, settings: Settings, cv2: object) -> float:
    """Estimate page skew from the dominant near-horizontal ruled lines.

    Table borders are the strongest orientation signal on a land record -- far more
    reliable than a text-baseline or minimum-area-rect estimate, both of which are
    thrown off by the dense mixed-script text. Returns 0.0 when no confident estimate
    exists; rotating on a bad estimate is worse than not rotating.
    """
    import cv2 as _cv2  # local alias keeps the signature dependency-free

    edges = _cv2.Canny(gray, 50, 150, apertureSize=3)
    min_length = int(min(gray.shape[:2]) * settings.table_min_line_length_ratio)
    lines = _cv2.HoughLinesP(
        edges, 1, np.pi / 720, threshold=100, minLineLength=max(50, min_length), maxLineGap=20
    )
    if lines is None or len(lines) == 0:
        return 0.0

    angles: list[float] = []
    for x0, y0, x1, y1 in lines[:, 0]:
        if x1 == x0:
            continue
        angle = np.degrees(np.arctan2(float(y1 - y0), float(x1 - x0)))
        # Keep near-horizontal lines only; vertical borders carry the same skew but
        # sit near 90 deg and would need unwrapping that adds no information.
        if abs(angle) <= settings.max_deskew_angle_deg:
            angles.append(angle)

    if len(angles) < 5:
        return 0.0

    # Median, not mean: a handful of diagonal strokes or a torn edge would drag a mean.
    return float(np.median(angles))


def _rotate(image: np.ndarray, angle_deg: float, cv2: object, *, border: object) -> np.ndarray:
    import cv2 as _cv2

    height, width = image.shape[:2]
    centre = (width / 2, height / 2)
    matrix = _cv2.getRotationMatrix2D(centre, angle_deg, 1.0)
    return _cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=_cv2.INTER_CUBIC,
        borderMode=_cv2.BORDER_CONSTANT,
        borderValue=border,
    )


def _prepare_without_cv2(
    image: np.ndarray, *, page_index: int, dpi: int, notes: list[str]
) -> PreparedPage:
    """NumPy-only fallback path."""
    if image.ndim == 3:
        # ITU-R 601-2 luma weights, matching PIL's "L" conversion.
        gray = (
            image[..., 0] * 0.299 + image[..., 1] * 0.587 + image[..., 2] * 0.114
        ).astype(np.uint8)
        rgb = image
    else:
        gray = image.astype(np.uint8)
        rgb = np.stack([gray] * 3, axis=-1)

    threshold = _otsu_threshold(gray)
    binary = np.where(gray > threshold, 255, 0).astype(np.uint8)

    return PreparedPage(
        page_index=page_index,
        rgb=rgb,
        grayscale=gray,
        binary=binary,
        rotation_deg=0.0,
        dpi=dpi,
        notes=notes,
    )


def _otsu_threshold(gray: np.ndarray) -> int:
    """Otsu's method, implemented directly so the fallback needs no OpenCV."""
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = histogram.sum()
    if total == 0:  # pragma: no cover - guarded by the empty-array check upstream
        return 127

    levels = np.arange(256)
    weight_bg = np.cumsum(histogram)
    weight_fg = total - weight_bg
    valid = (weight_bg > 0) & (weight_fg > 0)
    if not valid.any():  # pragma: no cover - a uniform page
        return 127

    cumulative_mean = np.cumsum(histogram * levels)
    global_mean = cumulative_mean[-1]
    mean_bg = np.divide(cumulative_mean, weight_bg, out=np.zeros(256), where=weight_bg > 0)
    mean_fg = np.divide(
        global_mean - cumulative_mean, weight_fg, out=np.zeros(256), where=weight_fg > 0
    )
    between_variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    between_variance[~valid] = -1.0
    return int(np.argmax(between_variance))
