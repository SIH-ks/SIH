"""The rule registry: what makes the engine data-driven.

Adding a check is writing one function and decorating it with :func:`rule` -- there is
no central if-ladder to edit, no dispatch table to update by hand, and no way for a
registered rule to be silently skipped by a missed wire-up. :func:`run_all` discovers
every registered rule, evaluates it against the policy, and collects the findings.

Each rule function has the signature ``(parcel, policy) -> Iterable[ValidationIssue]``
and is free to return zero, one, or many issues. A rule that raises is caught by
:func:`run_all` and converted into a single ``CRITICAL``-severity issue naming the
rule that broke -- a bug in one check must never silently cancel every other check on
the same record.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..schemas.land_record import LandParcelRecord
from ..schemas.validation import RuleCode, Severity, ValidationIssue, ValidationPolicy, ValidationReport

__all__ = ["RuleFunction", "registered_rules", "rule", "run_all"]

RuleFunction = Callable[[LandParcelRecord, ValidationPolicy], Iterable[ValidationIssue]]


@dataclass(slots=True, frozen=True)
class _RegisteredRule:
    code: RuleCode
    func: RuleFunction
    description: str


_REGISTRY: dict[RuleCode, _RegisteredRule] = {}


def rule(code: RuleCode, *, description: str = "") -> Callable[[RuleFunction], RuleFunction]:
    """Register a validation rule under a stable :class:`RuleCode`.

    :raises ValueError: if ``code`` is already registered -- a duplicate registration
        is a programming error (a copy-pasted decorator), not a runtime condition to
        tolerate silently.
    """

    def decorator(func: RuleFunction) -> RuleFunction:
        if code in _REGISTRY:
            raise ValueError(
                f"rule {code.value} is already registered by "
                f"{_REGISTRY[code].func.__qualname__}; cannot register {func.__qualname__}"
            )
        _REGISTRY[code] = _RegisteredRule(code=code, func=func, description=description)
        return func

    return decorator


def registered_rules() -> dict[RuleCode, str]:
    """Every registered rule code and its description, for docs and the CLI."""
    return {code: entry.description for code, entry in _REGISTRY.items()}


def run_all(
    parcel: LandParcelRecord,
    policy: ValidationPolicy,
    *,
    parcel_key: str | None = None,
) -> ValidationReport:
    """Run every enabled, registered rule against one parcel.

    A rule the policy disables is recorded in ``rules_skipped``, never silently
    dropped -- the report is complete evidence of what was and was not checked.
    """
    key = parcel_key if parcel_key is not None else parcel.parcel_key
    started = time.monotonic()
    issues: list[ValidationIssue] = []
    evaluated: list[RuleCode] = []
    skipped: list[RuleCode] = []

    for code, entry in _REGISTRY.items():
        if not policy.is_enabled(code):
            skipped.append(code)
            continue
        evaluated.append(code)
        try:
            for issue in entry.func(parcel, policy):
                if issue.parcel_key is None:
                    issue = issue.model_copy(update={"parcel_key": key})
                override = policy.tolerance_for(code).severity
                if override is not None and issue.severity != override:
                    issue = issue.model_copy(update={"severity": override})
                issues.append(issue)
        except Exception as exc:  # noqa: BLE001 - one broken rule must not sink the report
            issues.append(
                ValidationIssue(
                    rule_code=code,
                    severity=Severity.CRITICAL,
                    message=f"validation rule {code.value} raised an internal error: {exc}",
                    json_path="$",
                    parcel_key=key,
                    confidence=1.0,
                    remediation="Report this to the engineering team; the record could not be fully checked.",
                )
            )

    duration_ms = (time.monotonic() - started) * 1000
    return ValidationReport(
        policy_name=policy.name,
        issues=issues,
        rules_evaluated=evaluated,
        rules_skipped=skipped,
        duration_ms=round(duration_ms, 3),
    )
