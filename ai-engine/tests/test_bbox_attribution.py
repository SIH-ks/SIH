"""Bounding-box attribution: fuzzy-matching provenance raw_text against OCR lines."""

from __future__ import annotations

from adhikar.llm.bbox_attribution import attach_bboxes
from adhikar.schemas.artifact import FieldProvenance
from adhikar.schemas.enums import ExtractorKind
from adhikar.schemas.ocr import BoundingBox, OcrLine, PageOcr


def _line(page_index: int, text: str, x0: float, confidence: float = 0.9) -> OcrLine:
    return OcrLine(
        text=text,
        bbox=BoundingBox(page_index=page_index, x0=x0, y0=0.2, x1=x0 + 0.2, y1=0.25),
        confidence=confidence,
    )


def _prov(raw_text: str | None) -> FieldProvenance:
    return FieldProvenance(extractor=ExtractorKind.VISION_LLM, confidence=0.95, raw_text=raw_text)


def _pages(*lines: OcrLine) -> list[PageOcr]:
    return [PageOcr(page_index=0, width_px=1000, height_px=1400, lines=tuple(lines))]


def test_exact_text_match_gets_the_lines_bbox() -> None:
    pages = _pages(_line(0, "0-80-05 (H-R-Sq.M)", x0=0.1), _line(0, "Owner: Ramrao Patil", x0=0.1))
    provenance = {"total_area": _prov("0-80-05 (H-R-Sq.M)")}

    result = attach_bboxes(provenance, pages)

    assert result["total_area"].bbox is not None
    assert result["total_area"].bbox.x0 == 0.1


def test_raw_text_as_a_substring_of_a_longer_line_still_matches() -> None:
    """A field's raw_text is routinely shorter than the printed line it sits in --
    partial-ratio matching, not exact equality, is the point of this module."""
    pages = _pages(_line(0, "Owner Name: Ramrao Patil s/o Ganpat, Sr. No. 1", x0=0.05))
    provenance = {"owners[0].name.raw_name": _prov("Ramrao Patil s/o Ganpat")}

    result = attach_bboxes(provenance, pages)

    assert result["owners[0].name.raw_name"].bbox is not None


def test_no_matching_line_leaves_bbox_unset() -> None:
    """A field whose text appears nowhere on the page must not get a fabricated
    box -- an absent highlight is honest; a wrong one actively misleads."""
    pages = _pages(_line(0, "Completely unrelated printed text", x0=0.1))
    provenance = {"total_area": _prov("0-80-05")}

    result = attach_bboxes(provenance, pages)

    assert result["total_area"].bbox is None


def test_entry_with_no_raw_text_is_left_untouched() -> None:
    pages = _pages(_line(0, "0-80-05", x0=0.1))
    provenance = {"total_area": _prov(None)}

    result = attach_bboxes(provenance, pages)

    assert result["total_area"].bbox is None
    assert result["total_area"] is provenance["total_area"]  # untouched, not just unset


def test_existing_bbox_is_never_overwritten() -> None:
    existing_bbox = BoundingBox(page_index=0, x0=0.5, y0=0.5, x1=0.6, y1=0.55)
    pre_set = FieldProvenance(
        extractor=ExtractorKind.VISION_LLM, confidence=0.95, raw_text="0-80-05", bbox=existing_bbox
    )
    pages = _pages(_line(0, "0-80-05", x0=0.1))  # a different, better-looking match

    result = attach_bboxes({"total_area": pre_set}, pages)

    assert result["total_area"].bbox is existing_bbox


def test_empty_pages_returns_provenance_unchanged() -> None:
    provenance = {"total_area": _prov("0-80-05")}
    result = attach_bboxes(provenance, [])
    assert result["total_area"].bbox is None


def test_picks_the_best_match_among_multiple_similar_lines() -> None:
    pages = _pages(
        _line(0, "0-80-00", x0=0.1),  # close but not exact
        _line(0, "0-80-05", x0=0.4),  # exact match
    )
    provenance = {"total_area": _prov("0-80-05")}

    result = attach_bboxes(provenance, pages)

    assert result["total_area"].bbox is not None
    assert result["total_area"].bbox.x0 == 0.4
