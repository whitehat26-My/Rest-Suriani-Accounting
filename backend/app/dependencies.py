"""Access control dependencies.

Three gates, in increasing strictness:

* :func:`current_user` - who is signed in, or ``None``.
* :func:`require_user` - anyone signed in. The daily screen needs this.
* :func:`require_finance` - a role that may see money, *and* an unlocked
  Accountant Mode on this device. Reports, the ledger and payroll need this.

When Google credentials are not configured there is no way to sign in at all, so
the gates fall open and the app runs as a single-user local tool. That is a
deliberate trade - an unconfigured install that refuses every request would be
unusable rather than secure - and it is announced at startup and in the docs.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Role, User
from .security import read_token

SESSION_COOKIE = "rs_session"
UNLOCK_COOKIE = "rs_unlock"


def _user_from_request(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = read_token(token, purpose="session")
    if payload is None:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """The signed-in user, or ``None``. Never raises."""
    return _user_from_request(request, db)


def is_unlocked(request: Request, user: User | None) -> bool:
    """Whether Accountant Mode has been unlocked on this device recently."""
    if user is None:
        return False
    token = request.cookies.get(UNLOCK_COOKIE)
    if not token:
        return False
    payload = read_token(token, purpose="unlock")
    return payload is not None and payload.get("sub") == str(user.id)


def require_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Any signed-in user. Open when Google sign-in is not configured."""
    user = _user_from_request(request, db)
    if not settings.auth_enabled:
        return user
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please sign in to continue.",
        )
    return user


def require_finance(request: Request, db: Session = Depends(get_db)) -> User | None:
    """A finance role with Accountant Mode unlocked on this device."""
    user = _user_from_request(request, db)
    if not settings.auth_enabled:
        return user

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please sign in to continue.",
        )
    if not user.can_see_finances:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This part of the system is for the owner and the accountant.",
        )
    if not is_unlocked(request, user):
        # 423 rather than 403: the answer is "enter your PIN", not "you may
        # never do this", and the frontend needs to tell those apart.
        #
        # Someone who has not set a PIN yet is gated too, and made to choose one
        # on the way through. An optional gate that defaults to off is not a
        # gate - the tablet by the till would sit permanently open to whoever
        # picked it up.
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                "Enter your PIN to open Accountant Mode."
                if user.has_pin
                else "Choose a PIN to protect the accounts on this device."
            ),
        )
    return user


def require_owner(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Only the owner. Used for changing other people's roles."""
    user = require_finance(request, db)
    if settings.auth_enabled and (user is None or user.role is not Role.OWNER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can change who has access.",
        )
    return user
