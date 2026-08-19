"""Sign-in, sign-out, the PIN gate and role management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import (
    SESSION_COOKIE,
    UNLOCK_COOKIE,
    current_user,
    is_unlocked,
    require_finance,
    require_owner,
    require_user,
)
from ..models import Role, User
from ..schemas import AuthStatusOut, PinSet, PinVerify, RoleUpdate, UserOut
from ..security import create_session_token, create_unlock_token, read_token
from ..services import auth as auth_service
from ..services.auth import AuthError

router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE = "rs_oauth_state"


def _set_cookie(response: Response, key: str, value: str, max_age: int) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        httponly=True,          # never readable from JavaScript
        secure=settings.cookie_secure,
        samesite="lax",         # survives the redirect back from Google
        domain=settings.cookie_domain,
        path="/",
    )


def _clear_cookie(response: Response, key: str) -> None:
    response.delete_cookie(key, path="/", domain=settings.cookie_domain)


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
@router.get("/status", response_model=AuthStatusOut)
def status_endpoint(
    request: Request, user: User | None = Depends(current_user)
) -> AuthStatusOut:
    """What the frontend asks on load to decide what to render."""
    return AuthStatusOut(
        auth_enabled=settings.auth_enabled,
        signed_in=user is not None,
        user=UserOut.model_validate(user) if user else None,
        unlocked=is_unlocked(request, user),
        pin_required=bool(user and user.can_see_finances),
    )


# --------------------------------------------------------------------------- #
# Google OAuth
# --------------------------------------------------------------------------- #
@router.get("/google/login")
def google_login(redirect_to: str = "/") -> RedirectResponse:
    """Send the browser to Google's consent screen."""
    try:
        url, state = auth_service.build_authorization_url(redirect_to)
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    # The state carries the PKCE verifier and is signed, so nothing needs to be
    # held server-side between the two halves of the flow.
    _set_cookie(response, STATE_COOKIE, state, max_age=600)
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Complete the sign-in and set the session cookie."""

    def bounce(message: str) -> RedirectResponse:
        from urllib.parse import quote

        return RedirectResponse(
            f"{settings.frontend_url}/signin?error={quote(message)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if error:
        return bounce("Sign-in was cancelled.")
    if not code or not state:
        return bounce("Google did not return a sign-in code.")

    # The state must match the cookie we set, which is what stops a forged
    # callback from signing someone in.
    cookie_state = request.cookies.get(STATE_COOKIE)
    if not cookie_state or cookie_state != state:
        return bounce("The sign-in link has expired. Please try again.")

    payload = read_token(state, purpose="oauth-state")
    if payload is None:
        return bounce("The sign-in link has expired. Please try again.")

    try:
        claims = await auth_service.exchange_code_for_claims(code, payload["cv"])
        user = auth_service.upsert_user_from_claims(db, claims)
    except AuthError as exc:
        db.rollback()
        return bounce(str(exc))
    db.commit()

    destination = payload.get("redirect_to") or "/"
    if not destination.startswith("/"):
        # Never redirect off-site on the strength of a query parameter.
        destination = "/"

    response = RedirectResponse(
        f"{settings.frontend_url}{destination}", status_code=status.HTTP_303_SEE_OTHER
    )
    _set_cookie(
        response,
        SESSION_COOKIE,
        create_session_token(user.id, user.role.value),
        max_age=settings.session_days * 24 * 3600,
    )
    _clear_cookie(response, STATE_COOKIE)
    return response


@router.post("/logout")
def logout(response: Response) -> dict:
    _clear_cookie(response, SESSION_COOKIE)
    _clear_cookie(response, UNLOCK_COOKIE)
    return {"signed_out": True}


# --------------------------------------------------------------------------- #
# The PIN gate
# --------------------------------------------------------------------------- #
@router.post("/pin", response_model=AuthStatusOut)
def set_pin(
    payload: PinSet,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
) -> AuthStatusOut:
    """Set or change the PIN that opens Accountant Mode."""
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    if not user.can_see_finances:
        raise HTTPException(
            status_code=403, detail="Only the owner and the accountant use a PIN."
        )
    try:
        auth_service.set_pin(db, user, payload.new_pin, current_pin=payload.current_pin)
    except AuthError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()

    # Setting a PIN also unlocks this device; being asked for it immediately
    # after choosing it would be pure friction.
    _set_cookie(
        response,
        UNLOCK_COOKIE,
        create_unlock_token(user.id),
        max_age=settings.unlock_hours * 3600,
    )
    return AuthStatusOut(
        auth_enabled=settings.auth_enabled,
        signed_in=True,
        user=UserOut.model_validate(user),
        unlocked=True,
        pin_required=True,
    )


@router.post("/pin/verify", response_model=AuthStatusOut)
def verify_pin_endpoint(
    payload: PinVerify,
    response: Response,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_user),
) -> AuthStatusOut:
    """Unlock Accountant Mode on this device."""
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    try:
        auth_service.check_pin(db, user, payload.pin)
    except AuthError as exc:
        db.commit()  # keep the attempt counter even though the check failed
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    db.commit()

    _set_cookie(
        response,
        UNLOCK_COOKIE,
        create_unlock_token(user.id),
        max_age=settings.unlock_hours * 3600,
    )
    return AuthStatusOut(
        auth_enabled=settings.auth_enabled,
        signed_in=True,
        user=UserOut.model_validate(user),
        unlocked=True,
        pin_required=True,
    )


@router.post("/lock")
def lock(response: Response) -> dict:
    """Close Accountant Mode without signing out of the daily screen."""
    _clear_cookie(response, UNLOCK_COOKIE)
    return {"locked": True}


# --------------------------------------------------------------------------- #
# Who has access
# --------------------------------------------------------------------------- #
@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db), _: User | None = Depends(require_finance)
) -> list[UserOut]:
    users = db.scalars(select(User).order_by(User.email)).all()
    return [UserOut.model_validate(u) for u in users]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_role(
    user_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    actor: User | None = Depends(require_owner),
) -> UserOut:
    """Change someone's role. Owner only."""
    # Lock the target row so two simultaneous demotions cannot both pass the
    # "is there still an owner?" check below and leave the restaurant with none.
    target = db.execute(
        select(User).where(User.id == user_id).with_for_update()
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    demoting_an_owner = target.role is Role.OWNER and payload.role is not Role.OWNER
    if demoting_an_owner:
        if actor is not None and target.id == actor.id:
            # Otherwise the last owner can lock the restaurant out of its own books.
            raise HTTPException(
                status_code=400, detail="You cannot remove your own owner access."
            )
        remaining_owners = db.scalar(
            select(func.count(User.id)).where(
                User.role == Role.OWNER,
                User.is_active.is_(True),
                User.id != target.id,
            )
        )
        if not remaining_owners:
            raise HTTPException(
                status_code=400,
                detail="At least one active owner must remain. Promote someone else first.",
            )

    target.role = payload.role
    db.commit()
    db.refresh(target)
    return UserOut.model_validate(target)
