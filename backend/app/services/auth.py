"""Sign-in, role assignment and the Accountant Mode PIN gate.

The Google verification step is injected rather than imported directly, so the
rest of this module - role assignment, the PIN gate, lockout, session issuing -
is testable without a network round trip to Google.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Role, User
from ..security import (
    code_challenge_for,
    create_oauth_state,
    generate_code_verifier,
    hash_pin,
    verify_pin,
)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPES = "openid email profile"


class AuthError(ValueError):
    """Raised when sign-in or the PIN gate refuses a request."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """Coerce a stored datetime to aware UTC.

    Columns are declared ``DateTime(timezone=True)``, which round-trips as
    timezone-aware on PostgreSQL but comes back naive on SQLite. Comparing a
    naive value against an aware ``now`` raises, so anything read back from the
    database is normalised here before it is compared.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Google OAuth
# --------------------------------------------------------------------------- #
class IdTokenVerifier(Protocol):
    """Verifies a Google ID token and returns its claims."""

    def __call__(self, id_token: str, client_id: str) -> dict[str, Any]: ...


def verify_google_id_token(id_token: str, client_id: str) -> dict[str, Any]:
    """Verify an ID token's signature, issuer, audience and expiry.

    Delegated to ``google-auth`` rather than decoded by hand: it fetches and
    caches Google's rotating public keys and checks every claim that matters.
    Decoding the token without verifying it is the classic way to hand an
    attacker a free login.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    return google_id_token.verify_oauth2_token(
        id_token, google_requests.Request(), client_id
    )


def build_authorization_url(redirect_to: str) -> tuple[str, str]:
    """Return the Google consent URL and the signed state to set as a cookie.

    PKCE is used even though this is a confidential client: it costs nothing and
    removes the whole class of attacks where an intercepted authorization code
    is redeemed by someone else.
    """
    if not settings.google_configured:
        raise AuthError(
            "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in backend/.env."
        )

    verifier = generate_code_verifier()
    state = create_oauth_state(redirect_to, verifier)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge_for(verifier),
        "code_challenge_method": "S256",
        # Ask for a fresh account choice rather than silently reusing whichever
        # Google account the browser happens to be signed into.
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}", state


async def exchange_code_for_claims(
    code: str, code_verifier: str, *, verifier: IdTokenVerifier = verify_google_id_token
) -> dict[str, Any]:
    """Swap an authorization code for verified identity claims."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
    if response.status_code != 200:
        raise AuthError("Google rejected the sign-in. Please try again.")

    id_token = response.json().get("id_token")
    if not id_token:
        raise AuthError("Google did not return an identity token.")

    try:
        return verifier(id_token, settings.google_client_id)
    except Exception as exc:  # noqa: BLE001 - any failure here means "not signed in"
        raise AuthError("Could not verify the Google identity token.") from exc


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def role_for_email(db: Session, email: str) -> Role:
    """Decide a new user's role.

    The very first person to sign in becomes the owner, which bootstraps the
    system without a seeded admin password. Everyone after that starts as STAFF
    and has to be promoted deliberately - so an unexpected sign-in reaches the
    daily screen at most, never the books.
    """
    address = email.lower()
    if address in {e.lower() for e in settings.owner_emails}:
        return Role.OWNER
    if address in {e.lower() for e in settings.accountant_emails}:
        return Role.ACCOUNTANT
    if db.scalar(select(func.count(User.id))) == 0:
        return Role.OWNER
    return Role.STAFF


def upsert_user_from_claims(db: Session, claims: dict[str, Any]) -> User:
    """Find or create the user behind a set of verified Google claims."""
    email = (claims.get("email") or "").lower()
    if not email:
        raise AuthError("Google did not provide an email address.")
    if not claims.get("email_verified", False):
        raise AuthError("That Google account's email address is not verified.")

    if settings.allowed_emails and email not in {
        e.lower() for e in settings.allowed_emails
    }:
        raise AuthError(
            f"{email} is not on the allowed list for this restaurant's accounts."
        )

    subject = claims.get("sub")
    user = db.scalar(select(User).where(User.google_sub == subject)) if subject else None
    if user is None:
        # Someone invited by email address, signing in for the first time.
        user = db.scalar(select(User).where(User.email == email))

    if user is None:
        # Every field is set explicitly: column defaults land at INSERT, and
        # this row is read before the flush.
        user = User(
            google_sub=subject,
            email=email,
            name=claims.get("name", "") or email.split("@")[0],
            picture_url=claims.get("picture", "") or "",
            role=role_for_email(db, email),
            is_active=True,
            pin_hash="",
            pin_attempts=0,
        )
        db.add(user)
    else:
        # An account that was switched off must not be revived by signing in.
        if not user.is_active:
            raise AuthError("That account has been deactivated.")
        # Keep the profile fresh, and bind the Google subject the first time we
        # see it so a later email change does not create a second account.
        user.google_sub = subject or user.google_sub
        user.email = email
        user.name = claims.get("name", "") or user.name
        user.picture_url = claims.get("picture", "") or user.picture_url

    user.last_login_at = _now()
    db.flush()
    return user


# --------------------------------------------------------------------------- #
# The PIN gate
# --------------------------------------------------------------------------- #
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 8


def set_pin(db: Session, user: User, new_pin: str, *, current_pin: str | None = None) -> None:
    """Set or change the Accountant Mode PIN."""
    if not new_pin.isdigit() or not MIN_PIN_LENGTH <= len(new_pin) <= MAX_PIN_LENGTH:
        raise AuthError(
            f"The PIN must be {MIN_PIN_LENGTH} to {MAX_PIN_LENGTH} digits."
        )
    if len(set(new_pin)) == 1:
        raise AuthError("Please choose a PIN that is not all the same digit.")
    if user.has_pin:
        if current_pin is None or not verify_pin(current_pin, user.pin_hash):
            raise AuthError("The current PIN is not correct.")

    user.pin_hash = hash_pin(new_pin)
    user.pin_set_at = _now()
    user.pin_attempts = 0
    user.pin_locked_until = None
    db.flush()


def check_pin(db: Session, user: User, pin: str) -> None:
    """Verify a PIN, counting failures and locking out after too many.

    The lockout is the real defence here. A six-digit PIN is only a million
    possibilities, so without a limit on attempts an attacker with the tablet
    would simply try them all.

    The counter is incremented **before** the PIN is verified, in a single
    atomic ``UPDATE ... RETURNING`` evaluated by the database. The decision to
    check the PIN at all is then gated on the returned count. This is what makes
    the limit hold under concurrency: a burst of parallel guesses serialises on
    the atomic update, so only the first ``pin_max_attempts`` of them are ever
    verified - the rest are rejected as locked without the PIN being checked.
    An earlier version incremented in Python after a stale read, and a
    pen-test confirmed dozens of guesses slipping through a single burst.
    """
    if not user.has_pin:
        raise AuthError("No PIN has been set yet.")

    now = _now()
    max_attempts = settings.pin_max_attempts

    # Atomically bump the failure counter and read the fresh state back in one
    # statement. Because the increment is computed in the database, concurrent
    # guesses accumulate correctly instead of all overwriting the same stale
    # value - which is what bounds a burst to `max_attempts` real checks.
    attempts, locked_raw = db.execute(
        update(User)
        .where(User.id == user.id)
        .values(pin_attempts=User.pin_attempts + 1)
        .returning(User.pin_attempts, User.pin_locked_until)
    ).one()
    db.commit()
    locked_until = _as_utc(locked_raw)

    # Currently locked: reject without ever checking the PIN. The counter keeps
    # climbing meanwhile, which is harmless.
    if locked_until and locked_until > now:
        remaining = int((locked_until - now).total_seconds() // 60) + 1
        raise AuthError(
            f"Too many wrong tries. Try again in {remaining} minute"
            f"{'s' if remaining != 1 else ''}."
        )

    # A lock that has since expired opens a fresh window: this guess is attempt 1.
    if locked_until and locked_until <= now:
        db.execute(
            update(User)
            .where(User.id == user.id)
            .values(pin_attempts=1, pin_locked_until=None)
        )
        db.commit()
        attempts = 1

    def _lock() -> None:
        db.execute(
            update(User)
            .where(User.id == user.id)
            .values(pin_locked_until=now + timedelta(minutes=settings.pin_lockout_minutes))
        )
        db.commit()

    # Beyond the limit already: another guess in this same burst set the lock.
    # Reject without checking the PIN - this is the branch that bounds a
    # concurrent flood to at most `max_attempts` real verifications.
    if attempts > max_attempts:
        _lock()
        raise AuthError(
            f"Too many wrong tries. Locked for {settings.pin_lockout_minutes} minutes."
        )

    # Within the window (attempts 1..max). The PIN is checked; a correct one on
    # the final allowed try still succeeds, a wrong one on it trips the lock.
    if not verify_pin(pin, user.pin_hash):
        if attempts >= max_attempts:
            _lock()
            raise AuthError(
                f"Too many wrong tries. Locked for {settings.pin_lockout_minutes} minutes."
            )
        remaining = max_attempts - attempts
        raise AuthError(
            f"That PIN is not right. {remaining} tr{'y' if remaining == 1 else 'ies'} left."
        )

    # Correct: clear the counter and any lock.
    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(pin_attempts=0, pin_locked_until=None)
    )
    db.commit()
