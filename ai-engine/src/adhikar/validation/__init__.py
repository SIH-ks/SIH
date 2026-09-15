"""Data-driven consistency validation.

Importing this package registers every rule in :mod:`adhikar.validation.rules` via
its module-level ``@rule`` decorators, so ``adhikar.validation.run_all(...)`` is
always evaluating the complete, current rule set.

The same import registers the cross-document succession checks in
:mod:`adhikar.validation.succession`. Those judge a *bundle* of documents rather than
one parcel, so they have their own registry and their own entry point
(:func:`validate_succession`) -- but they emit findings under codes in the same
:class:`~adhikar.schemas.validation.RuleCode` catalogue, evaluated against the same
YAML policy, so everything downstream treats them as ordinary findings.
"""

from __future__ import annotations

from . import rules as _rules  # noqa: F401 - imported for its registration side effect
from . import succession as _succession  # noqa: F401 - same, for the succession registry
from .policy import DEFAULT_POLICY, load_policy
from .registry import registered_rules, run_all
from .succession import registered_succession_rules, validate_documents, validate_succession

__all__ = [
    "DEFAULT_POLICY",
    "load_policy",
    "registered_rules",
    "registered_succession_rules",
    "run_all",
    "validate_documents",
    "validate_succession",
]
