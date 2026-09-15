"""Parcel-identifier normalisation and comparison.

The same plot is ``125/2`` on the old Jamabandi, ``125 / 2`` on the mutation order,
``१२५/२`` on a Devanagari register, and ``0125/2`` where a clerk pads to a fixed
width. Rules S3 and S5 ask whether two documents refer to the same parcel, and a
comparison that answers "no" to any of those pairs would flag every correctly-filed
succession case in the district.

Normalisation is deliberately narrow. Separators are unified, Devanagari digits are
folded to ASCII, and leading zeros inside each numeric component are dropped --
nothing else. In particular a numeric suffix is **never** discarded: ``125`` and
``125/2`` are a parent survey number and one hissa of it, which is exactly the
distinction a succession case can turn on, so they compare as *related but not
equal* and the caller decides what that means.

Village, tehsil and district names go through :func:`normalize_place`, which is the
same folding minus the numeric handling -- ``Angol.`` and ``angol`` are one village.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .numerals import to_ascii_digits

__all__ = [
    "IdentifierMatch",
    "compare_identifier",
    "normalize_identifier",
    "normalize_place",
]

_SEPARATORS = re.compile(r"[\s\-_\\.,]+")
_MULTI_SLASH = re.compile(r"/+")
_LEADING_ZEROS = re.compile(r"\b0+(\d)")


def normalize_identifier(raw: str | None) -> str:
    """Fold a khasra / khata / survey number to its comparable form.

    ``" 0125 / 2 "`` and ``"१२५-२"`` both become ``"125/2"``. Hyphens and dots are
    treated as the same separator as a slash because registers use all three for a
    hissa suffix, and preserving which one a particular clerk chose would make two
    identical plots compare unequal.
    """
    if not raw or not str(raw).strip():
        return ""

    text = unicodedata.normalize("NFKC", str(raw))
    text = to_ascii_digits(text).strip().lower()
    text = _SEPARATORS.sub("/", text)
    text = _MULTI_SLASH.sub("/", text).strip("/")
    text = _LEADING_ZEROS.sub(r"\1", text)
    return text


def normalize_place(raw: str | None) -> str:
    """Fold a village / tehsil / district name for comparison.

    Transliteration variants (``Belagavi`` / ``Belgaum``) are explicitly *not*
    handled here: mapping those needs the LGD gazetteer, not string distance, and
    guessing would silently merge two real places. A place comparison that cannot
    resolve reports a conflict, which a reviewer can dismiss in one click, rather
    than an agreement nobody can detect is wrong.
    """
    if not raw or not str(raw).strip():
        return ""
    text = unicodedata.normalize("NFKC", str(raw)).strip().lower()
    text = re.sub(r"[\.\,\-_/()\[\]']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True, slots=True)
class IdentifierMatch:
    """The outcome of comparing one identifier across two documents."""

    field: str
    left: str
    right: str
    equal: bool
    related: bool
    """True when one value is a sub-division of the other (``125`` vs ``125/2``).

    Reported separately from equality because it is genuinely ambiguous: a mutation
    order naming the parent survey number for a hissa-level record is routine
    shorthand in some districts and a real mismatch in others. The engine surfaces
    the relationship and does not decide.
    """

    def describe(self) -> str:
        if self.equal:
            return f"{self.field} agrees ({self.left})"
        if self.related:
            return f"{self.field} differs in sub-division: '{self.left}' vs '{self.right}'"
        return f"{self.field} disagrees: '{self.left}' vs '{self.right}'"


def compare_identifier(field: str, left: str | None, right: str | None) -> IdentifierMatch | None:
    """Compare one named identifier, or ``None`` when either document omits it.

    Returning ``None`` for an absent value is the whole point: two documents that
    both omit the khata number agree on nothing, and counting that as a match would
    manufacture corroboration out of silence.
    """
    numeric_field = field not in {"village", "tehsil", "district", "state"}
    folder = normalize_identifier if numeric_field else normalize_place

    a, b = folder(left), folder(right)
    if not a or not b:
        return None

    if a == b:
        return IdentifierMatch(field=field, left=a, right=b, equal=True, related=True)

    related = numeric_field and (a.startswith(f"{b}/") or b.startswith(f"{a}/"))
    return IdentifierMatch(field=field, left=a, right=b, equal=False, related=related)
