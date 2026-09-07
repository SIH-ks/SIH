"""EasyOCR and Tesseract adapters behind one interface.

Neither engine is reliably best across the corpus this system targets: EasyOCR's deep
model handles degraded/low-contrast Devanagari conjuncts better, while Tesseract with
proper traineddata is often faster and more precise on clean, high-DPI scans and gives
denser word-level boxes. Rather than picking one, :mod:`adhikar.ocr.ensemble`
reconciles both -- which is only possible because they share this interface.

Both adapters degrade to :class:`~adhikar.exceptions.OcrEngineError` when their
backend is missing, so the pipeline can run (with a recorded warning) on whichever
engine actually installed on a given machine.
"""

from __future__ import annotations

import shutil
from typing import Protocol

import numpy as np

from ..config import Settings, get_settings
from ..exceptions import OcrEngineError
from ..normalize.numerals import detect_scripts
from ..schemas.enums import ExtractorKind
from ..schemas.ocr import BoundingBox, OcrToken

__all__ = ["EasyOcrEngine", "OcrEngine", "TesseractEngine", "build_engines"]


class OcrEngine(Protocol):
    """What every OCR adapter provides."""

    kind: ExtractorKind

    def recognise(self, image: np.ndarray, *, page_index: int) -> list[OcrToken]:
        """Return word-level tokens with normalised bounding boxes."""
        ...


class EasyOcrEngine:
    """Deep-learning OCR via EasyOCR. Best on low-contrast, degraded scans."""

    kind = ExtractorKind.OCR_EASYOCR

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._reader = None  # lazy: model weights load on first use, not at import

    def _ensure_reader(self):  # noqa: ANN202 - easyocr.Reader has no public type stub
        if self._reader is not None:
            return self._reader
        try:
            import easyocr
        except ImportError as exc:
            raise OcrEngineError(
                "easyocr is not installed; pip install easyocr, or disable it via "
                "ADHIKAR_ENABLE_EASYOCR=false",
                engine="easyocr",
            ) from exc
        try:
            self._reader = easyocr.Reader(
                self._settings.ocr_languages,
                gpu=self._settings.ocr_use_gpu,
                verbose=False,
            )
        except Exception as exc:  # noqa: BLE001 - easyocr raises assorted native errors
            raise OcrEngineError(
                f"failed to initialise EasyOCR reader: {exc}",
                engine="easyocr",
                context={"languages": self._settings.ocr_languages},
            ) from exc
        return self._reader

    def recognise(self, image: np.ndarray, *, page_index: int) -> list[OcrToken]:
        reader = self._ensure_reader()
        height, width = image.shape[:2]
        try:
            results = reader.readtext(image, detail=1, paragraph=False)
        except Exception as exc:  # noqa: BLE001
            raise OcrEngineError(
                f"EasyOCR recognition failed: {exc}", engine="easyocr", page_index=page_index
            ) from exc

        tokens: list[OcrToken] = []
        for polygon, text, confidence in results:
            text = text.strip()
            if not text or confidence < self._settings.ocr_min_token_confidence:
                continue
            xs = [p[0] for p in polygon]
            ys = [p[1] for p in polygon]
            bbox = BoundingBox.from_pixels(
                page_index, min(xs), min(ys), max(xs), max(ys), width=width, height=height
            )
            tokens.append(
                OcrToken(
                    text=text,
                    bbox=bbox,
                    confidence=float(confidence),
                    engine=self.kind,
                    script=detect_scripts(text).dominant,
                )
            )
        return tokens


class TesseractEngine:
    """LSTM OCR via the Tesseract binary. Fast and precise on clean high-DPI scans."""

    kind = ExtractorKind.OCR_TESSERACT

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._checked = False

    def _ensure_available(self) -> None:
        if self._checked:
            return
        try:
            import pytesseract
        except ImportError as exc:
            raise OcrEngineError(
                "pytesseract is not installed; pip install pytesseract and the "
                "Tesseract binary, or disable it via ADHIKAR_ENABLE_TESSERACT=false",
                engine="tesseract",
            ) from exc

        if self._settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._settings.tesseract_cmd
        elif shutil.which("tesseract") is None and not self._settings.tesseract_cmd:
            raise OcrEngineError(
                "tesseract binary not found on PATH; set ADHIKAR_TESSERACT_CMD to its "
                "location (common on Windows: 'C:\\\\Program Files\\\\Tesseract-OCR\\\\tesseract.exe')",
                engine="tesseract",
            )
        self._checked = True

    def recognise(self, image: np.ndarray, *, page_index: int) -> list[OcrToken]:
        self._ensure_available()
        import pytesseract
        from PIL import Image

        height, width = image.shape[:2]
        pil_image = Image.fromarray(image)

        try:
            data = pytesseract.image_to_data(
                pil_image,
                lang=self._settings.tesseract_languages,
                output_type=pytesseract.Output.DICT,
                config="--psm 6",  # assume a single uniform block of text -- true of a table cell/page crop
            )
        except Exception as exc:  # noqa: BLE001 - pytesseract wraps subprocess errors variably
            raise OcrEngineError(
                f"Tesseract recognition failed: {exc}",
                engine="tesseract",
                page_index=page_index,
                context={"languages": self._settings.tesseract_languages},
            ) from exc

        tokens: list[OcrToken] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = str(data["text"][i]).strip()
            raw_conf = data["conf"][i]
            try:
                confidence = max(0.0, float(raw_conf)) / 100.0
            except (TypeError, ValueError):
                confidence = 0.0
            if not text or confidence < self._settings.ocr_min_token_confidence:
                continue
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            if w <= 0 or h <= 0:
                continue
            bbox = BoundingBox.from_pixels(page_index, x, y, x + w, y + h, width=width, height=height)
            tokens.append(
                OcrToken(
                    text=text,
                    bbox=bbox,
                    confidence=confidence,
                    engine=self.kind,
                    script=detect_scripts(text).dominant,
                )
            )
        return tokens


def build_engines(settings: Settings | None = None) -> list[OcrEngine]:
    """Construct the configured engine set.

    Engines are constructed even when their backend is missing -- the failure
    surfaces lazily, on first :meth:`OcrEngine.recognise` call, which is where
    :mod:`adhikar.ocr.ensemble` catches it and degrades gracefully rather than
    failing the whole pipeline at startup.
    """
    settings = settings or get_settings()
    engines: list[OcrEngine] = []
    if settings.enable_easyocr:
        engines.append(EasyOcrEngine(settings=settings))
    if settings.enable_tesseract:
        engines.append(TesseractEngine(settings=settings))
    return engines
