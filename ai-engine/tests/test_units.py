"""Area unit conversion: exactness and the bigha-region guard."""

from __future__ import annotations

from decimal import Decimal

import pytest

from adhikar.schemas.units import (
    BIGHA_REGISTRY,
    SQ_METRE_PER_UNIT,
    AmbiguousUnitError,
    AreaMeasurement,
    AreaUnit,
)


def test_hectare_are_sqm_composition() -> None:
    area = AreaMeasurement.from_hectare_are_sqm(0, 80, 5)
    assert area.sq_metre == Decimal("8005.0000")


def test_acre_guntha_exact_factors() -> None:
    assert SQ_METRE_PER_UNIT[AreaUnit.GUNTHA] * 40 == SQ_METRE_PER_UNIT[AreaUnit.ACRE]
    assert SQ_METRE_PER_UNIT[AreaUnit.KANAL] * 8 == SQ_METRE_PER_UNIT[AreaUnit.ACRE]
    assert SQ_METRE_PER_UNIT[AreaUnit.MARLA] * 20 == SQ_METRE_PER_UNIT[AreaUnit.KANAL]


def test_bigha_requires_region() -> None:
    with pytest.raises(AmbiguousUnitError):
        AreaMeasurement.from_bigha(2, region_key="does_not_exist")


def test_bigha_with_region_resolves() -> None:
    area = AreaMeasurement.from_bigha(1, 0, 0, region_key="up_pucca")
    assert area.sq_metre == BIGHA_REGISTRY["up_pucca"].sq_metre_per_bigha.quantize(Decimal("0.0001"))


def test_addition_preserves_shared_unit_system() -> None:
    a = AreaMeasurement.from_hectare_are_sqm(0, 40, 0)
    b = AreaMeasurement.from_hectare_are_sqm(0, 40, 5)
    total = a + b
    assert total.sq_metre == Decimal("8005.0000")


def test_approx_equals_absolute_and_relative_tolerance() -> None:
    a = AreaMeasurement.from_sq_metre(10_000)
    b = AreaMeasurement.from_sq_metre(10_000.5)
    assert a.approx_equals(b, abs_tol_sq_metre=Decimal("1.0"), rel_tol=Decimal("0"))

    c = AreaMeasurement.from_sq_metre(10_060)  # 0.6% off
    assert not a.approx_equals(c, abs_tol_sq_metre=Decimal("1.0"), rel_tol=Decimal("0.005"))


def test_relative_difference_handles_zero_reference() -> None:
    zero = AreaMeasurement.zero()
    non_zero = AreaMeasurement.from_sq_metre(100)
    assert zero.relative_difference(zero) == Decimal(0)
    assert non_zero.relative_difference(zero) == Decimal(1)
