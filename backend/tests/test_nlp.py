"""The voice parser: what the owner says versus what the system understands."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import PaymentMethod
from app.schemas import InventoryItemCreate
from app.services.inventory import create_item
from app.services.nlp import parse


@pytest.fixture()
def stocked(db):
    for name, local in (("Chicken", "ayam"), ("Rice", "beras"), ("Cooking Oil", "minyak masak")):
        create_item(db, InventoryItemCreate(name=name, local_name=local, unit="kg"))
    db.commit()
    return db


class TestTheHeadlineExample:
    def test_bought_rm50_of_chicken(self, stocked):
        """The exact phrase the system was designed around."""
        result = parse(stocked, "Bought RM50 of chicken")
        assert result.understood is True
        assert result.kind == "out"
        assert result.amount == Decimal("50.00")
        assert result.category == "ingredients"
        assert result.inventory_item_name == "Chicken"
        assert "RM50.00" in result.confirmation


class TestAmounts:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Bought RM50 of chicken", "50.00"),
            ("bought rm 12.50 of rice", "12.50"),
            ("Beli ayam 35 ringgit", "35.00"),
            ("Sold 120 today", "120.00"),
            ("paid RM1200 wages", "1200.00"),
        ],
    )
    def test_amount_extraction(self, stocked, text, expected):
        assert parse(stocked, text).amount == Decimal(expected)

    def test_a_quantity_is_not_mistaken_for_a_price(self, stocked):
        """"2 kg chicken 35" means RM35, not RM2."""
        result = parse(stocked, "beli 2 kg ayam 35")
        assert result.amount == Decimal("35.00")
        assert result.quantity == Decimal("2")

    def test_a_sentence_with_no_amount_asks_for_one(self, stocked):
        result = parse(stocked, "bought some chicken")
        assert result.understood is False
        assert "amount" in result.confirmation.lower()


class TestDirection:
    @pytest.mark.parametrize(
        "text", ["Sold RM120 today", "Jual RM90 tunai", "Received RM300 from catering"]
    )
    def test_money_in(self, stocked, text):
        assert parse(stocked, text).kind == "in"

    @pytest.mark.parametrize(
        "text", ["Bought RM50 chicken", "Bayar gaji RM800", "Paid RM200 for gas"]
    )
    def test_money_out(self, stocked, text):
        assert parse(stocked, text).kind == "out"

    def test_money_in_needs_no_category(self, stocked):
        result = parse(stocked, "Sold RM250 cash")
        assert result.kind == "in"
        assert result.category is None


class TestCategories:
    @pytest.mark.parametrize(
        ("text", "category"),
        [
            ("Bought RM50 of chicken", "ingredients"),
            ("Beli sayur RM30", "ingredients"),
            ("Bayar gaji pekerja RM800", "wages"),
            ("Paid rent RM2000", "rent"),
            ("Paid RM120 for electricity", "utilities"),
            ("Beli gas RM35", "gas"),
            ("Bought RM60 plastic containers", "supplies"),
            ("Paid RM90 to fix the fridge", "repairs"),
            ("Paid RM50 petrol", "transport"),
            ("Paid RM100 for Facebook ads", "marketing"),
            ("Renew licence RM250", "licenses"),
        ],
    )
    def test_category_detection(self, stocked, text, category):
        assert parse(stocked, text).category == category

    def test_petrol_beats_cooking_oil(self, stocked):
        """Both are "minyak" in Malay, so word order and specificity matter."""
        assert parse(stocked, "Paid RM60 petrol for the van").category == "transport"
        assert parse(stocked, "Beli minyak masak RM40").category == "ingredients"


class TestPaymentMethod:
    @pytest.mark.parametrize(
        ("text", "method"),
        [
            ("Sold RM120 cash", PaymentMethod.CASH),
            ("Sold RM120 by card", PaymentMethod.CARD),
            ("Sold RM120 touch n go", PaymentMethod.EWALLET),
            ("Paid RM500 bank transfer", PaymentMethod.BANK),
            ("Beli ayam RM50 hutang", PaymentMethod.CREDIT),
        ],
    )
    def test_method_detection(self, stocked, text, method):
        assert parse(stocked, text).method is method

    def test_cash_is_the_default(self, stocked):
        assert parse(stocked, "Sold RM90").method is PaymentMethod.CASH


class TestInventoryMatching:
    def test_the_named_ingredient_is_linked(self, stocked):
        result = parse(stocked, "Beli beras 10 kg RM32")
        assert result.inventory_item_name == "Rice"
        assert result.quantity == Decimal("10")

    def test_the_longest_matching_name_wins(self, stocked):
        """"cooking oil" must not lose to a shorter partial match."""
        result = parse(stocked, "Bought RM45 cooking oil")
        assert result.inventory_item_name == "Cooking Oil"

    def test_an_unknown_ingredient_still_categorises(self, stocked):
        result = parse(stocked, "Bought RM25 of prawns")
        assert result.category == "ingredients"
        assert result.inventory_item_id is None


class TestConfirmation:
    def test_it_reads_back_a_full_sentence(self, stocked):
        result = parse(stocked, "Beli ayam 2 kg RM35 tunai")
        assert result.confirmation.startswith("Money OUT")
        assert "RM35.00" in result.confirmation
        assert "chicken" in result.confirmation.lower()
        assert result.confirmation.endswith("Is that right?")

    def test_money_in_reads_back_differently(self, stocked):
        result = parse(stocked, "Sold RM120 by card")
        assert result.confirmation.startswith("Money IN")
        assert "by card" in result.confirmation

    def test_credit_is_spelled_out_in_plain_words(self, stocked):
        """"On credit" means nothing to the owner; "to pay later" does."""
        result = parse(stocked, "Beli ayam RM50 hutang")
        assert "pay later" in result.confirmation

    def test_the_original_words_are_always_kept(self, stocked):
        spoken = "Bought RM50 of chicken"
        assert parse(stocked, spoken).original_text == spoken


class TestConfidence:
    def test_a_clear_sentence_scores_high(self, stocked):
        assert parse(stocked, "Bought RM50 of chicken cash").confidence > 0.6

    def test_a_vague_sentence_scores_lower(self, stocked):
        clear = parse(stocked, "Bought RM50 of chicken cash").confidence
        vague = parse(stocked, "RM50").confidence
        assert vague < clear
