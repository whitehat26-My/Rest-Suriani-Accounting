"""The invariants that must never break: every entry balances, always."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import chart_of_accounts as coa
from app.models import EntrySide, EventType, PaymentMethod
from app.schemas import QuickEntry, TransactionCreate
from app.services.ledger import (
    EVENT_DIRECTION,
    EVENT_FRIENDLY,
    POSTING_RULES,
    LedgerError,
    account_balances,
    build_legs,
    post_transaction,
    quick_entry_to_transaction,
    reverse_transaction,
)


def legs_by_account(legs) -> dict[str, tuple[str, Decimal]]:
    return {leg.account_code: (leg.side.value, leg.amount) for leg in legs}


class TestPostingRules:
    def test_every_event_type_has_a_rule(self):
        """A business event with no rule would silently fail to post."""
        missing = set(EventType) - set(POSTING_RULES)
        assert not missing, f"Event types without a posting rule: {missing}"

    def test_every_event_has_a_direction_and_a_friendly_name(self):
        """Grandma Mode cannot render an event it has no plain words for."""
        assert set(EventType) - set(EVENT_DIRECTION) == set()
        assert set(EventType) - set(EVENT_FRIENDLY) == set()

    @pytest.mark.parametrize("event_type", list(EventType))
    def test_every_rule_produces_a_balanced_entry(self, event_type):
        """The core guarantee: debits equal credits for every event type."""
        legs = build_legs(
            TransactionCreate(
                event_type=event_type,
                amount=Decimal("500.00"),
                expense_account_code=coa.UTILITIES,
                interest_amount=Decimal("25.00"),
                tax_amount=Decimal("0.00"),
            )
        )
        debits = sum(l.amount for l in legs if l.side is EntrySide.DEBIT)
        credits = sum(l.amount for l in legs if l.side is EntrySide.CREDIT)
        assert debits == credits == Decimal("500.00") or debits == credits
        assert len(legs) >= 2
        assert all(leg.amount > 0 for leg in legs)


class TestSmartPairing:
    def test_cash_sale_debits_cash_and_credits_sales(self):
        legs = legs_by_account(
            build_legs(
                TransactionCreate(
                    event_type=EventType.CASH_SALE,
                    amount=Decimal("120.00"),
                    payment_method=PaymentMethod.CASH,
                )
            )
        )
        assert legs[coa.CASH_ON_HAND] == ("DEBIT", Decimal("120.00"))
        assert legs[coa.SALES] == ("CREDIT", Decimal("120.00"))

    def test_cash_sale_with_tax_splits_out_sst(self):
        """Tax collected belongs to the government, not to revenue."""
        legs = legs_by_account(
            build_legs(
                TransactionCreate(
                    event_type=EventType.CASH_SALE,
                    amount=Decimal("106.00"),
                    tax_amount=Decimal("6.00"),
                )
            )
        )
        assert legs[coa.CASH_ON_HAND] == ("DEBIT", Decimal("106.00"))
        assert legs[coa.SALES] == ("CREDIT", Decimal("100.00"))
        assert legs[coa.SST_PAYABLE] == ("CREDIT", Decimal("6.00"))

    def test_card_sale_records_the_processor_fee_as_an_expense(self):
        legs = legs_by_account(
            build_legs(
                TransactionCreate(
                    event_type=EventType.CARD_SALE,
                    amount=Decimal("200.00"),
                    fee_amount=Decimal("3.60"),
                )
            )
        )
        assert legs[coa.BANK] == ("DEBIT", Decimal("196.40"))
        assert legs[coa.BANK_FEES] == ("DEBIT", Decimal("3.60"))
        assert legs[coa.SALES] == ("CREDIT", Decimal("200.00"))

    def test_card_sale_settles_to_bank_not_till(self):
        """Card money never reaches the cash drawer."""
        legs = legs_by_account(
            build_legs(
                TransactionCreate(event_type=EventType.CARD_SALE, amount=Decimal("50.00"))
            )
        )
        assert coa.CASH_ON_HAND not in legs
        assert coa.BANK in legs

    def test_buying_food_is_an_asset_not_an_expense(self):
        """The classic mistake this system is built to prevent."""
        legs = legs_by_account(
            build_legs(
                TransactionCreate(
                    event_type=EventType.PURCHASE_INVENTORY_CASH, amount=Decimal("50.00")
                )
            )
        )
        assert legs[coa.INVENTORY] == ("DEBIT", Decimal("50.00"))
        assert legs[coa.CASH_ON_HAND] == ("CREDIT", Decimal("50.00"))
        assert coa.COGS not in legs

    def test_owner_drawings_reduce_equity_rather_than_profit(self):
        legs = legs_by_account(
            build_legs(
                TransactionCreate(
                    event_type=EventType.OWNER_DRAWINGS, amount=Decimal("300.00")
                )
            )
        )
        assert legs[coa.OWNER_DRAWINGS] == ("DEBIT", Decimal("300.00"))
        assert coa.WAGES not in legs

    def test_loan_repayment_splits_principal_from_interest(self):
        legs = legs_by_account(
            build_legs(
                TransactionCreate(
                    event_type=EventType.LOAN_REPAYMENT,
                    amount=Decimal("720.00"),
                    interest_amount=Decimal("62.00"),
                )
            )
        )
        assert legs[coa.LOAN_PAYABLE] == ("DEBIT", Decimal("658.00"))
        assert legs[coa.INTEREST_EXPENSE] == ("DEBIT", Decimal("62.00"))
        assert legs[coa.BANK] == ("CREDIT", Decimal("720.00"))

    def test_sale_with_known_cost_recognises_cogs_in_the_same_entry(self):
        """Matching principle: the cost of the food goes with the sale."""
        legs = build_legs(
            TransactionCreate(
                event_type=EventType.CASH_SALE,
                amount=Decimal("100.00"),
                cogs_amount=Decimal("32.00"),
            )
        )
        mapping = legs_by_account(legs)
        assert mapping[coa.COGS] == ("DEBIT", Decimal("32.00"))
        assert mapping[coa.INVENTORY] == ("CREDIT", Decimal("32.00"))
        debits = sum(l.amount for l in legs if l.side is EntrySide.DEBIT)
        credits = sum(l.amount for l in legs if l.side is EntrySide.CREDIT)
        assert debits == credits


class TestQuickEntryTranslation:
    """Grandma taps a picture; the backend must pick the right accounts."""

    def test_money_in_cash_becomes_a_cash_sale(self):
        request = quick_entry_to_transaction(
            QuickEntry(kind="in", amount=Decimal("85.00"), method=PaymentMethod.CASH)
        )
        assert request.event_type is EventType.CASH_SALE

    def test_money_in_on_credit_becomes_a_receivable(self):
        request = quick_entry_to_transaction(
            QuickEntry(kind="in", amount=Decimal("400.00"), method=PaymentMethod.CREDIT)
        )
        assert request.event_type is EventType.CREDIT_SALE

    def test_money_out_for_ingredients_becomes_a_stock_purchase(self):
        request = quick_entry_to_transaction(
            QuickEntry(kind="out", amount=Decimal("50.00"), category="ingredients")
        )
        assert request.event_type is EventType.PURCHASE_INVENTORY_CASH

    def test_money_out_for_ingredients_on_credit_creates_a_payable(self):
        request = quick_entry_to_transaction(
            QuickEntry(
                kind="out",
                amount=Decimal("50.00"),
                category="ingredients",
                method=PaymentMethod.CREDIT,
            )
        )
        assert request.event_type is EventType.PURCHASE_INVENTORY_CREDIT

    def test_money_out_for_wages_uses_the_wages_account(self):
        request = quick_entry_to_transaction(
            QuickEntry(kind="out", amount=Decimal("800.00"), category="wages")
        )
        assert request.event_type is EventType.PAY_WAGES

    def test_unknown_category_falls_back_to_other_expense(self):
        """An owner tapping something unexpected must never break the books."""
        request = quick_entry_to_transaction(
            QuickEntry(kind="out", amount=Decimal("30.00"), category="banana-boat")
        )
        assert request.event_type is EventType.EXPENSE_CASH
        assert request.expense_account_code == coa.OTHER_EXPENSE

    def test_gas_and_electricity_share_the_utilities_account(self):
        for category in ("gas", "utilities"):
            request = quick_entry_to_transaction(
                QuickEntry(kind="out", amount=Decimal("60.00"), category=category)
            )
            assert request.expense_account_code == coa.UTILITIES


class TestValidation:
    def test_tax_larger_than_the_sale_is_rejected(self):
        with pytest.raises(LedgerError, match="Tax cannot be larger"):
            build_legs(
                TransactionCreate(
                    event_type=EventType.CASH_SALE,
                    amount=Decimal("50.00"),
                    tax_amount=Decimal("60.00"),
                )
            )

    def test_interest_larger_than_the_instalment_is_rejected(self):
        with pytest.raises(LedgerError, match="Interest portion"):
            build_legs(
                TransactionCreate(
                    event_type=EventType.LOAN_REPAYMENT,
                    amount=Decimal("100.00"),
                    interest_amount=Decimal("150.00"),
                )
            )


class TestPersistence:
    def test_posting_writes_balanced_entries_and_moves_the_balances(self, db):
        txn = post_transaction(
            db,
            TransactionCreate(event_type=EventType.CASH_SALE, amount=Decimal("250.00")),
        )
        db.commit()
        assert txn.is_balanced
        assert txn.reference.startswith("TXN-")

        balances = account_balances(db)
        assert balances[coa.CASH_ON_HAND] == Decimal("250.00")
        assert balances[coa.SALES] == Decimal("250.00")

    def test_references_are_sequential(self, db):
        references = []
        for _ in range(3):
            txn = post_transaction(
                db,
                TransactionCreate(event_type=EventType.CASH_SALE, amount=Decimal("10.00")),
            )
            references.append(txn.reference)
        db.commit()
        assert references == sorted(references)
        assert len(set(references)) == 3

    def test_reversal_cancels_the_original_without_deleting_it(self, db):
        """An accountant needs the mistake and the correction both on record."""
        txn = post_transaction(
            db,
            TransactionCreate(event_type=EventType.CASH_SALE, amount=Decimal("99.00")),
        )
        db.commit()
        reversal = reverse_transaction(db, txn, reason="Entered twice")
        db.commit()

        assert txn.is_reversed is True
        assert reversal.reverses_id == txn.id
        balances = account_balances(db)
        assert balances[coa.CASH_ON_HAND] == Decimal("0.00")
        assert balances[coa.SALES] == Decimal("0.00")

    def test_a_transaction_cannot_be_reversed_twice(self, db):
        txn = post_transaction(
            db, TransactionCreate(event_type=EventType.CASH_SALE, amount=Decimal("5.00"))
        )
        db.commit()
        reverse_transaction(db, txn)
        db.commit()
        with pytest.raises(LedgerError, match="already been reversed"):
            reverse_transaction(db, txn)

    def test_balances_respect_the_date_window(self, db):
        today = date.today()
        post_transaction(
            db,
            TransactionCreate(
                event_type=EventType.CASH_SALE,
                amount=Decimal("100.00"),
                txn_date=today - timedelta(days=10),
            ),
        )
        post_transaction(
            db,
            TransactionCreate(
                event_type=EventType.CASH_SALE, amount=Decimal("40.00"), txn_date=today
            ),
        )
        db.commit()
        window = account_balances(db, start=today, end=today)
        assert window[coa.SALES] == Decimal("40.00")
        assert account_balances(db)[coa.SALES] == Decimal("140.00")
