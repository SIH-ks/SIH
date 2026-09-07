"""Concrete validation rules.

Importing this module is what populates the registry (every function below is
decorated with :func:`~adhikar.validation.registry.rule`) -- callers should
``import adhikar.validation.rules`` (even if only for its side effect) before calling
:func:`~adhikar.validation.registry.run_all`. :mod:`adhikar.validation` does this on
package import, so in practice callers rarely need to think about it.

Each rule is intentionally narrow. That is what keeps the engine data-driven: a new
consistency check is a new function here, not a change to a monolithic validator.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, pstdev

from ..schemas.enums import EncumbranceStatus, MutationStatus, MutationType
from ..schemas.land_record import LandParcelRecord
from ..schemas.units import AreaMeasurement
from ..schemas.validation import RuleCode, Severity, ValidationIssue, ValidationPolicy
from .registry import rule

__all__: list[str] = []  # this module's public surface is its side effect: registration


# ==========================================================================================
# Arithmetic consistency
# ==========================================================================================


@rule(
    RuleCode.TOTAL_AREA_MISSING,
    description="The parcel's total area was not extracted at all.",
)
def _total_area_missing(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    if parcel.total_area is None:
        yield ValidationIssue(
            rule_code=RuleCode.TOTAL_AREA_MISSING,
            severity=Severity.CRITICAL,
            message="No total area could be read for this parcel; every area-based check below is skipped.",
            json_path="$.total_area",
            remediation="Re-examine the area column on the source scan; it may be faint, torn, or unconventionally formatted.",
        )


@rule(
    RuleCode.TOTAL_AREA_NON_POSITIVE,
    description="The parcel's total area is zero or negative.",
)
def _total_area_non_positive(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    if parcel.total_area is not None and parcel.total_area.sq_metre <= 0:
        yield ValidationIssue(
            rule_code=RuleCode.TOTAL_AREA_NON_POSITIVE,
            severity=Severity.CRITICAL,
            message=f"Total area is {parcel.total_area.format_native()}, which is not a usable parcel size.",
            json_path="$.total_area",
            observed=str(parcel.total_area.sq_metre),
            remediation="Confirm the area cell was read correctly; a zero area usually indicates a misread or an empty cell mistaken for '0'.",
        )


@rule(
    RuleCode.AREA_SUM_MISMATCH,
    description="Sum of sub-division areas does not equal the printed total area.",
)
def _area_sum_mismatch(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    if parcel.total_area is None or not parcel.sub_divisions:
        return
    tol = policy.tolerance_for(RuleCode.AREA_SUM_MISMATCH)
    total_sub = parcel.sub_division_area_total

    if total_sub.sq_metre > parcel.total_area.sq_metre:
        yield ValidationIssue(
            rule_code=RuleCode.AREA_SUM_EXCEEDS_TOTAL,
            severity=Severity.ERROR,
            message=(
                f"Sub-divisions total {total_sub.format_native()}, which exceeds the printed "
                f"parcel total of {parcel.total_area.format_native()}. Sub-divisions cannot "
                f"exceed their parent."
            ),
            json_path="$.sub_divisions",
            observed=str(total_sub.sq_metre),
            expected=str(parcel.total_area.sq_metre),
            delta=total_sub.sq_metre - parcel.total_area.sq_metre,
            remediation="Re-check each sub-division's area cell; one is likely misread, or the printed total itself is wrong.",
        )
        return

    if not total_sub.approx_equals(
        parcel.total_area,
        abs_tol_sq_metre=tol.absolute_sq_metre or Decimal("1.0"),
        rel_tol=tol.relative or Decimal("0.005"),
    ):
        delta = total_sub.sq_metre - parcel.total_area.sq_metre
        yield ValidationIssue(
            rule_code=RuleCode.AREA_SUM_MISMATCH,
            severity=tol.severity or Severity.ERROR,
            message=(
                f"Sub-divisions total {total_sub.format_native()} but the parcel's printed "
                f"total area is {parcel.total_area.format_native()} -- a difference of "
                f"{abs(delta):.2f} sq m."
            ),
            json_path="$.sub_divisions",
            observed=str(total_sub.sq_metre),
            expected=str(parcel.total_area.sq_metre),
            delta=delta,
            evidence={"n_sub_divisions": len(parcel.sub_divisions)},
            remediation="Verify each sub-division area against the scan; a single-digit transcription error in one row is the most common cause.",
        )


@rule(
    RuleCode.CLASSIFICATION_SPLIT_MISMATCH,
    description="Sum of classified areas does not equal the printed total area.",
)
def _classification_split_mismatch(
    parcel: LandParcelRecord, policy: ValidationPolicy
) -> Iterable[ValidationIssue]:
    if parcel.total_area is None or not parcel.classified_areas:
        return
    tol = policy.tolerance_for(RuleCode.CLASSIFICATION_SPLIT_MISMATCH)
    total_classified = parcel.classified_area_total

    if not total_classified.approx_equals(
        parcel.total_area,
        abs_tol_sq_metre=tol.absolute_sq_metre or Decimal("1.0"),
        rel_tol=tol.relative or Decimal("0.005"),
    ):
        delta = total_classified.sq_metre - parcel.total_area.sq_metre
        cultivable = parcel.cultivable_area_sq_metre
        non_cultivable = parcel.non_cultivable_area_sq_metre
        yield ValidationIssue(
            rule_code=RuleCode.CLASSIFICATION_SPLIT_MISMATCH,
            severity=tol.severity or Severity.ERROR,
            message=(
                f"Classified areas (cultivable {cultivable:.2f} + non-cultivable "
                f"{non_cultivable:.2f} = {total_classified.sq_metre:.2f} sq m) do not match "
                f"the printed total of {parcel.total_area.sq_metre:.2f} sq m."
            ),
            json_path="$.classified_areas",
            observed=str(total_classified.sq_metre),
            expected=str(parcel.total_area.sq_metre),
            delta=delta,
            evidence={"cultivable_sq_metre": str(cultivable), "non_cultivable_sq_metre": str(non_cultivable)},
            remediation="Check whether a classification row was missed (e.g. an unlabelled Pot-Kharaba strip) or double-counted.",
        )


@rule(
    RuleCode.AREA_COMPONENT_OUT_OF_RANGE,
    description="A printed H-R-Sq.M component exceeds its natural range.",
)
def _area_component_out_of_range(
    parcel: LandParcelRecord, policy: ValidationPolicy
) -> Iterable[ValidationIssue]:
    from ..schemas.units import AreaUnit, AreaUnitSystem

    candidates: list[tuple[str, AreaMeasurement]] = []
    if parcel.total_area is not None:
        candidates.append(("$.total_area", parcel.total_area))
    for i, sd in enumerate(parcel.sub_divisions):
        candidates.append((f"$.sub_divisions[{i}].area", sd.area))

    for path, area in candidates:
        if area.unit_system is not AreaUnitSystem.METRIC_HA_ARE_SQM:
            continue
        are = area.components.get(AreaUnit.ARE)
        sqm = area.components.get(AreaUnit.SQ_METRE)
        if are is not None and are >= 100:
            yield ValidationIssue(
                rule_code=RuleCode.AREA_COMPONENT_OUT_OF_RANGE,
                severity=Severity.WARNING,
                message=f"The 'are' component is {are}, but are must be under 100 (100 are = 1 hectare).",
                json_path=f"{path}.components.are",
                observed=str(are),
                remediation="The hectare and are digits may have been transposed or merged during transcription.",
            )
        if sqm is not None and sqm >= 100:
            yield ValidationIssue(
                rule_code=RuleCode.AREA_COMPONENT_OUT_OF_RANGE,
                severity=Severity.WARNING,
                message=f"The 'sq.m' component is {sqm}, but sq.m must be under 100 (100 sq m = 1 are).",
                json_path=f"{path}.components.sq_metre",
                observed=str(sqm),
                remediation="The are and sq.m digits may have been transposed or merged during transcription.",
            )


@rule(
    RuleCode.ASSESSMENT_DISPROPORTIONATE,
    description="A sub-division's revenue-per-area is a statistical outlier among its siblings.",
)
def _assessment_disproportionate(
    parcel: LandParcelRecord, policy: ValidationPolicy
) -> Iterable[ValidationIssue]:
    tol = policy.tolerance_for(RuleCode.ASSESSMENT_DISPROPORTIONATE)
    threshold = tol.z_score_threshold or 2.5

    rated = [
        (i, sd, float(sd.assessment_amount) / float(sd.area.sq_metre))
        for i, sd in enumerate(parcel.sub_divisions)
        if sd.assessment_amount is not None and sd.area.sq_metre > 0
    ]
    if len(rated) < 3:
        return  # a z-score is not meaningful with fewer than three data points

    rates = [r for _, _, r in rated]
    mu, sigma = mean(rates), pstdev(rates)
    if sigma == 0:
        return

    for i, sd, rate in rated:
        z = (rate - mu) / sigma
        if abs(z) >= threshold:
            yield ValidationIssue(
                rule_code=RuleCode.ASSESSMENT_DISPROPORTIONATE,
                severity=Severity.WARNING,
                message=(
                    f"Sub-division {sd.sub_division_number} is assessed at "
                    f"Rs.{rate:.2f} per sq m, versus a sibling average of Rs.{mu:.2f} "
                    f"(z-score {z:+.2f}). This may indicate a misread area or assessment figure."
                ),
                json_path=f"$.sub_divisions[{i}].assessment_amount",
                observed=f"{rate:.4f}",
                expected=f"{mu:.4f}",
                confidence=0.7,  # a statistical flag, not a certain arithmetic contradiction
                evidence={"z_score": round(z, 3), "sibling_count": len(rated)},
                remediation="Compare against the scan; legitimate rate differences exist (irrigated vs. waste land) so confirm before treating this as an error.",
            )


# ==========================================================================================
# Ownership
# ==========================================================================================


@rule(RuleCode.NO_OWNERS_RECORDED, description="No owners were extracted for the parcel.")
def _no_owners_recorded(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    if not parcel.owners:
        yield ValidationIssue(
            rule_code=RuleCode.NO_OWNERS_RECORDED,
            severity=Severity.WARNING,
            message="No owner or occupant rows were extracted for this parcel.",
            json_path="$.owners",
            remediation="Confirm the ownership table was present and legible; a blank result here often means the column was outside the scanned crop area.",
        )


@rule(
    RuleCode.SHARE_SUM_NOT_UNITY,
    description="Recorded ownership shares do not sum to the whole parcel.",
)
def _share_sum_not_unity(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    shared_owners = [o for o in parcel.owners if o.share is not None]
    if len(shared_owners) < len(parcel.owners) or not shared_owners:
        return  # SHARE_MISSING covers the partially-recorded case; nothing to sum otherwise

    total = parcel.total_ownership_share
    if total > 1:
        yield ValidationIssue(
            rule_code=RuleCode.SHARE_SUM_EXCEEDS_UNITY,
            severity=Severity.ERROR,
            message=f"Recorded ownership shares sum to {total} ({float(total):.4f}), which exceeds the whole parcel.",
            json_path="$.owners",
            observed=str(total),
            expected="1",
            remediation="At least one share was likely misread; check numerators and denominators against the scan.",
        )
    elif total < 1:
        yield ValidationIssue(
            rule_code=RuleCode.SHARE_SUM_NOT_UNITY,
            severity=Severity.WARNING,
            message=f"Recorded ownership shares sum to {total} ({float(total):.4f}), short of the whole parcel.",
            json_path="$.owners",
            observed=str(total),
            expected="1",
            remediation="An owner row may be missing, or one recorded share is understated.",
        )


@rule(
    RuleCode.SHARE_MISSING,
    description="Multiple owners are recorded with no shares stated for any of them.",
)
def _share_missing(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    if len(parcel.owners) > 1 and all(o.share is None for o in parcel.owners):
        yield ValidationIssue(
            rule_code=RuleCode.SHARE_MISSING,
            severity=Severity.WARNING,
            message=f"{len(parcel.owners)} owners are recorded but none carries a share; apportionment among them is undefined.",
            json_path="$.owners",
            remediation="Check the share/hissa column for this khata; it may use an 'equal share' marker that needs the owner count to resolve.",
        )


@rule(RuleCode.DUPLICATE_OWNER_SERIAL, description="Two owner rows share the same serial number.")
def _duplicate_owner_serial(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    seen: dict[str, int] = {}
    for i, owner in enumerate(parcel.owners):
        if owner.serial_number is None:
            continue
        if owner.serial_number in seen:
            yield ValidationIssue(
                rule_code=RuleCode.DUPLICATE_OWNER_SERIAL,
                severity=Severity.ERROR,
                message=f"Owner serial number {owner.serial_number!r} appears on more than one row.",
                json_path=f"$.owners[{i}].serial_number",
                observed=owner.serial_number,
                remediation="Sub-division owner references keyed to this serial number are now ambiguous; resolve the duplicate first.",
            )
        else:
            seen[owner.serial_number] = i


@rule(
    RuleCode.ORPHAN_OWNER_REFERENCE,
    description="A sub-division references an owner serial number no owner row carries.",
)
def _orphan_owner_reference(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    known_serials = {o.serial_number for o in parcel.owners if o.serial_number is not None}
    for i, sd in enumerate(parcel.sub_divisions):
        for serial in sd.owner_serial_numbers:
            if serial not in known_serials:
                yield ValidationIssue(
                    rule_code=RuleCode.ORPHAN_OWNER_REFERENCE,
                    severity=Severity.ERROR,
                    message=f"Sub-division {sd.sub_division_number} references owner serial {serial!r}, which no owner row carries.",
                    json_path=f"$.sub_divisions[{i}].owner_serial_numbers",
                    observed=serial,
                    remediation="Check whether the owner row for this serial number was dropped or misread.",
                )


# ==========================================================================================
# Mutation chain
# ==========================================================================================


@rule(RuleCode.MUTATION_OUT_OF_SEQUENCE, description="Mutation entry dates are not in ascending order.")
def _mutation_out_of_sequence(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    dated = [(i, m) for i, m in enumerate(parcel.mutations) if m.entry_date is not None]
    for (i_prev, prev), (i_next, nxt) in zip(dated, dated[1:], strict=False):
        if nxt.entry_date < prev.entry_date:  # type: ignore[operator]
            yield ValidationIssue(
                rule_code=RuleCode.MUTATION_OUT_OF_SEQUENCE,
                severity=Severity.WARNING,
                message=(
                    f"Mutation {nxt.mutation_number or i_next} is dated {nxt.entry_date}, "
                    f"before mutation {prev.mutation_number or i_prev} dated {prev.entry_date}, "
                    f"though it appears later in the register."
                ),
                json_path=f"$.mutations[{i_next}].entry_date",
                observed=str(nxt.entry_date),
                expected=f">= {prev.entry_date}",
                remediation="Confirm both dates against the scan; one may have a transposed day/month.",
            )


@rule(RuleCode.MUTATION_DATE_IN_FUTURE, description="A mutation is dated after today.")
def _mutation_date_in_future(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    today = date.today()
    for i, m in enumerate(parcel.mutations):
        for label, d in (("entry_date", m.entry_date), ("order_date", m.order_date)):
            if d is not None and d > today:
                yield ValidationIssue(
                    rule_code=RuleCode.MUTATION_DATE_IN_FUTURE,
                    severity=Severity.ERROR,
                    message=f"Mutation {m.mutation_number or i} has {label} {d}, which is in the future.",
                    json_path=f"$.mutations[{i}].{label}",
                    observed=str(d),
                    remediation="Likely a misread year (e.g. an OCR digit substitution); verify against the scan.",
                )


@rule(
    RuleCode.MUTATION_PENDING_UNRESOLVED,
    description="A pending mutation is older than the policy's staleness horizon.",
)
def _mutation_pending_unresolved(
    parcel: LandParcelRecord, policy: ValidationPolicy
) -> Iterable[ValidationIssue]:
    tol = policy.tolerance_for(RuleCode.MUTATION_PENDING_UNRESOLVED)
    max_age = tol.max_age_days or 180
    today = date.today()
    for i, m in enumerate(parcel.mutations):
        if m.status is MutationStatus.PENDING and m.entry_date is not None:
            age = (today - m.entry_date).days
            if age > max_age:
                yield ValidationIssue(
                    rule_code=RuleCode.MUTATION_PENDING_UNRESOLVED,
                    severity=Severity.WARNING,
                    message=f"Mutation {m.mutation_number or i} has been pending for {age} days (entered {m.entry_date}).",
                    json_path=f"$.mutations[{i}].status",
                    observed=str(age),
                    expected=f"<= {max_age} days",
                    remediation="Escalate to the Revenue Officer's pending-mutation queue for this village.",
                )


@rule(
    RuleCode.MUTATION_AREA_EXCEEDS_PARCEL,
    description="A mutation's transacted area exceeds the parcel's total area.",
)
def _mutation_area_exceeds_parcel(
    parcel: LandParcelRecord, policy: ValidationPolicy
) -> Iterable[ValidationIssue]:
    if parcel.total_area is None:
        return
    for i, m in enumerate(parcel.mutations):
        if m.area_transacted is not None and m.area_transacted.sq_metre > parcel.total_area.sq_metre:
            yield ValidationIssue(
                rule_code=RuleCode.MUTATION_AREA_EXCEEDS_PARCEL,
                severity=Severity.ERROR,
                message=(
                    f"Mutation {m.mutation_number or i} transacts "
                    f"{m.area_transacted.format_native()}, exceeding the parcel's total area "
                    f"of {parcel.total_area.format_native()}."
                ),
                json_path=f"$.mutations[{i}].area_transacted",
                observed=str(m.area_transacted.sq_metre),
                expected=f"<= {parcel.total_area.sq_metre}",
                remediation="Check whether the mutation area or the parcel total area was misread.",
            )


@rule(
    RuleCode.CORRECTION_CHANGED_AREA,
    description="A mutation typed as a clerical correction nonetheless moves area.",
)
def _correction_changed_area(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    for i, m in enumerate(parcel.mutations):
        if m.mutation_type is MutationType.CORRECTION and m.area_transacted is not None and not m.area_transacted.is_zero:
            yield ValidationIssue(
                rule_code=RuleCode.CORRECTION_CHANGED_AREA,
                severity=Severity.WARNING,
                message=(
                    f"Mutation {m.mutation_number or i} is recorded as a clerical correction but "
                    f"transacts {m.area_transacted.format_native()}; a correction should not move area."
                ),
                json_path=f"$.mutations[{i}].mutation_type",
                observed=str(m.area_transacted.sq_metre),
                remediation="Confirm the mutation type; this may actually be a partition or sale.",
            )


@rule(
    RuleCode.OWNER_WITHOUT_MUTATION_TRAIL,
    description="A current owner appears in no sanctioned mutation's transferee list.",
)
def _owner_without_mutation_trail(
    parcel: LandParcelRecord, policy: ValidationPolicy
) -> Iterable[ValidationIssue]:
    if not parcel.mutations:
        return  # no mutation history was extracted at all; distinct from a genuine gap

    sanctioned_transferees = {
        p.raw.strip().casefold()
        for m in parcel.mutations
        if m.status is MutationStatus.SANCTIONED
        for p in m.to_parties
    }
    if not sanctioned_transferees:
        return

    for i, owner in enumerate(parcel.owners):
        if owner.name.raw.strip().casefold() not in sanctioned_transferees:
            yield ValidationIssue(
                rule_code=RuleCode.OWNER_WITHOUT_MUTATION_TRAIL,
                severity=Severity.INFO,
                message=(
                    f"{owner.display_name} is a current owner but does not appear as a "
                    f"transferee in any sanctioned mutation on this record."
                ),
                json_path=f"$.owners[{i}]",
                confidence=0.6,  # name matching across scripts/spelling is approximate
                remediation="This can be legitimate (original allottee, pre-digitisation history) -- confirm against the mutation register before treating it as a gap.",
            )


# ==========================================================================================
# Encumbrance
# ==========================================================================================


@rule(RuleCode.ENCUMBRANCE_ACTIVE, description="A live charge or restriction exists on the parcel.")
def _encumbrance_active(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    for i, enc in enumerate(parcel.encumbrances):
        if enc.is_live and enc.status is not EncumbranceStatus.UNKNOWN:
            yield ValidationIssue(
                rule_code=RuleCode.ENCUMBRANCE_ACTIVE,
                severity=Severity.INFO,
                message=f"Active {enc.encumbrance_type.value.replace('_', ' ')} recorded"
                + (f" in favour of {enc.holder_name}." if enc.holder_name else "."),
                json_path=f"$.encumbrances[{i}]",
                remediation="Material to any transaction on this parcel; surface prominently to a prospective buyer or lender.",
            )


@rule(
    RuleCode.ENCUMBRANCE_STATUS_UNKNOWN,
    description="An encumbrance's status could not be determined from the record.",
)
def _encumbrance_status_unknown(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    for i, enc in enumerate(parcel.encumbrances):
        if enc.status is EncumbranceStatus.UNKNOWN:
            yield ValidationIssue(
                rule_code=RuleCode.ENCUMBRANCE_STATUS_UNKNOWN,
                severity=Severity.WARNING,
                message="An encumbrance entry exists but its active/discharged status could not be read.",
                json_path=f"$.encumbrances[{i}].status",
                remediation="Treated as active by default for safety; confirm against the scan before relying on this.",
            )


# ==========================================================================================
# Identifiers and jurisdiction
# ==========================================================================================


@rule(RuleCode.IDENTIFIER_MISSING, description="Neither survey number nor khata number was extracted.")
def _identifier_missing(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    if not parcel.survey_number and not parcel.khata_number and not parcel.khasra_numbers:
        yield ValidationIssue(
            rule_code=RuleCode.IDENTIFIER_MISSING,
            severity=Severity.CRITICAL,
            message="No survey number, khata number, or khasra number was extracted; this parcel cannot be identified.",
            json_path="$",
            remediation="Re-examine the header row of the source table; the identifier column may have been cropped out of the scan.",
        )


@rule(RuleCode.DUPLICATE_KHASRA_NUMBER, description="A khasra number appears more than once on the parcel.")
def _duplicate_khasra_number(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    seen: set[str] = set()
    for khasra in parcel.khasra_numbers:
        if khasra in seen:
            yield ValidationIssue(
                rule_code=RuleCode.DUPLICATE_KHASRA_NUMBER,
                severity=Severity.WARNING,
                message=f"Khasra number {khasra!r} appears more than once under this khata.",
                json_path="$.khasra_numbers",
                observed=khasra,
                remediation="Confirm this is not a transcription duplicate of an adjoining row.",
            )
        seen.add(khasra)


@rule(RuleCode.JURISDICTION_INCOMPLETE, description="The record's jurisdiction cannot be resolved to a village.")
def _jurisdiction_incomplete(parcel: LandParcelRecord, policy: ValidationPolicy) -> Iterable[ValidationIssue]:
    if not parcel.jurisdiction.is_resolvable:
        yield ValidationIssue(
            rule_code=RuleCode.JURISDICTION_INCOMPLETE,
            severity=Severity.WARNING,
            message="State/district/tehsil/village could not all be determined; this record cannot be geolocated to a village.",
            json_path="$.jurisdiction",
            remediation="Fill in the missing jurisdiction fields from the document header or from the upload metadata.",
        )
