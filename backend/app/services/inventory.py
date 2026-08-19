"""Smart inventory: stock levels, weighted-average costing and COGS.

Inventory is where a restaurant's money quietly leaks, so the module does three
jobs at once:

1. Track quantity and value per item at weighted-average cost.
2. Post the matching ledger entries, so buying food debits an *asset* and using
   it debits Cost of Goods Sold - the link the accounting student needs.
3. Expose depletion signals (``ok`` / ``low`` / ``critical`` plus days of cover)
   that the UI turns into colour-coded cards the owner can read at a glance.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    EventType,
    InventoryItem,
    InventoryMovement,
    MovementType,
    PaymentMethod,
    StockCount,
    Transaction,
    TransactionSource,
)
from ..schemas import (
    InventoryItemCreate,
    StockCountCreate,
    StockCountResultOut,
    StockPurchase,
    TransactionCreate,
)
from .ledger import ZERO, money, post_transaction

QTY = Decimal("0.001")
COST = Decimal("0.0001")


def quantity(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(QTY, rounding=ROUND_HALF_UP)


def unit_cost(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(COST, rounding=ROUND_HALF_UP)


class InventoryError(ValueError):
    """Raised when a stock operation cannot be applied."""


def get_item(db: Session, item_id: int) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise InventoryError(f"Inventory item {item_id} does not exist.")
    return item


def _record_movement(
    db: Session,
    item: InventoryItem,
    *,
    movement_type: MovementType,
    qty: Decimal,
    cost_per_unit: Decimal,
    total_cost: Decimal,
    movement_date: date,
    transaction: Transaction | None = None,
    note: str = "",
) -> InventoryMovement:
    movement = InventoryMovement(
        item_id=item.id,
        item=item,
        transaction_id=transaction.id if transaction else None,
        movement_type=movement_type,
        movement_date=movement_date,
        quantity=quantity(qty),
        unit_cost=unit_cost(cost_per_unit),
        total_cost=money(total_cost),
        balance_after=quantity(item.quantity_on_hand),
        note=note,
    )
    db.add(movement)
    return movement


# --------------------------------------------------------------------------- #
# Creating items
# --------------------------------------------------------------------------- #
def create_item(db: Session, payload: InventoryItemCreate) -> InventoryItem:
    """Add a stock item, optionally with an opening quantity.

    Opening stock is capital the owner already put into the business, so it is
    posted as Dr Inventory / Cr Owner's Capital rather than as a purchase.
    """
    existing = db.scalar(select(InventoryItem).where(InventoryItem.name == payload.name))
    if existing is not None:
        raise InventoryError(f"An item named {payload.name!r} already exists.")

    item = InventoryItem(
        name=payload.name,
        local_name=payload.local_name,
        category=payload.category,
        unit=payload.unit,
        reorder_level=quantity(payload.reorder_level),
        par_level=quantity(payload.par_level),
        emoji=payload.emoji,
        quantity_on_hand=quantity(payload.opening_quantity),
        unit_cost=unit_cost(payload.opening_unit_cost),
    )
    db.add(item)
    db.flush()

    opening_value = money(item.quantity_on_hand * item.unit_cost)
    if opening_value > 0:
        txn = post_transaction(
            db,
            TransactionCreate(
                event_type=EventType.OPENING_INVENTORY,
                amount=opening_value,
                description=f"Opening stock: {item.name}",
                source=TransactionSource.SYSTEM,
            ),
        )
        _record_movement(
            db,
            item,
            movement_type=MovementType.OPENING,
            qty=item.quantity_on_hand,
            cost_per_unit=item.unit_cost,
            total_cost=opening_value,
            movement_date=txn.txn_date,
            transaction=txn,
            note="Opening balance",
        )
    return item


# --------------------------------------------------------------------------- #
# Buying stock
# --------------------------------------------------------------------------- #
def apply_purchase(
    db: Session,
    item: InventoryItem,
    *,
    qty: Decimal,
    total_cost: Decimal,
    movement_date: date,
    transaction: Transaction | None = None,
    note: str = "",
) -> InventoryMovement:
    """Add stock and recompute the weighted-average unit cost.

    Weighted average is used rather than FIFO because a restaurant's stock is
    fungible - one kilo of chicken is like any other - and because it keeps the
    valuation understandable to a non-specialist.
    """
    qty = quantity(qty)
    if qty <= 0:
        raise InventoryError("Purchase quantity must be positive.")

    old_value = item.quantity_on_hand * item.unit_cost
    new_quantity = quantity(item.quantity_on_hand + qty)
    new_value = old_value + Decimal(str(total_cost))

    item.quantity_on_hand = new_quantity
    item.unit_cost = unit_cost(new_value / new_quantity) if new_quantity > 0 else ZERO

    return _record_movement(
        db,
        item,
        movement_type=MovementType.PURCHASE,
        qty=qty,
        cost_per_unit=unit_cost(Decimal(str(total_cost)) / qty),
        total_cost=total_cost,
        movement_date=movement_date,
        transaction=transaction,
        note=note,
    )


def purchase_stock(db: Session, payload: StockPurchase) -> tuple[Transaction, InventoryItem]:
    """Buy stock: post the purchase to the ledger and take it into inventory."""
    item = get_item(db, payload.item_id)
    txn_date = payload.txn_date or date.today()

    event = (
        EventType.PURCHASE_INVENTORY_CASH
        if payload.paid
        else EventType.PURCHASE_INVENTORY_CREDIT
    )
    txn = post_transaction(
        db,
        TransactionCreate(
            event_type=event,
            amount=payload.total_cost,
            txn_date=txn_date,
            description=payload.note or f"Bought {payload.quantity} {item.unit} {item.name}",
            counterparty=payload.supplier,
            payment_method=payload.method if payload.paid else PaymentMethod.CREDIT,
            source=TransactionSource.ACCOUNTANT_UI,
            inventory_item_id=item.id,
            quantity=payload.quantity,
        ),
    )
    apply_purchase(
        db,
        item,
        qty=payload.quantity,
        total_cost=payload.total_cost,
        movement_date=txn_date,
        transaction=txn,
        note=payload.supplier,
    )
    return txn, item


# --------------------------------------------------------------------------- #
# Using stock: the bridge to Cost of Goods Sold
# --------------------------------------------------------------------------- #
def consume_stock(
    db: Session,
    item: InventoryItem,
    *,
    qty: Decimal,
    movement_date: date,
    as_wastage: bool = False,
    note: str = "",
) -> tuple[Transaction | None, Decimal]:
    """Take stock out and charge it to COGS (or to wastage if it spoiled).

    Returns the posted transaction and the value consumed. Consuming zero-value
    stock posts nothing, since a ledger entry of zero would be meaningless.
    """
    qty = quantity(qty)
    if qty <= 0:
        raise InventoryError("Consumption quantity must be positive.")
    if qty > item.quantity_on_hand:
        raise InventoryError(
            f"Cannot use {qty} {item.unit} of {item.name}; only "
            f"{item.quantity_on_hand} {item.unit} on hand."
        )

    value = money(qty * item.unit_cost)
    item.quantity_on_hand = quantity(item.quantity_on_hand - qty)

    txn: Transaction | None = None
    if value > 0:
        txn = post_transaction(
            db,
            TransactionCreate(
                event_type=EventType.STOCK_WASTAGE if as_wastage else EventType.COGS_USAGE,
                amount=value,
                txn_date=movement_date,
                description=note
                or (f"Wastage: {item.name}" if as_wastage else f"Used {item.name}"),
                source=TransactionSource.SYSTEM,
            ),
        )

    _record_movement(
        db,
        item,
        movement_type=MovementType.WASTAGE if as_wastage else MovementType.USAGE,
        qty=-qty,
        cost_per_unit=item.unit_cost,
        total_cost=value,
        movement_date=movement_date,
        transaction=txn,
        note=note,
    )
    return txn, value


def record_stock_count(db: Session, payload: StockCountCreate) -> list[StockCountResultOut]:
    """Reconcile physical stock to the books.

    A shortfall is what was actually used (or spoiled) and becomes an expense.
    A surplus means earlier usage was overstated, so it credits COGS back.
    This is the "Count Stock" button in Grandma Mode.
    """
    count_date = payload.count_date or date.today()
    results: list[StockCountResultOut] = []

    for entry in payload.counts:
        item = get_item(db, entry.item_id)
        expected = quantity(item.quantity_on_hand)
        counted = quantity(entry.counted_quantity)
        variance = quantity(counted - expected)

        txn: Transaction | None = None
        variance_value = ZERO
        treated_as = entry.treat_shortfall_as

        if variance < 0:
            txn, variance_value = consume_stock(
                db,
                item,
                qty=-variance,
                movement_date=count_date,
                as_wastage=entry.treat_shortfall_as is MovementType.WASTAGE,
                note=payload.note or f"Stock count on {count_date:%d %b %Y}",
            )
            variance_value = -variance_value
        elif variance > 0:
            variance_value = money(variance * item.unit_cost)
            item.quantity_on_hand = counted
            treated_as = MovementType.ADJUSTMENT
            if variance_value > 0:
                txn = post_transaction(
                    db,
                    TransactionCreate(
                        event_type=EventType.STOCK_ADJUSTMENT_GAIN,
                        amount=variance_value,
                        txn_date=count_date,
                        description=f"Stock count surplus: {item.name}",
                        source=TransactionSource.SYSTEM,
                    ),
                )
            _record_movement(
                db,
                item,
                movement_type=MovementType.ADJUSTMENT,
                qty=variance,
                cost_per_unit=item.unit_cost,
                total_cost=variance_value,
                movement_date=count_date,
                transaction=txn,
                note=payload.note,
            )
        else:
            treated_as = MovementType.ADJUSTMENT

        db.add(
            StockCount(
                item_id=item.id,
                transaction_id=txn.id if txn else None,
                count_date=count_date,
                expected_quantity=expected,
                counted_quantity=counted,
                variance=variance,
                variance_value=money(variance_value),
                treated_as=treated_as,
                note=payload.note,
            )
        )
        results.append(
            StockCountResultOut(
                item_id=item.id,
                item_name=item.name,
                expected_quantity=expected,
                counted_quantity=counted,
                variance=variance,
                variance_value=money(variance_value),
                treated_as=treated_as,
                transaction_reference=txn.reference if txn else None,
            )
        )

    return results


# --------------------------------------------------------------------------- #
# Reporting helpers
# --------------------------------------------------------------------------- #
def average_daily_usage(db: Session, item_id: int, *, days: int = 30) -> Decimal:
    """Average quantity consumed per day over the recent window."""
    since = date.today() - timedelta(days=days)
    rows = db.scalars(
        select(InventoryMovement).where(
            InventoryMovement.item_id == item_id,
            InventoryMovement.movement_date >= since,
            InventoryMovement.movement_type.in_(
                [MovementType.USAGE, MovementType.WASTAGE]
            ),
        )
    ).all()
    used = sum((abs(row.quantity) for row in rows), Decimal("0"))
    return quantity(used / days) if days else ZERO


def days_of_cover(db: Session, item: InventoryItem, *, days: int = 30) -> float | None:
    """How many days the current stock lasts at the recent usage rate."""
    rate = average_daily_usage(db, item.id, days=days)
    if rate <= 0:
        return None
    return round(float(item.quantity_on_hand / rate), 1)


def total_inventory_value(db: Session) -> Decimal:
    items = db.scalars(select(InventoryItem).where(InventoryItem.is_active.is_(True))).all()
    return money(sum((item.stock_value for item in items), ZERO))


def low_stock_items(db: Session) -> list[InventoryItem]:
    """Items in the amber or red band, worst first."""
    items = db.scalars(select(InventoryItem).where(InventoryItem.is_active.is_(True))).all()
    flagged = [item for item in items if item.status in ("low", "critical")]
    return sorted(flagged, key=lambda i: i.stock_ratio)
