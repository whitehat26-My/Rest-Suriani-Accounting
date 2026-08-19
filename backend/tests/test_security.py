"""Security regression tests.

Each of these locks in a fix for a vulnerability found during the pre-deployment
penetration test, so the hole cannot silently reopen. Where a finding was about
concurrency (the PIN-lockout race) the property is asserted at the unit level;
the full concurrent exploit was verified separately against a running instance.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app import chart_of_accounts as coa
from app.config import Settings
from app.models import EventType, Role, User
from app.schemas import TransactionCreate
from app.security import hash_pin
from app.services import auth as auth_service
from app.services.auth import AuthError, check_pin
from app.services.ledger import LedgerError, build_legs, money

# Reuse the helpers/fixtures shape from test_auth via direct construction.
from tests.test_auth import make_user, sign_in, unlock  # noqa: F401


# --------------------------------------------------------------------------- #
# Amount bounds — oversized/malformed money must 422, never 500 or overflow
# --------------------------------------------------------------------------- #
class TestAmountBounds:
    @pytest.mark.parametrize("amount", ["1e30", "1e400", "9999999999999999", "1" * 40])
    def test_absurd_amounts_are_rejected_cleanly(self, client, amount):
        """These used to 500 (unhandled InvalidOperation) or overflow on Postgres."""
        r = client.post("/api/transactions/quick", json={"kind": "in", "amount": amount})
        assert r.status_code == 422, f"{amount} -> {r.status_code}"

    def test_money_helper_refuses_out_of_range(self):
        for bad in ["1e30", "NaN", "Infinity", "1" * 20]:
            with pytest.raises(LedgerError):
                money(bad)

    def test_a_sane_large_amount_still_posts(self, client):
        r = client.post("/api/transactions/quick", json={"kind": "in", "amount": "9999999999.99"})
        assert r.status_code == 201

    def test_component_and_tax_fields_are_bounded(self, client):
        r = client.post(
            "/api/transactions",
            json={"event_type": "CASH_SALE", "amount": "100", "tax_amount": "1e30"},
        )
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Ledger integrity — expense must hit an expense account
# --------------------------------------------------------------------------- #
class TestLedgerIntegrity:
    @pytest.mark.parametrize("code", ["1000", "4000", "3000"])  # Cash, Sales, Capital
    def test_expense_cannot_be_posted_to_a_non_expense_account(self, code):
        with pytest.raises(LedgerError, match="not an expense account"):
            build_legs(
                TransactionCreate(
                    event_type=EventType.EXPENSE_CASH,
                    amount=Decimal("10.00"),
                    expense_account_code=code,
                )
            )

    def test_a_real_expense_account_is_accepted(self):
        legs = build_legs(
            TransactionCreate(
                event_type=EventType.EXPENSE_CASH,
                amount=Decimal("10.00"),
                expense_account_code=coa.UTILITIES,
            )
        )
        assert any(l.account_code == coa.UTILITIES for l in legs)


# --------------------------------------------------------------------------- #
# Reversal guards
# --------------------------------------------------------------------------- #
class TestReversalGuards:
    def test_reverse_requires_a_finance_role(self, client, db, auth_on):
        owner = make_user(db, "o@test.my", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, owner)
        unlock(client, owner)
        txn = client.post(
            "/api/transactions",
            json={"event_type": "CASH_SALE", "amount": "100"},
        ).json()

        # Staff (signed in, no finance) must not be able to reverse it.
        staff = make_user(db, "s@test.my", Role.STAFF)
        client.cookies.clear()
        sign_in(client, staff)
        assert client.post(f"/api/transactions/{txn['id']}/reverse").status_code == 403

    def test_a_reversal_cannot_itself_be_reversed(self, client, db, auth_on):
        owner = make_user(db, "o@test.my", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, owner)
        unlock(client, owner)
        txn = client.post(
            "/api/transactions", json={"event_type": "CASH_SALE", "amount": "50"}
        ).json()
        rev = client.post(f"/api/transactions/{txn['id']}/reverse")
        assert rev.status_code == 201
        again = client.post(f"/api/transactions/{rev.json()['id']}/reverse")
        assert again.status_code == 400
        assert "reversal" in again.json()["detail"].lower()

    def test_payroll_transactions_cannot_be_reversed_from_here(self, client, db, auth_on):
        owner = make_user(db, "o@test.my", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, owner)
        unlock(client, owner)
        txn = client.post(
            "/api/transactions",
            json={
                "event_type": "PAYROLL_ACCRUAL",
                "amount": "100",
                "components": {"gross": "100", "net": "100"},
            },
        ).json()
        r = client.post(f"/api/transactions/{txn['id']}/reverse")
        assert r.status_code == 400
        assert "payroll" in r.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# STAFF must not see wage data
# --------------------------------------------------------------------------- #
class TestStaffCannotSeeWages:
    def test_recent_hides_wage_events_from_staff(self, client, db, auth_on):
        owner = make_user(db, "o@test.my", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, owner)
        unlock(client, owner)
        client.post(
            "/api/transactions",
            json={"event_type": "PAY_WAGES", "amount": "5000", "description": "salary"},
        )
        client.post("/api/transactions/quick", json={"kind": "in", "amount": "80"})

        staff = make_user(db, "s@test.my", Role.STAFF)
        client.cookies.clear()
        sign_in(client, staff)
        body = client.get("/api/transactions/recent").text
        assert "PAY_WAGES" not in body
        assert "salary" not in body.lower()
        assert "6000" not in body  # the Salaries & Wages account code

    def test_owner_still_sees_wages(self, client, db, auth_on):
        owner = make_user(db, "o@test.my", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, owner)
        unlock(client, owner)
        client.post(
            "/api/transactions",
            json={"event_type": "PAY_WAGES", "amount": "5000"},
        )
        assert "PAY_WAGES" in client.get("/api/transactions/recent").text


# --------------------------------------------------------------------------- #
# Receipt access + upload validation
# --------------------------------------------------------------------------- #
class TestReceiptAccess:
    PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
        b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def test_staff_cannot_read_a_receipt(self, client, db, auth_on):
        owner = make_user(db, "o@test.my", Role.OWNER, pin_hash=hash_pin("2468"))
        sign_in(client, owner)
        unlock(client, owner)
        up = client.post(
            "/api/uploads", files={"file": ("r.png", self.PNG, "image/png")}
        ).json()

        staff = make_user(db, "s@test.my", Role.STAFF)
        client.cookies.clear()
        sign_in(client, staff)
        # Staff may still upload (daily-screen action)...
        assert (
            client.post(
                "/api/uploads", files={"file": ("r.png", self.PNG, "image/png")}
            ).status_code
            == 201
        )
        # ...but not read finance receipts back.
        assert client.get(up["url"]).status_code == 403

    def test_content_type_spoof_is_rejected(self, client):
        # Bytes that are not a PNG, declared as image/png.
        r = client.post(
            "/api/uploads",
            files={"file": ("x.png", b"<html>not a png</html>", "image/png")},
        )
        assert r.status_code == 400
        assert "do not match" in r.json()["detail"]

    def test_served_receipt_carries_nosniff(self, client):
        up = client.post(
            "/api/uploads", files={"file": ("r.png", self.PNG, "image/png")}
        ).json()
        served = client.get(up["url"])
        assert served.status_code == 200
        assert served.headers.get("x-content-type-options") == "nosniff"
        assert served.headers.get("content-disposition") == "attachment"


# --------------------------------------------------------------------------- #
# List caps
# --------------------------------------------------------------------------- #
class TestListCaps:
    def test_stock_count_list_is_capped(self, client):
        counts = [{"item_id": 1, "counted_quantity": "1"} for _ in range(600)]
        r = client.post("/api/inventory/count", json={"counts": counts})
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# PIN lockout contract (the concurrent exploit was verified live)
# --------------------------------------------------------------------------- #
class TestPinLockout:
    def test_lockout_trips_at_the_limit_and_blocks_even_the_right_pin(self, db):
        user = make_user(db, pin_hash=hash_pin("2468"))
        for _ in range(4):
            with pytest.raises(AuthError, match="not right"):
                check_pin(db, user, "0000")
        with pytest.raises(AuthError, match="Locked for"):
            check_pin(db, user, "0000")
        # Correct PIN is refused while locked.
        with pytest.raises(AuthError, match="Try again in"):
            check_pin(db, user, "2468")

    def test_a_correct_pin_before_the_limit_resets_the_counter(self, db):
        user = make_user(db, pin_hash=hash_pin("2468"))
        with pytest.raises(AuthError):
            check_pin(db, user, "0000")
        check_pin(db, user, "2468")  # correct
        db.refresh(user)
        assert user.pin_attempts == 0

    def test_the_lockout_window_reopens_after_it_expires(self, db):
        user = make_user(db, pin_hash=hash_pin("2468"))
        for _ in range(5):
            with pytest.raises(AuthError):
                check_pin(db, user, "0000")
        # Force the lock into the past.
        db.refresh(user)
        user.pin_locked_until = auth_service._now() - timedelta(minutes=1)
        db.commit()
        # A correct PIN now works again (fresh window).
        check_pin(db, user, "2468")
        db.refresh(user)
        assert user.pin_attempts == 0


# --------------------------------------------------------------------------- #
# Deployment configuration must fail closed
# --------------------------------------------------------------------------- #
class TestDeploymentValidation:
    def test_production_requires_full_configuration(self):
        s = Settings(
            environment="production",
            secret_key="",
            google_client_id="x.apps.googleusercontent.com",
            google_client_secret="y",
            owner_emails=[],
            cookie_secure=False,
        )
        problems = s.validate_deployment()
        assert any("SECRET_KEY" in p for p in problems)
        assert any("OWNER_EMAILS" in p for p in problems)
        assert any("COOKIE_SECURE" in p for p in problems)

    def test_a_half_configured_google_client_is_always_fatal(self):
        s = Settings(google_client_id="x.apps.googleusercontent.com", google_client_secret="")
        assert any("Exactly one" in p for p in s.validate_deployment())
        assert s.auth_enabled is False

    def test_a_fully_configured_production_setup_is_accepted(self):
        s = Settings(
            environment="production",
            secret_key="a-sufficiently-long-secret-key-value-1234567890",
            google_client_id="x.apps.googleusercontent.com",
            google_client_secret="y",
            owner_emails=["owner@shop.my"],
            cookie_secure=True,
            cors_origins=["https://shop.my"],
        )
        assert s.validate_deployment() == []
        assert s.auth_enabled is True


# --------------------------------------------------------------------------- #
# Security headers
# --------------------------------------------------------------------------- #
class TestSecurityHeaders:
    def test_baseline_headers_present_on_api(self, client):
        r = client.get("/api/health")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        assert "content-security-policy" in r.headers
        assert r.headers.get("cache-control") == "no-store"
