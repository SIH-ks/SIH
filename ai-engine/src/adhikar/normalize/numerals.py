"""Multilingual numeral and script handling.

Land records mix numeral systems within a single row: a Devanagari khasra number
beside a Latin area figure beside an Indian-grouped rupee amount. Every numeric read
in this package routes through here.

Digit conversion uses :func:`unicodedata.decimal` rather than a hand-written table, so
it covers every Unicode decimal digit -- Devanagari, Gujarati, Bengali, Gurmukhi,
Odia, Tamil, Telugu, Kannada, Malayalam, Arabic-Indic and the extended Arabic-Indic
forms -- without a per-script maintenance burden. The explicit
:data:`SCRIPT_DIGIT_ZEROS` table exists only for script *detection* and for tests.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from ..schemas.ocr import ScriptHistogram

__all__ = [
    "OCR_DIGIT_CONFUSIONS",
    "SCRIPT_DIGIT_ZEROS",
    "detect_scripts",
    "dominant_script",
    "normalise_numeric_text",
    "parse_decimal",
    "parse_int",
    "repair_ocr_digits",
    "split_numeric_triple",
    "to_ascii_digits",
]

SCRIPT_DIGIT_ZEROS: dict[str, str] = {
    "Devanagari": "०",
    "Bengali": "০",
    "Gurmukhi": "੦",
    "Gujarati": "૦",
    "Oriya": "୦",
    "Tamil": "௦",
    "Telugu": "౦",
    "Kannada": "೦",
    "Malayalam": "൦",
    "Arabic": "٠",
    "Extended_Arabic": "۰",
}
"""U+0030-equivalent for each script that appears on Indian land records."""

OCR_DIGIT_CONFUSIONS: dict[str, str] = {
    "O": "0",
    "o": "0",
    "Q": "0",
    "D": "0",
    "l": "1",
    "I": "1",
    "|": "1",
    "!": "1",
    "Z": "2",
    "z": "2",
    "S": "5",
    "s": "5",
    "b": "6",
    "G": "6",
    "T": "7",
    "B": "8",
    "g": "9",
    "q": "9",
}
"""Latin glyphs OCR substitutes for digits.

Applied **only** by :func:`repair_ocr_digits`, and only to strings already known to be
numeric fields. Applying it to free text would corrupt names, so it is never automatic.
"""

# Separators that appear between area components: hyphen, en/em dash, Devanagari danda,
# middle dot, and the various slashes clerks use interchangeably.
_COMPONENT_SEPARATOR = re.compile(r"[-‐-―−/\\|.।·:]+")
_NON_NUMERIC = re.compile(r"[^0-9.\-]")
_WHITESPACE = re.compile(r"\s+")


def to_ascii_digits(text: str) -> str:
    """Replace every Unicode decimal digit with its ASCII equivalent.

    Non-digit characters pass through untouched, so this is safe to run over mixed
    text such as ``"सर्वे नं. १४२"`` -> ``"सर्वे नं. 142"``.

    >>> to_ascii_digits("१२३")
    '123'
    >>> to_ascii_digits("૦-૮૦-૦૫")
    '0-80-05'
    >>> to_ascii_digits("Khasra 45/2")
    'Khasra 45/2'
    """
    if not text:
        return text
    out: list[str] = []
    for ch in text:
        if ch.isdigit() and not ch.isascii():
            try:
                out.append(str(unicodedata.decimal(ch)))
                continue
            except (TypeError, ValueError):  # pragma: no cover - isdigit implies decimal
                pass
        out.append(ch)
    return "".join(out)


def detect_scripts(text: str) -> ScriptHistogram:
    """Count characters by Unicode script block.

    Drives OCR language selection: a page that is 70% Devanagari and 25% Latin needs
    both engines configured for both, and running either alone loses a quarter of
    the page.
    """
    counts: dict[str, int] = {}
    for ch in text:
        if ch.isspace() or not ch.isprintable():
            continue
        script = _script_of(ch)
        if script == "Common" and not ch.isdigit():
            continue
        counts[script] = counts.get(script, 0) + 1
    return ScriptHistogram(counts=counts)


def _script_of(ch: str) -> str:
    """Approximate Unicode script name from the character's Unicode name.

    The stdlib does not expose the Script property, and pulling in a dependency for
    it is not worth it: character names are prefixed with the script for every block
    this project encounters.
    """
    if ch.isascii():
        return "Latin" if ch.isalnum() else "Common"
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "Unknown"
    first = name.split(" ", 1)[0]
    known = {
        "DEVANAGARI": "Devanagari",
        "BENGALI": "Bengali",
        "GURMUKHI": "Gurmukhi",
        "GUJARATI": "Gujarati",
        "ORIYA": "Oriya",
        "TAMIL": "Tamil",
        "TELUGU": "Telugu",
        "KANNADA": "Kannada",
        "MALAYALAM": "Malayalam",
        "ARABIC": "Arabic",
        "LATIN": "Latin",
    }
    return known.get(first, "Other")


def dominant_script(text: str) -> str:
    return detect_scripts(text).dominant


def repair_ocr_digits(text: str) -> str:
    """Substitute Latin look-alikes for digits in a field known to be numeric.

    Only call this on values that must be numeric -- areas, amounts, years. It is
    destructive on anything else: ``"Solapur"`` would become ``"5olapur"``.

    >>> repair_ocr_digits("O-8O-O5")
    '0-80-05'
    """
    return "".join(OCR_DIGIT_CONFUSIONS.get(ch, ch) for ch in text)


def normalise_numeric_text(text: str, *, repair: bool = False) -> str:
    """Prepare a numeric string for parsing.

    Converts Indic digits, strips Indian-style digit grouping (``1,25,000``), removes
    currency marks and collapses whitespace. Optionally applies OCR digit repair.
    """
    if not text:
        return ""
    value = to_ascii_digits(text)
    value = value.replace("₹", " ").replace("Rs.", " ").replace("Rs", " ").replace("रू", " ")
    value = value.replace(",", "")
    if repair:
        value = repair_ocr_digits(value)
    return _WHITESPACE.sub(" ", value).strip()


def parse_decimal(text: str | None, *, repair: bool = False) -> Decimal | None:
    """Extract a single decimal from noisy text, or ``None``.

    Returns ``None`` rather than raising, and rather than guessing: an unparseable
    numeric cell becomes a missing value plus a validation finding, which is visible,
    instead of a zero, which is not.

    >>> parse_decimal("१२३.४५")
    Decimal('123.45')
    >>> parse_decimal("Rs. 1,25,000/-")
    Decimal('125000')
    >>> parse_decimal("---") is None
    True
    """
    if text is None:
        return None
    cleaned = normalise_numeric_text(text, repair=repair)
    if not cleaned:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if match is None:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:  # pragma: no cover - regex guarantees a valid literal
        return None


def parse_int(text: str | None, *, repair: bool = False) -> int | None:
    """Extract a single integer from noisy text, or ``None``."""
    value = parse_decimal(text, repair=repair)
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, OverflowError):  # pragma: no cover - Decimal is finite here
        return None


def split_numeric_triple(text: str | None, *, repair: bool = False) -> list[Decimal]:
    """Split a hyphen/slash/dot-separated component group into its numbers.

    This is how ``0-80-05`` (H-R-Sq.M) and ``2/8`` (kanal-marla) are read. The caller
    decides what the positions mean, because that depends on the record format --
    this function only splits.

    >>> split_numeric_triple("0-80-05")
    [Decimal('0'), Decimal('80'), Decimal('5')]
    >>> split_numeric_triple("१-२०-००")
    [Decimal('1'), Decimal('20'), Decimal('0')]
    >>> split_numeric_triple("1.205")
    [Decimal('1.205')]
    """
    if not text:
        return []
    cleaned = normalise_numeric_text(text, repair=repair)
    if not cleaned:
        return []

    # A plain decimal such as "1.205" is one number, not two components. Treat a dot
    # as a separator only when the string carries another separator too, or when a
    # dot-delimited group has more than two parts (e.g. "0.80.05").
    dot_parts = cleaned.split(".")
    has_other_separator = bool(re.search(r"[-‐-―−/\\|।·:]", cleaned))
    if not has_other_separator and len(dot_parts) <= 2:
        single = parse_decimal(cleaned)
        return [single] if single is not None else []

    pieces = [p for p in _COMPONENT_SEPARATOR.split(cleaned) if p.strip()]
    values: list[Decimal] = []
    for piece in pieces:
        stripped = _NON_NUMERIC.sub("", piece)
        if not stripped:
            continue
        try:
            values.append(Decimal(stripped))
        except InvalidOperation:
            continue
    return values
