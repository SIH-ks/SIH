"""System introspection: the rule catalogue, the active policy, and runtime status.

These endpoints exist so the console can *explain itself*. A reviewer who is told a
record failed ``AREA_SUM_MISMATCH`` deserves to be able to read what that rule checks
and what tolerance it was checked against, without anyone opening a YAML file on the
server. In a system whose output carries legal weight, "why did it say that?" has to
be answerable from the interface.
"""

from __future__ import annotations

from adhikar.schemas.validation import RuleCode, Severity
from adhikar.validation import DEFAULT_POLICY, registered_rules, registered_succession_rules
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ....core.config import get_settings
from ....db.base import database_fallback_active, engine, get_db
from ...deps import CurrentUser, current_user

router = APIRouter(prefix="/system", tags=["system"])

#: Which family each rule belongs to, for grouping in the UI. Derived from the code's
#: own prefix where that is unambiguous and mapped explicitly where it is not --
#: `LOW_OCR_CONFIDENCE` is an extraction-quality check, not an OCR subsystem.
_RULE_GROUPS: dict[str, str] = {
    "AREA": "Arithmetic consistency",
    "CLASSIFICATION": "Arithmetic consistency",
    "TOTAL": "Arithmetic consistency",
    "ASSESSMENT": "Arithmetic consistency",
    "SHARE": "Ownership",
    "OWNER": "Ownership",
    "NO_OWNERS": "Ownership",
    "DUPLICATE_OWNER": "Ownership",
    "ORPHAN": "Ownership",
    "MUTATION": "Mutation chain",
    "CORRECTION": "Mutation chain",
    # Its own group rather than being split across the families above: these are
    # cross-document checks, and SUCCESSION_MUTATION_PARCEL_MISMATCH answers a
    # different question from the single-record mutation rules despite the name.
    "SUCCESSION": "Ownership succession",
    "ENCUMBRANCE": "Encumbrance",
    "IDENTIFIER": "Identifiers",
    "DUPLICATE_KHASRA": "Identifiers",
    "JURISDICTION": "Identifiers",
    "LOW": "Extraction quality",
    "UNRESOLVED": "Extraction quality",
    "TABLE": "Extraction quality",
    "GEOMETRY": "Geospatial",
}


def _group_for(code: str) -> str:
    for prefix, group in _RULE_GROUPS.items():
        if code.startswith(prefix):
            return group
    return "Other"


@router.get("/rules", response_model=list[dict])
def rule_catalogue(_: CurrentUser = Depends(current_user)) -> list[dict]:
    """Every registered validation rule, with its description, group and tolerance.

    Read straight from the live registry rather than a hand-maintained list, so a
    rule added to the engine appears here the moment it is registered -- a
    documentation page that can silently fall behind the code is not documentation.
    """
    # Both registries: the per-parcel rules and the cross-document succession checks.
    # Read live rather than from a hand-maintained list, so a rule added to either
    # engine appears here the moment it is registered -- a documentation page that can
    # silently fall behind the code is not documentation.
    descriptions = {**registered_rules(), **registered_succession_rules()}
    out: list[dict] = []
    for code in RuleCode:
        tolerance = DEFAULT_POLICY.tolerance_for(code)
        out.append(
            {
                "code": code.value,
                "group": _group_for(code.value),
                "description": descriptions.get(code) or (code.__doc__ or "").strip(),
                "enabled": DEFAULT_POLICY.is_enabled(code),
                "severity_override": tolerance.severity.value if tolerance.severity else None,
                "registered": code in descriptions,
                "risk_points": tolerance.risk_points,
            }
        )
    return sorted(out, key=lambda r: (r["group"], r["code"]))


@router.get("/policy", response_model=dict)
def active_policy(_: CurrentUser = Depends(current_user)) -> dict:
    """The tolerance policy the rule engine is currently evaluating against.

    Surfaced because tolerances are the part a state revenue department is expected
    to tune (``policies/validation_policy.yaml``), and a reviewer disputing a finding
    needs to see the threshold it was judged against, not be told one exists.
    """
    return {
        "name": DEFAULT_POLICY.name,
        "policy": DEFAULT_POLICY.model_dump(mode="json"),
        "severity_levels": [{"value": s.value, "rank": s.rank} for s in Severity],
    }


@router.get("/status", response_model=dict)
def status(db: Session = Depends(get_db), user: CurrentUser = Depends(current_user)) -> dict:
    """Runtime status for the console's system-status readout.

    Reports the *actual* database in use, including whether the SQLite fallback took
    over (see :mod:`app.db.base`). A status pill that says "System Online" while the
    API is quietly writing to a different database than the one configured is worse
    than no pill at all.
    """
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001 - the endpoint's job is to report this, not raise
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "environment": settings.environment,
        "auth_enforced": settings.require_auth,
        "signed_in_as": {"username": user.username, "role": user.role.value},
        "database": {
            "dialect": engine.dialect.name,
            "reachable": db_ok,
            "fallback_active": database_fallback_active,
            "configured_url_scheme": settings.database_url.split("://", 1)[0],
        },
        "limits": {
            "max_upload_size_mb": settings.max_upload_size_mb,
            "max_batch_upload_files": settings.max_batch_upload_files,
        },
        "sla_hours_by_priority": settings.sla_hours_by_priority,
    }
