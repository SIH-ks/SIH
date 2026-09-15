"""Authentication and account management.

Login is the only unauthenticated write endpoint in the API. Everything else in this
module requires the administrator role, because in a revenue department "who can
approve a land record" is itself a controlled decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....core.config import get_settings
from ....core.logging import get_logger
from ....core.security import create_access_token, hash_password, verify_password
from ....db.base import get_db
from ....models.enums import UserRole
from ....models.user import User
from ....schemas.record import (
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    UserProfile,
)
from ...deps import CurrentUser, current_user, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("adhikar.auth")


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Exchange credentials for a bearer token.

    Answers the same 401 with the same message for an unknown username, a wrong
    password, and a suspended account. Distinguishing them turns the login form into
    a username oracle -- worth avoiding anywhere, and worth avoiding especially in a
    system whose usernames are officials' names.
    """
    settings = get_settings()
    user = db.scalar(select(User).where(User.username == payload.username.strip().lower()))

    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        logger.warning("login_failed", username=payload.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")

    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=user.id, role=user.role, full_name=user.full_name)
    logger.info("login_ok", username=user.username, role=user.role)
    return LoginResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserProfile.model_validate(user),
    )


@router.get("/me", response_model=UserProfile)
def me(user: CurrentUser = Depends(current_user), db: Session = Depends(get_db)) -> UserProfile:
    """The signed-in user's profile, for the console's identity chip and role gating."""
    if user.id is not None:
        row = db.get(User, user.id)
        if row is not None:
            return UserProfile.model_validate(row)
    # Reachable only when `require_auth` is off: there is no row behind the caller,
    # so the anonymous identity is described rather than 404'd.
    return UserProfile(
        id=uuid.UUID(int=0),
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=True,
    )


@router.get("/users", response_model=list[UserProfile])
def list_users(
    _: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.role.desc(), User.username)).all())


@router.post("/users", response_model=UserProfile, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    actor: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    username = payload.username.strip().lower()
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"username {username!r} is already taken")

    user = User(
        id=uuid.uuid4(),
        username=username,
        full_name=payload.full_name,
        designation=payload.designation,
        email=payload.email,
        role=payload.role.value,
        district=payload.district,
        state=payload.state,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("user_created", username=username, role=user.role, by=actor.username)
    return user


@router.post("/users/{user_id}/deactivate", response_model=UserProfile)
def deactivate_user(
    user_id: uuid.UUID,
    actor: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    """Suspend an account. Never deletes it.

    The audit trail references reviewers by username; deleting the row would orphan
    every decision that person ever made. Deactivation revokes access immediately
    (:func:`app.api.deps._user_from_token` re-checks ``is_active`` on every request)
    while leaving the history intact.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.id == actor.id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="you cannot deactivate your own account")

    user.is_active = False
    db.commit()
    db.refresh(user)
    logger.info("user_deactivated", username=user.username, by=actor.username)
    return user


@router.get("/roles", response_model=list[dict])
def roles() -> list[dict]:
    """The role vocabulary, for a client that renders a role picker.

    Unauthenticated on purpose: it is a static description of the permission model,
    not a list of who holds what, and the login screen needs it before any token
    exists.
    """
    return [
        {"value": role.value, "label": role.label, "rank": role.rank}
        for role in sorted(UserRole, key=lambda r: r.rank)
    ]
