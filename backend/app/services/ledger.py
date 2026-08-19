"""The event-driven double-entry engine.

This module is the only place in the system that decides which account gets
debited and which gets credited. Everything upstream - the owner tapping "Money
Out", the voice parser, the accountant's manual entry form - eventually produces
a :class:`~app.schemas.TransactionCreate` describing *what happened in the
business*. This module turns that into balanced ledger entries.

The mapping lives in :data:`POSTING_RULES`: one function per business event,
each returning the list of legs to post. Adding a new kind of business event
means adding one rule here and nothing else - the statements, trial balance and
analytics all read from the ledger generically.

Every transaction is validated before it is written: at least two legs, every
amount strictly positive, and total debits exactly equal to total credits.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from .. import chart_of_accounts as coa
from ..models import (
    Account,
    AccountType,
    EntrySide,
    EventType,
    LedgerEntry,
    PaymentMethod,
    Transaction,
    TransactionSource,
)
from ..schemas import QuickEntry, TransactionCreate

ZERO = Decimal("0.00")


class LedgerError(ValueError):
    """Raised when a transaction cannot be posted as a valid double entry."""


def money(value: Decimal | int | float | str) -> Decimal:
    """Round to two decimal places using half-up, the convention for currency."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Leg construction
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Leg:
    """One side of a double entry, before it is attached to an account row."""

    account_code: str
    side: EntrySide
    amount: Decimal
    memo: str = ""

    def __post_init__(self) -> None:
        self.amount = money(self.amount)


def debit(code: str, amount: Decimal, memo: str = "") -> Leg:
    return Leg(code, EntrySide.DEBIT, amount, memo)


def credit(code: str, amount: Decimal, memo: str = "") -> Leg:
    return Leg(code, EntrySide.CREDIT, amount, memo)


@dataclass(slots=True)
class PostingContext:
    """Everything a posting rule needs, normalised and pre-rounded."""

    event_type: EventType
    amount: Decimal
    payment_method: PaymentMethod
    expense_account_code: str
    tax_amount: Decimal = ZERO
    fee_amount: Decimal = ZERO
    cogs_amount: Decimal = ZERO
    interest_amount: Decimal = ZERO
    description: str = ""
    counterparty: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def net_revenue(self) -> Decimal:
        """Sales value excluding any tax collected on behalf of the government."""
        return money(self.amount - self.tax_amount)

    @property
    def payment_account(self) -> str:
        """Which asset account the money physically moved through."""
        return payment_account_code(self.payment_method)


def payment_account_code(method: PaymentMethod) -> str:
    """Map a payment method to the asset account that actually moves.

    Card and e-wallet settlements land in the bank, not the till, which is why
    they do not map to Cash on Hand.
    """
    if method is PaymentMethod.CASH:
        return coa.CASH_ON_HAND
    if method in (PaymentMethod.BANK, PaymentMethod.CARD, PaymentMethod.EWALLET):
        return coa.BANK
    raise LedgerError(
        "Payment method CREDIT does not move cash; use a credit event type instead."
    )


# --------------------------------------------------------------------------- #
# Posting rules - one per business event
# --------------------------------------------------------------------------- #
def _sale_legs(ctx: PostingContext, debit_code: str, fee: Decimal = ZERO) -> list[Leg]:
    """Shared shape for every kind of sale.

    The customer's gross payment splits into what we keep as revenue, what we
    hold for the tax authority, and any processor fee taken off the top.
    """
    legs: list[Leg] = []
    received = money(ctx.amount - fee)
    if received > 0:
        legs.append(debit(debit_code, received, "Sale proceeds received"))
    if fee > 0:
        legs.append(debit(coa.BANK_FEES, fee, "Payment processing fee"))
    if ctx.tax_amount > 0:
        legs.append(credit(coa.SST_PAYABLE, ctx.tax_amount, "SST collected on sale"))
    legs.append(credit(coa.SALES, ctx.net_revenue, ctx.description or "Food & beverage sales"))

    # A sale also consumes stock. When the caller knows the cost of what went
    # out of the kitchen, recognise it in the same period as the revenue.
    if ctx.cogs_amount > 0:
        legs.append(debit(coa.COGS, ctx.cogs_amount, "Cost of goods sold"))
        legs.append(credit(coa.INVENTORY, ctx.cogs_amount, "Stock consumed by sale"))
    return legs


def rule_cash_sale(ctx: PostingContext) -> list[Leg]:
    """Customer pays immediately: Dr Cash/Bank, Cr Sales (+ Cr SST)."""
    return _sale_legs(ctx, ctx.payment_account)


def rule_card_sale(ctx: PostingContext) -> list[Leg]:
    """Card or e-wallet: the processor's fee is an expense, not a discount."""
    return _sale_legs(ctx, coa.BANK, fee=ctx.fee_amount)


def rule_credit_sale(ctx: PostingContext) -> list[Leg]:
    """Catering invoiced on account: Dr Accounts Receivable, Cr Sales."""
    return _sale_legs(ctx, coa.ACCOUNTS_RECEIVABLE)


def rule_customer_payment(ctx: PostingContext) -> list[Leg]:
    """Settling an invoice. No revenue here - that was recognised on the sale."""
    return [
        debit(ctx.payment_account, ctx.amount, f"Payment from {ctx.counterparty or 'customer'}"),
        credit(coa.ACCOUNTS_RECEIVABLE, ctx.amount, "Receivable settled"),
    ]


def rule_purchase_inventory_cash(ctx: PostingContext) -> list[Leg]:
    """Buying food is not an expense yet - it is an asset until it is used."""
    return [
        debit(coa.INVENTORY, ctx.amount, ctx.description or "Stock purchased"),
        credit(ctx.payment_account, ctx.amount, f"Paid {ctx.counterparty or 'supplier'}"),
    ]


def rule_purchase_inventory_credit(ctx: PostingContext) -> list[Leg]:
    """Stock taken on account from a supplier."""
    return [
        debit(coa.INVENTORY, ctx.amount, ctx.description or "Stock purchased on credit"),
        credit(coa.ACCOUNTS_PAYABLE, ctx.amount, f"Owed to {ctx.counterparty or 'supplier'}"),
    ]


def rule_pay_supplier(ctx: PostingContext) -> list[Leg]:
    """Paying down a supplier balance. Not an expense - the expense already ran."""
    return [
        debit(coa.ACCOUNTS_PAYABLE, ctx.amount, f"Settled {ctx.counterparty or 'supplier'}"),
        credit(ctx.payment_account, ctx.amount, "Payment made"),
    ]


def rule_expense_cash(ctx: PostingContext) -> list[Leg]:
    return [
        debit(ctx.expense_account_code, ctx.amount, ctx.description or "Expense paid"),
        credit(ctx.payment_account, ctx.amount, f"Paid {ctx.counterparty or 'supplier'}"),
    ]


def rule_expense_credit(ctx: PostingContext) -> list[Leg]:
    """A bill received but not yet paid still belongs in this period's profit."""
    return [
        debit(ctx.expense_account_code, ctx.amount, ctx.description or "Expense incurred"),
        credit(coa.ACCRUED_EXPENSES, ctx.amount, f"Accrued to {ctx.counterparty or 'supplier'}"),
    ]


def rule_pay_wages(ctx: PostingContext) -> list[Leg]:
    return [
        debit(coa.WAGES, ctx.amount, ctx.description or "Staff wages"),
        credit(ctx.payment_account, ctx.amount, f"Paid {ctx.counterparty or 'staff'}"),
    ]


def rule_owner_contribution(ctx: PostingContext) -> list[Leg]:
    return [
        debit(ctx.payment_account, ctx.amount, "Owner injected funds"),
        credit(coa.OWNER_CAPITAL, ctx.amount, ctx.description or "Capital contribution"),
    ]


def rule_owner_drawings(ctx: PostingContext) -> list[Leg]:
    """Money the owner takes for herself reduces equity, it is not an expense."""
    return [
        debit(coa.OWNER_DRAWINGS, ctx.amount, ctx.description or "Owner's drawings"),
        credit(ctx.payment_account, ctx.amount, "Withdrawn by owner"),
    ]


def rule_loan_received(ctx: PostingContext) -> list[Leg]:
    return [
        debit(ctx.payment_account, ctx.amount, "Loan disbursed"),
        credit(coa.LOAN_PAYABLE, ctx.amount, ctx.description or "Bank loan received"),
    ]


def rule_loan_repayment(ctx: PostingContext) -> list[Leg]:
    """Split the instalment: principal reduces the liability, interest is a cost."""
    principal = money(ctx.amount - ctx.interest_amount)
    if principal < 0:
        raise LedgerError("Interest portion cannot exceed the total repayment.")
    legs: list[Leg] = []
    if principal > 0:
        legs.append(debit(coa.LOAN_PAYABLE, principal, "Loan principal repaid"))
    if ctx.interest_amount > 0:
        legs.append(debit(coa.INTEREST_EXPENSE, ctx.interest_amount, "Loan interest"))
    legs.append(credit(ctx.payment_account, ctx.amount, "Loan instalment paid"))
    return legs


def rule_buy_equipment(ctx: PostingContext) -> list[Leg]:
    """Capital spend: a fryer lasts years, so it is an asset, not an expense."""
    return [
        debit(coa.EQUIPMENT, ctx.amount, ctx.description or "Equipment purchased"),
        credit(ctx.payment_account, ctx.amount, f"Paid {ctx.counterparty or 'supplier'}"),
    ]


def rule_depreciation(ctx: PostingContext) -> list[Leg]:
    """Spreading the cost of equipment over its useful life. No cash moves."""
    return [
        debit(coa.DEPRECIATION_EXPENSE, ctx.amount, ctx.description or "Depreciation charge"),
        credit(coa.ACCUM_DEPRECIATION, ctx.amount, "Accumulated depreciation"),
    ]


def rule_opening_inventory(ctx: PostingContext) -> list[Leg]:
    """Stock the owner already had when the books were opened.

    She paid for it out of her own pocket before the system existed, so it
    enters as capital introduced in kind rather than as a purchase.
    """
    return [
        debit(coa.INVENTORY, ctx.amount, ctx.description or "Opening stock"),
        credit(coa.OWNER_CAPITAL, ctx.amount, "Capital introduced as stock"),
    ]


def rule_cogs_usage(ctx: PostingContext) -> list[Leg]:
    """Stock leaving the store room becomes the cost of what was sold."""
    return [
        debit(coa.COGS, ctx.amount, ctx.description or "Stock used in production"),
        credit(coa.INVENTORY, ctx.amount, "Inventory consumed"),
    ]


def rule_stock_wastage(ctx: PostingContext) -> list[Leg]:
    """Spoilage is separated from COGS so the margin story stays honest."""
    return [
        debit(coa.WASTAGE, ctx.amount, ctx.description or "Spoilage and waste"),
        credit(coa.INVENTORY, ctx.amount, "Inventory written off"),
    ]


def rule_stock_adjustment_gain(ctx: PostingContext) -> list[Leg]:
    """A favourable count variance: stock was understated, so reverse some COGS."""
    return [
        debit(coa.INVENTORY, ctx.amount, ctx.description or "Stock count surplus"),
        credit(coa.COGS, ctx.amount, "Cost of sales adjusted"),
    ]


def rule_bank_deposit(ctx: PostingContext) -> list[Leg]:
    """Banking the day's takings. Cash total is unchanged, only its location."""
    return [
        debit(coa.BANK, ctx.amount, "Cash banked"),
        credit(coa.CASH_ON_HAND, ctx.amount, "Taken from till"),
    ]


def rule_cash_withdrawal(ctx: PostingContext) -> list[Leg]:
    return [
        debit(coa.CASH_ON_HAND, ctx.amount, "Cash drawn for float"),
        credit(coa.BANK, ctx.amount, "Withdrawn from bank"),
    ]


POSTING_RULES: dict[EventType, Callable[[PostingContext], list[Leg]]] = {
    EventType.CASH_SALE: rule_cash_sale,
    EventType.CARD_SALE: rule_card_sale,
    EventType.EWALLET_SALE: rule_card_sale,
    EventType.CREDIT_SALE: rule_credit_sale,
    EventType.CUSTOMER_PAYMENT: rule_customer_payment,
    EventType.PURCHASE_INVENTORY_CASH: rule_purchase_inventory_cash,
    EventType.PURCHASE_INVENTORY_CREDIT: rule_purchase_inventory_credit,
    EventType.PAY_SUPPLIER: rule_pay_supplier,
    EventType.EXPENSE_CASH: rule_expense_cash,
    EventType.EXPENSE_CREDIT: rule_expense_credit,
    EventType.PAY_WAGES: rule_pay_wages,
    EventType.OWNER_CONTRIBUTION: rule_owner_contribution,
    EventType.OWNER_DRAWINGS: rule_owner_drawings,
    EventType.LOAN_RECEIVED: rule_loan_received,
    EventType.LOAN_REPAYMENT: rule_loan_repayment,
    EventType.BUY_EQUIPMENT: rule_buy_equipment,
    EventType.DEPRECIATION: rule_depreciation,
    EventType.OPENING_INVENTORY: rule_opening_inventory,
    EventType.COGS_USAGE: rule_cogs_usage,
    EventType.STOCK_WASTAGE: rule_stock_wastage,
    EventType.STOCK_ADJUSTMENT_GAIN: rule_stock_adjustment_gain,
    EventType.BANK_DEPOSIT: rule_bank_deposit,
    EventType.CASH_WITHDRAWAL: rule_cash_withdrawal,
}

# Which direction the owner perceives each event as moving money.
EVENT_DIRECTION: dict[EventType, str] = {
    EventType.CASH_SALE: "in",
    EventType.CARD_SALE: "in",
    EventType.EWALLET_SALE: "in",
    EventType.CREDIT_SALE: "in",
    EventType.CUSTOMER_PAYMENT: "in",
    EventType.OWNER_CONTRIBUTION: "in",
    EventType.LOAN_RECEIVED: "in",
    EventType.STOCK_ADJUSTMENT_GAIN: "neutral",
    EventType.PURCHASE_INVENTORY_CASH: "out",
    EventType.PURCHASE_INVENTORY_CREDIT: "out",
    EventType.PAY_SUPPLIER: "out",
    EventType.EXPENSE_CASH: "out",
    EventType.EXPENSE_CREDIT: "out",
    EventType.PAY_WAGES: "out",
    EventType.OWNER_DRAWINGS: "out",
    EventType.LOAN_REPAYMENT: "out",
    EventType.BUY_EQUIPMENT: "out",
    EventType.DEPRECIATION: "neutral",
    EventType.OPENING_INVENTORY: "neutral",
    EventType.COGS_USAGE: "neutral",
    EventType.STOCK_WASTAGE: "neutral",
    EventType.BANK_DEPOSIT: "neutral",
    EventType.CASH_WITHDRAWAL: "neutral",
}

# Postings the system makes on its own. The owner never triggered these, so they
# are kept off her daily list - showing her "Opening stock: Sugar" beside her own
# entries would just be noise she cannot act on. They remain fully visible in
# Accountant Mode and in every report.
SYSTEM_ONLY_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.OPENING_INVENTORY,
        EventType.COGS_USAGE,
        EventType.STOCK_WASTAGE,
        EventType.STOCK_ADJUSTMENT_GAIN,
        EventType.DEPRECIATION,
    }
)


# Plain-language names, so no screen ever has to say "Accounts Payable".
EVENT_FRIENDLY: dict[EventType, str] = {
    EventType.CASH_SALE: "Money in from customers",
    EventType.CARD_SALE: "Money in by card",
    EventType.EWALLET_SALE: "Money in by e-wallet",
    EventType.CREDIT_SALE: "Sold now, customer pays later",
    EventType.CUSTOMER_PAYMENT: "Customer paid what they owed",
    EventType.PURCHASE_INVENTORY_CASH: "Bought food and ingredients",
    EventType.PURCHASE_INVENTORY_CREDIT: "Took ingredients, pay supplier later",
    EventType.PAY_SUPPLIER: "Paid the supplier",
    EventType.EXPENSE_CASH: "Money out for the shop",
    EventType.EXPENSE_CREDIT: "Bill received, not paid yet",
    EventType.PAY_WAGES: "Paid the workers",
    EventType.OWNER_CONTRIBUTION: "I put money in",
    EventType.OWNER_DRAWINGS: "I took money out",
    EventType.LOAN_RECEIVED: "Loan money received",
    EventType.LOAN_REPAYMENT: "Loan instalment paid",
    EventType.BUY_EQUIPMENT: "Bought kitchen equipment",
    EventType.DEPRECIATION: "Machines getting older",
    EventType.OPENING_INVENTORY: "Stock we already had",
    EventType.COGS_USAGE: "Food used from the store room",
    EventType.STOCK_WASTAGE: "Food thrown away",
    EventType.STOCK_ADJUSTMENT_GAIN: "Found extra stock",
    EventType.BANK_DEPOSIT: "Cash put into the bank",
    EventType.CASH_WITHDRAWAL: "Cash taken from the bank",
}


# --------------------------------------------------------------------------- #
# Smart pairing: turning a one-tap owner action into a real transaction
# --------------------------------------------------------------------------- #
def quick_entry_to_transaction(entry: QuickEntry) -> TransactionCreate:
    """Translate Grandma Mode's "Money In / Money Out" into a posting request.

    This is the whole trick behind the owner never seeing accounting. She picks a
    direction, an amount and a picture-labelled category; this function decides
    whether that is a sale, a stock purchase, a wage payment or a general
    expense, and whether it settles in cash or on credit.
    """
    txn_date = entry.txn_date or date.today()
    common = {
        "amount": entry.amount,
        "txn_date": txn_date,
        "description": entry.note,
        "counterparty": entry.counterparty,
        "payment_method": entry.method,
        "source": entry.source,
        "raw_input": entry.raw_input,
        "attachment_ids": entry.attachment_ids,
    }

    if entry.kind == "in":
        event = {
            PaymentMethod.CASH: EventType.CASH_SALE,
            PaymentMethod.BANK: EventType.CASH_SALE,
            PaymentMethod.CARD: EventType.CARD_SALE,
            PaymentMethod.EWALLET: EventType.EWALLET_SALE,
            PaymentMethod.CREDIT: EventType.CREDIT_SALE,
        }[entry.method]
        return TransactionCreate(event_type=event, **common)

    # Money out. The category decides which account absorbs the spend.
    category = (entry.category or "other").lower()
    on_credit = entry.method is PaymentMethod.CREDIT

    if category == "ingredients":
        event = (
            EventType.PURCHASE_INVENTORY_CREDIT if on_credit
            else EventType.PURCHASE_INVENTORY_CASH
        )
        return TransactionCreate(
            event_type=event,
            inventory_item_id=entry.inventory_item_id,
            quantity=entry.quantity,
            **common,
        )

    if category == "wages" and not on_credit:
        return TransactionCreate(event_type=EventType.PAY_WAGES, **common)

    account_code = coa.CATEGORY_TO_ACCOUNT.get(category, coa.OTHER_EXPENSE)
    event = EventType.EXPENSE_CREDIT if on_credit else EventType.EXPENSE_CASH
    return TransactionCreate(event_type=event, expense_account_code=account_code, **common)


# --------------------------------------------------------------------------- #
# Posting
# --------------------------------------------------------------------------- #
def get_account(db: Session, code: str) -> Account:
    account = db.scalar(select(Account).where(Account.code == code))
    if account is None:
        raise LedgerError(f"Account {code!r} is not in the chart of accounts.")
    return account


def _validate(legs: list[Leg]) -> None:
    if len(legs) < 2:
        raise LedgerError("A double entry needs at least two legs.")
    if any(leg.amount <= 0 for leg in legs):
        raise LedgerError("Every ledger entry must have a positive amount.")
    total_debits = sum((leg.amount for leg in legs if leg.side is EntrySide.DEBIT), ZERO)
    total_credits = sum((leg.amount for leg in legs if leg.side is EntrySide.CREDIT), ZERO)
    if total_debits != total_credits:
        raise LedgerError(
            f"Entry does not balance: debits {total_debits} vs credits {total_credits}."
        )


def build_legs(request: TransactionCreate) -> list[Leg]:
    """Run the posting rule for an event and return its validated legs."""
    rule = POSTING_RULES.get(request.event_type)
    if rule is None:
        raise LedgerError(f"No posting rule defined for {request.event_type.value}.")

    method = request.payment_method
    if method is None:
        # Sensible default per event: things that move through the bank default
        # to the bank, everything else to the till.
        method = (
            PaymentMethod.BANK
            if request.event_type
            in (
                EventType.CARD_SALE,
                EventType.EWALLET_SALE,
                EventType.LOAN_RECEIVED,
                EventType.LOAN_REPAYMENT,
                EventType.BUY_EQUIPMENT,
            )
            else PaymentMethod.CASH
        )

    ctx = PostingContext(
        event_type=request.event_type,
        amount=money(request.amount),
        payment_method=method,
        expense_account_code=request.expense_account_code or coa.OTHER_EXPENSE,
        tax_amount=money(request.tax_amount),
        fee_amount=money(request.fee_amount),
        cogs_amount=money(request.cogs_amount),
        interest_amount=money(request.interest_amount),
        description=request.description,
        counterparty=request.counterparty,
    )

    if ctx.tax_amount > ctx.amount:
        raise LedgerError("Tax cannot be larger than the transaction amount.")
    if ctx.fee_amount > ctx.amount:
        raise LedgerError("Processing fee cannot be larger than the transaction amount.")

    legs = rule(ctx)
    _validate(legs)
    return legs


def next_reference(db: Session, txn_date: date) -> str:
    """Human-readable sequential reference, unique per year."""
    year = txn_date.year
    prefix = f"TXN-{year}-"
    highest = db.scalar(
        select(func.max(Transaction.reference)).where(Transaction.reference.like(f"{prefix}%"))
    )
    sequence = int(highest.rsplit("-", 1)[1]) + 1 if highest else 1
    return f"{prefix}{sequence:06d}"


def post_transaction(db: Session, request: TransactionCreate, *, flush: bool = True) -> Transaction:
    """Create a transaction and its balanced ledger entries.

    The caller owns the commit, so a transaction can be posted alongside related
    inventory movements in a single atomic unit of work.
    """
    legs = build_legs(request)
    txn_date = request.txn_date or date.today()

    txn = Transaction(
        reference=next_reference(db, txn_date),
        event_type=request.event_type,
        txn_date=txn_date,
        amount=money(request.amount),
        description=request.description,
        counterparty=request.counterparty,
        payment_method=request.payment_method,
        source=request.source,
        raw_input=request.raw_input,
        notes=request.notes,
    )
    db.add(txn)

    for leg in legs:
        account = get_account(db, leg.account_code)
        txn.entries.append(
            LedgerEntry(
                account_id=account.id,
                account=account,
                side=leg.side,
                amount=leg.amount,
                memo=leg.memo,
                entry_date=txn_date,
            )
        )

    if not txn.is_balanced:  # pragma: no cover - guarded by _validate already
        raise LedgerError("Refusing to post an unbalanced transaction.")

    if flush:
        db.flush()
    return txn


def reverse_transaction(db: Session, txn: Transaction, *, reason: str = "") -> Transaction:
    """Post a mirror-image transaction instead of deleting history.

    Deleting a posted entry would break the audit trail an accountant relies on,
    so a correction is itself a transaction with every debit and credit swapped.
    """
    if txn.is_reversed:
        raise LedgerError(f"{txn.reference} has already been reversed.")

    reversal = Transaction(
        reference=next_reference(db, date.today()),
        event_type=txn.event_type,
        txn_date=date.today(),
        amount=txn.amount,
        description=f"Reversal of {txn.reference}" + (f" - {reason}" if reason else ""),
        counterparty=txn.counterparty,
        payment_method=txn.payment_method,
        source=TransactionSource.SYSTEM,
        notes=reason,
        reverses_id=txn.id,
    )
    db.add(reversal)

    for entry in txn.entries:
        reversal.entries.append(
            LedgerEntry(
                account_id=entry.account_id,
                side=(
                    EntrySide.CREDIT if entry.side is EntrySide.DEBIT else EntrySide.DEBIT
                ),
                amount=entry.amount,
                memo=f"Reversal: {entry.memo}",
                entry_date=reversal.txn_date,
            )
        )

    txn.is_reversed = True
    db.flush()
    return reversal


# --------------------------------------------------------------------------- #
# Balance queries - the shared foundation for every report
# --------------------------------------------------------------------------- #
def account_totals(
    db: Session,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[int, tuple[Decimal, Decimal]]:
    """Total debits and credits per account id over an optional date window."""
    stmt = select(
        LedgerEntry.account_id,
        func.coalesce(
            func.sum(case((LedgerEntry.side == EntrySide.DEBIT, LedgerEntry.amount), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((LedgerEntry.side == EntrySide.CREDIT, LedgerEntry.amount), else_=0)),
            0,
        ),
    ).group_by(LedgerEntry.account_id)

    if start is not None:
        stmt = stmt.where(LedgerEntry.entry_date >= start)
    if end is not None:
        stmt = stmt.where(LedgerEntry.entry_date <= end)

    return {
        account_id: (money(debits), money(credits))
        for account_id, debits, credits in db.execute(stmt).all()
    }


def account_balances(
    db: Session,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Decimal]:
    """Balance per account *code*, signed in each account's normal direction."""
    totals = account_totals(db, start=start, end=end)
    accounts = db.scalars(select(Account)).all()
    balances: dict[str, Decimal] = {}
    for account in accounts:
        debits, credits = totals.get(account.id, (ZERO, ZERO))
        balances[account.code] = account.signed_balance(debits, credits)
    return balances


def signed_movement(
    db: Session, code: str, *, start: date | None = None, end: date | None = None
) -> Decimal:
    """Movement on one account over a window, in its normal direction."""
    return account_balances(db, start=start, end=end).get(code, ZERO)


def cash_balance(db: Session, *, as_of: date | None = None) -> Decimal:
    """Total cash and cash equivalents: the till plus the bank."""
    balances = account_balances(db, end=as_of)
    return money(balances.get(coa.CASH_ON_HAND, ZERO) + balances.get(coa.BANK, ZERO))


def net_profit(db: Session, *, start: date | None = None, end: date | None = None) -> Decimal:
    """Revenue less expenses over the window."""
    totals = account_totals(db, start=start, end=end)
    accounts = db.scalars(select(Account)).all()
    revenue = ZERO
    expense = ZERO
    for account in accounts:
        debits, credits = totals.get(account.id, (ZERO, ZERO))
        balance = account.signed_balance(debits, credits)
        if account.type is AccountType.REVENUE:
            revenue += balance
        elif account.type is AccountType.EXPENSE:
            expense += balance
    return money(revenue - expense)


def load_transaction(db: Session, txn_id: int) -> Transaction | None:
    return db.scalar(
        select(Transaction)
        .where(Transaction.id == txn_id)
        .options(
            selectinload(Transaction.entries).selectinload(LedgerEntry.account),
            selectinload(Transaction.attachments),
        )
    )
