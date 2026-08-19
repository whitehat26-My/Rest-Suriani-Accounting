"""End-to-end tests through the HTTP layer."""
from __future__ import annotations

from datetime import date

import pytest


class TestSystem:
    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_config_exposes_the_spending_buttons(self, client):
        payload = client.get("/api/config").json()
        slugs = {c["slug"] for c in payload["spending_categories"]}
        assert {"ingredients", "wages", "rent", "utilities"} <= slugs
        assert all(c["emoji"] for c in payload["spending_categories"])

    def test_the_chart_of_accounts_is_loaded_on_startup(self, client):
        accounts = client.get("/api/accounts").json()
        codes = {a["code"] for a in accounts}
        assert {"1000", "1200", "4000", "5000", "6000"} <= codes
        assert all(a["friendly_name"] for a in accounts)


class TestGrandmaFlow:
    """The complete owner journey, using only the endpoints her screen calls."""

    def test_money_in_creates_a_balanced_sale(self, client):
        response = client.post(
            "/api/transactions/quick",
            json={"kind": "in", "amount": "150.00", "method": "CASH"},
        )
        assert response.status_code == 201
        body = response.json()

        assert body["direction"] == "in"
        assert body["event_type"] == "CASH_SALE"
        assert "Money in" in body["friendly_summary"]

        debits = sum(float(e["amount"]) for e in body["entries"] if e["side"] == "DEBIT")
        credits = sum(float(e["amount"]) for e in body["entries"] if e["side"] == "CREDIT")
        assert debits == credits == 150.00

    def test_money_out_for_food_debits_inventory(self, client):
        body = client.post(
            "/api/transactions/quick",
            json={
                "kind": "out",
                "amount": "50.00",
                "category": "ingredients",
                "counterparty": "Pasar Borong",
            },
        ).json()
        accounts = {e["account_code"]: e["side"] for e in body["entries"]}
        assert accounts["1200"] == "DEBIT"   # Inventory
        assert accounts["1000"] == "CREDIT"  # Cash on hand

    def test_the_daily_screen_summarises_the_day(self, client):
        client.post("/api/transactions/quick", json={"kind": "in", "amount": "300.00"})
        client.post(
            "/api/transactions/quick",
            json={"kind": "out", "amount": "120.00", "category": "ingredients"},
        )
        summary = client.get("/api/insights/daily").json()

        assert summary["money_in"] == "300.00"
        assert summary["money_out"] == "120.00"
        assert summary["net"] == "180.00"
        assert summary["verdict"] == "good"
        assert summary["transaction_count"] == 2
        assert len(summary["recent"]) == 2

    def test_a_bad_day_is_flagged_in_plain_words(self, client):
        client.post("/api/transactions/quick", json={"kind": "in", "amount": "50.00"})
        client.post(
            "/api/transactions/quick",
            json={"kind": "out", "amount": "400.00", "category": "rent"},
        )
        summary = client.get("/api/insights/daily").json()
        assert summary["verdict"] == "bad"
        assert "spent" in summary["verdict_message"].lower()
        assert "debit" not in summary["verdict_message"].lower()

    def test_an_empty_day_invites_the_first_entry(self, client):
        summary = client.get("/api/insights/daily").json()
        assert summary["transaction_count"] == 0
        assert "green button" in summary["verdict_message"]

    def test_speaking_a_purchase_then_confirming_it(self, client):
        """Voice input never writes on its own; the owner confirms first."""
        parsed = client.post(
            "/api/transactions/parse", json={"text": "Bought RM50 of chicken"}
        ).json()
        assert parsed["understood"] is True
        assert parsed["kind"] == "out"

        created = client.post(
            "/api/transactions/quick",
            json={
                "kind": parsed["kind"],
                "amount": parsed["amount"],
                "category": parsed["category"],
                "method": parsed["method"],
                "raw_input": parsed["original_text"],
                "source": "VOICE",
            },
        )
        assert created.status_code == 201
        assert created.json()["raw_input"] == "Bought RM50 of chicken"
        assert created.json()["source"] == "VOICE"


class TestAccountantFlow:
    def test_the_preview_shows_the_double_entry_without_saving(self, client):
        """This is how the automation explains itself to the student."""
        legs = client.post(
            "/api/transactions/preview",
            json={"event_type": "CASH_SALE", "amount": "106.00", "tax_amount": "6.00"},
        ).json()
        by_account = {leg["account_code"]: leg for leg in legs}
        assert by_account["1000"]["side"] == "DEBIT"
        assert by_account["4000"]["amount"] == "100.00"
        assert by_account["2200"]["amount"] == "6.00"
        assert client.get("/api/transactions").json()["total"] == 0

    def test_the_three_statements_are_produced(self, client):
        client.post("/api/transactions/quick", json={"kind": "in", "amount": "1000.00"})
        client.post(
            "/api/transactions/quick",
            json={"kind": "out", "amount": "300.00", "category": "rent"},
        )

        profit_loss = client.get("/api/reports/income-statement?period=month").json()
        assert profit_loss["revenue"] == "1000.00"
        assert profit_loss["net_profit"] == "700.00"

        sheet = client.get("/api/reports/balance-sheet").json()
        assert sheet["balances"] is True

        cash_flow = client.get("/api/reports/cash-flow?period=month").json()
        assert cash_flow["reconciles"] is True

    def test_the_trial_balance_proves_the_ledger_is_intact(self, client):
        client.post("/api/transactions/quick", json={"kind": "in", "amount": "500.00"})
        report = client.get("/api/reports/trial-balance").json()
        assert report["balanced"] is True
        assert report["total_debit"] == report["total_credit"]

    def test_the_dashboard_returns_everything_in_one_call(self, client):
        client.post("/api/transactions/quick", json={"kind": "in", "amount": "800.00"})
        dashboard = client.get("/api/insights/dashboard?period=month").json()
        assert {
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "evaluation",
            "expense_breakdown",
            "revenue_by_day",
        } <= set(dashboard)
        assert 0 <= dashboard["evaluation"]["health_score"] <= 100
        assert dashboard["evaluation"]["suggestions"]

    def test_the_general_ledger_shows_a_running_balance(self, client):
        for amount in ("100.00", "50.00"):
            client.post("/api/transactions/quick", json={"kind": "in", "amount": amount})
        ledger = client.get("/api/accounts/1000/ledger").json()
        assert [row["balance"] for row in ledger["rows"]] == ["100.00", "150.00"]
        assert ledger["closing_balance"] == "150.00"

    def test_evaluation_of_an_empty_period_explains_itself(self, client):
        evaluation = client.get("/api/insights/evaluation?period=month").json()
        assert evaluation["suggestions"][0]["severity"] == "info"
        assert "no sales" in evaluation["suggestions"][0]["message"].lower()


class TestInventoryApi:
    @pytest.fixture()
    def item_id(self, client) -> int:
        response = client.post(
            "/api/inventory",
            json={
                "name": "Chicken",
                "local_name": "ayam",
                "unit": "kg",
                "par_level": "40",
                "reorder_level": "12",
                "opening_quantity": "20",
                "opening_unit_cost": "10.00",
            },
        )
        assert response.status_code == 201
        return response.json()["id"]

    def test_creating_an_item_reports_its_colour_band(self, client, item_id):
        item = client.get(f"/api/inventory/{item_id}").json()
        assert item["status"] == "ok"        # 20 of a par level of 40, reorder at 12
        assert item["stock_value"] == "200.00"
        assert item["stock_ratio"] == 0.5

    def test_duplicate_names_are_refused(self, client, item_id):
        response = client.post("/api/inventory", json={"name": "Chicken"})
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_buying_stock_updates_quantity_and_average_cost(self, client, item_id):
        client.post(
            "/api/inventory/purchase",
            json={"item_id": item_id, "quantity": "20", "total_cost": "280.00"},
        )
        item = client.get(f"/api/inventory/{item_id}").json()
        assert item["quantity_on_hand"] == "40.000"
        assert item["unit_cost"] == "12.0000"
        assert item["status"] == "ok"

    def test_counting_stock_creates_the_cost_of_goods_sold(self, client, item_id):
        results = client.post(
            "/api/inventory/count",
            json={"counts": [{"item_id": item_id, "counted_quantity": "14"}]},
        ).json()
        assert results[0]["variance"] == "-6.000"

        accounts = {a["code"]: a["balance"] for a in client.get("/api/accounts").json()}
        assert accounts["5000"] == "60.00"   # COGS
        assert accounts["1200"] == "140.00"  # Inventory

    def test_the_stock_card_lists_every_movement(self, client, item_id):
        client.post(
            "/api/inventory/purchase",
            json={"item_id": item_id, "quantity": "5", "total_cost": "55.00"},
        )
        movements = client.get(f"/api/inventory/{item_id}/movements").json()
        assert [m["movement_type"] for m in movements] == ["PURCHASE", "OPENING"]

    def test_depletion_moves_an_item_into_the_low_stock_list(self, client, item_id):
        """Nothing is flagged until stock actually runs down."""
        assert client.get("/api/inventory?low_only=true").json() == []

        client.post(
            "/api/inventory/count",
            json={"counts": [{"item_id": item_id, "counted_quantity": "8"}]},
        )
        flagged = client.get("/api/inventory?low_only=true").json()
        assert [item["name"] for item in flagged] == ["Chicken"]
        assert flagged[0]["status"] == "low"

        client.post(
            "/api/inventory/count",
            json={"counts": [{"item_id": item_id, "counted_quantity": "1"}]},
        )
        assert client.get(f"/api/inventory/{item_id}").json()["status"] == "critical"


class TestErrorHandling:
    def test_a_negative_amount_is_rejected(self, client):
        response = client.post(
            "/api/transactions/quick", json={"kind": "in", "amount": "-5.00"}
        )
        assert response.status_code == 422

    def test_an_unknown_direction_is_rejected(self, client):
        response = client.post(
            "/api/transactions/quick", json={"kind": "sideways", "amount": "5.00"}
        )
        assert response.status_code == 422

    def test_a_missing_transaction_returns_404(self, client):
        assert client.get("/api/transactions/999999").status_code == 404

    def test_buying_stock_for_an_unknown_item_is_refused(self, client):
        response = client.post(
            "/api/inventory/purchase",
            json={"item_id": 4242, "quantity": "1", "total_cost": "1.00"},
        )
        assert response.status_code == 400


class TestReversal:
    def test_reversing_restores_the_balances_and_keeps_both_records(self, client):
        created = client.post(
            "/api/transactions/quick", json={"kind": "in", "amount": "200.00"}
        ).json()

        reversal = client.post(
            f"/api/transactions/{created['id']}/reverse", params={"reason": "Wrong amount"}
        )
        assert reversal.status_code == 201

        accounts = {a["code"]: a["balance"] for a in client.get("/api/accounts").json()}
        assert accounts["1000"] == "0.00"
        assert client.get("/api/transactions").json()["total"] == 2
        assert client.get(f"/api/transactions/{created['id']}").json()["is_reversed"] is True

    def test_double_reversal_is_refused(self, client):
        created = client.post(
            "/api/transactions/quick", json={"kind": "in", "amount": "10.00"}
        ).json()
        client.post(f"/api/transactions/{created['id']}/reverse")
        assert client.post(f"/api/transactions/{created['id']}/reverse").status_code == 400


class TestReceiptUpload:
    def test_a_photo_can_be_attached_to_a_transaction(self, client):
        # A minimal valid PNG.
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080600000"
            "01f15c4890000000a49444154789c6300010000050001"
            "0d0a2db40000000049454e44ae426082"
        )
        upload = client.post(
            "/api/uploads", files={"file": ("receipt.png", png, "image/png")}
        )
        assert upload.status_code == 201
        attachment_id = upload.json()["id"]

        created = client.post(
            "/api/transactions/quick",
            json={
                "kind": "out",
                "amount": "50.00",
                "category": "ingredients",
                "attachment_ids": [attachment_id],
                "source": "RECEIPT_PHOTO",
            },
        ).json()
        assert len(created["attachments"]) == 1
        assert created["attachments"][0]["url"].endswith("/file")

        stored = client.get(created["attachments"][0]["url"])
        assert stored.status_code == 200
        assert stored.content == png

    def test_a_non_image_is_refused(self, client):
        response = client.post(
            "/api/uploads", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]
