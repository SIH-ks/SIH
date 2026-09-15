"""Assembling a succession case from documents.

Three ways a document reaches :func:`adhikar.validation.succession.validate_succession`,
in decreasing order of how much of the existing pipeline they reuse:

1. **A Record of Rights that the full pipeline already extracted.**
   :func:`snapshot_from_record` projects a
   :class:`~adhikar.schemas.land_record.LandParcelRecord` -- whatever
   ``process_document`` produced, OCR ensemble, Vision LLM, normalisation and all --
   onto a :class:`~adhikar.schemas.succession.RecordSnapshot`. No second extraction
   pass and no parallel schema.

2. **A structured payload** for the documents the RoR extraction contract does not
   cover (a death certificate is not a land record and has no table to parse).
   :func:`normalize_case` takes the raw, string-valued JSON an API caller or a
   registry integration supplies and runs it through the *same* deterministic
   normalisers the pipeline's mapping stage uses --
   :func:`~adhikar.normalize.vocab.parse_record_date`,
   :func:`~adhikar.normalize.vocab.parse_share`,
   :func:`~adhikar.normalize.vocab.resolve_relation`, the area unit machinery. What
   the LLM is to a Jamabandi table, the caller is to a death certificate; the
   interpretation is deterministic either way.

3. **An OCR text layer.** :func:`parse_document_text` reads the labelled fields off a
   death certificate or legal-heir certificate using the OCR ensemble's own output,
   for the case where nobody has keyed the document at all.

The split matters for honesty about coverage: (1) is the production path for land
records, (2) is the production path for everything else today, and (3) is a
best-effort convenience whose confidence is reported rather than assumed.
"""

from __future__ import annotations

from .extraction import (
    SUPPORTED_TEXT_DOCUMENTS,
    TextExtraction,
    normalize_case,
    parse_document_text,
    snapshot_from_record,
)

__all__ = [
    "SUPPORTED_TEXT_DOCUMENTS",
    "TextExtraction",
    "normalize_case",
    "parse_document_text",
    "snapshot_from_record",
]
