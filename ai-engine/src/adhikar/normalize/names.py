"""Person-name normalisation and tolerant matching.

Succession validation lives or dies on linking a name on one document to a name on
another. The same person is written ``Ramesh Sharma`` on the Jamabandi, ``Shri Ramesh
Sharma`` on the death certificate, ``रमेश शर्मा`` on the mutation order, and
``Ramesh Sarma`` by an OCR pass that lost a conjunct. A comparison strict enough to
reject a different Ramesh has to tolerate all four.

The strategy mirrors :mod:`adhikar.normalize.vocab`, which does the same job for
vernacular terms: fold aggressively, compare in tiers, and report the score rather
than only the verdict. Two things are specific to names.

**Honorifics and status words are stripped, not compared.** ``Shri``, ``Smt.``,
``Late``, ``स्व.`` say something about the person, never about which person, and
leaving them in makes ``Late Ramesh Sharma`` and ``Ramesh Sharma`` look 12% different
purely because one document noted the death.

**Token order does not matter; every token does.** Registers write
``Sharma Ramesh`` and ``Ramesh Sharma`` interchangeably, so the comparison is over
token *sets* -- and it scores on the worst-matching token, not the average one,
because a shared family name would otherwise carry a mismatched given name over the
line and link one member of a household to another's certificate. Single-letter
tokens are matched as initials, since ``Karthikeyan R`` and ``Karthikeyan Ramasamy``
are the same person on a Tamil RoR.

:data:`NAME_MATCH_THRESHOLD` is deliberately higher than the vocabulary threshold.
A misresolved vernacular term produces a wrong classification and a finding; a
misresolved *name* silently links one family's land to another family's death
certificate, which is the worst failure this system could have.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .numerals import to_ascii_digits

__all__ = [
    "HONORIFICS",
    "NAME_MATCH_THRESHOLD",
    "NameMatch",
    "best_match",
    "match_names",
    "name_similarity",
    "name_tokens",
    "normalize_name",
]

NAME_MATCH_THRESHOLD = 0.88
"""Minimum similarity at which two names are treated as the same person.

Above 0.94 the match is reported as effectively exact; between the threshold and
0.94 it is reported as *approximate*, which raises
``SUCCESSION_NAME_MATCH_APPROXIMATE`` so a chain resting on a fuzzy link says so on
its face. Below it, the names are simply different people as far as the engine is
concerned -- it never picks the closest candidate regardless of distance.
"""

_EXACT_ENOUGH = 0.94
"""Score at or above which a fuzzy match is not worth flagging to a reviewer.

One transposed vowel in a ten-character name lands here. Flagging that as an
approximate link would bury the cases where the flag actually matters.
"""

HONORIFICS: frozenset[str] = frozenset(
    {
        # Latin surface forms
        "shri", "sri", "shree", "sh", "smt", "smtt", "srimati", "shrimati",
        "mr", "mrs", "ms", "miss", "kum", "kumari", "km", "dr", "prof",
        "late", "l", "m/s", "messrs",
        # Devanagari surface forms
        "श्री", "श्रीमती", "सौ", "कु", "कुमारी", "स्व", "स्वर्गीय", "डॉ",
    }
)
"""Titles and status words that are never part of identity.

``late`` / ``स्व`` earn their place here: a death certificate and the register it
relates to routinely differ by exactly that word, and it is the one difference that
must not reduce the match score.
"""

_PUNCTUATION = re.compile(r"[\.\,\-_/\\()\[\]{}:;'\"`~!?*+|<>]+")
_WHITESPACE = re.compile(r"\s+")

try:  # pragma: no cover - whichever backend is installed
    from rapidfuzz.distance import JaroWinkler

    def _ratio(a: str, b: str) -> float:
        return float(JaroWinkler.normalized_similarity(a, b))

except ImportError:  # pragma: no cover - stdlib fallback keeps the package importable
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()


def normalize_name(raw: str | None) -> str:
    """Fold a name to its comparable form.

    NFKC first, because OCR engines emit pre-composed and decomposed Devanagari
    interchangeably for the same glyph; then relation markers (``s/o``, ``w/o``,
    ``बिन``) and anything after them are dropped, since the qualifier is compared
    separately where it matters and would otherwise dominate the similarity of two
    short given names.
    """
    if not raw or not raw.strip():
        return ""

    text = unicodedata.normalize("NFKC", raw)
    text = to_ascii_digits(text)
    text = _strip_relation_clause(text)
    text = _PUNCTUATION.sub(" ", text).lower()
    text = _WHITESPACE.sub(" ", text).strip()

    tokens = [t for t in text.split(" ") if t and t not in HONORIFICS]
    return " ".join(tokens)


_RELATION_MARKERS = (
    " s/o ", " d/o ", " w/o ", " wd/o ", " c/o ", " r/o ",
    " son of ", " daughter of ", " wife of ", " widow of ", " heir of ",
    " बिन ", " वल्द ", " कोम ", " पत्नी ", " मुलगा ", " मुलगी ",
)


def _strip_relation_clause(text: str) -> str:
    """Drop ``s/o Hari Singh`` and friends, keeping only the name itself.

    Relation is part of identity in a village register (see
    :class:`~adhikar.schemas.land_record.PersonName`), which is exactly why it is not
    folded into the *name* comparison: a check that wants to use it compares
    ``relation_name`` explicitly and can say so, rather than having it silently
    inflate or deflate a similarity score.
    """
    padded = f" {_WHITESPACE.sub(' ', text)} ".lower()
    original = f" {_WHITESPACE.sub(' ', text)} "
    cut = len(original)
    for marker in _RELATION_MARKERS:
        index = padded.find(marker)
        if index != -1:
            cut = min(cut, index)
    return original[:cut].strip()


def name_tokens(raw: str | None) -> list[str]:
    """Normalised tokens of a name, in printed order."""
    folded = normalize_name(raw)
    return folded.split(" ") if folded else []


def _token_set_similarity(left: list[str], right: list[str]) -> float:
    """Order-insensitive similarity over tokens, scored by the *worst* pairing.

    Each token on the shorter side is greedily paired with its best partner on the
    longer side, and the result is the **minimum** of those pairings -- every part of
    a name has to match, not the average part.

    The minimum rather than the mean is the single most important decision in this
    module. Indian family names are shared by everyone in the household, so a mean
    lets one matching surname carry a mismatched given name over the line:
    ``Sita Sharma`` and ``Gita Sharma`` average 0.92 and are two different people,
    as are ``Sita Sharma`` and ``Amit Sharma``. Linking a death certificate to the
    wrong member of the same family is the worst failure this system could have, and
    the mean produces exactly it.

    A single-letter token matches any token sharing its first letter at 0.92 -- high
    enough to link ``Karthikeyan R`` to ``Karthikeyan Ramasamy``, low enough that the
    pair is still reported as an approximate rather than exact match.
    """
    if not left or not right:
        return 0.0

    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    available = list(longer)
    scores: list[float] = []

    for token in shorter:
        if not available:
            break
        best_index, best_score = 0, 0.0
        for index, candidate in enumerate(available):
            if len(token) == 1 or len(candidate) == 1:
                score = 0.92 if token[0] == candidate[0] else 0.0
            else:
                score = _ratio(token, candidate)
            if score > best_score:
                best_index, best_score = index, score
        scores.append(best_score)
        available.pop(best_index)

    if not scores:
        return 0.0

    # Tokens on the longer side that found no partner are evidence of difference, but
    # a middle name or a village suffix present on one document and not the other is
    # normal -- so they dilute the score rather than veto the match.
    coverage = len(scores) / len(longer)
    return min(scores) * (0.75 + 0.25 * coverage)


def name_similarity(left: str | None, right: str | None) -> float:
    """Similarity of two names in [0, 1], 1.0 for an exact normalised match.

    For names of two or more tokens the token comparison is **authoritative** and the
    whole-string ratio is not consulted at all. Whole-string Jaro-Winkler is badly
    behaved on multi-token Indian names -- ``Sita Sharma`` against ``Amit Sharma``
    scores 0.91, because eleven of their characters agree and the six that matter are
    outnumbered. Taking the better of the two measures would reintroduce exactly the
    failure :func:`_token_set_similarity` exists to prevent.

    The whole-string ratio is still used when either side is a single token, where a
    per-token comparison has nothing to pair against and the coverage penalty alone
    would reject a register that printed only a given name.
    """
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    left_tokens, right_tokens = a.split(" "), b.split(" ")
    token_score = _token_set_similarity(left_tokens, right_tokens)
    if len(left_tokens) > 1 and len(right_tokens) > 1:
        return round(token_score, 4)
    return round(max(_ratio(a, b), token_score), 4)


@dataclass(frozen=True, slots=True)
class NameMatch:
    """The outcome of comparing two names, with the number behind the verdict."""

    left: str
    right: str
    score: float
    threshold: float
    matched: bool

    @property
    def is_exact(self) -> bool:
        return self.matched and self.score >= 1.0

    @property
    def is_approximate(self) -> bool:
        """Matched, but not closely enough to pass without a reviewer knowing."""
        return self.matched and self.score < _EXACT_ENOUGH

    def describe(self) -> str:
        if self.is_exact:
            return f"'{self.left}' and '{self.right}' are identical after normalisation"
        verb = "matched" if self.matched else "did not match"
        return (
            f"'{self.left}' and '{self.right}' {verb} at similarity "
            f"{self.score:.2f} against a {self.threshold:.2f} threshold"
        )


def match_names(
    left: str | None, right: str | None, *, threshold: float = NAME_MATCH_THRESHOLD
) -> NameMatch:
    """Compare two names at an explicit, reportable threshold."""
    score = name_similarity(left, right)
    return NameMatch(
        left=(left or "").strip(),
        right=(right or "").strip(),
        score=score,
        threshold=threshold,
        matched=score >= threshold,
    )


def best_match(
    needle: str | None,
    candidates: list[str],
    *,
    threshold: float = NAME_MATCH_THRESHOLD,
) -> NameMatch | None:
    """The best-scoring candidate at or above ``threshold``, or ``None``.

    Returns ``None`` rather than the nearest candidate when nothing clears the bar.
    Falling back to "closest available" is how a system ends up confidently matching
    a death certificate to the wrong family.
    """
    if not needle or not candidates:
        return None
    best: NameMatch | None = None
    for candidate in candidates:
        match = match_names(needle, candidate, threshold=threshold)
        if best is None or match.score > best.score:
            best = match
    return best if best is not None and best.matched else None
