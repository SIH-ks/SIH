"""Deterministic normalisation: numerals, areas, vocabulary, shares, dates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from adhikar.normalize.areas import parse_area
from adhikar.normalize.numerals import (
    parse_decimal,
    repair_ocr_digits,
    split_numeric_triple,
    to_ascii_digits,
)
from adhikar.normalize.vocab import (
    is_equal_share_marker,
    parse_record_date,
    parse_share,
    resolve_classification,
    resolve_tenure,
)
from adhikar.schemas.enums import LandClassification, TenureType
from adhikar.schemas.units import AmbiguousUnitError, AreaUnitSystem

# -- numerals ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("१२३", "123"),
        ("૦-૮૦-૦૫", "0-80-05"),
        ("Khasra 45/2", "Khasra 45/2"),
    ],
)
def test_to_ascii_digits(raw: str, expected: str) -> None:
    assert to_ascii_digits(raw) == expected


def test_parse_decimal_handles_currency_and_grouping() -> None:
    assert parse_decimal("Rs. 1,25,000/-") == Decimal("125000")


def test_parse_decimal_returns_none_for_junk() -> None:
    assert parse_decimal("---") is None
    assert parse_decimal(None) is None


def test_split_numeric_triple() -> None:
    assert split_numeric_triple("0-80-05") == [Decimal("0"), Decimal("80"), Decimal("5")]
    assert split_numeric_triple("1.205") == [Decimal("1.205")]


def test_repair_ocr_digits() -> None:
    assert repair_ocr_digits("O-8O-O5") == "0-80-05"


# -- areas ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_sq_m"),
    [
        ("0-80-05", "8005.0000"),
        ("8005 sq.m.", "8005.0000"),
        ("1.20 Ha", "12000.0000"),
        ("1 acre 20 guntha", "6070.2846"),
    ],
)
def test_parse_area_metric(raw: str, expected_sq_m: str) -> None:
    area = parse_area(raw, default_system=AreaUnitSystem.METRIC_HA_ARE_SQM)
    assert area is not None
    assert area.sq_metre == Decimal(expected_sq_m)


def test_parse_area_bare_number_is_ambiguous_under_positional_layout() -> None:
    assert parse_area("1.20", default_system=AreaUnitSystem.METRIC_HA_ARE_SQM) is None


def test_parse_area_bigha_requires_region() -> None:
    with pytest.raises(AmbiguousUnitError):
        parse_area("2 bigha 10 biswa")
    area = parse_area("2 bigha 10 biswa", region_key="up_pucca")
    assert area is not None


# -- vocabulary ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("चाही", LandClassification.IRRIGATED),
        ("Gair Mumkin", LandClassification.NON_CULTIVABLE),
        ("banjar", LandClassification.CULTIVABLE_WASTE),
    ],
)
def test_resolve_classification_exact(raw: str, expected: LandClassification) -> None:
    match = resolve_classification(raw)
    assert match.resolved
    assert match.value is expected


def test_resolve_tenure_fuzzy_matches_ocr_noise() -> None:
    match = resolve_tenure("भागवटादार वर्ग-1")  # one-character OCR slip
    assert match.resolved
    assert match.value is TenureType.OCCUPANT_CLASS_I
    assert match.is_fuzzy


def test_unresolvable_term_is_unknown_not_a_guess() -> None:
    match = resolve_classification("something entirely unrelated")
    assert not match.resolved


# -- shares --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1/3", "1/3"),
        ("0.3333", "1/3"),
        ("33.33%", "1/3"),
        ("0.25", "1/4"),
        ("0.5", "1/2"),
        ("0.123", "123/1000"),  # not a smooth fraction: taken as written
        ("0.2", "1/5"),
    ],
)
def test_parse_share(raw: str, expected: str) -> None:
    share = parse_share(raw)
    assert share is not None
    assert f"{share.numerator}/{share.denominator}" == expected


def test_equal_share_marker_returns_none() -> None:
    assert is_equal_share_marker("समान")
    assert parse_share("समान") is None


def test_share_cannot_exceed_unity() -> None:
    assert parse_share("5/3") is None


# -- dates -------------------------------------------------------------------------------------


def test_parse_record_date_is_day_first() -> None:
    assert parse_record_date("03/04/2019") == date(2019, 4, 3)


def test_parse_record_date_handles_devanagari_digits() -> None:
    assert parse_record_date("१५-०८-२०२१") == date(2021, 8, 15)


def test_parse_record_date_returns_none_for_junk() -> None:
    assert parse_record_date("junk") is None
