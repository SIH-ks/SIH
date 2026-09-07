"""Multi-engine OCR reconciliation.

Running two OCR engines only helps if their disagreements are resolved sensibly.
The policy here:

* **Non-overlapping tokens** (IoU below :data:`OVERLAP_IOU_THRESHOLD`) are both kept
  -- each engine reads text the other missed, which happens often on mixed-script
  lines where one engine's language model is a poor fit for one of the scripts.
* **Overlapping tokens that agree** (case/whitespace-insensitive) are merged into one
  token whose confidence is boosted -- agreement between two independent models is
  real evidence.
* **Overlapping tokens that disagree** keep the higher-confidence reading as primary
  and record the other in :attr:`~adhikar.schemas.artifact.FieldProvenance.alternatives`
  (surfaced by the caller, not here) -- and the merged confidence is *penalised*, not
  averaged, because two engines disagreeing on the same glyphs is itself a signal
  that the text is genuinely hard to read.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from typing import NamedTuple

from ..config import Settings, get_settings
from ..exceptions import OcrEngineError, StageDegradedError
from ..normalize.numerals import detect_scripts
from ..schemas.enums import ExtractorKind
from ..schemas.ocr import BoundingBox, OcrLine, OcrToken, PageOcr
from .engines import OcrEngine, build_engines

__all__ = ["OVERLAP_IOU_THRESHOLD", "OcrEnsembleResult", "reconcile_tokens", "run_ocr_ensemble"]

OVERLAP_IOU_THRESHOLD = 0.30
"""Minimum box overlap to treat two engines' tokens as readings of the same word.

Set below 0.5 because the two engines rarely agree on exact box tightness even when
they agree on the text -- EasyOCR's polygons hug the glyph, Tesseract's word boxes
include more whitespace padding.
"""

_DISAGREEMENT_PENALTY = 0.85
"""Confidence multiplier applied when engines disagree on the same region."""

_AGREEMENT_BONUS = 1.10
"""Confidence multiplier applied when engines agree, capped at 1.0."""


def _texts_agree(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


@dataclass(slots=True)
class _EngineResult:
    kind: ExtractorKind
    tokens: list[OcrToken]
    error: OcrEngineError | None


class OcrEnsembleResult(NamedTuple):
    """Return shape of :func:`run_ocr_ensemble`."""

    page: PageOcr
    degradation: StageDegradedError | None
    """Set when at least one configured engine failed but the page still produced a
    result from the rest. The caller (the pipeline orchestrator) is responsible for
    recording this in ``ProcessingMetadata.warnings`` -- it is never raised."""


def run_ocr_ensemble(
    image: np.ndarray,
    *,
    page_index: int,
    dpi: int = 300,
    settings: Settings | None = None,
    engines: list[OcrEngine] | None = None,
) -> OcrEnsembleResult:
    """Run every configured OCR engine on one page and reconcile the results.

    :raises OcrEngineError: only when *every* configured engine fails -- a page with
        no text source at all is a genuine failure the caller must know about. A
        single engine failing while another succeeds is reported via the returned
        :attr:`OcrEnsembleResult.degradation` instead of raising.
    """
    settings = settings or get_settings()
    active_engines = engines if engines is not None else build_engines(settings)
    if not active_engines:
        raise OcrEngineError(
            "no OCR engines are configured", engine="none", page_index=page_index
        )

    results: list[_EngineResult] = []
    for engine in active_engines:
        try:
            tokens = engine.recognise(image, page_index=page_index)
            results.append(_EngineResult(kind=engine.kind, tokens=tokens, error=None))
        except OcrEngineError as exc:
            results.append(_EngineResult(kind=engine.kind, tokens=[], error=exc))

    succeeded = [r for r in results if r.error is None]
    if not succeeded:
        first_error = results[0].error
        assert first_error is not None  # non-empty results guaranteed by the loop above
        raise first_error

    degraded_note = None
    if len(succeeded) < len(results):
        failed_names = [r.kind.value for r in results if r.error is not None]
        degraded_note = StageDegradedError(
            f"OCR engine(s) unavailable: {', '.join(failed_names)}; continuing with "
            f"{', '.join(r.kind.value for r in succeeded)} only",
            page_index=page_index,
        )

    all_tokens = [t for r in succeeded for t in r.tokens]
    merged = reconcile_tokens(all_tokens) if len(succeeded) > 1 else all_tokens

    lines = _assemble_lines(merged)
    full_text = "\n".join(line.text for line in lines)

    height, width = image.shape[:2]
    page = PageOcr(
        page_index=page_index,
        width_px=width,
        height_px=height,
        dpi=dpi,
        lines=tuple(lines),
        scripts=detect_scripts(full_text),
        engines_used=tuple(r.kind for r in succeeded),
    )
    return OcrEnsembleResult(page=page, degradation=degraded_note)


def reconcile_tokens(tokens: list[OcrToken]) -> list[OcrToken]:
    """Merge overlapping tokens from different engines; keep the rest as-is.

    O(n^2) in token count, which is acceptable at page granularity (a dense land
    record page holds a few hundred tokens, not thousands).
    """
    if not tokens:
        return []

    by_engine: dict[ExtractorKind, list[OcrToken]] = {}
    for token in tokens:
        by_engine.setdefault(token.engine, []).append(token)

    if len(by_engine) < 2:
        return tokens

    engine_groups = list(by_engine.values())
    base, *others = sorted(engine_groups, key=len, reverse=True)
    consumed_others: set[int] = set()
    result: list[OcrToken] = []

    for token in base:
        best_match: OcrToken | None = None
        best_iou = OVERLAP_IOU_THRESHOLD
        best_ref: tuple[int, int] | None = None
        for gi, group in enumerate(others):
            for ti, candidate in enumerate(group):
                if (gi, ti) in consumed_others:
                    continue
                iou = token.bbox.intersection_over_union(candidate.bbox)
                if iou > best_iou:
                    best_iou, best_match, best_ref = iou, candidate, (gi, ti)

        if best_match is None:
            result.append(token)
            continue

        assert best_ref is not None
        consumed_others.add(best_ref)
        result.append(_merge_pair(token, best_match))

    # Tokens from the other engine(s) that never matched anything in the base group
    # are genuinely unique reads and are kept.
    for gi, group in enumerate(others):
        for ti, candidate in enumerate(group):
            if (gi, ti) not in consumed_others:
                result.append(candidate)

    return result


def _merge_pair(a: OcrToken, b: OcrToken) -> OcrToken:
    primary, secondary = (a, b) if a.confidence >= b.confidence else (b, a)
    agree = _texts_agree(a.text, b.text)
    multiplier = _AGREEMENT_BONUS if agree else _DISAGREEMENT_PENALTY
    merged_confidence = min(1.0, primary.confidence * multiplier)
    hull = BoundingBox.hull([a.bbox, b.bbox])
    assert hull is not None  # two boxes on the same page always have a hull
    return OcrToken(
        text=primary.text,
        bbox=hull,
        confidence=round(merged_confidence, 4),
        engine=ExtractorKind.OCR_ENSEMBLE,
        script=primary.script,
    )


def _assemble_lines(tokens: list[OcrToken]) -> list[OcrLine]:
    """Group tokens into reading-order lines by vertical proximity.

    Clusters on y-centre with a tolerance proportional to token height, then sorts
    each cluster left-to-right. This is a lightweight heuristic, not a text-layout
    model -- it is sufficient because table cell assignment (which is what downstream
    stages actually rely on) uses token boxes directly, not this line grouping.
    """
    if not tokens:
        return []

    sorted_tokens = sorted(tokens, key=lambda t: (t.bbox.centre[1], t.bbox.x0))
    clusters: list[list[OcrToken]] = []
    for token in sorted_tokens:
        placed = False
        token_height = max(token.bbox.height, 1e-6)
        for cluster in clusters:
            ref = cluster[-1]
            ref_height = max(ref.bbox.height, 1e-6)
            tolerance = 0.6 * max(token_height, ref_height)
            if abs(token.bbox.centre[1] - ref.bbox.centre[1]) <= tolerance:
                cluster.append(token)
                placed = True
                break
        if not placed:
            clusters.append([token])

    lines: list[OcrLine] = []
    for cluster in clusters:
        line = OcrLine.from_tokens(cluster)
        if line is not None:
            lines.append(line)
    return sorted(lines, key=lambda line: line.bbox.y0)
