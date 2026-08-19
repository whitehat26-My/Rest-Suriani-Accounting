"""Chart of accounts bootstrap and demo data.

``ensure_chart_of_accounts`` runs on every startup and is idempotent - it only
adds accounts that are missing, so an existing database is never disturbed.

``seed_demo_data`` builds three months of plausible trading for a small
Malaysian restaurant, so both dashboards have something real to show and the
statements can be checked against figures a person can follow.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from . import chart_of_accounts as coa
from .database import init_db, session_scope
from .models import (
    Account,
    EventType,
    InventoryItem,
    MovementType,
    PaymentMethod,
    TransactionSource,
)
from .schemas import (
    InventoryItemCreate,
    StockCountCreate,
    StockCountEntry,
    StockPurchase,
    TransactionCreate,
)
from .services.inventory import create_item, purchase_stock, record_stock_count
from .services.ledger import money, post_transaction


def ensure_chart_of_accounts() -> int:
    """Insert any account from the default chart that is not present yet."""
    init_db()
    added = 0
    with session_scope() as db:
        existing = set(db.scalars(select(Account.code)).all())
        for spec in coa.DEFAULT_ACCOUNTS:
            if spec.code in existing:
                continue
            db.add(
                Account(
                    code=spec.code,
                    name=spec.name,
                    type=spec.type,
                    normal_balance=spec.normal_balance,
                    cash_flow_section=spec.cash_flow_section,
                    statement_group=spec.statement_group,
                    friendly_name=spec.friendly_name,
                    is_contra=spec.is_contra,
                    sort_order=spec.sort_order,
                )
            )
            added += 1
    return added


DEMO_ITEMS = [
    # name, local name, unit, par, reorder, opening qty, unit cost, emoji
    ("Chicken", "ayam", "kg", 40, 12, 26, "9.80", "\N{POULTRY LEG}"),
    ("Rice", "beras", "kg", 100, 30, 75, "3.20", "\N{COOKED RICE}"),
    ("Cooking Oil", "minyak masak", "litre", 40, 10, 22, "7.50", "\N{HONEY POT}"),
    ("Onion", "bawang", "kg", 25, 8, 9, "4.60", "\N{ONION}"),
    ("Chilli", "cili", "kg", 15, 5, 3, "12.00", "\N{HOT PEPPER}"),
    ("Egg", "telur", "tray", 20, 6, 14, "13.50", "\N{EGG}"),
    ("Fish", "ikan", "kg", 25, 8, 6, "16.00", "\N{FISH}"),
    ("Vegetables", "sayur", "kg", 30, 10, 18, "5.40", "\N{BROCCOLI}"),
    ("Coconut Milk", "santan", "litre", 20, 6, 11, "6.20", "\N{COCONUT}"),
    ("Sugar", "gula", "kg", 30, 10, 21, "2.90", "\N{CANDY}"),
]

SUPPLIERS = ["Pasar Borong Selayang", "Ayam Segar Sdn Bhd", "Kedai Runcit Pak Mat"]


def seed_demo_data(*, days: int = 90, seed: int = 20260819) -> dict:
    """Generate a few months of trading. Safe to run only on an empty ledger.

    The figures are modelled on a real independent restaurant rather than picked
    at random: food cost lands around a third of sales, labour around a third,
    and the rest covers rent, utilities and a single-digit net margin. That
    matters because the evaluation engine grades against industry benchmarks -
    seeding implausible numbers would make every dashboard read as a red alert.
    """
    rng = random.Random(seed)
    ensure_chart_of_accounts()

    stats = {"transactions": 0, "items": 0, "days": days}
    today = date.today()
    start = today - timedelta(days=days - 1)

    def post(**kwargs) -> None:
        kwargs.setdefault("source", TransactionSource.SEED)
        post_transaction(db, TransactionCreate(**kwargs))
        stats["transactions"] += 1

    with session_scope() as db:
        if db.scalar(select(InventoryItem.id).limit(1)) is not None:
            return {"skipped": "database already has inventory data"}

        # ------------------------------------------------------------------ #
        # Opening the business
        # ------------------------------------------------------------------ #
        post(
            event_type=EventType.OWNER_CONTRIBUTION,
            amount=Decimal("35000.00"),
            txn_date=start,
            description="Opening capital",
            payment_method=PaymentMethod.BANK,
        )
        post(
            event_type=EventType.LOAN_RECEIVED,
            amount=Decimal("15000.00"),
            txn_date=start,
            description="SME equipment loan",
            counterparty="Bank Rakyat",
            payment_method=PaymentMethod.BANK,
        )
        post(
            event_type=EventType.CASH_WITHDRAWAL,
            amount=Decimal("2000.00"),
            txn_date=start,
            description="Float for the till",
        )
        post(
            event_type=EventType.BUY_EQUIPMENT,
            amount=Decimal("28000.00"),
            txn_date=start,
            description="Kitchen fit-out: fryer, chiller, cooker, tables",
            counterparty="Restoran Supply Depot",
            payment_method=PaymentMethod.BANK,
        )

        # ------------------------------------------------------------------ #
        # Stock items, opened at roughly two-thirds of their par level
        # ------------------------------------------------------------------ #
        items: list[InventoryItem] = []
        for name, local, unit, par, reorder, qty, cost, emoji in DEMO_ITEMS:
            items.append(
                create_item(
                    db,
                    InventoryItemCreate(
                        name=name,
                        local_name=local,
                        unit=unit,
                        par_level=Decimal(str(par)),
                        reorder_level=Decimal(str(reorder)),
                        opening_quantity=Decimal(str(qty)),
                        opening_unit_cost=Decimal(cost),
                        emoji=emoji,
                    ),
                )
            )
            stats["items"] += 1

        # Each item's share of the kitchen's total food cost, used to spread the
        # week's consumption across the store room in believable proportions.
        par_value = {
            item.id: Decimal(str(item.par_level)) * item.unit_cost for item in items
        }
        total_par_value = sum(par_value.values(), Decimal("0"))

        # ------------------------------------------------------------------ #
        # Daily trading
        # ------------------------------------------------------------------ #
        week_takings = Decimal("0.00")
        outstanding_payables = Decimal("0.00")
        pending_receivable: tuple[date, Decimal] | None = None

        day = start
        while day <= today:
            weekend = day.weekday() >= 5
            base = rng.uniform(820, 1080) * (1.3 if weekend else 1.0)
            # A gentle upward trend, so the charts have a story to tell.
            growth = 1 + (day - start).days / (days * 5)
            takings = money(Decimal(str(base * growth)))
            week_takings += takings

            cash_part = money(takings * Decimal(str(rng.uniform(0.58, 0.72))))
            card_part = money(takings - cash_part)

            post(
                event_type=EventType.CASH_SALE,
                amount=cash_part,
                txn_date=day,
                description="Counter sales",
                payment_method=PaymentMethod.CASH,
            )
            post(
                event_type=EventType.CARD_SALE,
                amount=card_part,
                txn_date=day,
                description="Card and e-wallet sales",
                fee_amount=money(card_part * Decimal("0.018")),
                payment_method=PaymentMethod.CARD,
            )

            # Occasional catering order billed on account.
            if rng.random() < 0.05:
                amount = money(Decimal(str(rng.uniform(450, 1400))))
                post(
                    event_type=EventType.CREDIT_SALE,
                    amount=amount,
                    txn_date=day,
                    description="Catering order",
                    counterparty=rng.choice(["Surau Al-Hidayah", "SK Taman Melati", "Koperasi ABC"]),
                    payment_method=PaymentMethod.CREDIT,
                )
                pending_receivable = (day + timedelta(days=rng.randint(9, 20)), amount)

            # Customers settling those invoices.
            if pending_receivable and day >= pending_receivable[0]:
                post(
                    event_type=EventType.CUSTOMER_PAYMENT,
                    amount=pending_receivable[1],
                    txn_date=day,
                    description="Catering invoice settled",
                    payment_method=PaymentMethod.BANK,
                )
                pending_receivable = None

            # -------------------------------------------------------------- #
            # Restocking: top items back up towards their par level
            # -------------------------------------------------------------- #
            if day.weekday() in (0, 3):
                for item in items:
                    shortfall = Decimal(str(item.par_level)) - item.quantity_on_hand
                    if shortfall <= 0:
                        continue
                    # Buy most of the gap, not all of it - nobody orders exactly.
                    qty = (shortfall * Decimal(str(rng.uniform(0.7, 1.0)))).quantize(
                        Decimal("0.1")
                    )
                    if qty <= 0:
                        continue
                    unit_price = item.unit_cost * Decimal(str(rng.uniform(0.94, 1.10)))
                    cost = money(qty * unit_price)
                    on_account = rng.random() < 0.35
                    purchase_stock(
                        db,
                        StockPurchase(
                            item_id=item.id,
                            quantity=qty,
                            total_cost=cost,
                            paid=not on_account,
                            method=PaymentMethod.CASH,
                            supplier=rng.choice(SUPPLIERS),
                            txn_date=day,
                            note=f"Restock {item.name.lower()}",
                        ),
                    )
                    stats["transactions"] += 1
                    if on_account:
                        outstanding_payables += cost

            # Settle supplier accounts every fortnight.
            if day.weekday() == 4 and outstanding_payables > 0 and rng.random() < 0.6:
                payment = money(outstanding_payables * Decimal(str(rng.uniform(0.6, 1.0))))
                post(
                    event_type=EventType.PAY_SUPPLIER,
                    amount=payment,
                    txn_date=day,
                    description="Supplier account settled",
                    counterparty=rng.choice(SUPPLIERS),
                    payment_method=PaymentMethod.BANK,
                )
                outstanding_payables = money(outstanding_payables - payment)

            # Bank the takings twice a week.
            if day.weekday() in (2, 5):
                post(
                    event_type=EventType.BANK_DEPOSIT,
                    amount=money(Decimal(str(rng.uniform(1200, 2200)))),
                    txn_date=day,
                    description="Banked the takings",
                )

            # -------------------------------------------------------------- #
            # Weekly stock count: this is what turns stock into COGS
            # -------------------------------------------------------------- #
            if day.weekday() == 6 and week_takings > 0:
                # Aim the week's food cost at a normal share of the week's sales,
                # then let the count discover it item by item.
                target_cost = week_takings * Decimal(str(rng.uniform(0.30, 0.34)))
                counts = []
                for item in items:
                    if total_par_value <= 0 or item.unit_cost <= 0:
                        continue
                    share = par_value[item.id] / total_par_value
                    used_qty = (target_cost * share / item.unit_cost).quantize(
                        Decimal("0.001")
                    )
                    used_qty = min(used_qty, item.quantity_on_hand)
                    remaining = (item.quantity_on_hand - used_qty).quantize(Decimal("0.001"))
                    counts.append(
                        StockCountEntry(
                            item_id=item.id,
                            counted_quantity=max(remaining, Decimal("0")),
                            treat_shortfall_as=(
                                MovementType.WASTAGE
                                if rng.random() < 0.035
                                else MovementType.USAGE
                            ),
                        )
                    )
                if counts:
                    record_stock_count(
                        db,
                        StockCountCreate(
                            counts=counts, count_date=day, note="Weekly stock count"
                        ),
                    )
                    stats["transactions"] += len(counts)
                week_takings = Decimal("0.00")

            # -------------------------------------------------------------- #
            # Month-start fixed costs
            # -------------------------------------------------------------- #
            if day.day == 1:
                for amount, code, label, event in (
                    (Decimal("3000.00"), coa.RENT, "Monthly shop rent", EventType.EXPENSE_CASH),
                    (Decimal("9600.00"), coa.WAGES, "Staff wages", EventType.PAY_WAGES),
                    (Decimal("1300.00"), coa.UTILITIES, "Electricity, water and gas", EventType.EXPENSE_CASH),
                    (Decimal("700.00"), coa.SUPPLIES, "Packaging and cleaning", EventType.EXPENSE_CASH),
                    (Decimal("300.00"), coa.MARKETING, "Facebook promotion", EventType.EXPENSE_CASH),
                    (Decimal("400.00"), coa.TRANSPORT, "Petrol and delivery", EventType.EXPENSE_CASH),
                ):
                    post(
                        event_type=event,
                        amount=amount,
                        txn_date=day,
                        description=label,
                        expense_account_code=code,
                        payment_method=PaymentMethod.BANK,
                    )

                post(
                    event_type=EventType.DEPRECIATION,
                    amount=Decimal("467.00"),
                    txn_date=day,
                    description="Monthly depreciation on kitchen equipment",
                )
                post(
                    event_type=EventType.LOAN_REPAYMENT,
                    amount=Decimal("720.00"),
                    txn_date=day,
                    description="Monthly loan instalment",
                    counterparty="Bank Rakyat",
                    interest_amount=Decimal("62.00"),
                    payment_method=PaymentMethod.BANK,
                )
                post(
                    event_type=EventType.OWNER_DRAWINGS,
                    amount=Decimal("2000.00"),
                    txn_date=day,
                    description="Owner's monthly drawings",
                    payment_method=PaymentMethod.BANK,
                )

            # Occasional one-off repair.
            if rng.random() < 0.02:
                post(
                    event_type=EventType.EXPENSE_CASH,
                    amount=money(Decimal(str(rng.uniform(80, 420)))),
                    txn_date=day,
                    description="Repair and maintenance",
                    expense_account_code=coa.REPAIRS,
                    counterparty="Tukang Servis",
                    payment_method=PaymentMethod.CASH,
                )

            day += timedelta(days=1)

    return stats


if __name__ == "__main__":  # pragma: no cover - operator entry point
    added = ensure_chart_of_accounts()
    print(f"Chart of accounts ready ({added} accounts added).")
    result = seed_demo_data()
    print(f"Demo data: {result}")
