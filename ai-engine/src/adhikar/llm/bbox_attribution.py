"""Best-effort bounding-box attribution for extraction provenance.

The Vision LLM never reports pixel coordinates -- it transcribes text, and
:mod:`adhikar.llm.mapper` records that transcription's ``raw_text`` in each
:class:`FieldProvenance` entry, but nothing sets ``bbox``. This module fills that
in *after the fact*, by fuzzy-matching each entry's ``raw_text`` against the OCR
ensemble's own line-level boxes on every page and attaching the best match's box.

This is deliberately conservative: a fuzzy match below :data:`MATCH_THRESHOLD`
leaves ``bbox`` unset rather than attaching a wrong one. A missing highlight is an
honest "we don't know where this is on the page"; a wrong highlight is worse than
either, since it actively misdirects a reviewer toward text that isn't the field
in question.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from ..schemas.artifact import FieldProvenance
from ..schemas.ocr import PageOcr

__all__ = ["MATCH_THRESHOLD", "attach_bboxes"]

MATCH_THRESHOLD = 72.0
"""Minimum rapidfuzz partial-ratio score (0-100) to accept a line as the source of
a provenance entry's text. Partial-ratio (not a full-string ratio) is used because
a field's ``raw_text`` is routinely a substring of a longer printed line -- e.g. a
mutation cell's ``raw_text`` might be a few words out of a whole paragraph-length
line. Calibrated empirically against real extraction output: short numeric fields
(area figures, survey numbers) match cleanly above 85; free-text fields with heavier
OCR noise (names, remarks) can legitimately sit in the low 70s, so the floor is set
there rather than higher, at the cost of occasionally accepting a near-miss over
rejecting a real (but noisily-OCR'd) match.
"""


def attach_bboxes(
    provenance: dict[str, FieldProvenance], pages: list[PageOcr]
) -> dict[str, FieldProvenance]:
    """Return a copy of ``provenance`` with ``bbox`` filled in wherever a
    confident match was found against the page OCR.

    :param provenance: Path -> :class:`FieldProvenance`, as produced by
        :func:`adhikar.llm.mapper.map_extraction`. Entries that already carry a
        ``bbox`` (none do today, but a future extractor might) are left untouched.
    :param pages: The same :class:`PageOcr` list the pipeline is about to store on
        the artifact -- the line boxes being matched against.
    """
    candidate_lines = [line for page in pages for line in page.lines if line.text.strip()]
    if not candidate_lines:
        return dict(provenance)

    updated: dict[str, FieldProvenance] = {}
    for path, prov in provenance.items():
        if prov.bbox is not None or not prov.raw_text or not prov.raw_text.strip():
            updated[path] = prov
            continue

        best_line, best_score = None, 0.0
        for line in candidate_lines:
            score = fuzz.partial_ratio(prov.raw_text, line.text)
            if score > best_score:
                best_line, best_score = line, score

        if best_line is not None and best_score >= MATCH_THRESHOLD:
            updated[path] = prov.model_copy(update={"bbox": best_line.bbox})
        else:
            updated[path] = prov

    return updated
