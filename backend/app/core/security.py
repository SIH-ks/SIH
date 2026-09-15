"""Password hashing and JWT issuance/verification.

Deliberately small: this module knows how to turn a password into a hash and a user
into a signed token, and nothing about HTTP. The FastAPI wiring that reads the
``Authorization`` header and enforces roles lives in :mod:`app.api.deps`, so the
crypto here stays testable without a request object.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from .config import get_settings

__all__ = [
    "InvalidTokenError",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "verify_password",
]

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
"""Argon2id, the current password-hashing recommendation. `deprecated="auto"` means
that if this list ever gains a newer scheme, existing hashes keep verifying and get
transparently upgraded on the next successful login rather than locking users out."""


class InvalidTokenError(Exception):
    """A bearer token was absent, malformed, expired, or signed with the wrong key.

    One exception type for all four on purpose: the caller (the auth dependency)
    answers 401 regardless, and distinguishing them in the response body would tell
    an attacker which half of a guess was right.
    """


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        # A stored hash in an unrecognised format is a data problem, not a valid
        # password -- fail closed rather than propagating a 500 out of a login form.
        return False


def create_access_token(
    *, subject: uuid.UUID | str, role: str, full_name: str, extra: dict[str, Any] | None = None
) -> str:
    """Sign a short-lived access token carrying the claims the API authorizes on.

    ``role`` is embedded in the token so the common case (checking whether a caller
    may approve a parcel) costs no database round trip. The trade-off is that a role
    change only takes effect on the user's next login -- acceptable for a token that
    expires within a working day, and the alternative (a users-table read on every
    request) buys revocation latency the deployment does not need.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "name": full_name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
        "iss": "adhikar-api",
        **(extra or {}),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature + expiry and return the claims.

    :raises InvalidTokenError: on any failure -- see that class's docstring for why
        the failure modes are not distinguished.
    """
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="adhikar-api",
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
