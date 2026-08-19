"""Inventory valuation and the link from stock to Cost of Goods Sold."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app import chart_of_accounts as coa
from app.models import MovementType
from app.schemas import (
    InventoryItemCreate,
    StockCountCreate,
    StockCountEntry,
    StockPurchase,
)
from app.services.inventory import (
    InventoryError,
    consume_stock,
    create_item,
    low_stock_items,
    purchase_stock,
    record_stock_count,
    total_inventory_value,
)
from app.services.ledger import account_balances


@pytest.fixture()
def chicken(db):
    item = create_item(
        db,
        InventoryItemCreate(
            name="Chicken",
            local_name="ayam",
            unit="kg",
            par_level=Decimal("40"),
            reorder_level=Decimal("12"),
            opening_quantity=Decimal("10"),
            opening_unit_cost=Decimal("10.00"),
        ),
    )
    db.commit()
    return item


class TestValuation:
    def test_opening_stock_enters_as_capital_not_as_a_purchase(self, db, chicken):
        """The owner already paid for it, so it cannot be this period's expense."""
        balances = account_balances(db)
        assert balances[coa.INVENTORY] == Decimal("100.00")
        assert balances[coa.OWNER_CAPITAL] == Decimal("100.00")
        assert balances[coa.COGS] == Decimal("0.00")

    def test_purchases_recompute_the_weighted_average_cost(self, db, chicken):
        # 10 kg at RM10.00 plus 10 kg at RM14.00 averages to RM12.00.
        purchase_stock(
            db,
            StockPurchase(
                item_id=chicken.id, quantity=Decimal("10"), total_cost=Decimal("140.00")
            ),
        )
        db.commit()
        db.refresh(chicken)
        assert chicken.quantity_on_hand == Decimal("20.000")
        assert chicken.unit_cost == Decimal("12.0000")
        assert chicken.stock_value == Decimal("240.00")

    def test_purchase_debits_inventory_and_credits_cash(self, db, chicken):
        purchase_stock(
            db,
            StockPurchase(
                item_id=chicken.id, quantity=Decimal("5"), total_cost=Decimal("60.00")
            ),
        )
        db.commit()
        balances = account_balances(db)
        assert balances[coa.INVENTORY] == Decimal("160.00")
        assert balances[coa.CASH_ON_HAND] == Decimal("-60.00")

    def test_unpaid_purchase_creates_a_payable(self, db, chicken):
        purchase_stock(
            db,
            StockPurchase(
                item_id=chicken.id,
                quantity=Decimal("5"),
                total_cost=Decimal("60.00"),
                paid=False,
                supplier="Pasar Borong",
            ),
        )
        db.commit()
        balances = account_balances(db)
        assert balances[coa.ACCOUNTS_PAYABLE] == Decimal("60.00")
        assert balances[coa.CASH_ON_HAND] == Decimal("0.00")

    def test_stock_value_totals_across_items(self, db, chicken):
        create_item(
            db,
            InventoryItemCreate(
                name="Rice",
                unit="kg",
                par_level=Decimal("50"),
                opening_quantity=Decimal("20"),
                opening_unit_cost=Decimal("3.00"),
            ),
        )
        db.commit()
        assert total_inventory_value(db) == Decimal("160.00")


class TestConsumption:
    def test_using_stock_moves_value_from_inventory_to_cogs(self, db, chicken):
        """This is the bridge the accounting student needs to see."""
        txn, value = consume_stock(
            db, chicken, qty=Decimal("4"), movement_date=date.today()
        )
        db.commit()
        assert value == Decimal("40.00")
        balances = account_balances(db)
        assert balances[coa.COGS] == Decimal("40.00")
        assert balances[coa.INVENTORY] == Decimal("60.00")

    def test_spoilage_is_kept_separate_from_cost_of_sales(self, db, chicken):
        consume_stock(
            db, chicken, qty=Decimal("2"), movement_date=date.today(), as_wastage=True
        )
        db.commit()
        balances = account_balances(db)
        assert balances[coa.WASTAGE] == Decimal("20.00")
        assert balances[coa.COGS] == Decimal("0.00")

    def test_using_more_than_is_held_is_refused(self, db, chicken):
        with pytest.raises(InventoryError, match="only"):
            consume_stock(db, chicken, qty=Decimal("999"), movement_date=date.today())


class TestStockCount:
    def test_a_shortfall_becomes_cost_of_goods_sold(self, db, chicken):
        """The "Count Stock" button, seen from the accountant's side."""
        results = record_stock_count(
            db,
            StockCountCreate(
                counts=[StockCountEntry(item_id=chicken.id, counted_quantity=Decimal("6"))]
            ),
        )
        db.commit()
        result = results[0]
        assert result.variance == Decimal("-4.000")
        assert result.variance_value == Decimal("-40.00")
        assert account_balances(db)[coa.COGS] == Decimal("40.00")

    def test_a_shortfall_can_be_recorded_as_spoilage_instead(self, db, chicken):
        record_stock_count(
            db,
            StockCountCreate(
                counts=[
                    StockCountEntry(
                        item_id=chicken.id,
                        counted_quantity=Decimal("7"),
                        treat_shortfall_as=MovementType.WASTAGE,
                    )
                ]
            ),
        )
        db.commit()
        assert account_balances(db)[coa.WASTAGE] == Decimal("30.00")

    def test_a_surplus_credits_cost_of_goods_sold_back(self, db, chicken):
        record_stock_count(
            db,
            StockCountCreate(
                counts=[StockCountEntry(item_id=chicken.id, counted_quantity=Decimal("13"))]
            ),
        )
        db.commit()
        db.refresh(chicken)
        assert chicken.quantity_on_hand == Decimal("13.000")
        assert account_balances(db)[coa.COGS] == Decimal("-30.00")
        assert account_balances(db)[coa.INVENTORY] == Decimal("130.00")

    def test_an_exact_count_posts_nothing(self, db, chicken):
        results = record_stock_count(
            db,
            StockCountCreate(
                counts=[StockCountEntry(item_id=chicken.id, counted_quantity=Decimal("10"))]
            ),
        )
        db.commit()
        assert results[0].variance == Decimal("0.000")
        assert results[0].transaction_reference is None


class TestDepletionSignals:
    def test_status_bands_drive_the_colour_coding(self, db, chicken):
        # 10 of a par level of 40 is 25% - amber.
        assert chicken.status == "low"

        chicken.quantity_on_hand = Decimal("35")
        assert chicken.status == "ok"

        chicken.quantity_on_hand = Decimal("2")
        assert chicken.status == "critical"

        chicken.quantity_on_hand = Decimal("0")
        assert chicken.status == "critical"

    def test_low_stock_lists_the_worst_first(self, db, chicken):
        create_item(
            db,
            InventoryItemCreate(
                name="Rice",
                unit="kg",
                par_level=Decimal("100"),
                reorder_level=Decimal("30"),
                opening_quantity=Decimal("2"),
                opening_unit_cost=Decimal("3.00"),
            ),
        )
        db.commit()
        flagged = low_stock_items(db)
        assert [item.name for item in flagged] == ["Rice", "Chicken"]

    def test_an_item_with_no_par_level_is_never_flagged(self, db):
        """Without a target level there is nothing to compare against."""
        item = create_item(db, InventoryItemCreate(name="Salt", unit="kg"))
        db.commit()
        assert item.status == "critical"  # zero on hand is always critical
        item.quantity_on_hand = Decimal("1")
        assert item.status == "ok"
