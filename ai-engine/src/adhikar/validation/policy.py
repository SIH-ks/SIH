"""Load a :class:`ValidationPolicy` from YAML.

Keeping tolerances in a file rather than in code is the point of the "data-driven"
requirement: a state revenue department that surveys to +/-1% instead of +/-0.5% edits
``validation_policy.yaml``, not this package.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ..exceptions import ValidationConfigError
from ..schemas.validation import RuleCode, RuleTolerance, ValidationPolicy

__all__ = ["DEFAULT_POLICY", "load_policy"]


def load_policy(path: str | Path) -> ValidationPolicy:
    """Load and validate a policy file.

    :raises ValidationConfigError: if the file is missing, is not valid YAML, fails
        the :class:`ValidationPolicy` schema, or names a rule code that does not
        exist -- the last case is what stops a typo (``AREA_SUM_MISMTCH``) from
        silently defining a tolerance nothing ever reads.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise ValidationConfigError(f"validation policy file not found: {file_path}")

    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValidationConfigError(f"malformed YAML in {file_path}: {exc}") from exc

    rules_section = raw.pop("rules", {}) or {}
    known_codes = {code.value for code in RuleCode}
    unknown = set(rules_section) - known_codes
    if unknown:
        raise ValidationConfigError(
            f"{file_path} references unknown rule code(s): {sorted(unknown)}. "
            f"Known codes: {sorted(known_codes)}"
        )

    try:
        rules = {RuleCode(code): RuleTolerance.model_validate(cfg or {}) for code, cfg in rules_section.items()}
        return ValidationPolicy.model_validate({**raw, "rules": rules})
    except ValidationError as exc:
        raise ValidationConfigError(f"invalid validation policy in {file_path}: {exc}") from exc


DEFAULT_POLICY = ValidationPolicy(
    name="default",
    description="Conservative defaults used when no policy file is configured.",
)
"""In-code fallback so the engine works out of the box with no YAML file present."""
