"""Access control: sign-in, roles and the Accountant Mode PIN gate.

The Google round trip itself cannot be exercised here - it needs a browser and
real credentials. Everything on this side of it can be, and is: role assignment
from verified claims, session issuing, every gate, the PIN and its lockout, and
the token-forgery cases.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import settings
from app.dependencies import SESSION_COOKIE, UNLOCK_COOKIE
from app.models import Role, User
from app.security import (
    create_token,
    create_unlock_token,
    hash_pin,
    read_token,
    verify_pin,
)
from app.services.auth import AuthError, check_pin, role_for_email, set_pin, upsert_user_from_claims

# Endpoints that must never be reachable without a finance role.
FINANCE_ENDPOINTS = [
    "/api/reports/income-statement",
    "/api/reports/balance-sheet",
    "/api/reports/cash-flow",
    "/api/reports/trial-balance",
    "/api/insights/dashboard",
    "/api/insights/evaluation",
    "/api/accounts",
    "/api/payroll/overview",
    "/api/payroll/employees",
    "/api/transactions",
]

# Endpoints the daily screen needs, which any signed-in user may reach.
DAILY_ENDPOINTS = [
    "/api/insights/daily",
    "/api/insights/week",
    "/api/inventory",
    "/api/accounts/spending-categories",
]


@pytest.fixture()
def auth_on(monkeypatch):
    """Turn on authentication, as configuring Google credentials would."""
    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    assert settings.auth_enabled is True
    return settings


def make_user(db, email="owner@example.com", role=Role.OWNER, **kwargs) -> User:
    user = User(email=email, name=email.split("@")[0], role=role, google_sub=email, **kwargs)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def sign_in(client, user: User) -> None:
    """Attach a valid session cookie, as a completed Google sign-in would."""
    from app.security import create_session_token

    client.cookies.set(SESSION_COOKIE, create_session_token(user.id, user.role.value))


def unlock(client, user: User) -> None:
    client.cookies.set(UNLOCK_COOKIE, create_unlock_token(user.id))


# --------------------------------------------------------------------------- #
# The unconfigured case
# --------------------------------------------------------------------------- #
class TestWithoutGoogleConfigured:
    def test_the_app_runs_open_so_it_is_usable_before_setup(self, client):
        """Refusing everything until Google is configured would be unusable."""
        assert settings.auth_enabled is False
        for endpoint in FINANCE_ENDPOINTS + DAILY_ENDPOINTS:
            assert client.get(endpoint).status_code == 200, endpoint

    def test_the_status_endpoint_says_auth_is_off(self, client):
        body = client.get("/api/auth/status").json()
        assert body["auth_enabled"] is False
        assert body["signed_in"] is False

    def test_the_login_route_explains_it_is_not_configured(self, client):
        response = client.get("/api/auth/google/login", follow_redirects=False)
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# The gates
# --------------------------------------------------------------------------- #
class TestGates:
    def test_signed_out_users_are_refused_everywhere(self, client, auth_on):
        for endpoint in FINANCE_ENDPOINTS + DAILY_ENDPOINTS:
            assert client.get(endpoint).status_code == 401, endpoint

    def test_writing_a_transaction_requires_signing_in(self, client, auth_on):
        response = client.post(
            "/api/transactions/quick", json={"kind": "in", "amount": "100.00"}
        )
        assert response.status_code == 401

    def test_staff_reach_the_daily_screen(self, client, db, auth_on):
        sign_in(client, make_user(db, "server@example.com", Role.STAFF))
        for endpoint in DAILY_ENDPOINTS:
            assert client.get(endpoint).status_code == 200, endpoint

    def test_staff_can_record_money_but_not_read_the_books(self, client, db, auth_on):
        """The whole point of the role split."""
        sign_in(client, make_user(db, "server@example.com", Role.STAFF))
        assert (
            client.post(
                "/api/transactions/quick", json={"kind": "in", "amount": "100.00"}
            ).status_code
            == 201
        )
        for endpoint in FINANCE_ENDPOINTS:
            response = client.get(endpoint)
            assert response.status_code == 403, endpoint
            assert "owner and the accountant" in response.json()["detail"]

    def test_staff_cannot_see_the_payroll(self, client, db, auth_on):
        """Wages are exactly what a server should not read over the counter."""
        sign_in(client, make_user(db, "server@example.com", Role.STAFF))
        assert client.get("/api/payroll/overview").status_code == 403

    def test_an_owner_who_has_not_chosen_a_pin_is_still_gated(self, client, db, auth_on):
        """An optional gate that defaults to off is not a gate."""
        user = make_user(db, "grandma@example.com", Role.OWNER)
        sign_in(client, user)
        for endpoint in DAILY_ENDPOINTS:
            assert client.get(endpoint).status_code == 200, endpoint
        for endpoint in FINANCE_ENDPOINTS:
            response = client.get(endpoint)
            assert response.status_code == 423, endpoint
            assert "Choose a PIN" in response.json()["detail"]

    def test_an_unlocked_owner_reaches_everything(self, client, db, auth_on):
        user = make_user(db, "grandma@example.com", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, user)
        unlock(client, user)
        for endpoint in FINANCE_ENDPOINTS + DAILY_ENDPOINTS:
            assert client.get(endpoint).status_code == 200, endpoint

    def test_an_accountant_reaches_the_finances_once_unlocked(self, client, db, auth_on):
        user = make_user(db, "acct@example.com", Role.ACCOUNTANT, pin_hash=hash_pin("1357"))
        sign_in(client, user)
        unlock(client, user)
        assert client.get("/api/reports/trial-balance").status_code == 200

    def test_a_deactivated_account_is_refused(self, client, db, auth_on):
        user = make_user(db, "gone@example.com", Role.OWNER)
        sign_in(client, user)
        user.is_active = False
        db.commit()
        assert client.get("/api/insights/daily").status_code == 401


class TestPinGate:
    def test_a_set_pin_locks_accountant_mode_until_it_is_entered(self, client, db, auth_on):
        user = make_user(db, "grandma@example.com", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, user)

        # 423 Locked, not 403: the answer is "enter your PIN", not "never".
        response = client.get("/api/reports/trial-balance")
        assert response.status_code == 423
        assert "PIN" in response.json()["detail"]

        # The daily screen is unaffected - it is not what the PIN protects.
        assert client.get("/api/insights/daily").status_code == 200

    def test_verifying_the_pin_unlocks_this_device(self, client, db, auth_on):
        user = make_user(db, "grandma@example.com", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, user)

        response = client.post("/api/auth/pin/verify", json={"pin": "2468"})
        assert response.status_code == 200
        assert response.json()["unlocked"] is True
        assert client.get("/api/reports/trial-balance").status_code == 200

    def test_a_wrong_pin_is_refused_and_counted(self, client, db, auth_on):
        user = make_user(db, "grandma@example.com", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, user)

        response = client.post("/api/auth/pin/verify", json={"pin": "1111"})
        assert response.status_code == 401
        assert "tries left" in response.json()["detail"]
        assert client.get("/api/reports/trial-balance").status_code == 423

    def test_locking_closes_accountant_mode_without_signing_out(self, client, db, auth_on):
        user = make_user(db, "grandma@example.com", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, user)
        client.post("/api/auth/pin/verify", json={"pin": "2468"})
        assert client.get("/api/reports/trial-balance").status_code == 200

        client.post("/api/auth/lock")
        assert client.get("/api/reports/trial-balance").status_code == 423
        # Still signed in for the daily screen.
        assert client.get("/api/insights/daily").status_code == 200

    def test_setting_a_pin_also_unlocks_the_device(self, client, db, auth_on):
        """Being asked for a PIN you just chose is pure friction."""
        sign_in(client, make_user(db, "grandma@example.com", Role.OWNER))
        response = client.post("/api/auth/pin", json={"new_pin": "2468"})
        assert response.status_code == 200
        assert response.json()["unlocked"] is True
        # And the finances open immediately afterwards.
        assert client.get("/api/reports/trial-balance").status_code == 200

    def test_changing_a_pin_needs_the_current_one(self, client, db, auth_on):
        user = make_user(db, "grandma@example.com", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, user)

        refused = client.post("/api/auth/pin", json={"new_pin": "1357", "current_pin": "0000"})
        assert refused.status_code == 400
        assert "current PIN is not correct" in refused.json()["detail"]

        accepted = client.post(
            "/api/auth/pin", json={"new_pin": "1357", "current_pin": "2468"}
        )
        assert accepted.status_code == 200

    def test_staff_have_no_pin_to_set(self, client, db, auth_on):
        sign_in(client, make_user(db, "server@example.com", Role.STAFF))
        assert client.post("/api/auth/pin", json={"new_pin": "2468"}).status_code == 403


class TestPinRules:
    def test_a_pin_must_be_digits_of_a_sensible_length(self, db):
        user = make_user(db)
        for bad in ("12", "abcd", "123456789"):
            with pytest.raises(AuthError, match="4 to 8 digits"):
                set_pin(db, user, bad)

    def test_a_repeated_digit_pin_is_refused(self, db):
        user = make_user(db)
        with pytest.raises(AuthError, match="not all the same digit"):
            set_pin(db, user, "1111")

    def test_lockout_stops_a_pin_being_guessed(self, db):
        """Six digits is a million options; without a limit that is not enough."""
        user = make_user(db, pin_hash=hash_pin("2468"))

        for _ in range(settings.pin_max_attempts - 1):
            with pytest.raises(AuthError, match="not right"):
                check_pin(db, user, "0000")

        with pytest.raises(AuthError, match="Locked for"):
            check_pin(db, user, "0000")

        # Even the correct PIN is refused while the lockout stands.
        with pytest.raises(AuthError, match="Try again in"):
            check_pin(db, user, "2468")

    def test_a_correct_pin_clears_the_attempt_counter(self, db):
        user = make_user(db, pin_hash=hash_pin("2468"))
        with pytest.raises(AuthError):
            check_pin(db, user, "0000")
        assert user.pin_attempts == 1
        check_pin(db, user, "2468")
        assert user.pin_attempts == 0

    def test_hashes_are_salted_so_two_identical_pins_differ(self, db):
        assert hash_pin("2468") != hash_pin("2468")
        assert verify_pin("2468", hash_pin("2468")) is True
        assert verify_pin("1357", hash_pin("2468")) is False

    def test_a_malformed_hash_never_verifies(self):
        for stored in ("", "nonsense", "pbkdf2_sha256$notanumber$aa$bb"):
            assert verify_pin("2468", stored) is False


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
class TestTokens:
    def test_a_tampered_session_cookie_is_rejected(self, client, db, auth_on):
        user = make_user(db)
        sign_in(client, user)
        assert client.get("/api/insights/daily").status_code == 200

        good = client.cookies[SESSION_COOKIE]
        client.cookies.set(SESSION_COOKIE, good[:-4] + "AAAA")
        assert client.get("/api/insights/daily").status_code == 401

    def test_a_token_cannot_be_replayed_for_another_purpose(self, db):
        """An unlock token must not work as a session, or vice versa."""
        token = create_unlock_token(1)
        assert read_token(token, purpose="unlock") is not None
        assert read_token(token, purpose="session") is None

    def test_an_expired_token_is_rejected(self):
        token = create_token({"sub": "1"}, expires_in=timedelta(seconds=-10), purpose="session")
        assert read_token(token, purpose="session") is None

    def test_an_unlock_token_for_someone_else_does_not_unlock(self, client, db, auth_on):
        owner = make_user(db, "grandma@example.com", Role.OWNER, pin_hash=hash_pin("2468"))
        other = make_user(db, "other@example.com", Role.OWNER, pin_hash=hash_pin("1357"))
        sign_in(client, owner)
        client.cookies.set(UNLOCK_COOKIE, create_unlock_token(other.id))
        assert client.get("/api/reports/trial-balance").status_code == 423


# --------------------------------------------------------------------------- #
# Sign-in from verified claims
# --------------------------------------------------------------------------- #
class TestSignIn:
    def test_the_first_person_to_sign_in_becomes_the_owner(self, db):
        """Bootstraps the system without shipping a default admin password."""
        user = upsert_user_from_claims(
            db,
            {"sub": "g-1", "email": "grandma@example.com", "email_verified": True,
             "name": "Suriani"},
        )
        db.commit()
        assert user.role is Role.OWNER

    def test_everyone_after_the_first_starts_as_staff(self, db):
        upsert_user_from_claims(
            db, {"sub": "g-1", "email": "first@example.com", "email_verified": True}
        )
        db.commit()
        second = upsert_user_from_claims(
            db, {"sub": "g-2", "email": "second@example.com", "email_verified": True}
        )
        db.commit()
        assert second.role is Role.STAFF

    def test_an_unverified_email_is_refused(self, db):
        with pytest.raises(AuthError, match="not verified"):
            upsert_user_from_claims(
                db, {"sub": "g-1", "email": "spoof@example.com", "email_verified": False}
            )

    def test_claims_without_an_email_are_refused(self, db):
        with pytest.raises(AuthError, match="email address"):
            upsert_user_from_claims(db, {"sub": "g-1", "email_verified": True})

    def test_an_allowed_list_shuts_out_everyone_else(self, db, monkeypatch):
        monkeypatch.setattr(settings, "allowed_emails", ["grandma@example.com"])
        with pytest.raises(AuthError, match="not on the allowed list"):
            upsert_user_from_claims(
                db, {"sub": "g-9", "email": "stranger@example.com", "email_verified": True}
            )

    def test_configured_addresses_get_their_role(self, db, monkeypatch):
        monkeypatch.setattr(settings, "accountant_emails", ["Acct@Example.com"])
        # Matching is case-insensitive: nobody types their email consistently.
        assert role_for_email(db, "acct@example.com") is Role.ACCOUNTANT

    def test_signing_in_again_updates_the_profile_not_the_role(self, db):
        first = upsert_user_from_claims(
            db, {"sub": "g-1", "email": "grandma@example.com", "email_verified": True,
                 "name": "Suriani"},
        )
        db.commit()
        first.role = Role.ACCOUNTANT
        db.commit()

        again = upsert_user_from_claims(
            db, {"sub": "g-1", "email": "grandma@example.com", "email_verified": True,
                 "name": "Puan Suriani"},
        )
        db.commit()
        assert again.id == first.id
        assert again.name == "Puan Suriani"
        assert again.role is Role.ACCOUNTANT

    def test_a_changed_email_still_finds_the_same_account(self, db):
        """Google's subject id is stable; the email address is not."""
        first = upsert_user_from_claims(
            db, {"sub": "g-1", "email": "old@example.com", "email_verified": True}
        )
        db.commit()
        again = upsert_user_from_claims(
            db, {"sub": "g-1", "email": "new@example.com", "email_verified": True}
        )
        db.commit()
        assert again.id == first.id
        assert again.email == "new@example.com"

    def test_a_deactivated_account_cannot_sign_back_in(self, db):
        user = upsert_user_from_claims(
            db, {"sub": "g-1", "email": "gone@example.com", "email_verified": True}
        )
        user.is_active = False
        db.commit()
        with pytest.raises(AuthError, match="deactivated"):
            upsert_user_from_claims(
                db, {"sub": "g-1", "email": "gone@example.com", "email_verified": True}
            )


class TestOAuthFlow:
    def test_the_login_route_redirects_to_google_with_pkce(self, client, auth_on):
        response = client.get("/api/auth/google/login", follow_redirects=False)
        assert response.status_code == 307
        location = response.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "code_challenge_method=S256" in location
        assert "test-client-id" in location
        # The signed state is held in a cookie so nothing is stored server-side.
        assert "rs_oauth_state" in response.cookies

    def test_a_callback_whose_state_does_not_match_is_refused(self, client, auth_on):
        """This is the check that stops a forged callback signing someone in."""
        response = client.get(
            "/api/auth/google/callback?code=abc&state=forged", follow_redirects=False
        )
        assert response.status_code == 303
        assert "signin?error=" in response.headers["location"]
        assert SESSION_COOKIE not in response.cookies

    def test_a_cancelled_sign_in_bounces_back_with_a_message(self, client, auth_on):
        response = client.get(
            "/api/auth/google/callback?error=access_denied", follow_redirects=False
        )
        assert response.status_code == 303
        assert "cancelled" in response.headers["location"].lower()


class TestRoleManagement:
    def test_an_owner_can_promote_someone(self, client, db, auth_on):
        owner = make_user(db, "grandma@example.com", Role.OWNER)
        staff = make_user(db, "server@example.com", Role.STAFF)
        sign_in(client, owner)
        unlock(client, owner)

        response = client.patch(
            f"/api/auth/users/{staff.id}", json={"role": "ACCOUNTANT"}
        )
        assert response.status_code == 200
        assert response.json()["role"] == "ACCOUNTANT"

    def test_an_accountant_cannot_promote_anyone(self, client, db, auth_on):
        acct = make_user(db, "acct@example.com", Role.ACCOUNTANT)
        staff = make_user(db, "server@example.com", Role.STAFF)
        sign_in(client, acct)
        unlock(client, acct)
        assert (
            client.patch(f"/api/auth/users/{staff.id}", json={"role": "OWNER"}).status_code
            == 403
        )

    def test_the_owner_cannot_demote_themselves(self, client, db, auth_on):
        """Otherwise the last owner locks the restaurant out of its own books."""
        owner = make_user(db, "grandma@example.com", Role.OWNER)
        sign_in(client, owner)
        unlock(client, owner)
        response = client.patch(f"/api/auth/users/{owner.id}", json={"role": "STAFF"})
        assert response.status_code == 400
        assert "your own owner access" in response.json()["detail"]
