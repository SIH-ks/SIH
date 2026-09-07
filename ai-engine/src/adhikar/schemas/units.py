"""Area value type with exact, auditable unit conversion.

Design notes
------------
**Everything canonicalises to square metres, stored as :class:`~decimal.Decimal`.**
Land-record arithmetic is money-adjacent: a parcel that fails an area-sum check by
0.5 sq m is a real dispute, so binary floating point is not acceptable. All factors
below are exact rationals where a statutory definition exists.

**Bigha is not a unit -- it is a family of units.** It ranges from ~843 sq m
(Punjab / UP kachcha) to ~2529 sq m (UP / Rajasthan pucca), a 3x spread. Converting
a bigha figure without knowing the region silently fabricates area, so
:meth:`AreaMeasurement.from_bigha` *requires* a region key and raises
:class:`AmbiguousUnitError` otherwise. Refusing to guess is the whole point.

**Components are retained.** ``0-80-05`` on a 7/12 extract means 0 hectare, 80 are,
5 sq m. Keeping the printed triple alongside the canonical value lets the reviewer
console show the record as the clerk wrote it, and lets the validator check that the
printed triple is internally consistent with any printed sq-m total.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "BIGHA_REGISTRY",
    "SQ_METRE_PER_UNIT",
    "AmbiguousUnitError",
    "AreaMeasurement",
    "AreaUnit",
    "AreaUnitSystem",
    "BighaDefinition",
    "UnitConversionError",
]


class UnitConversionError(ValueError):
    """Raised when a quantity cannot be converted to square metres."""


class AmbiguousUnitError(UnitConversionError):
    """Raised when a region-dependent unit is used without a region key.

    Deliberately *not* recoverable by falling back to a default. A wrong bigha
    definition is worse than no answer, because it produces a plausible number.
    """


class AreaUnit(StrEnum):
    """Units that appear on Indian land records."""

    SQ_METRE = "sq_metre"
    HECTARE = "hectare"
    ARE = "are"
    """1/100 hectare = 100 sq m. The 'R' in the 7/12 H-R-Sq.M triple."""

    ACRE = "acre"
    GUNTHA = "guntha"
    """1/40 acre. Maharashtra / Karnataka."""

    KANAL = "kanal"
    """1/8 acre. Punjab, Haryana, Himachal, J&K."""

    MARLA = "marla"
    """1/20 kanal."""

    BIGHA = "bigha"
    """Region-dependent. See :data:`BIGHA_REGISTRY`."""

    BISWA = "biswa"
    """1/20 bigha -- inherits the bigha's region dependence."""

    BISWANSI = "biswansi"
    """1/20 biswa."""

    SQ_FOOT = "sq_foot"
    SQ_YARD = "sq_yard"


class AreaUnitSystem(StrEnum):
    """The notation the record actually prints, used to render values back."""

    METRIC_HA_ARE_SQM = "metric_ha_are_sqm"
    """7/12 style ``H-R-Sq.M``, e.g. ``0-80-05``."""

    ACRE_GUNTHA = "acre_guntha"
    KANAL_MARLA = "kanal_marla"
    BIGHA_BISWA = "bigha_biswa"
    SQ_METRE = "sq_metre"
    HECTARE = "hectare"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------------------
# Exact conversion factors
# --------------------------------------------------------------------------------------
# International yard = 0.9144 m exactly (1959 agreement, adopted by the Indian
# Standards of Weights and Measures Act). Every imperial-derived factor below is
# derived from it, so they are exact rather than rounded.

_SQ_YARD = Decimal("0.83612736")  # 0.9144^2
_SQ_FOOT = Decimal("0.09290304")  # 0.3048^2
_ACRE = Decimal("4046.8564224")  # 4840 sq yd

SQ_METRE_PER_UNIT: dict[AreaUnit, Decimal] = {
    AreaUnit.SQ_METRE: Decimal(1),
    AreaUnit.HECTARE: Decimal(10_000),
    AreaUnit.ARE: Decimal(100),
    AreaUnit.ACRE: _ACRE,
    AreaUnit.GUNTHA: _ACRE / 40,  # 101.17141056
    AreaUnit.KANAL: _ACRE / 8,  # 505.8570528
    AreaUnit.MARLA: _ACRE / 160,  # 25.29285264
    AreaUnit.SQ_FOOT: _SQ_FOOT,
    AreaUnit.SQ_YARD: _SQ_YARD,
}
"""Square metres per unit, for units with a single national definition.

BIGHA/BISWA/BISWANSI are intentionally absent -- they resolve through
:data:`BIGHA_REGISTRY` instead.
"""


class BighaDefinition(BaseModel):
    """One region's bigha, with the authority it derives from."""

    model_config = ConfigDict(frozen=True)

    region_key: str
    label: str
    sq_metre_per_bigha: Decimal
    biswa_per_bigha: int = 20
    biswansi_per_biswa: int = 20
    note: str = ""

    @property
    def sq_metre_per_biswa(self) -> Decimal:
        return self.sq_metre_per_bigha / self.biswa_per_bigha

    @property
    def sq_metre_per_biswansi(self) -> Decimal:
        return self.sq_metre_per_biswa / self.biswansi_per_biswa


def _bigha(key: str, label: str, sq_yards: str | None, sq_m: str | None, note: str) -> BighaDefinition:
    value = Decimal(sq_yards) * _SQ_YARD if sq_yards is not None else Decimal(str(sq_m))
    return BighaDefinition(region_key=key, label=label, sq_metre_per_bigha=value, note=note)


BIGHA_REGISTRY: dict[str, BighaDefinition] = {
    d.region_key: d
    for d in [
        _bigha("up_pucca", "Uttar Pradesh (pucca bigha)", "3025", None, "3025 sq yd."),
        _bigha(
            "up_kachcha",
            "Uttar Pradesh (kachcha bigha)",
            None,
            "843.0950880",
            "One third of the pucca bigha; district practice varies -- verify locally.",
        ),
        _bigha("rajasthan_pucca", "Rajasthan (pucca bigha)", "3025", None, "3025 sq yd."),
        _bigha("rajasthan_kachcha", "Rajasthan (kachcha bigha)", "1936", None, "1936 sq yd."),
        _bigha("gujarat", "Gujarat", "1936", None, "1936 sq yd; 1 bigha = 16 guntha locally."),
        _bigha("west_bengal", "West Bengal", "1600", None, "1600 sq yd = 20 katha."),
        _bigha("assam", "Assam", "1600", None, "1600 sq yd = 5 katha."),
        _bigha("bihar", "Bihar", None, "2529.2852640", "20 katha; 27225 sq ft."),
        _bigha(
            "punjab_haryana",
            "Punjab / Haryana",
            "1008",
            None,
            "1008 sq yd; 4 bigha 16 biswa = 1 acre.",
        ),
        _bigha("himachal", "Himachal Pradesh", "1008", None, "1008 sq yd."),
        _bigha("madhya_pradesh", "Madhya Pradesh", "1200", None, "1200 sq yd."),
        _bigha("uttarakhand", "Uttarakhand", "1000", None, "Hill districts; 1000 sq yd."),
    ]
}
"""Region-keyed bigha definitions.

Sourced from state Land Revenue Acts and settlement manuals. Where district practice
diverges from the state norm the ``note`` says so -- treat those as review-worthy.
"""

NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class AreaMeasurement(BaseModel):
    """An immutable area, canonicalised to square metres.

    Construct through the ``from_*`` classmethods rather than the initialiser, so the
    printed components and the canonical value can never drift apart.

    >>> a = AreaMeasurement.from_hectare_are_sqm(0, 80, 5)
    >>> a.sq_metre
    Decimal('8005')
    >>> b = AreaMeasurement.from_acre_guntha(1, 20)
    >>> round(float(b.hectare), 4)
    0.6070
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sq_metre: NonNegativeDecimal
    """Canonical value. Every comparison and sum uses this field."""

    unit_system: AreaUnitSystem = AreaUnitSystem.UNKNOWN
    """How the source document printed it -- drives display, never arithmetic."""

    components: dict[AreaUnit, Decimal] = Field(default_factory=dict)
    """The printed parts, e.g. ``{HECTARE: 0, ARE: 80, SQ_METRE: 5}``."""

    raw_text: str | None = None
    """Verbatim cell text, kept for audit and for reviewer diffing."""

    region_key: str | None = None
    """Set when a region-dependent unit (bigha family) was resolved."""

    @field_validator("sq_metre")
    @classmethod
    def _quantise(cls, v: Decimal) -> Decimal:
        """Round to 1 sq cm.

        Cadastral survey precision does not exceed this, and it keeps equality
        well-behaved across the several division paths (acre/40, kanal/160, ...).
        """
        return v.quantize(Decimal("0.0001"))

    @model_validator(mode="after")
    def _check_region_key(self) -> Self:
        if self.region_key is not None and self.region_key not in BIGHA_REGISTRY:
            raise ValueError(
                f"unknown region_key {self.region_key!r}; "
                f"expected one of {sorted(BIGHA_REGISTRY)}"
            )
        return self

    # -- constructors ------------------------------------------------------------------

    @classmethod
    def zero(cls) -> AreaMeasurement:
        return cls(sq_metre=Decimal(0), unit_system=AreaUnitSystem.SQ_METRE)

    @classmethod
    def from_sq_metre(cls, value: Decimal | int | float | str, *, raw_text: str | None = None) -> AreaMeasurement:
        return cls(
            sq_metre=_as_decimal(value),
            unit_system=AreaUnitSystem.SQ_METRE,
            components={AreaUnit.SQ_METRE: _as_decimal(value)},
            raw_text=raw_text,
        )

    @classmethod
    def from_hectare_are_sqm(
        cls,
        hectare: Decimal | int | float | str = 0,
        are: Decimal | int | float | str = 0,
        sq_metre: Decimal | int | float | str = 0,
        *,
        raw_text: str | None = None,
    ) -> AreaMeasurement:
        """Build from the ``H-R-Sq.M`` triple used on 7/12 extracts.

        No range check on ``are``/``sq_metre``: clerks legitimately write ``0-105-00``
        for 1.05 ha. Out-of-range components are surfaced by the validation rule
        ``AREA_COMPONENT_OUT_OF_RANGE`` instead, where a reviewer can see them.
        """
        h, a, s = _as_decimal(hectare), _as_decimal(are), _as_decimal(sq_metre)
        total = h * SQ_METRE_PER_UNIT[AreaUnit.HECTARE] + a * SQ_METRE_PER_UNIT[AreaUnit.ARE] + s
        return cls(
            sq_metre=total,
            unit_system=AreaUnitSystem.METRIC_HA_ARE_SQM,
            components={AreaUnit.HECTARE: h, AreaUnit.ARE: a, AreaUnit.SQ_METRE: s},
            raw_text=raw_text,
        )

    @classmethod
    def from_acre_guntha(
        cls,
        acre: Decimal | int | float | str = 0,
        guntha: Decimal | int | float | str = 0,
        *,
        raw_text: str | None = None,
    ) -> AreaMeasurement:
        ac, gu = _as_decimal(acre), _as_decimal(guntha)
        total = ac * SQ_METRE_PER_UNIT[AreaUnit.ACRE] + gu * SQ_METRE_PER_UNIT[AreaUnit.GUNTHA]
        return cls(
            sq_metre=total,
            unit_system=AreaUnitSystem.ACRE_GUNTHA,
            components={AreaUnit.ACRE: ac, AreaUnit.GUNTHA: gu},
            raw_text=raw_text,
        )

    @classmethod
    def from_kanal_marla(
        cls,
        kanal: Decimal | int | float | str = 0,
        marla: Decimal | int | float | str = 0,
        *,
        raw_text: str | None = None,
    ) -> AreaMeasurement:
        ka, ma = _as_decimal(kanal), _as_decimal(marla)
        total = ka * SQ_METRE_PER_UNIT[AreaUnit.KANAL] + ma * SQ_METRE_PER_UNIT[AreaUnit.MARLA]
        return cls(
            sq_metre=total,
            unit_system=AreaUnitSystem.KANAL_MARLA,
            components={AreaUnit.KANAL: ka, AreaUnit.MARLA: ma},
            raw_text=raw_text,
        )

    @classmethod
    def from_bigha(
        cls,
        bigha: Decimal | int | float | str = 0,
        biswa: Decimal | int | float | str = 0,
        biswansi: Decimal | int | float | str = 0,
        *,
        region_key: str,
        raw_text: str | None = None,
    ) -> AreaMeasurement:
        """Build from bigha-biswa-biswansi for an explicitly named region.

        :raises AmbiguousUnitError: if ``region_key`` is not in :data:`BIGHA_REGISTRY`.
            The caller must resolve the region (from the record's district header, or
            from operator configuration) -- the engine will not pick one.
        """
        definition = BIGHA_REGISTRY.get(region_key)
        if definition is None:
            raise AmbiguousUnitError(
                f"bigha is region-dependent and {region_key!r} is not a known region. "
                f"Known regions: {sorted(BIGHA_REGISTRY)}. "
                "Resolve the district from the record header before converting."
            )
        bi, bs, bn = _as_decimal(bigha), _as_decimal(biswa), _as_decimal(biswansi)
        total = (
            bi * definition.sq_metre_per_bigha
            + bs * definition.sq_metre_per_biswa
            + bn * definition.sq_metre_per_biswansi
        )
        return cls(
            sq_metre=total,
            unit_system=AreaUnitSystem.BIGHA_BISWA,
            components={AreaUnit.BIGHA: bi, AreaUnit.BISWA: bs, AreaUnit.BISWANSI: bn},
            raw_text=raw_text,
            region_key=region_key,
        )

    @classmethod
    def from_unit(
        cls,
        value: Decimal | int | float | str,
        unit: AreaUnit,
        *,
        region_key: str | None = None,
        raw_text: str | None = None,
    ) -> AreaMeasurement:
        """Generic single-unit constructor, used by the free-text area parser."""
        if unit in (AreaUnit.BIGHA, AreaUnit.BISWA, AreaUnit.BISWANSI):
            if region_key is None:
                raise AmbiguousUnitError(f"{unit.value} requires an explicit region_key")
            definition = BIGHA_REGISTRY.get(region_key)
            if definition is None:
                raise AmbiguousUnitError(f"unknown region_key {region_key!r}")
            factor = {
                AreaUnit.BIGHA: definition.sq_metre_per_bigha,
                AreaUnit.BISWA: definition.sq_metre_per_biswa,
                AreaUnit.BISWANSI: definition.sq_metre_per_biswansi,
            }[unit]
            system = AreaUnitSystem.BIGHA_BISWA
        else:
            try:
                factor = SQ_METRE_PER_UNIT[unit]
            except KeyError as exc:  # pragma: no cover - enum is exhaustive above
                raise UnitConversionError(f"no conversion factor for {unit!r}") from exc
            system = {
                AreaUnit.HECTARE: AreaUnitSystem.HECTARE,
                AreaUnit.SQ_METRE: AreaUnitSystem.SQ_METRE,
                AreaUnit.ACRE: AreaUnitSystem.ACRE_GUNTHA,
                AreaUnit.GUNTHA: AreaUnitSystem.ACRE_GUNTHA,
                AreaUnit.KANAL: AreaUnitSystem.KANAL_MARLA,
                AreaUnit.MARLA: AreaUnitSystem.KANAL_MARLA,
            }.get(unit, AreaUnitSystem.UNKNOWN)

        amount = _as_decimal(value)
        return cls(
            sq_metre=amount * factor,
            unit_system=system,
            components={unit: amount},
            raw_text=raw_text,
            region_key=region_key,
        )

    # -- conversions ---------------------------------------------------------------------

    @property
    def hectare(self) -> Decimal:
        return self.sq_metre / SQ_METRE_PER_UNIT[AreaUnit.HECTARE]

    @property
    def are(self) -> Decimal:
        return self.sq_metre / SQ_METRE_PER_UNIT[AreaUnit.ARE]

    @property
    def acre(self) -> Decimal:
        return self.sq_metre / SQ_METRE_PER_UNIT[AreaUnit.ACRE]

    def to_hectare_are_sqm(self) -> tuple[int, int, Decimal]:
        """Decompose into the printed ``H-R-Sq.M`` triple."""
        total = self.sq_metre
        hectare = int(total // SQ_METRE_PER_UNIT[AreaUnit.HECTARE])
        remainder = total - hectare * SQ_METRE_PER_UNIT[AreaUnit.HECTARE]
        are = int(remainder // SQ_METRE_PER_UNIT[AreaUnit.ARE])
        sq_m = remainder - are * SQ_METRE_PER_UNIT[AreaUnit.ARE]
        return hectare, are, sq_m

    def to_acre_guntha(self) -> tuple[int, Decimal]:
        acre = int(self.sq_metre // SQ_METRE_PER_UNIT[AreaUnit.ACRE])
        remainder = self.sq_metre - acre * SQ_METRE_PER_UNIT[AreaUnit.ACRE]
        return acre, remainder / SQ_METRE_PER_UNIT[AreaUnit.GUNTHA]

    def format_native(self) -> str:
        """Render in the notation the source used -- what the reviewer expects to see."""
        match self.unit_system:
            case AreaUnitSystem.METRIC_HA_ARE_SQM:
                h, a, s = self.to_hectare_are_sqm()
                return f"{h}-{a:02d}-{s:05.2f} H-R-Sq.M"
            case AreaUnitSystem.ACRE_GUNTHA:
                ac, gu = self.to_acre_guntha()
                return f"{ac} acre {gu:.2f} guntha"
            case AreaUnitSystem.KANAL_MARLA:
                ka = int(self.sq_metre // SQ_METRE_PER_UNIT[AreaUnit.KANAL])
                ma = (self.sq_metre - ka * SQ_METRE_PER_UNIT[AreaUnit.KANAL]) / SQ_METRE_PER_UNIT[
                    AreaUnit.MARLA
                ]
                return f"{ka} kanal {ma:.2f} marla"
            case AreaUnitSystem.HECTARE:
                return f"{self.hectare:.4f} ha"
            case _:
                return f"{self.sq_metre:.2f} sq m"

    # -- arithmetic -----------------------------------------------------------------------

    def __add__(self, other: AreaMeasurement) -> AreaMeasurement:
        """Sum two areas.

        The result keeps the shared unit system when both agree, so a sum of 7/12
        sub-division areas still renders as an H-R-Sq.M triple.
        """
        if not isinstance(other, AreaMeasurement):  # pragma: no cover - typing guard
            return NotImplemented
        system = self.unit_system if self.unit_system == other.unit_system else AreaUnitSystem.SQ_METRE
        return AreaMeasurement(
            sq_metre=self.sq_metre + other.sq_metre,
            unit_system=system,
            region_key=self.region_key or other.region_key,
        )

    def __sub__(self, other: AreaMeasurement) -> AreaMeasurement:
        """Difference of two areas, floored at zero.

        Areas are non-negative by construction; a negative difference means the
        record is inconsistent, which the validation engine reports as
        ``AREA_SUM_EXCEEDS_TOTAL`` rather than being represented as a negative area.
        """
        if not isinstance(other, AreaMeasurement):  # pragma: no cover - typing guard
            return NotImplemented
        return AreaMeasurement(
            sq_metre=max(Decimal(0), self.sq_metre - other.sq_metre),
            unit_system=self.unit_system,
            region_key=self.region_key,
        )

    @property
    def is_zero(self) -> bool:
        return self.sq_metre == 0

    def absolute_difference(self, other: AreaMeasurement) -> Decimal:
        return abs(self.sq_metre - other.sq_metre)

    def relative_difference(self, other: AreaMeasurement) -> Decimal:
        """Fractional difference against ``other`` as the reference denominator.

        Returns ``0`` when both are zero, and ``1`` when the reference is zero but
        this is not -- avoids a ZeroDivisionError on empty rows without inventing a
        misleadingly small mismatch.
        """
        if other.sq_metre == 0:
            return Decimal(0) if self.sq_metre == 0 else Decimal(1)
        return self.absolute_difference(other) / other.sq_metre

    def approx_equals(
        self,
        other: AreaMeasurement,
        *,
        abs_tol_sq_metre: Decimal = Decimal("1.0"),
        rel_tol: Decimal = Decimal("0.005"),
    ) -> bool:
        """Tolerant equality.

        Passes when the difference is within *either* the absolute floor (rounding on
        small parcels) or the relative band (survey error on large ones). Defaults are
        1 sq m / 0.5%, overridable per-rule from the validation policy file.
        """
        diff = self.absolute_difference(other)
        return diff <= abs_tol_sq_metre or self.relative_difference(other) <= rel_tol

    def __str__(self) -> str:
        return self.format_native()


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    """Coerce to Decimal without inheriting binary float error.

    Floats route through ``str`` so ``0.1`` becomes ``Decimal('0.1')`` rather than
    ``Decimal('0.1000000000000000055511151231257827021181583404541015625')``.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, int):
        return Decimal(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return Decimal(0)
    try:
        return Decimal(text)
    except Exception as exc:  # noqa: BLE001 - normalise every failure to our error type
        raise UnitConversionError(f"cannot parse {value!r} as a numeric area") from exc


def sum_areas(areas: list[AreaMeasurement] | tuple[AreaMeasurement, ...]) -> AreaMeasurement:
    """Total a collection, preserving the unit system when it is unanimous."""
    if not areas:
        return AreaMeasurement.zero()
    total = areas[0]
    for area in areas[1:]:
        total = total + area
    return total


def _sanity_check() -> dict[str, Any]:  # pragma: no cover - documentation aid
    """Hand-checkable conversions, used in the README and by ``test_units``."""
    return {
        "1 acre in sq m": SQ_METRE_PER_UNIT[AreaUnit.ACRE],
        "40 guntha == 1 acre": SQ_METRE_PER_UNIT[AreaUnit.GUNTHA] * 40 == SQ_METRE_PER_UNIT[AreaUnit.ACRE],
        "8 kanal == 1 acre": SQ_METRE_PER_UNIT[AreaUnit.KANAL] * 8 == SQ_METRE_PER_UNIT[AreaUnit.ACRE],
        "0-80-05 in sq m": AreaMeasurement.from_hectare_are_sqm(0, 80, 5).sq_metre,
    }
