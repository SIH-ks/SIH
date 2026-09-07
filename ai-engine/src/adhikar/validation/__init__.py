"""Data-driven consistency validation.

Importing this package registers every rule in :mod:`adhikar.validation.rules` via
its module-level ``@rule`` decorators, so ``adhikar.validation.run_all(...)`` is
always evaluating the complete, current rule set.
"""

from __future__ import annotations

from . import rules as _rules  # noqa: F401 - imported for its registration side effect
from .policy import DEFAULT_POLICY, load_policy
from .registry import registered_rules, run_all

__all__ = ["DEFAULT_POLICY", "load_policy", "registered_rules", "run_all"]
