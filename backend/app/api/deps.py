"""Shared FastAPI dependencies: authentication, role enforcement, pagination.

This is the only module that knows how a caller's identity arrives over HTTP. Routers
declare *what* they require (``Depends(require_reviewer)``) and never parse a header
themselves, so there is exactly one place to audit for "can this endpoint be reached
without a token?".
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.security import InvalidTokenError, decode_access_token
from ..db.base import get_db
from ..models.enums import UserRole
from ..models.user import User

__all__ = [
    "CurrentUser",
    "current_user",
    "optional_user",
    "require_admin",
    "require_operator",
    "require_reviewer",
    "require_role",
]

_bearer = HTTPBearer(auto_error=False, description="JWT issued by POST /api/v1/auth/login")


@dataclass(slots=True, frozen=True)
class CurrentUser:
    """The authenticated caller, as the request handlers see them.

    A frozen dataclass built from token claims rather than the ORM ``User`` row: the
    handlers only ever need identity + role, and not returning a live ORM object
    keeps a handler from accidentally mutating and committing the user record while
    doing something else entirely.
    """

    id: uuid.UUID | None
    username: str
    full_name: str
    role: UserRole
    district: str | None = None
    is_anonymous: bool = False

    @property
    def can_approve(self) -> bool:
        return self.role.outranks_or_equals(UserRole.REVIEWER)

    @property
    def can_write(self) -> bool:
        return self.role.outranks_or_equals(UserRole.OPERATOR)


ANONYMOUS = CurrentUser(
    id=None,
    username="anonymous",
    full_name="Unauthenticated caller",
    role=UserRole.AUDITOR,
    is_anonymous=True,
)
"""Who a caller is when ``require_auth`` is off. Given the *lowest* role rather than
the highest, so switching auth off opens the API for reading without also handing
every anonymous caller the ability to approve land records."""


def _user_from_token(token: str, db: Session) -> CurrentUser:
    claims = decode_access_token(token)  # raises InvalidTokenError
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("token subject is not a user id") from exc

    row = db.get(User, user_id)
    if row is None or not row.is_active:
        # A token for a deleted or suspended account must stop working immediately,
        # which is the one thing the embedded-claims design cannot do on its own --
        # so existence and active-status are the two things still read per request.
        raise InvalidTokenError("account is inactive or no longer exists")

    return CurrentUser(
        id=row.id,
        username=row.username,
        full_name=row.full_name,
        role=UserRole(row.role),
        district=row.district,
    )


def optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser | None:
    """Resolve the caller if they presented a valid token; ``None`` otherwise.

    Never raises. Used by endpoints that behave differently for a signed-in user but
    are not gated on one -- and by :func:`current_user`, which adds the gate.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        user = _user_from_token(credentials.credentials, db)
    except InvalidTokenError:
        return None
    structlog.contextvars.bind_contextvars(user=user.username, role=user.role.value)
    request.state.user = user
    return user


def current_user(user: CurrentUser | None = Depends(optional_user)) -> CurrentUser:
    """Require an authenticated caller (unless ``require_auth`` is off)."""
    if user is not None:
        return user
    if not get_settings().require_auth:
        return ANONYMOUS
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. POST /api/v1/auth/login to obtain a token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(minimum: UserRole) -> Callable[..., CurrentUser]:
    """Build a dependency that admits any role at or above ``minimum``.

    Hierarchical rather than an explicit allow-list because the roles genuinely nest
    here (an admin can do everything a reviewer can). A future permission that does
    *not* nest -- something only an auditor may do, say -- would need its own
    dependency rather than being forced into this ordering.
    """

    def _dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not user.role.outranks_or_equals(minimum):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action requires the {minimum.label} role or higher; "
                    f"you are signed in as {user.role.label}."
                ),
            )
        return user

    return _dependency


require_operator = require_role(UserRole.OPERATOR)
"""Upload a scan, key a correction. The floor for changing anything."""

require_reviewer = require_role(UserRole.REVIEWER)
"""Approve, reject, escalate, assign. The separation-of-duties boundary: an operator
who keys a correction cannot also be the one who approves the record carrying it."""

require_admin = require_role(UserRole.ADMIN)
"""User management and validation-policy changes."""


def client_ip(request: Request) -> str | None:
    """Best-effort caller IP for the audit trail.

    Trusts ``X-Forwarded-For``'s first hop, which is correct behind a reverse proxy
    the deployment controls and forgeable without one. Recorded as supporting
    evidence in the audit trail, never as an authorization input -- so a forged value
    misleads a later investigation but cannot grant access.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
