"""Vernacular term resolution, share parsing and date parsing.

This module is where the LLM's *transcription* becomes the domain model's
*classification*. Keeping that step here -- deterministic, unit-tested, and auditable
-- rather than asking the model to pick enum members directly is the central design
choice of the extraction pipeline: a lookup that misses produces ``UNKNOWN`` plus an
``UNRESOLVED_VOCABULARY`` finding, whereas a model that misses produces a confident
wrong answer that nothing downstream can detect.

Matching is three-tier: exact, then normalised-exact (punctuation and diacritic
folding), then fuzzy above :data:`FUZZY_THRESHOLD`. The fuzzy tier exists because OCR
mangles long conjuncts -- ``भोगवटादार`` routinely arrives as ``भागवटादार`` -- and the
threshold is high enough that unrelated terms do not cross it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Generic, TypeVar

from ..schemas.enums import (
    VERNACULAR_ALIASES,
    EncumbranceStatus,
    EncumbranceType,
    IrrigationSource,
    LandClassification,
    MutationStatus,
    MutationType,
    RelationType,
    TenureType,
)
from ..schemas.land_record import OwnershipShare
from .numerals import parse_decimal, to_ascii_digits

__all__ = [
    "FUZZY_THRESHOLD",
    "VocabMatch",
    "is_equal_share_marker",
    "parse_record_date",
    "parse_share",
    "resolve_classification",
    "resolve_encumbrance_status",
    "resolve_encumbrance_type",
    "resolve_irrigation",
    "resolve_mutation_status",
    "resolve_mutation_type",
    "resolve_relation",
    "resolve_tenure",
]

FUZZY_THRESHOLD = 0.86
"""Minimum similarity for a fuzzy vocabulary match.

Chosen so that single-character OCR substitutions in a 6+ character term still match
(``भोगवटादार``/``भागवटादार`` scores ~0.89) while genuinely different terms of similar
length stay below it. Lowering this trades unresolved terms for silent misclassification.
"""

T = TypeVar("T")

try:  # pragma: no cover - exercised by whichever backend is installed
    from rapidfuzz.distance import JaroWinkler

    def _similarity(a: str, b: str) -> float:
        return float(JaroWinkler.normalized_similarity(a, b))

except ImportError:  # pragma: no cover - stdlib fallback keeps the package importable
    from difflib import SequenceMatcher

    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True, slots=True)
class VocabMatch(Generic[T]):
    """The outcome of resolving one vernacular term."""

    value: T
    raw: str | None
    matched_key: str | None
    score: float
    resolved: bool

    @property
    def is_fuzzy(self) -> bool:
        return self.resolved and self.score < 1.0


def _fold(text: str) -> str:
    """Normalise for comparison: NFKC, digits to ASCII, punctuation and spaces out.

    NFKC first so that pre-composed and decomposed Devanagari forms -- which OCR
    engines emit interchangeably for the same glyph -- compare equal.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = to_ascii_digits(folded).lower()
    folded = re.sub(r"[\s\-_.,/()\[\]:;'\"]+", " ", folded)
    return folded.strip()


def _resolve(
    raw: str | None,
    table: dict[str, T],
    unknown: T,
) -> VocabMatch[T]:
    """Three-tier lookup against a surface-form table."""
    if raw is None or not raw.strip():
        return VocabMatch(value=unknown, raw=raw, matched_key=None, score=0.0, resolved=False)

    if raw in table:
        return VocabMatch(value=table[raw], raw=raw, matched_key=raw, score=1.0, resolved=True)

    folded = _fold(raw)
    folded_table = {_fold(k): (k, v) for k, v in table.items()}
    if folded in folded_table:
        key, value = folded_table[folded]
        return VocabMatch(value=value, raw=raw, matched_key=key, score=1.0, resolved=True)

    # Substring containment: cells often carry the term inside a longer phrase,
    # e.g. "इतर हक्क: गहाण बँक ऑफ महाराष्ट्र".
    for candidate_folded, (key, value) in folded_table.items():
        if len(candidate_folded) >= 4 and candidate_folded in folded:
            return VocabMatch(value=value, raw=raw, matched_key=key, score=0.95, resolved=True)

    best_key, best_value, best_score = None, unknown, 0.0
    for candidate_folded, (key, value) in folded_table.items():
        score = _similarity(folded, candidate_folded)
        if score > best_score:
            best_key, best_value, best_score = key, value, score

    if best_score >= FUZZY_THRESHOLD:
        return VocabMatch(value=best_value, raw=raw, matched_key=best_key, score=best_score, resolved=True)

    return VocabMatch(value=unknown, raw=raw, matched_key=None, score=best_score, resolved=False)


# --------------------------------------------------------------------------------------
# Alias tables derived from the shared vocabulary, plus type-specific additions
# --------------------------------------------------------------------------------------

_CLASSIFICATION_TABLE: dict[str, LandClassification] = {
    k: v for k, v in VERNACULAR_ALIASES.items() if isinstance(v, LandClassification)
}
_TENURE_TABLE: dict[str, TenureType] = {
    k: v for k, v in VERNACULAR_ALIASES.items() if isinstance(v, TenureType)
}
_MUTATION_TYPE_TABLE: dict[str, MutationType] = {
    k: v for k, v in VERNACULAR_ALIASES.items() if isinstance(v, MutationType)
}

_MUTATION_STATUS_TABLE: dict[str, MutationStatus] = {
    "sanctioned": MutationStatus.SANCTIONED,
    "approved": MutationStatus.SANCTIONED,
    "manjur": MutationStatus.SANCTIONED,
    "मंजूर": MutationStatus.SANCTIONED,
    "मंजुर": MutationStatus.SANCTIONED,
    "pending": MutationStatus.PENDING,
    "pralambit": MutationStatus.PENDING,
    "प्रलंबित": MutationStatus.PENDING,
    "rejected": MutationStatus.REJECTED,
    "napasand": MutationStatus.REJECTED,
    "नामंजूर": MutationStatus.REJECTED,
    "disputed": MutationStatus.DISPUTED,
    "tantamukt": MutationStatus.DISPUTED,
    "वादग्रस्त": MutationStatus.DISPUTED,
}

_ENCUMBRANCE_TYPE_TABLE: dict[str, EncumbranceType] = {
    "mortgage": EncumbranceType.MORTGAGE,
    "gahan": EncumbranceType.MORTGAGE,
    "गहाण": EncumbranceType.MORTGAGE,
    "rehan": EncumbranceType.MORTGAGE,
    "boja": EncumbranceType.BANK_CHARGE,
    "बोजा": EncumbranceType.BANK_CHARGE,
    "bank charge": EncumbranceType.BANK_CHARGE,
    "कर्ज": EncumbranceType.BANK_CHARGE,
    "kcc": EncumbranceType.BANK_CHARGE,
    "injunction": EncumbranceType.COURT_INJUNCTION,
    "stay order": EncumbranceType.COURT_INJUNCTION,
    "मनाई हुकूम": EncumbranceType.COURT_INJUNCTION,
    "acquisition": EncumbranceType.GOVERNMENT_ACQUISITION,
    "bhusampadan": EncumbranceType.GOVERNMENT_ACQUISITION,
    "भूसंपादन": EncumbranceType.GOVERNMENT_ACQUISITION,
    "tenancy": EncumbranceType.TENANCY_RIGHT,
    "kul hakk": EncumbranceType.TENANCY_RIGHT,
    "कुळ हक्क": EncumbranceType.TENANCY_RIGHT,
    "lis pendens": EncumbranceType.LIS_PENDENS,
    "attachment": EncumbranceType.ATTACHMENT,
    "japti": EncumbranceType.ATTACHMENT,
    "जप्ती": EncumbranceType.ATTACHMENT,
}

_ENCUMBRANCE_STATUS_TABLE: dict[str, EncumbranceStatus] = {
    "active": EncumbranceStatus.ACTIVE,
    "chalu": EncumbranceStatus.ACTIVE,
    "चालू": EncumbranceStatus.ACTIVE,
    "subsisting": EncumbranceStatus.ACTIVE,
    "discharged": EncumbranceStatus.DISCHARGED,
    "released": EncumbranceStatus.DISCHARGED,
    "fak": EncumbranceStatus.DISCHARGED,
    "कमी केला": EncumbranceStatus.DISCHARGED,
    "मुक्त": EncumbranceStatus.DISCHARGED,
}

_IRRIGATION_TABLE: dict[str, IrrigationSource] = {
    "canal": IrrigationSource.CANAL,
    "nahar": IrrigationSource.CANAL,
    "कालवा": IrrigationSource.CANAL,
    "नहर": IrrigationSource.CANAL,
    "well": IrrigationSource.WELL,
    "kuan": IrrigationSource.WELL,
    "विहीर": IrrigationSource.WELL,
    "tubewell": IrrigationSource.TUBEWELL,
    "borewell": IrrigationSource.TUBEWELL,
    "कूपनलिका": IrrigationSource.TUBEWELL,
    "tank": IrrigationSource.TANK,
    "talav": IrrigationSource.TANK,
    "तलाव": IrrigationSource.TANK,
    "rain fed": IrrigationSource.RAIN_FED,
    "barani": IrrigationSource.RAIN_FED,
    "जिरायत": IrrigationSource.RAIN_FED,
    "lift": IrrigationSource.LIFT,
    "उपसा": IrrigationSource.LIFT,
}

_RELATION_TABLE: dict[str, RelationType] = {
    "s/o": RelationType.SON_OF,
    "so": RelationType.SON_OF,
    "son of": RelationType.SON_OF,
    "बिन": RelationType.SON_OF,
    "वल्द": RelationType.SON_OF,
    "पुत्र": RelationType.SON_OF,
    "मुलगा": RelationType.SON_OF,
    "d/o": RelationType.DAUGHTER_OF,
    "do": RelationType.DAUGHTER_OF,
    "daughter of": RelationType.DAUGHTER_OF,
    "मुलगी": RelationType.DAUGHTER_OF,
    "पुत्री": RelationType.DAUGHTER_OF,
    "w/o": RelationType.WIFE_OF,
    "wo": RelationType.WIFE_OF,
    "wife of": RelationType.WIFE_OF,
    "कोम": RelationType.WIFE_OF,
    "पत्नी": RelationType.WIFE_OF,
    "wd/o": RelationType.WIDOW_OF,
    "widow of": RelationType.WIDOW_OF,
    "विधवा": RelationType.WIDOW_OF,
    "heir of": RelationType.HEIR_OF,
    "वारस": RelationType.HEIR_OF,
    "guardian of": RelationType.GUARDIAN_OF,
    "पालक": RelationType.GUARDIAN_OF,
}


def resolve_classification(raw: str | None) -> VocabMatch[LandClassification]:
    return _resolve(raw, _CLASSIFICATION_TABLE, LandClassification.UNKNOWN)


def resolve_tenure(raw: str | None) -> VocabMatch[TenureType]:
    return _resolve(raw, _TENURE_TABLE, TenureType.UNKNOWN)


def resolve_mutation_type(raw: str | None) -> VocabMatch[MutationType]:
    return _resolve(raw, _MUTATION_TYPE_TABLE, MutationType.UNKNOWN)


def resolve_mutation_status(raw: str | None) -> VocabMatch[MutationStatus]:
    return _resolve(raw, _MUTATION_STATUS_TABLE, MutationStatus.UNKNOWN)


def resolve_encumbrance_type(raw: str | None) -> VocabMatch[EncumbranceType]:
    return _resolve(raw, _ENCUMBRANCE_TYPE_TABLE, EncumbranceType.UNKNOWN)


def resolve_encumbrance_status(raw: str | None) -> VocabMatch[EncumbranceStatus]:
    return _resolve(raw, _ENCUMBRANCE_STATUS_TABLE, EncumbranceStatus.UNKNOWN)


def resolve_irrigation(raw: str | None) -> VocabMatch[IrrigationSource]:
    return _resolve(raw, _IRRIGATION_TABLE, IrrigationSource.UNKNOWN)


def resolve_relation(raw: str | None) -> VocabMatch[RelationType]:
    return _resolve(raw, _RELATION_TABLE, RelationType.UNKNOWN)


# --------------------------------------------------------------------------------------
# Shares
# --------------------------------------------------------------------------------------

_EQUAL_SHARE_MARKERS = {
    "equal",
    "equal share",
    "समान",
    "समान हिस्सा",
    "सारखा",
    "बराबर",
    "barabar",
    "saman",
}

_FRACTION = re.compile(r"(\d+)\s*[/:]\s*(\d+)")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


_SIMPLE_SHARE_DENOMINATORS: tuple[int, ...] = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 16, 18, 20, 24, 25, 30, 32, 36, 40, 48, 50, 60, 64,
)
"""Denominators a share is plausibly a *rounding of*, smallest first.

Successive partition among heirs generates halves, thirds and their products, so real
share denominators cluster on small smooth numbers. The cap at 64 matters as much as
the membership: allowing 400 would let ``0.123`` match ``49/400``, which is neither
what the clerk wrote nor a share anyone holds.
"""

_MAX_ROUNDING_TOLERANCE = Fraction(1, 200)
"""Ceiling on the rounding tolerance, 0.5%.

A share written to one decimal place is still a share: however coarsely it was
written, the recorded figure should not be more than half a percent from the fraction
intended, and treating a 1-decimal value as +/-5% admits fractions that are simply wrong.
"""


def _fraction_from_decimal(value: Decimal) -> Fraction:
    """Recover the fraction a decimal was rounded from.

    Records write ``1/3`` as ``0.3333``. Taken at face value that is ``3333/10000``,
    and three co-owners each holding ``3333/10000`` fail the sum-to-unity rule for a
    reason that appears nowhere on the document.

    The recovery is constrained two ways, because an unconstrained "nearest simple
    fraction" search is worse than the problem it solves:

    * **Candidates** come only from :data:`_SIMPLE_SHARE_DENOMINATORS`, smallest
      first, so the first hit is the simplest fraction consistent with the text.
    * **Tolerance** is half a unit in the written decimal's last place -- the largest
      error rounding could actually have introduced -- capped at
      :data:`_MAX_ROUNDING_TOLERANCE`. A 4-decimal ``0.3333`` admits only candidates
      within 0.00005, which ``1/3`` meets and little else does. The cap matters at the
      other end: half a unit in the last place of the 1-decimal ``0.2`` is 0.05, wide
      enough to swallow ``1/4``, so the cap is what keeps ``0.2`` at ``1/5``.

    Simplest-within-tolerance rather than nearest: ``0.33`` is reproduced exactly by
    ``33/100`` and approximately by ``1/3``, and ``1/3`` is what was meant -- a
    two-decimal figure is a rounded share, not a share in hundredths.

    When no simple fraction fits, the decimal is taken **exactly as written**
    (``0.123`` stays ``123/1000``). Falling back to a nearest-simple-fraction search
    here is what produces spurious values like ``7/57``, so it deliberately does not.
    """
    exact = Fraction(value)
    exponent = value.as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if places == 0:
        return exact.limit_denominator(10_000)

    tolerance = min(Fraction(1, 2 * 10**places), _MAX_ROUNDING_TOLERANCE)
    for denominator in _SIMPLE_SHARE_DENOMINATORS:  # ascending: first hit is simplest
        numerator = round(exact * denominator)
        if not 0 <= numerator <= denominator:
            continue
        candidate = Fraction(numerator, denominator)
        if abs(candidate - exact) <= tolerance:
            return candidate

    return exact.limit_denominator(10_000)


def is_equal_share_marker(raw: str | None) -> bool:
    """Whether the cell says 'equal share' rather than giving a fraction.

    The caller supplies the co-owner count, since that is what turns 'equal' into a
    number -- see :meth:`OwnershipShare.equal_among`.
    """
    return raw is not None and _fold(raw) in {_fold(m) for m in _EQUAL_SHARE_MARKERS}


def parse_share(
    raw: str | None,
    *,
    numerator: str | None = None,
    denominator: str | None = None,
) -> OwnershipShare | None:
    """Parse an ownership share into an exact rational.

    Handles, in order: explicit numerator/denominator from the LLM, ``a/b`` fractions
    (including Devanagari digits), percentages, and bare decimals. Decimals go through
    :func:`_fraction_from_decimal`, which recovers ``1/3`` from ``0.3333`` -- the case
    that otherwise breaks the sum-to-unity rule for no reason present on the document.

    Returns ``None`` for 'equal share' markers and anything unparseable; the caller
    decides what to do, because only the caller knows the co-owner count.
    """
    if numerator is not None and denominator is not None:
        num = parse_decimal(numerator, repair=True)
        den = parse_decimal(denominator, repair=True)
        if num is not None and den is not None and den != 0:
            frac = Fraction(int(num), int(den))
            if frac <= 1:
                return OwnershipShare(
                    numerator=frac.numerator, denominator=frac.denominator, raw_text=raw
                )

    if raw is None or not raw.strip():
        return None
    if is_equal_share_marker(raw):
        return None

    text = to_ascii_digits(raw).strip()

    if _fold(text) in {"whole", "full", "1", "पूर्ण", "संपूर्ण"}:
        return OwnershipShare(numerator=1, denominator=1, raw_text=raw)

    match = _FRACTION.search(text)
    if match:
        num, den = int(match.group(1)), int(match.group(2))
        if den != 0 and num <= den:
            frac = Fraction(num, den)
            return OwnershipShare(numerator=frac.numerator, denominator=frac.denominator, raw_text=raw)
        return None

    match = _PERCENT.search(text)
    if match:
        try:
            frac = _fraction_from_decimal(Decimal(match.group(1)) / 100)
        except (InvalidOperation, ValueError):  # pragma: no cover - regex guarantees validity
            return None
        if 0 <= frac <= 1:
            return OwnershipShare(numerator=frac.numerator, denominator=frac.denominator, raw_text=raw)
        return None

    value = parse_decimal(text)
    if value is not None and 0 <= value <= 1:
        frac = _fraction_from_decimal(value)
        return OwnershipShare(numerator=frac.numerator, denominator=frac.denominator, raw_text=raw)

    return None


# --------------------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------------------

_DATE_PATTERNS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%Y-%m-%d",
    "%d %B %Y",
    "%d %b %Y",
    "%m/%Y",
    "%Y",
)


def parse_record_date(raw: str | None) -> date | None:
    """Parse a date from a record cell, day-first.

    Indian revenue records are unambiguously day-first, so ``03/04/2019`` is 3 April,
    never 4 March. Parsing is tried against explicit patterns before falling back to
    :mod:`dateutil`, because dateutil's fuzzy mode will happily extract a date from a
    mutation number and that is worse than returning ``None``.

    Two-digit years resolve to 1930-2029 via :mod:`datetime`'s standard pivot.
    """
    if raw is None or not raw.strip():
        return None

    text = to_ascii_digits(raw).strip()
    text = re.sub(r"\s+", " ", text)

    for pattern in _DATE_PATTERNS:
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        if pattern == "%Y":
            return date(parsed.year, 1, 1)
        if pattern == "%m/%Y":
            return date(parsed.year, parsed.month, 1)
        return parsed.date()

    try:
        from dateutil import parser as dateutil_parser
    except ImportError:  # pragma: no cover - dateutil is a hard dependency
        return None

    try:
        return dateutil_parser.parse(text, dayfirst=True, fuzzy=False).date()
    except (ValueError, OverflowError, TypeError):
        return None
