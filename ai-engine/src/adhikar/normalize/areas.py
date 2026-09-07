"""Area-cell parsing: free text and LLM components to :class:`AreaMeasurement`.

The hard case is the **bare component group** -- ``0-80-05`` with no unit words at
all, which is how most 7/12 extracts print area. Three numbers could be H-R-Sq.M
(Maharashtra), or bigha-biswa-biswansi (north India), and the difference is a factor
of hundreds. So a bare group is only interpreted when the caller supplies a
``default_system``, which the pipeline derives from the detected record format. With
no hint, parsing returns ``None`` and the field is reported missing rather than
silently assigned the wrong unit.
"""

from __future__ import annotations

import re
from decimal import Decimal

from ..schemas.enums import RecordFormat
from ..schemas.llm_contract import LlmArea
from ..schemas.units import AmbiguousUnitError, AreaMeasurement, AreaUnit, AreaUnitSystem
from .numerals import normalise_numeric_text, parse_decimal, split_numeric_triple

__all__ = [
    "UNIT_KEYWORDS",
    "area_from_llm",
    "default_system_for_format",
    "parse_area",
]

UNIT_KEYWORDS: dict[str, AreaUnit] = {
    # -- metric -------------------------------------------------------------------
    "hectare": AreaUnit.HECTARE,
    "hectares": AreaUnit.HECTARE,
    "hect": AreaUnit.HECTARE,
    "ha": AreaUnit.HECTARE,
    "he": AreaUnit.HECTARE,
    "हेक्टर": AreaUnit.HECTARE,
    "हेक्टेयर": AreaUnit.HECTARE,
    "हे": AreaUnit.HECTARE,
    "are": AreaUnit.ARE,
    "ares": AreaUnit.ARE,
    "आर": AreaUnit.ARE,
    "आरे": AreaUnit.ARE,
    "sqm": AreaUnit.SQ_METRE,
    "sqmt": AreaUnit.SQ_METRE,
    "sqmeter": AreaUnit.SQ_METRE,
    "sqmetre": AreaUnit.SQ_METRE,
    "squaremeter": AreaUnit.SQ_METRE,
    "squaremetre": AreaUnit.SQ_METRE,
    "chaurasmeter": AreaUnit.SQ_METRE,
    "चौमी": AreaUnit.SQ_METRE,
    "चौरसमीटर": AreaUnit.SQ_METRE,
    "चौरसमी": AreaUnit.SQ_METRE,
    "चटरशमीटर": AreaUnit.SQ_METRE,
    # -- imperial / traditional -------------------------------------------------------
    "acre": AreaUnit.ACRE,
    "acres": AreaUnit.ACRE,
    "ac": AreaUnit.ACRE,
    "एकर": AreaUnit.ACRE,
    "guntha": AreaUnit.GUNTHA,
    "gunthas": AreaUnit.GUNTHA,
    "gunta": AreaUnit.GUNTHA,
    "गुंठा": AreaUnit.GUNTHA,
    "गुंठे": AreaUnit.GUNTHA,
    "kanal": AreaUnit.KANAL,
    "kanals": AreaUnit.KANAL,
    "कनाल": AreaUnit.KANAL,
    "marla": AreaUnit.MARLA,
    "marlas": AreaUnit.MARLA,
    "मरला": AreaUnit.MARLA,
    "bigha": AreaUnit.BIGHA,
    "bighas": AreaUnit.BIGHA,
    "बीघा": AreaUnit.BIGHA,
    "बिघा": AreaUnit.BIGHA,
    "biswa": AreaUnit.BISWA,
    "बिस्वा": AreaUnit.BISWA,
    "biswansi": AreaUnit.BISWANSI,
    "बिस्वांसी": AreaUnit.BISWANSI,
    "sqft": AreaUnit.SQ_FOOT,
    "squarefeet": AreaUnit.SQ_FOOT,
    "sqyd": AreaUnit.SQ_YARD,
    "squareyard": AreaUnit.SQ_YARD,
}
"""Surface forms to units. Keys are matched after lower-casing and stripping
punctuation and internal spaces, so ``"Sq. Mtr."`` and ``"sqmtr"`` both hit."""

_UNIT_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

_ABBREVIATION_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Multi-token abbreviations must be glued before tokenisation, or "sq.m." splits
    # into "sq" and "m" and neither half is a unit. Offsets shift, but the binding in
    # _parse_with_units depends only on the order of numbers and units, not offsets.
    (re.compile(r"\bsq\W*(?:mtrs?|mtr|metres?|meters?|m)\b", re.IGNORECASE), " sqm "),
    (re.compile(r"\bsq\W*(?:ft|feet|foot)\b", re.IGNORECASE), " sqft "),
    (re.compile(r"\bsq\W*(?:yds?|yards?)\b", re.IGNORECASE), " sqyd "),
    (re.compile(r"\b(?:square)\W*(?:metres?|meters?)\b", re.IGNORECASE), " sqm "),
    (re.compile(r"चौ\W*(?:रस)?\W*मी(?:टर)?"), " sqm "),
    (re.compile(r"\bh\W*a\W*r\b", re.IGNORECASE), " "),  # "H.A.R" column headers
)


def _apply_abbreviations(text: str) -> str:
    for pattern, replacement in _ABBREVIATION_FIXES:
        text = pattern.sub(replacement, text)
    return text

_SYSTEM_LAYOUTS: dict[AreaUnitSystem, tuple[AreaUnit, ...]] = {
    AreaUnitSystem.METRIC_HA_ARE_SQM: (AreaUnit.HECTARE, AreaUnit.ARE, AreaUnit.SQ_METRE),
    AreaUnitSystem.ACRE_GUNTHA: (AreaUnit.ACRE, AreaUnit.GUNTHA),
    AreaUnitSystem.KANAL_MARLA: (AreaUnit.KANAL, AreaUnit.MARLA),
    AreaUnitSystem.BIGHA_BISWA: (AreaUnit.BIGHA, AreaUnit.BISWA, AreaUnit.BISWANSI),
}
"""Positional meaning of a bare component group, per unit system."""


def default_system_for_format(record_format: RecordFormat) -> AreaUnitSystem | None:
    """The unit system a bare component group most likely uses, given the template.

    Returns ``None`` for formats with no dominant convention -- Jamabandi is used
    across states that print kanal-marla and states that print bigha-biswa, so
    guessing from the format alone would be unsound. Those records need either unit
    words on the page or an operator-configured default.
    """
    return {
        RecordFormat.SATBARA: AreaUnitSystem.METRIC_HA_ARE_SQM,
        RecordFormat.KHASRA_GIRDAWARI: AreaUnitSystem.METRIC_HA_ARE_SQM,
    }.get(record_format)


def _canonical_token(token: str) -> str:
    return re.sub(r"[\s.\-_]", "", token).lower()


def _find_units(text: str) -> list[tuple[int, AreaUnit]]:
    """Locate unit keywords with their character offsets, in order of appearance."""
    found: list[tuple[int, AreaUnit]] = []
    for match in _UNIT_TOKEN.finditer(text):
        unit = UNIT_KEYWORDS.get(_canonical_token(match.group(0)))
        if unit is not None:
            found.append((match.start(), unit))
    return found


def parse_area(
    raw: str | None,
    *,
    default_system: AreaUnitSystem | None = None,
    region_key: str | None = None,
) -> AreaMeasurement | None:
    """Parse an area cell into a canonical measurement.

    Resolution order:

    1. **Unit words present** -- each number is bound to the unit keyword that
       follows it (``"1 acre 20 guntha"``), or precedes it when the record writes the
       unit first (``"ha 1 are 20"``).
    2. **Bare component group** (two or more numbers) -- positions are assigned from
       ``default_system``, most significant first.
    3. **Single bare number** -- resolved only when ``default_system`` names one unit
       outright (``SQ_METRE``/``HECTARE``). Under a positional layout it is ambiguous
       and returns ``None``; see the inline note in the implementation.

    :param default_system: How to read a group with no unit words. Usually
        :func:`default_system_for_format` of the detected record format.
    :param region_key: Required when the value resolves to the bigha family.
    :returns: ``None`` when the text carries no usable number, or when a bare group
        cannot be interpreted without a hint.
    :raises AmbiguousUnitError: if a bigha value is parsed with no ``region_key``.
        Deliberately raised rather than returning ``None`` -- the number was read
        fine, so this is a configuration failure the operator must fix, not missing
        data a reviewer should re-key.
    """
    if raw is None:
        return None
    cleaned = _apply_abbreviations(normalise_numeric_text(raw))
    if not cleaned or not _NUMBER.search(cleaned):
        return None

    units = _find_units(cleaned)
    if units:
        return _parse_with_units(cleaned, units, raw_text=raw, region_key=region_key)

    components = split_numeric_triple(cleaned)
    if not components:
        return None

    if default_system is None:
        return None

    layout = _SYSTEM_LAYOUTS.get(default_system)
    if layout is None:
        # SQ_METRE / HECTARE systems name their unit, so a lone scalar is unambiguous.
        unit = AreaUnit.SQ_METRE if default_system is AreaUnitSystem.SQ_METRE else AreaUnit.HECTARE
        return AreaMeasurement.from_unit(components[0], unit, region_key=region_key, raw_text=raw)

    if len(components) > len(layout):
        # More numbers than the layout has slots: the cell is not what we assumed.
        return None

    if len(components) < 2:
        # A single bare number under a positional layout is genuinely ambiguous --
        # "1.20" on a 7/12 could be 1.20 hectare or 1 ha 20 are, and "8005" could be
        # square metres. Two or more components fix the alignment (most significant
        # first); one does not, so it is reported missing rather than guessed at.
        return None

    values = dict(zip(layout, components, strict=False))
    return _build(values, default_system, raw_text=raw, region_key=region_key)


def _parse_with_units(
    cleaned: str,
    units: list[tuple[int, AreaUnit]],
    *,
    raw_text: str,
    region_key: str | None,
) -> AreaMeasurement | None:
    """Bind each number to its nearest unit keyword."""
    numbers = [(m.start(), Decimal(m.group(0))) for m in _NUMBER.finditer(cleaned)]
    if not numbers:
        return None

    values: dict[AreaUnit, Decimal] = {}
    for position, value in numbers:
        following = [(p, u) for p, u in units if p >= position]
        preceding = [(p, u) for p, u in units if p < position]
        if following:
            unit = following[0][1]
        elif preceding:
            unit = preceding[-1][1]
        else:  # pragma: no cover - units is non-empty by the caller's guard
            continue
        values[unit] = values.get(unit, Decimal(0)) + value

    if not values:
        return None
    return _build(values, _system_for_units(set(values)), raw_text=raw_text, region_key=region_key)


def _system_for_units(units: set[AreaUnit]) -> AreaUnitSystem:
    for system, layout in _SYSTEM_LAYOUTS.items():
        if units & set(layout):
            return system
    if units == {AreaUnit.SQ_METRE}:
        return AreaUnitSystem.SQ_METRE
    if units == {AreaUnit.HECTARE}:
        return AreaUnitSystem.HECTARE
    return AreaUnitSystem.UNKNOWN


def _build(
    values: dict[AreaUnit, Decimal],
    system: AreaUnitSystem,
    *,
    raw_text: str,
    region_key: str | None,
) -> AreaMeasurement:
    """Sum unit-tagged components into one measurement."""
    needs_region = bool(values.keys() & {AreaUnit.BIGHA, AreaUnit.BISWA, AreaUnit.BISWANSI})
    if needs_region and region_key is None:
        raise AmbiguousUnitError(
            f"cannot convert {raw_text!r}: bigha-family units require an explicit region. "
            "Set ADHIKAR_DEFAULT_BIGHA_REGION, or resolve the district from the record header."
        )

    total = AreaMeasurement.zero()
    for unit, amount in values.items():
        total = total + AreaMeasurement.from_unit(amount, unit, region_key=region_key)

    return AreaMeasurement(
        sq_metre=total.sq_metre,
        unit_system=system,
        components=values,
        raw_text=raw_text,
        region_key=region_key if needs_region else None,
    )


def area_from_llm(
    area: LlmArea | None,
    *,
    default_system: AreaUnitSystem | None = None,
    region_key: str | None = None,
) -> AreaMeasurement | None:
    """Convert the LLM's component-wise area reading into a measurement.

    Structured components win when the model filled any of them: they encode the
    model's reading of *which unit each number is*, which is exactly the information
    a bare string loses. ``raw_text`` is the fallback, and is also what gets attached
    to the result for audit either way.
    """
    if area is None:
        return None

    component_fields: list[tuple[AreaUnit, str | None]] = [
        (AreaUnit.HECTARE, area.hectare),
        (AreaUnit.ARE, area.are),
        (AreaUnit.SQ_METRE, area.sq_metre),
        (AreaUnit.ACRE, area.acre),
        (AreaUnit.GUNTHA, area.guntha),
        (AreaUnit.KANAL, area.kanal),
        (AreaUnit.MARLA, area.marla),
        (AreaUnit.BIGHA, area.bigha),
        (AreaUnit.BISWA, area.biswa),
        (AreaUnit.BISWANSI, area.biswansi),
    ]

    values: dict[AreaUnit, Decimal] = {}
    for unit, text in component_fields:
        if text is None or not str(text).strip():
            continue
        parsed = parse_decimal(text, repair=True)
        if parsed is not None:
            values[unit] = parsed

    if values:
        return _build(
            values,
            _system_for_units(set(values)),
            raw_text=area.raw_text or "",
            region_key=region_key,
        )

    return parse_area(area.raw_text, default_system=default_system, region_key=region_key)
