"""The validation rule engine, exercised against deliberately inconsistent parcels."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from adhikar.schemas.enums import EncumbranceStatus, EncumbranceType, MutationStatus, MutationType
from adhikar.schemas.land_record import (
    Encumbrance,
    Jurisdiction,
    LandParcelRecord,
    MutationEntry,
    OwnerRecord,
    OwnershipShare,
    PersonName,
    SubDivision,
)
from adhikar.schemas.units import AreaMeasurement
from adhikar.schemas.validation import RuleCode, Severity
from adhikar.validation import DEFAULT_POLICY, load_policy, registered_rules, run_all


def test_all_rules_are_registered() -> None:
    assert len(registered_rules()) >= 20


def test_clean_parcel_has_no_blocking_issues() -> None:
    parcel = LandParcelRecord(
        survey_number="142",
        total_area=AreaMeasurement.from_hectare_are_sqm(1, 20, 0),
        sub_divisions=[
            SubDivision(sub_division_number="142/1", area=AreaMeasurement.from_hectare_are_sqm(0, 60, 0)),
            SubDivision(sub_division_number="142/2", area=AreaMeasurement.from_hectare_are_sqm(0, 60, 0)),
        ],
        owners=[OwnerRecord(name=PersonName(raw="Test Owner"), share=OwnershipShare.whole())],
        jurisdiction=Jurisdiction(state="Maharashtra", district="Pune", tehsil="Haveli", village="Kondhwa"),
    )
    report = run_all(parcel, DEFAULT_POLICY)
    assert not report.is_blocking
    assert report.integrity_score == 1.0


def test_area_sum_exceeds_total_is_an_error() -> None:
    parcel = LandParcelRecord(
        survey_number="1",
        total_area=AreaMeasurement.from_hectare_are_sqm(1, 0, 0),
        sub_divisions=[
            SubDivision(sub_division_number="1/1", area=AreaMeasurement.from_hectare_are_sqm(0, 70, 0)),
            SubDivision(sub_division_number="1/2", area=AreaMeasurement.from_hectare_are_sqm(0, 70, 0)),
        ],
    )
    report = run_all(parcel, DEFAULT_POLICY)
    codes = {i.rule_code for i in report.issues}
    assert RuleCode.AREA_SUM_EXCEEDS_TOTAL in codes
    assert report.is_blocking


def test_area_sum_mismatch_within_tolerance_is_silent() -> None:
    parcel = LandParcelRecord(
        survey_number="1",
        total_area=AreaMeasurement.from_sq_metre(10_000),
        sub_divisions=[SubDivision(sub_division_number="1/1", area=AreaMeasurement.from_sq_metre(9_999.5))],
    )
    report = run_all(parcel, DEFAULT_POLICY)
    codes = {i.rule_code for i in report.issues}
    assert RuleCode.AREA_SUM_MISMATCH not in codes


def test_share_sum_exceeds_unity() -> None:
    parcel = LandParcelRecord(
        survey_number="1",
        owners=[
            OwnerRecord(name=PersonName(raw="A"), share=OwnershipShare(numerator=2, denominator=3)),
            OwnerRecord(name=PersonName(raw="B"), share=OwnershipShare(numerator=2, denominator=3)),
        ],
    )
    report = run_all(parcel, DEFAULT_POLICY)
    issues = report.issues_for(RuleCode.SHARE_SUM_EXCEEDS_UNITY)
    assert len(issues) == 1
    assert issues[0].severity is Severity.ERROR


def test_orphan_owner_reference() -> None:
    parcel = LandParcelRecord(
        survey_number="1",
        owners=[OwnerRecord(name=PersonName(raw="A"), serial_number="1")],
        sub_divisions=[
            SubDivision(
                sub_division_number="1/1",
                area=AreaMeasurement.from_sq_metre(100),
                owner_serial_numbers=["1", "9"],
            )
        ],
    )
    report = run_all(parcel, DEFAULT_POLICY)
    issues = report.issues_for(RuleCode.ORPHAN_OWNER_REFERENCE)
    assert len(issues) == 1
    assert issues[0].observed == "9"


def test_mutation_pending_unresolved_respects_policy_horizon() -> None:
    old_pending = MutationEntry(
        mutation_number="1",
        mutation_type=MutationType.SALE,
        status=MutationStatus.PENDING,
        entry_date=date.today() - timedelta(days=400),
    )
    parcel = LandParcelRecord(survey_number="1", mutations=[old_pending])
    report = run_all(parcel, DEFAULT_POLICY)
    assert RuleCode.MUTATION_PENDING_UNRESOLVED in {i.rule_code for i in report.issues}


def test_mutation_date_in_future_is_an_error() -> None:
    future = MutationEntry(
        mutation_number="1",
        mutation_type=MutationType.SALE,
        entry_date=date.today() + timedelta(days=10),
    )
    parcel = LandParcelRecord(survey_number="1", mutations=[future])
    report = run_all(parcel, DEFAULT_POLICY)
    issues = report.issues_for(RuleCode.MUTATION_DATE_IN_FUTURE)
    assert len(issues) == 1
    assert issues[0].severity is Severity.ERROR


def test_active_encumbrance_is_informational() -> None:
    parcel = LandParcelRecord(
        survey_number="1",
        total_area=AreaMeasurement.from_sq_metre(1000),  # avoid the unrelated TOTAL_AREA_MISSING critical
        encumbrances=[Encumbrance(encumbrance_type=EncumbranceType.MORTGAGE, status=EncumbranceStatus.ACTIVE)],
    )
    report = run_all(parcel, DEFAULT_POLICY)
    issues = report.issues_for(RuleCode.ENCUMBRANCE_ACTIVE)
    assert len(issues) == 1
    assert issues[0].severity is Severity.INFO
    assert not report.is_blocking


def test_identifier_missing_is_critical() -> None:
    parcel = LandParcelRecord()
    report = run_all(parcel, DEFAULT_POLICY)
    issues = report.issues_for(RuleCode.IDENTIFIER_MISSING)
    assert len(issues) == 1
    assert issues[0].severity is Severity.CRITICAL


def test_policy_severity_override(tmp_path) -> None:  # noqa: ANN001
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        """
name: test
default_absolute_sq_metre: 1.0
default_relative: 0.005
rules:
  IDENTIFIER_MISSING:
    severity: warning
""",
        encoding="utf-8",
    )
    policy = load_policy(policy_file)
    parcel = LandParcelRecord(total_area=AreaMeasurement.from_sq_metre(1000))
    report = run_all(parcel, policy)
    issues = report.issues_for(RuleCode.IDENTIFIER_MISSING)
    assert issues[0].severity is Severity.WARNING
    assert not report.is_blocking


def test_policy_rejects_unknown_rule_code(tmp_path) -> None:  # noqa: ANN001
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text("rules:\n  NOT_A_REAL_RULE:\n    severity: error\n", encoding="utf-8")
    import pytest

    from adhikar.exceptions import ValidationConfigError

    with pytest.raises(ValidationConfigError):
        load_policy(policy_file)


def test_a_broken_rule_does_not_sink_the_whole_report(monkeypatch) -> None:  # noqa: ANN001
    """A rule that raises becomes one CRITICAL finding, not a crashed pipeline."""
    from adhikar.validation import registry, rules

    def _boom(parcel, policy):  # noqa: ANN001, ARG001
        raise RuntimeError("simulated bug in a rule")
        yield  # pragma: no cover - makes this a generator function

    monkeypatch.setitem(
        registry._REGISTRY,
        RuleCode.TOTAL_AREA_MISSING,
        registry._RegisteredRule(code=RuleCode.TOTAL_AREA_MISSING, func=_boom, description="broken for test"),
    )
    parcel = LandParcelRecord(survey_number="1")
    report = run_all(parcel, DEFAULT_POLICY)
    broken = [i for i in report.issues if "simulated bug" in i.message]
    assert len(broken) == 1
    assert broken[0].severity is Severity.CRITICAL
    # every other rule still ran
    assert RuleCode.IDENTIFIER_MISSING not in {i.rule_code for i in report.issues}  # survey_number present
