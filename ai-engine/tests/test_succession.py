"""Ownership succession validation, exercised against deliberately awkward bundles.

Each test builds a case the way a revenue office would actually receive one -- some
documents present, some missing, names spelled two ways -- and asserts on the *check
statuses and rule codes*, never on the prose. Asserting on wording would make every
copy edit a test failure, and the wording is the part most likely to be improved.

The commitment these tests are really protecting is the one in the module docstring:
the engine never concludes that a transfer was improper. ``test_exclusive_transfer_*``
asserts the outcome is ``REVIEW_REQUIRED`` rather than any kind of failure, and
``test_no_outcome_asserts_wrongdoing`` asserts the vocabulary has no member that could.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from adhikar.normalize.identifiers import compare_identifier, normalize_identifier
from adhikar.normalize.names import match_names, name_similarity, normalize_name
from adhikar.schemas.enums import MutationStatus, MutationType, RelationType
from adhikar.schemas.land_record import (
    Jurisdiction,
    LandParcelRecord,
    OwnerRecord,
    OwnershipShare,
    PersonName,
)
from adhikar.schemas.succession import (
    CheckStatus,
    DeathRecord,
    HeirCandidate,
    MutationRecord,
    OwnershipEntry,
    OwnershipEventType,
    ParcelIdentity,
    RecordSnapshot,
    RiskLevel,
    SuccessionAction,
    SuccessionCase,
    SuccessionDocumentType,
    SuccessionEventType,
    SuccessionOutcome,
    SupportingDocument,
)
from adhikar.schemas.units import AreaMeasurement
from adhikar.schemas.validation import RuleCode
from adhikar.succession import normalize_case, parse_document_text, snapshot_from_record
from adhikar.validation import DEFAULT_POLICY, validate_documents, validate_succession

# ======================================================================================
# Fixtures: the running example from the specification
# ======================================================================================

HECTARE = Decimal("10000")


def _ha(value: str) -> AreaMeasurement:
    return AreaMeasurement.from_unit(Decimal(value), __import__(
        "adhikar.schemas.units", fromlist=["AreaUnit"]
    ).AreaUnit.HECTARE)


def _parcel(**overrides) -> ParcelIdentity:
    base = {
        "khasra_number": "125/2",
        "khata_number": "123",
        "village": "Angol",
        "tehsil": "Belagavi",
        "district": "Belagavi",
        "state": "Karnataka",
        "area": _ha("5.0"),
    }
    return ParcelIdentity(**{**base, **overrides})


def _owner(name: str, share: str | None = "1/1", *, relation: RelationType = RelationType.UNKNOWN,
           relation_name: str | None = None) -> OwnershipEntry:
    numerator, denominator = (share.split("/") if share else (None, None))
    return OwnershipEntry(
        name=PersonName(raw=name, relation_type=relation, relation_name=relation_name),
        share=OwnershipShare(numerator=int(numerator), denominator=int(denominator)) if share else None,
    )


def _old_record(**overrides) -> RecordSnapshot:
    defaults = {
        "label": "Old Jamabandi (2019-20)",
        "document_type": SuccessionDocumentType.JAMABANDI,
        "as_of": date(2019, 1, 1),
        "as_of_inferred": True,
        "revenue_year": "2019-20",
        "parcel": _parcel(),
        "owners": [_owner("Ramesh Sharma")],
    }
    return RecordSnapshot(**{**defaults, **overrides})


def _new_record(**overrides) -> RecordSnapshot:
    defaults = {
        "label": "Updated Jamabandi (2025-26)",
        "document_type": SuccessionDocumentType.UPDATED_JAMABANDI,
        "as_of": date(2025, 1, 1),
        "as_of_inferred": True,
        "revenue_year": "2025-26",
        "parcel": _parcel(),
        "owners": [
            _owner("Amit Sharma", relation=RelationType.SON_OF, relation_name="Ramesh Sharma")
        ],
    }
    return RecordSnapshot(**{**defaults, **overrides})


def _death(name: str = "Ramesh Sharma", when: date | None = date(2025, 5, 12)) -> DeathRecord:
    return DeathRecord(
        person=PersonName(raw=name),
        date_of_death=when,
        registration_number="BLG/2025/4471",
        document_label="Death certificate",
    )


def _heirs() -> list[HeirCandidate]:
    return [
        HeirCandidate(name=PersonName(raw="Sita Sharma"), relation_to_deceased=RelationType.WIFE_OF,
                      deceased_name="Ramesh Sharma"),
        HeirCandidate(name=PersonName(raw="Amit Sharma"), relation_to_deceased=RelationType.SON_OF,
                      deceased_name="Ramesh Sharma"),
        HeirCandidate(name=PersonName(raw="Priya Sharma"), relation_to_deceased=RelationType.DAUGHTER_OF,
                      deceased_name="Ramesh Sharma"),
    ]


def _mutation(**overrides) -> MutationRecord:
    defaults = {
        "mutation_number": "MUT/2025/812",
        "mutation_type": MutationType.INHERITANCE,
        "status": MutationStatus.SANCTIONED,
        "order_date": date(2025, 8, 2),
        "parcel": _parcel(),
        "previous_owners": [_owner("Ramesh Sharma", None)],
        "new_owners": [_owner("Amit Sharma")],
        "document_label": "Mutation MUT/2025/812",
    }
    return MutationRecord(**{**defaults, **overrides})


def _case(**overrides) -> SuccessionCase:
    defaults = {
        "case_id": "demo",
        "parcel_key": "Angol/123/125/2",
        "record_snapshots": [_old_record(), _new_record()],
        "death_records": [_death()],
        "heirs": _heirs(),
        "mutations": [_mutation()],
    }
    return SuccessionCase(**{**defaults, **overrides})


def _status(report, rule: str) -> CheckStatus:
    matches = [c for c in report.checks if c.rule == rule]
    assert matches, f"check {rule!r} did not run; checks were {sorted({c.rule for c in report.checks})}"
    return max((c.status for c in matches), key=lambda s: s.rank)


def _codes(report) -> set[RuleCode]:
    return {c.rule_code for c in report.checks if not c.status.is_clear}


# ======================================================================================
# 1. Owner death + matching mutation
# ======================================================================================


def test_owner_death_with_matching_mutation_passes_the_identity_and_parcel_checks() -> None:
    report = validate_succession(_case())

    assert report.event_type is SuccessionEventType.OWNER_DEATH_SUCCESSION
    assert report.death_verified is True
    assert _status(report, "OWNER_IDENTITY_MATCH") is CheckStatus.PASS
    assert _status(report, "PARCEL_MATCH") is CheckStatus.PASS
    assert _status(report, "MUTATION_PREDECESSOR_MATCH") is CheckStatus.PASS
    assert _status(report, "MUTATION_PARCEL_MATCH") is CheckStatus.PASS
    assert _status(report, "TRANSITION_AFTER_DEATH") is CheckStatus.PASS
    assert _status(report, "SUCCESSION_EVIDENCE") is CheckStatus.PASS


def test_a_coherent_chain_is_validated_and_scores_zero() -> None:
    """The sole heir takes the parcel: nothing is unexplained, so nothing is flagged.

    The counter-case to every test below. A system that flagged this one too would
    be useless in a district where most successions are exactly this shape.
    """
    case = _case(
        heirs=[
            HeirCandidate(
                name=PersonName(raw="Amit Sharma"),
                relation_to_deceased=RelationType.SON_OF,
                deceased_name="Ramesh Sharma",
            )
        ]
    )
    report = validate_succession(case)

    assert report.outcome is SuccessionOutcome.VALIDATED
    assert report.risk_score == 0.0
    assert report.risk_level is RiskLevel.LOW
    assert report.recommended_action is SuccessionAction.ACCEPT_RECORD
    assert report.findings == []
    assert report.requires_human_review is False


# ======================================================================================
# 2. Death certificate owner mismatch
# ======================================================================================


def test_death_certificate_for_someone_who_was_never_the_owner_fails_s1() -> None:
    report = validate_succession(_case(death_records=[_death("Mahesh Kulkarni")]))

    assert _status(report, "OWNER_IDENTITY_MATCH") is CheckStatus.FAIL
    assert RuleCode.SUCCESSION_OWNER_IDENTITY_MISMATCH in _codes(report)
    assert report.outcome is SuccessionOutcome.INCONSISTENT
    assert report.death_verified is False


def test_identity_mismatch_names_the_score_it_rejected_on() -> None:
    """The threshold has to be auditable, not just applied."""
    report = validate_succession(_case(death_records=[_death("Mahesh Kulkarni")]))
    check = next(c for c in report.checks if c.rule == "OWNER_IDENTITY_MATCH")
    assert check.match_score is not None
    assert check.match_score < 0.88
    assert "0.88" in check.explanation


# ======================================================================================
# 3. Parcel mismatch
# ======================================================================================


def test_records_describing_different_land_fail_s3() -> None:
    report = validate_succession(
        _case(record_snapshots=[_old_record(), _new_record(parcel=_parcel(khasra_number="311/1"))])
    )

    assert _status(report, "PARCEL_MATCH") is CheckStatus.FAIL
    assert RuleCode.SUCCESSION_PARCEL_MISMATCH in _codes(report)


def test_a_parent_survey_number_against_its_hissa_is_a_warning_not_a_failure() -> None:
    """``125`` against ``125/2`` is routine shorthand in some districts.

    Reported so a reviewer sees it, not failed -- the engine has no way to know which
    district's convention is in play, and refusing the whole case over it would be
    wrong more often than right.
    """
    report = validate_succession(
        _case(record_snapshots=[_old_record(parcel=_parcel(khasra_number="125")), _new_record()])
    )
    assert _status(report, "PARCEL_MATCH") is CheckStatus.WARNING


def test_records_with_no_identifier_in_common_ask_for_review_rather_than_asserting_a_match() -> None:
    bare = ParcelIdentity(village="Angol")
    report = validate_succession(
        _case(
            record_snapshots=[
                _old_record(parcel=ParcelIdentity(khasra_number="125/2")),
                _new_record(parcel=ParcelIdentity(khata_number="123")),
            ]
        )
    )
    assert _status(report, "PARCEL_MATCH") is CheckStatus.REVIEW_REQUIRED
    assert bare.identifier_fields == {"village": "Angol"}


# ======================================================================================
# 4. Area mismatch
# ======================================================================================


def test_a_transfer_that_enlarges_the_parcel_fails_s6() -> None:
    report = validate_succession(
        _case(mutations=[_mutation(parcel=_parcel(area=_ha("6.2")))])
    )

    assert _status(report, "AREA_CONSISTENCY") is CheckStatus.FAIL
    assert RuleCode.SUCCESSION_AREA_MISMATCH in _codes(report)


def test_a_smaller_area_is_a_warning_because_a_partial_transfer_looks_the_same() -> None:
    report = validate_succession(_case(mutations=[_mutation(parcel=_parcel(area=_ha("3.0")))]))
    assert _status(report, "AREA_CONSISTENCY") is CheckStatus.WARNING


def test_rounding_differences_stay_within_tolerance() -> None:
    """5.0 ha vs 50 000.4 sq m is survey rounding, not a discrepancy."""
    tweaked = _parcel(area=AreaMeasurement.from_sq_metre(Decimal("50000.4")))
    report = validate_succession(_case(record_snapshots=[_old_record(), _new_record(parcel=tweaked)]))
    assert _status(report, "AREA_CONSISTENCY") is CheckStatus.PASS


def test_area_evidence_cites_both_documents() -> None:
    """Requirement 10: a finding has to be traceable to the fields that caused it."""
    report = validate_succession(_case(mutations=[_mutation(parcel=_parcel(area=_ha("6.2")))]))
    check = next(c for c in report.checks if c.rule == "AREA_CONSISTENCY" and c.status is CheckStatus.FAIL)
    described = [e.describe() for e in check.evidence]
    assert len(described) == 2
    assert any("Old Jamabandi" in d for d in described)
    assert any("Mutation" in d for d in described)


# ======================================================================================
# 5. Multiple potential heirs + exclusive mutation  (the headline case)
# ======================================================================================


def test_exclusive_transfer_to_one_of_three_heirs_requires_review() -> None:
    report = validate_succession(_case())

    assert _status(report, "EXCLUSIVE_TRANSFER_EVIDENCE") is CheckStatus.REVIEW_REQUIRED
    assert report.outcome is SuccessionOutcome.REVIEW_REQUIRED
    assert report.risk_level is RiskLevel.HIGH
    assert report.recommended_action is SuccessionAction.HUMAN_REVIEW
    assert sorted(report.heir_names) == ["Amit Sharma", "Priya Sharma", "Sita Sharma"]


def test_exclusive_transfer_finding_states_evidence_not_wrongdoing() -> None:
    """The legal-design commitment, asserted rather than trusted to review."""
    report = validate_succession(_case())
    check = next(c for c in report.checks if c.rule == "EXCLUSIVE_TRANSFER_EVIDENCE")

    lowered = check.explanation.lower()
    for forbidden in ("fraud", "fraudulent", "illegal", "unlawful", "entitled", "rightful heir"):
        assert forbidden not in lowered, f"succession finding must not use {forbidden!r}"
    assert "not a finding that the transfer was improper" in lowered


def test_no_outcome_or_action_in_the_vocabulary_can_assert_wrongdoing() -> None:
    values = {o.value for o in SuccessionOutcome} | {a.value for a in SuccessionAction}
    assert not any("fraud" in v or "illegal" in v for v in values)
    assert {o.value for o in SuccessionOutcome} == {
        "validated",
        "incomplete",
        "inconsistent",
        "review_required",
    }


def test_risk_score_is_the_sum_of_its_itemised_contributions() -> None:
    report = validate_succession(_case())
    assert report.risk_contributions
    assert report.risk_score == pytest.approx(
        round(sum(c.points for c in report.risk_contributions), 2)
    )
    for contribution in report.risk_contributions:
        assert contribution.points == pytest.approx(
            round(contribution.base_points * contribution.multiplier, 2)
        )


def test_every_heir_on_the_record_clears_s9() -> None:
    joint = _new_record(
        owners=[
            _owner("Sita Sharma", "1/3"),
            _owner("Amit Sharma", "1/3"),
            _owner("Priya Sharma", "1/3"),
        ]
    )
    report = validate_succession(_case(record_snapshots=[_old_record(), joint]))
    assert _status(report, "EXCLUSIVE_TRANSFER_EVIDENCE") is CheckStatus.PASS


# ======================================================================================
# 6. A supporting document exists
# ======================================================================================


def _relinquishment(*names: str) -> SupportingDocument:
    return SupportingDocument(
        document_type=SuccessionDocumentType.RELINQUISHMENT_DEED,
        label="Relinquishment deed",
        reference="BLG/RD/2025/91",
        issued_on=date(2025, 7, 10),
        executants=[PersonName(raw=name) for name in names],
        beneficiaries=[_owner("Amit Sharma")],
    )


def test_a_relinquishment_covering_every_other_heir_clears_s9() -> None:
    report = validate_succession(
        _case(supporting_documents=[_relinquishment("Sita Sharma", "Priya Sharma")])
    )
    check = next(c for c in report.checks if c.rule == "EXCLUSIVE_TRANSFER_EVIDENCE")

    assert check.status is CheckStatus.PASS
    # Present is not the same as valid, and the finding has to keep saying so.
    assert "not something this check establishes" in check.explanation
    assert check.remediation is not None


def test_a_relinquishment_that_misses_one_heir_is_a_warning_naming_who() -> None:
    report = validate_succession(_case(supporting_documents=[_relinquishment("Sita Sharma")]))
    check = next(c for c in report.checks if c.rule == "EXCLUSIVE_TRANSFER_EVIDENCE")

    assert check.status is CheckStatus.WARNING
    assert "Priya Sharma" in check.explanation


def test_a_deed_naming_nobody_on_the_record_does_not_count_as_corroboration() -> None:
    """Otherwise the check would be satisfiable by attaching unrelated paperwork."""
    unrelated = SupportingDocument(
        document_type=SuccessionDocumentType.WILL,
        label="Will of an unrelated testator",
        executants=[PersonName(raw="Govind Patil")],
        beneficiaries=[_owner("Sunil Patil")],
    )
    report = validate_succession(_case(supporting_documents=[unrelated]))
    assert _status(report, "EXCLUSIVE_TRANSFER_EVIDENCE") is CheckStatus.REVIEW_REQUIRED


# ======================================================================================
# 7. Missing documents
# ======================================================================================


def test_a_transition_with_no_mutation_and_no_deed_requires_review_not_a_failure() -> None:
    """An absent explanation is an evidence gap, not a contradiction between
    documents -- FAIL is reserved for two documents that actively disagree.
    """
    report = validate_succession(_case(mutations=[], supporting_documents=[]))

    assert _status(report, "SUCCESSION_EVIDENCE") is CheckStatus.REVIEW_REQUIRED
    assert _status(report, "MUTATION_RECORD_PRESENT") is CheckStatus.WARNING
    assert RuleCode.SUCCESSION_EVIDENCE_MISSING in _codes(report)
    assert report.outcome is SuccessionOutcome.REVIEW_REQUIRED


def test_an_unsanctioned_mutation_is_a_warning_not_a_pass() -> None:
    report = validate_succession(_case(mutations=[_mutation(status=MutationStatus.PENDING)]))
    assert _status(report, "SUCCESSION_EVIDENCE") is CheckStatus.WARNING


def test_a_missing_death_certificate_on_an_inheritance_mutation_is_reported() -> None:
    report = validate_succession(_case(death_records=[], heirs=[]))

    assert _status(report, "DEATH_RECORD_PRESENT") is CheckStatus.WARNING
    assert RuleCode.SUCCESSION_DEATH_RECORD_MISSING in _codes(report)
    assert report.event_type is SuccessionEventType.OWNERSHIP_TRANSITION


def test_an_empty_case_produces_a_report_rather_than_an_exception() -> None:
    report = validate_succession(SuccessionCase(case_id="empty"))

    assert report.event_type is SuccessionEventType.INSUFFICIENT_DOCUMENTS
    assert report.outcome is SuccessionOutcome.VALIDATED
    assert all(c.status is CheckStatus.NOT_APPLICABLE or c.status.is_clear for c in report.checks)


def test_a_death_certificate_alone_asks_for_the_record_rather_than_failing() -> None:
    report = validate_succession(SuccessionCase(case_id="partial", death_records=[_death()]))
    assert _status(report, "OWNER_IDENTITY_MATCH") is CheckStatus.REVIEW_REQUIRED


def test_a_death_with_no_update_to_the_register_is_reported_as_a_backlog_item() -> None:
    report = validate_succession(
        SuccessionCase(case_id="stale", record_snapshots=[_old_record()], death_records=[_death()])
    )
    codes = _codes(report)
    assert RuleCode.SUCCESSION_RECORD_NOT_UPDATED_AFTER_DEATH in codes
    assert report.outcome is SuccessionOutcome.INCOMPLETE


def test_an_unreadable_document_degrades_the_report_rather_than_stopping_it() -> None:
    report = validate_succession(_case(death_records=[_death().model_copy(update={"is_legible": False})]))

    assert _status(report, "DOCUMENT_LEGIBILITY") is CheckStatus.WARNING
    assert RuleCode.SUCCESSION_DOCUMENT_UNREADABLE in _codes(report)
    # Every other check still ran against what was readable.
    assert _status(report, "PARCEL_MATCH") is CheckStatus.PASS


# ======================================================================================
# 8. Unexplained ownership transition
# ======================================================================================


def test_an_intermediate_holder_nothing_accounts_for_is_flagged() -> None:
    """2010 Ramesh -> 2022 Amit -> 2025 Suresh, with only the first step documented."""
    chain = [
        _old_record(as_of=date(2010, 1, 1), revenue_year="2010-11", owners=[_owner("Ramesh Sharma")]),
        _old_record(
            label="Jamabandi (2022-23)", as_of=date(2022, 1, 1), revenue_year="2022-23",
            owners=[_owner("Amit Sharma")],
        ),
        _new_record(
            label="Jamabandi (2025-26)", as_of=date(2025, 1, 1), revenue_year="2025-26",
            owners=[_owner("Suresh Sharma")],
        ),
    ]
    report = validate_succession(_case(record_snapshots=chain, death_records=[], heirs=[], mutations=[]))

    assert _status(report, "TRANSITION_CHAIN_COMPLETE") is CheckStatus.REVIEW_REQUIRED
    assert RuleCode.SUCCESSION_UNEXPLAINED_TRANSITION in _codes(report)
    check = next(c for c in report.checks if c.rule == "TRANSITION_CHAIN_COMPLETE")
    assert "2010-11" in check.explanation and "2022-23" in check.explanation


def test_a_documented_chain_clears_s10() -> None:
    report = validate_succession(_case())
    assert _status(report, "TRANSITION_CHAIN_COMPLETE") is CheckStatus.PASS


def test_a_mutation_dated_inside_the_later_revenue_year_still_explains_the_step() -> None:
    """A revenue year is a range; an August order belongs to the year it falls in.

    Treating the year's *start* as the record's date would put this mutation after
    the record it produced and report a clean case as an unexplained transition.
    """
    report = validate_succession(_case(mutations=[_mutation(order_date=date(2025, 8, 2))]))
    assert _status(report, "TRANSITION_CHAIN_COMPLETE") is CheckStatus.PASS
    assert _status(report, "TRANSITION_AFTER_DEATH") is CheckStatus.PASS


def test_a_transfer_dated_before_the_death_it_follows_fails_s2() -> None:
    report = validate_succession(
        _case(
            mutations=[_mutation(order_date=date(2025, 1, 9))],
            death_records=[_death(when=date(2025, 5, 12))],
        )
    )
    assert _status(report, "TRANSITION_AFTER_DEATH") is CheckStatus.FAIL
    assert RuleCode.SUCCESSION_EVENT_SEQUENCE_INVALID in _codes(report)


def test_undated_documents_ask_for_review_rather_than_guessing_an_order() -> None:
    report = validate_succession(
        _case(mutations=[_mutation(order_date=None)], death_records=[_death(when=None)])
    )
    assert _status(report, "TRANSITION_AFTER_DEATH") is CheckStatus.REVIEW_REQUIRED


# ======================================================================================
# 9. Shares, co-ownership and contradictions
# ======================================================================================


def test_multiple_owners_before_the_death_only_transition_the_deceased_s_holding() -> None:
    jointly_held = _old_record(
        owners=[_owner("Ramesh Sharma", "1/2"), _owner("Sita Sharma", "1/2")]
    )
    after = _new_record(
        owners=[_owner("Sita Sharma", "1/2"), _owner("Amit Sharma", "1/2")]
    )
    report = validate_succession(_case(record_snapshots=[jointly_held, after]))

    assert _status(report, "OWNER_IDENTITY_MATCH") is CheckStatus.PASS
    assert _status(report, "SHARE_SUM_CONSISTENCY") in {CheckStatus.PASS, CheckStatus.WARNING}
    assert report.event_type is SuccessionEventType.OWNER_DEATH_SUCCESSION


def test_shares_over_unity_fail() -> None:
    report = validate_succession(
        _case(record_snapshots=[_old_record(), _new_record(owners=[_owner("Amit Sharma"), _owner("Sita Sharma")])])
    )
    assert _status(report, "SHARE_SUM_CONSISTENCY") is CheckStatus.FAIL
    assert RuleCode.SUCCESSION_SHARE_SUM_INCONSISTENT in _codes(report)


def test_co_owners_with_no_share_stated_is_a_warning() -> None:
    report = validate_succession(
        _case(
            record_snapshots=[
                _old_record(),
                _new_record(owners=[_owner("Amit Sharma", None), _owner("Sita Sharma", None)]),
            ]
        )
    )
    assert _status(report, "SHARE_SUM_CONSISTENCY") is CheckStatus.WARNING


def test_multiple_successors_on_the_mutation_are_handled() -> None:
    split = _mutation(new_owners=[_owner("Amit Sharma", "1/2"), _owner("Priya Sharma", "1/2")])
    after = _new_record(owners=[_owner("Amit Sharma", "1/2"), _owner("Priya Sharma", "1/2")])
    report = validate_succession(_case(mutations=[split], record_snapshots=[_old_record(), after]))

    assert _status(report, "SHARE_SUM_CONSISTENCY") is CheckStatus.PASS
    assert _status(report, "DOCUMENT_CONSISTENCY") is CheckStatus.PASS
    # Sita is still unaccounted for, so the case is surfaced -- but as evidence, not fault.
    assert _status(report, "EXCLUSIVE_TRANSFER_EVIDENCE") is CheckStatus.REVIEW_REQUIRED


def test_documents_that_contradict_each_other_are_referred_not_resolved() -> None:
    report = validate_succession(
        _case(mutations=[_mutation(new_owners=[_owner("Priya Sharma")])])
    )

    assert _status(report, "DOCUMENT_CONSISTENCY") is CheckStatus.FAIL
    assert report.outcome is SuccessionOutcome.INCONSISTENT
    assert report.recommended_action is SuccessionAction.REFER_TO_REVENUE_AUTHORITY


def test_two_death_certificates_with_different_dates_contradict() -> None:
    report = validate_succession(
        _case(death_records=[_death(when=date(2025, 5, 12)), _death(when=date(2025, 6, 30))])
    )
    assert _status(report, "DOCUMENT_CONSISTENCY") is CheckStatus.FAIL
    assert RuleCode.SUCCESSION_DOCUMENTS_CONTRADICT in _codes(report)


def test_a_mutation_naming_a_transferor_who_never_owned_the_parcel_fails_s4() -> None:
    report = validate_succession(
        _case(mutations=[_mutation(previous_owners=[_owner("Govind Patil", None)])])
    )
    assert _status(report, "MUTATION_PREDECESSOR_MATCH") is CheckStatus.FAIL
    assert RuleCode.SUCCESSION_MUTATION_PREDECESSOR_MISMATCH in _codes(report)


def test_a_mutation_for_a_different_parcel_fails_s5() -> None:
    report = validate_succession(_case(mutations=[_mutation(parcel=_parcel(khasra_number="404/9"))]))
    assert _status(report, "MUTATION_PARCEL_MATCH") is CheckStatus.FAIL


# ======================================================================================
# 10. OCR and name normalisation
# ======================================================================================


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Ramesh Sharma", "Shri Ramesh Sharma"),
        ("Ramesh Sharma", "Late Ramesh Sharma"),
        ("Ramesh Sharma", "Sharma Ramesh"),
        ("Ramesh Sharma", "Ramesh  Sharma "),
        ("Karthikeyan R", "Karthikeyan Ramasamy"),
        ("Ramesh Sharma", "Ramesh Sharrma"),
    ],
)
def test_names_that_should_match_do(left: str, right: str) -> None:
    assert match_names(left, right).matched, f"{left!r} should match {right!r}"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Ramesh Sharma", "Mahesh Kulkarni"),
        ("Amit Sharma", "Sumit Verma"),
        ("Sita Sharma", "Gita Sharma"),
    ],
)
def test_names_that_should_not_match_do_not(left: str, right: str) -> None:
    assert not match_names(left, right).matched, f"{left!r} must not match {right!r}"


def test_the_relation_clause_is_not_folded_into_the_name_comparison() -> None:
    assert normalize_name("Amit Sharma s/o Ramesh Sharma") == "amit sharma"
    assert name_similarity("Amit Sharma s/o Ramesh Sharma", "Amit Sharma") == 1.0


def test_an_ocr_variant_still_links_the_chain_but_is_reported_as_approximate() -> None:
    report = validate_succession(_case(death_records=[_death("Ramesh Sharrna")]))

    assert _status(report, "OWNER_IDENTITY_MATCH") is CheckStatus.PASS
    assert _status(report, "NAME_MATCH_QUALITY") is CheckStatus.WARNING
    assert RuleCode.SUCCESSION_NAME_MATCH_APPROXIMATE in _codes(report)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("125/2", "125/2"), (" 125 / 2 ", "125/2"), ("125-2", "125/2"), ("0125/2", "125/2"), ("१२५/२", "125/2")],
)
def test_parcel_identifiers_normalise_to_one_form(raw: str, expected: str) -> None:
    assert normalize_identifier(raw) == expected


def test_a_hissa_is_related_to_its_parent_but_not_equal_to_it() -> None:
    comparison = compare_identifier("khasra_number", "125", "125/2")
    assert comparison is not None
    assert comparison.equal is False
    assert comparison.related is True


def test_an_absent_identifier_is_not_treated_as_agreement() -> None:
    assert compare_identifier("khata_number", None, "123") is None
    assert compare_identifier("khata_number", "", "") is None


# ======================================================================================
# Timeline, evidence and the report surface
# ======================================================================================


def test_the_timeline_orders_the_events_a_reviewer_reads() -> None:
    report = validate_succession(_case())
    kinds = [e.event_type for e in report.timeline]

    assert kinds[0] is OwnershipEventType.RECORD_SNAPSHOT
    assert kinds[-1] is OwnershipEventType.RECORD_SNAPSHOT
    assert OwnershipEventType.DEATH in kinds
    assert OwnershipEventType.MUTATION in kinds
    assert OwnershipEventType.SUCCESSION_CLAIM in kinds
    assert [e.sequence for e in report.timeline] == list(range(len(report.timeline)))


def test_an_undated_previous_record_still_opens_the_timeline() -> None:
    """A register-sourced 'previous Record of Rights' commonly carries no date at
    all (no revenue year, no as_of). It must still draw first, as the baseline —
    not last, as if it were the most recent thing on the parcel.
    """
    undated_previous = RecordSnapshot(
        label="Record of Rights (on file)",
        document_type=SuccessionDocumentType.JAMABANDI,
        parcel=_parcel(),
        owners=[_owner("Ramesh Sharma")],
    )
    report = validate_succession(_case(record_snapshots=[undated_previous, _new_record()]))

    assert report.timeline[0].event_type is OwnershipEventType.RECORD_SNAPSHOT
    assert report.timeline[0].to_owners[0].name == "Ramesh Sharma"
    assert report.timeline[0].date_stated is False


def test_an_inferred_revenue_year_position_is_marked_as_inferred() -> None:
    report = validate_succession(_case())
    snapshots = [e for e in report.timeline if e.event_type is OwnershipEventType.RECORD_SNAPSHOT]
    assert all(e.date_stated is False for e in snapshots)
    death = next(e for e in report.timeline if e.event_type is OwnershipEventType.DEATH)
    assert death.date_stated is True


def test_the_succession_event_carries_the_parties_the_graph_draws() -> None:
    report = validate_succession(_case())
    mutation = next(e for e in report.timeline if e.event_type is OwnershipEventType.MUTATION)

    assert [p.name for p in mutation.from_owners] == ["Ramesh Sharma"]
    assert [p.name for p in mutation.to_owners] == ["Amit Sharma"]
    assert mutation.to_owners[0].share == "1/1"


def test_every_check_is_recorded_including_the_ones_that_could_not_run() -> None:
    report = validate_succession(SuccessionCase(case_id="empty"))
    assert report.counts_by_status["not_applicable"] > 0
    assert len(report.checks) >= 10


def test_findings_project_onto_the_engine_s_ordinary_issue_shape() -> None:
    """What lets the existing console, triage and exports consume these unchanged."""
    report = validate_succession(_case())
    assert report.findings
    issue = report.findings[0]
    assert issue.rule_code in RuleCode
    assert issue.severity.value in {"info", "warning", "error", "critical"}
    assert issue.json_path.startswith("$.succession.checks[")
    assert issue.evidence["sources"]


def test_the_disclaimer_travels_with_the_report() -> None:
    report = validate_succession(_case())
    assert "not a determination of legal entitlement" in report.disclaimer
    assert "does not decide who inherits" in report.disclaimer


def test_disabling_a_rule_in_policy_removes_its_check_entirely() -> None:
    policy = DEFAULT_POLICY.model_copy(deep=True)
    policy.rules[RuleCode.SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED] = (
        policy.tolerance_for(RuleCode.SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED).model_copy(
            update={"enabled": False}
        )
    )
    report = validate_succession(_case(), policy)

    assert not any(c.rule == "EXCLUSIVE_TRANSFER_EVIDENCE" for c in report.checks)
    assert report.outcome is SuccessionOutcome.VALIDATED


def test_policy_risk_weights_change_the_score_not_the_verdict() -> None:
    policy = DEFAULT_POLICY.model_copy(deep=True)
    policy.rules[RuleCode.SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED] = (
        policy.tolerance_for(RuleCode.SUCCESSION_EXCLUSIVE_TRANSFER_UNSUPPORTED).model_copy(
            update={"risk_points": 10.0}
        )
    )
    report = validate_succession(_case(), policy)

    assert report.risk_level is RiskLevel.LOW
    assert report.outcome is SuccessionOutcome.REVIEW_REQUIRED  # the finding still stands


# ======================================================================================
# The document-shaped entry point and the extraction layer
# ======================================================================================


def test_validate_documents_accepts_the_six_things_a_clerk_actually_has() -> None:
    report = validate_documents(
        previous_land_record=_old_record(),
        death_certificate=_death(),
        heir_information=_heirs(),
        mutation_record=_mutation(),
        current_land_record=_new_record(),
        case_id="clerk-view",
    )
    assert report.case_id == "clerk-view"
    assert report.outcome is SuccessionOutcome.REVIEW_REQUIRED


def test_a_pipeline_extracted_record_becomes_a_snapshot_without_a_second_pass() -> None:
    record = LandParcelRecord(
        khata_number="123",
        khasra_numbers=["125/2"],
        total_area=_ha("5.0"),
        jurisdiction=Jurisdiction(
            state="Karnataka", district="Belagavi", tehsil="Belagavi",
            village="Angol", revenue_year="2019-20",
        ),
        owners=[OwnerRecord(name=PersonName(raw="Ramesh Sharma"), share=OwnershipShare.whole())],
    )
    snapshot = snapshot_from_record(record)

    assert snapshot.parcel.khasra_number == "125/2"
    assert snapshot.owner_names == ["Ramesh Sharma"]
    assert snapshot.as_of == date(2019, 1, 1)
    assert snapshot.as_of_inferred is True
    assert snapshot.owners[0].source is not None  # provenance for the console


def test_normalize_case_interprets_raw_strings_deterministically() -> None:
    case, warnings = normalize_case(
        {
            "case_id": "raw",
            "documents": [
                {
                    "document_type": "jamabandi",
                    "land": {"khasra": "125/2", "area": 5.0, "area_unit": "hectare"},
                    "owners": [{"name": "Ramesh Sharma", "share": "1/1"}],
                },
                {"document_type": "death_certificate", "person": {"name": "Ramesh Sharma"},
                 "date_of_death": "12/05/2025"},
            ],
        }
    )

    assert warnings == []
    # Day-first, as Indian revenue records are: 12 May, never 5 December.
    assert case.death_records[0].date_of_death == date(2025, 5, 12)
    assert case.record_snapshots[0].parcel.area is not None
    assert case.record_snapshots[0].parcel.area.sq_metre == Decimal("50000.0000")


def test_normalize_case_recovers_a_third_from_a_rounded_decimal_share() -> None:
    case, _ = normalize_case(
        {
            "documents": [
                {
                    "document_type": "updated_jamabandi",
                    "owners": [
                        {"name": "A", "share": "0.3333"},
                        {"name": "B", "share": "0.3333"},
                        {"name": "C", "share": "0.3333"},
                    ],
                }
            ]
        }
    )
    shares = [str(o.share) for o in case.record_snapshots[0].owners]
    assert shares == ["1/3", "1/3", "1/3"]


def test_an_unreadable_value_becomes_a_warning_rather_than_a_guess() -> None:
    case, warnings = normalize_case(
        {
            "documents": [
                {"document_type": "death_certificate", "person": {"name": "X"},
                 "date_of_death": "not a date"},
                {"document_type": "jamabandi", "land": {"khasra": "1", "area": 5, "area_unit": "bigha"}},
            ]
        }
    )
    assert case.death_records[0].date_of_death is None
    assert case.record_snapshots[0].parcel.area is None
    assert len(warnings) == 2
    assert any("region_key" in w for w in warnings)  # bigha is refused, never guessed


def test_the_case_round_trips_through_json() -> None:
    """The backend stores the case and re-validates from it, so this has to hold."""
    case = _case()
    restored = SuccessionCase.model_validate(_strip_computed(case.model_dump(mode="json")))
    assert restored.previous_record is not None
    assert restored.previous_record.owner_names == ["Ramesh Sharma"]
    assert validate_succession(restored).outcome is SuccessionOutcome.REVIEW_REQUIRED


def _strip_computed(data):  # noqa: ANN001, ANN202
    """Drop the computed fields a dump adds, which ``extra="forbid"`` would reject."""
    computed = {"display_key", "decimal_value", "parcel_key", "cultivable_area_sq_metre",
                "non_cultivable_area_sq_metre", "cultivability"}
    if isinstance(data, dict):
        return {k: _strip_computed(v) for k, v in data.items() if k not in computed}
    if isinstance(data, list):
        return [_strip_computed(item) for item in data]
    return data


def test_a_death_certificate_text_layer_yields_the_labelled_fields() -> None:
    extraction = parse_document_text(
        "OFFICE OF THE REGISTRAR OF BIRTHS AND DEATHS\n"
        "Name of the deceased : Ramesh Sharma\n"
        "Date of Death : 12/05/2025\n"
        "Place of death : Angol, Belagavi\n"
        "Registration No : BLG/2025/4471\n",
        SuccessionDocumentType.DEATH_CERTIFICATE,
    )

    assert extraction.fields["name"] == "Ramesh Sharma"
    assert extraction.fields["date_of_death"] == "12/05/2025"
    assert extraction.confidence == 1.0

    case, warnings = normalize_case({"documents": [extraction.as_payload()]})
    assert warnings == []
    assert case.death_records[0].date_of_death == date(2025, 5, 12)


def test_a_text_layer_missing_a_field_reports_lower_confidence_rather_than_guessing() -> None:
    extraction = parse_document_text(
        "Name of the deceased : Ramesh Sharma\nIssued by : Registrar\n",
        SuccessionDocumentType.DEATH_CERTIFICATE,
    )
    assert "date_of_death" not in extraction.fields
    assert extraction.confidence == 0.5
    assert extraction.unmatched_labels == ["date_of_death"]


def test_a_record_of_rights_is_refused_by_the_text_parser() -> None:
    """It has a table, which the OCR + layout + Vision-LLM pipeline already reads."""
    with pytest.raises(ValueError, match="process_document"):
        parse_document_text("anything", SuccessionDocumentType.JAMABANDI)
