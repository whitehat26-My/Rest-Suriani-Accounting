"""Password-free security primitives: PIN hashing and signed session tokens.

There are no passwords in this system - identity comes from Google. What is
here is the two things that still have to be done carefully:

**PIN hashing.** A four to six digit PIN has at most a million possibilities, so
no hash function makes it safe against an attacker who has the database and
time. PBKDF2 with a high iteration count raises the cost of each guess, but the
protection that actually matters is the attempt counter and lockout in
:mod:`app.services.auth`. Both are used together; neither is sufficient alone.

**Session tokens.** Signed JWTs in httpOnly cookies. The session is deliberately
long-lived so the owner never meets a login screen on the shop tablet, while the
Accountant Mode unlock is short-lived and separate, so leaving the tablet on the
counter does not leave the wage bill on display.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from .config import settings

# OWASP's floor for PBKDF2-HMAC-SHA256 at time of writing.
PBKDF2_ITERATIONS = 600_000
PBKDF2_ALGORITHM = "sha256"
SALT_BYTES = 16

ALGORITHM = "HS256"


# --------------------------------------------------------------------------- #
# PIN hashing
# --------------------------------------------------------------------------- #
def hash_pin(pin: str) -> str:
    """Hash a PIN as ``pbkdf2_sha256$iterations$salt$digest``."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM, pin.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    """Check a PIN against its stored hash in constant time."""
    if not stored:
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if not algorithm.startswith("pbkdf2_"):
            return False
        candidate = hashlib.pbkdf2_hmac(
            algorithm.removeprefix("pbkdf2_"),
            pin.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    # compare_digest, not ==, so the comparison leaks no timing information.
    return hmac.compare_digest(candidate.hex(), digest_hex)


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(claims: dict[str, Any], *, expires_in: timedelta, purpose: str) -> str:
    """Sign a JWT for one specific purpose.

    The ``purpose`` claim is checked on the way back in, so a session cookie can
    never be replayed as an unlock cookie or as an OAuth state value even though
    all three are signed with the same key.
    """
    issued = _now()
    payload = {
        **claims,
        "purpose": purpose,
        "iat": issued,
        "exp": issued + expires_in,
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def read_token(token: str, *, purpose: str) -> dict[str, Any] | None:
    """Verify and decode a token, or return ``None`` if it is not usable."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != purpose:
        return None
    return payload


def create_session_token(user_id: int, role: str) -> str:
    return create_token(
        {"sub": str(user_id), "role": role},
        expires_in=timedelta(days=settings.session_days),
        purpose="session",
    )


def create_unlock_token(user_id: int) -> str:
    return create_token(
        {"sub": str(user_id)},
        expires_in=timedelta(hours=settings.unlock_hours),
        purpose="unlock",
    )


def create_oauth_state(redirect_to: str, code_verifier: str) -> str:
    return create_token(
        {"redirect_to": redirect_to, "cv": code_verifier},
        expires_in=timedelta(minutes=10),
        purpose="oauth-state",
    )


def generate_code_verifier() -> str:
    """A PKCE verifier: 43-128 characters of unreserved URL-safe text."""
    return secrets.token_urlsafe(64)


def code_challenge_for(verifier: str) -> str:
    """The S256 challenge Google expects for the given verifier."""
    import base64

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
