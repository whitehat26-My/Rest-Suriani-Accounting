"""Database schema for the Restaurant Accounting System.

Design notes
------------
The schema is built around classic double-entry bookkeeping:

    Transaction  1 --- N  LedgerEntry  N --- 1  Account

A ``Transaction`` is the *business event* the owner understands ("I sold RM120
of food", "I paid the chicken supplier"). It carries no debit/credit meaning on
its own. Each transaction owns two or more ``LedgerEntry`` rows - the actual
debits and credits - and the sum of debits must always equal the sum of credits.
That invariant is enforced in :mod:`app.services.ledger` before a transaction is
committed, so the books can never go out of balance.

``Account`` rows form the chart of accounts. Each account knows its type
(asset / liability / equity / revenue / expense), whether it is a contra
account, and which section of the cash flow statement it belongs to. Those three
attributes are enough to generate all three financial statements generically,
without hard-coding account names into the reporting logic.

``InventoryItem`` tracks stock at weighted-average cost. Stock movements are
what drive Cost of Goods Sold, so inventory is linked to the ledger rather than
living beside it.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Money is stored as NUMERIC(14, 2): exact decimal arithmetic, never float.
MONEY = Numeric(14, 2)
# Quantities allow finer granularity (0.250 kg of chilli).
QUANTITY = Numeric(14, 3)


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class AccountType(str, enum.Enum):
    """The five classical account types."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class NormalBalance(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class CashFlowSection(str, enum.Enum):
    """Which section of the Statement of Cash Flows an account rolls into.

    ``CASH`` marks the cash and cash-equivalent accounts themselves. ``NONE`` is
    used for nominal (revenue / expense) accounts, whose net effect enters the
    statement through profit for the period.
    """

    CASH = "CASH"
    OPERATING = "OPERATING"
    INVESTING = "INVESTING"
    FINANCING = "FINANCING"
    NONE = "NONE"


class EntrySide(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class EventType(str, enum.Enum):
    """Business events the system knows how to post automatically.

    Each value maps to a posting rule in :mod:`app.services.ledger`. The owner
    never picks from this list directly - the UI offers plain language ("Money
    In", "Money Out") and the backend resolves the event type.
    """

    CASH_SALE = "CASH_SALE"
    CARD_SALE = "CARD_SALE"
    EWALLET_SALE = "EWALLET_SALE"
    CREDIT_SALE = "CREDIT_SALE"
    CUSTOMER_PAYMENT = "CUSTOMER_PAYMENT"

    PURCHASE_INVENTORY_CASH = "PURCHASE_INVENTORY_CASH"
    PURCHASE_INVENTORY_CREDIT = "PURCHASE_INVENTORY_CREDIT"
    PAY_SUPPLIER = "PAY_SUPPLIER"

    EXPENSE_CASH = "EXPENSE_CASH"
    EXPENSE_CREDIT = "EXPENSE_CREDIT"
    PAY_WAGES = "PAY_WAGES"

    OWNER_CONTRIBUTION = "OWNER_CONTRIBUTION"
    OWNER_DRAWINGS = "OWNER_DRAWINGS"

    LOAN_RECEIVED = "LOAN_RECEIVED"
    LOAN_REPAYMENT = "LOAN_REPAYMENT"

    BUY_EQUIPMENT = "BUY_EQUIPMENT"
    DEPRECIATION = "DEPRECIATION"

    OPENING_INVENTORY = "OPENING_INVENTORY"
    COGS_USAGE = "COGS_USAGE"
    STOCK_WASTAGE = "STOCK_WASTAGE"
    STOCK_ADJUSTMENT_GAIN = "STOCK_ADJUSTMENT_GAIN"

    PAYROLL_ACCRUAL = "PAYROLL_ACCRUAL"
    PAY_NET_WAGES = "PAY_NET_WAGES"
    REMIT_STATUTORY = "REMIT_STATUTORY"

    BANK_DEPOSIT = "BANK_DEPOSIT"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    BANK = "BANK"
    CARD = "CARD"
    EWALLET = "EWALLET"
    CREDIT = "CREDIT"


class TransactionSource(str, enum.Enum):
    """How the transaction reached the system - useful for audit."""

    GRANDMA_UI = "GRANDMA_UI"
    ACCOUNTANT_UI = "ACCOUNTANT_UI"
    VOICE = "VOICE"
    RECEIPT_PHOTO = "RECEIPT_PHOTO"
    SYSTEM = "SYSTEM"
    SEED = "SEED"


class Role(str, enum.Enum):
    """What a signed-in person is allowed to reach.

    ``STAFF`` covers the daily screen only. Wages, profit and the ledger are
    exactly what a restaurant owner does not want a server reading over the
    counter, so those need ``OWNER`` or ``ACCOUNTANT``.
    """

    OWNER = "OWNER"
    ACCOUNTANT = "ACCOUNTANT"
    STAFF = "STAFF"


class EmploymentType(str, enum.Enum):
    PERMANENT = "PERMANENT"
    PART_TIME = "PART_TIME"
    CASUAL = "CASUAL"


class PayBasis(str, enum.Enum):
    """How an employee's basic pay is worked out."""

    MONTHLY = "MONTHLY"
    DAILY = "DAILY"
    HOURLY = "HOURLY"


class PayrollStatus(str, enum.Enum):
    """A payroll run's lifecycle.

    Only ``APPROVED`` writes to the ledger, so a run can be edited freely while
    it is still a draft without leaving corrections behind.
    """

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"


class MovementType(str, enum.Enum):
    PURCHASE = "PURCHASE"
    USAGE = "USAGE"
    WASTAGE = "WASTAGE"
    ADJUSTMENT = "ADJUSTMENT"
    OPENING = "OPENING"


# --------------------------------------------------------------------------- #
# Chart of accounts
# --------------------------------------------------------------------------- #
class Account(Base):
    """A single line in the chart of accounts.

    ``normal_balance`` tells the reporting layer which side increases the
    account. ``is_contra`` marks accounts such as Accumulated Depreciation and
    Owner's Drawings, which sit inside a parent section but carry the opposite
    normal balance.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))

    type: Mapped[AccountType] = mapped_column(Enum(AccountType), index=True)
    normal_balance: Mapped[NormalBalance] = mapped_column(Enum(NormalBalance))
    cash_flow_section: Mapped[CashFlowSection] = mapped_column(
        Enum(CashFlowSection), default=CashFlowSection.NONE
    )

    # Statement grouping, e.g. "Current Assets", "Operating Expenses".
    statement_group: Mapped[str] = mapped_column(String(60), default="")
    # Plain-language label shown in Grandma Mode instead of the accounting name.
    friendly_name: Mapped[str] = mapped_column(String(120), default="")

    is_contra: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Display order within the statement group.
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="account")

    @property
    def is_nominal(self) -> bool:
        """True for revenue / expense accounts, which close into profit."""
        return self.type in (AccountType.REVENUE, AccountType.EXPENSE)

    @property
    def is_real(self) -> bool:
        """True for balance sheet accounts, whose balances carry forward."""
        return not self.is_nominal

    def signed_balance(self, debits: Decimal, credits: Decimal) -> Decimal:
        """Return the balance in the account's own natural direction.

        A debit-normal account with more debits than credits returns a positive
        number, and so does a credit-normal account with more credits than
        debits. This keeps statement figures positive without the reporting code
        having to remember which way each account runs.
        """
        if self.normal_balance is NormalBalance.DEBIT:
            return debits - credits
        return credits - debits

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Account {self.code} {self.name}>"


# --------------------------------------------------------------------------- #
# Transactions and ledger entries
# --------------------------------------------------------------------------- #
class Transaction(Base):
    """A business event. Owns the balanced set of ledger entries it produced."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human-facing reference, e.g. "TXN-2026-000042".
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)

    event_type: Mapped[EventType] = mapped_column(Enum(EventType), index=True)
    txn_date: Mapped[date] = mapped_column(Date, index=True)

    # The headline amount as the owner understands it. The ledger entries carry
    # the authoritative figures; this is for display and for quick filtering.
    amount: Mapped[Decimal] = mapped_column(MONEY)

    description: Mapped[str] = mapped_column(String(255), default="")
    counterparty: Mapped[str] = mapped_column(String(120), default="")
    payment_method: Mapped[PaymentMethod | None] = mapped_column(
        Enum(PaymentMethod), nullable=True
    )
    source: Mapped[TransactionSource] = mapped_column(
        Enum(TransactionSource), default=TransactionSource.GRANDMA_UI
    )

    # Free-text the owner spoke or typed, kept verbatim for audit.
    raw_input: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    # Reversals keep an audit trail instead of deleting history.
    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    reverses_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="LedgerEntry.id",
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )
    movements: Mapped[list["InventoryMovement"]] = relationship(
        back_populates="transaction"
    )
    reverses: Mapped["Transaction | None"] = relationship(
        remote_side=[id], back_populates="reversed_by"
    )
    reversed_by: Mapped[list["Transaction"]] = relationship(back_populates="reverses")

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_transaction_amount_non_negative"),
        Index("ix_transactions_date_event", "txn_date", "event_type"),
    )

    @property
    def total_debits(self) -> Decimal:
        return sum(
            (e.amount for e in self.entries if e.side is EntrySide.DEBIT), Decimal("0.00")
        )

    @property
    def total_credits(self) -> Decimal:
        return sum(
            (e.amount for e in self.entries if e.side is EntrySide.CREDIT), Decimal("0.00")
        )

    @property
    def is_balanced(self) -> bool:
        return self.total_debits == self.total_credits

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Transaction {self.reference} {self.event_type.value} {self.amount}>"


class LedgerEntry(Base):
    """One leg of a double entry: an amount posted to one side of one account."""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)

    side: Mapped[EntrySide] = mapped_column(Enum(EntrySide))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    memo: Mapped[str] = mapped_column(String(255), default="")

    # Denormalised for fast statement queries without joining transactions.
    entry_date: Mapped[date] = mapped_column(Date, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    transaction: Mapped["Transaction"] = relationship(back_populates="entries")
    account: Mapped["Account"] = relationship(back_populates="entries")

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_ledger_entry_amount_positive"),
        Index("ix_ledger_entries_account_date", "account_id", "entry_date"),
    )

    @property
    def debit(self) -> Decimal:
        return self.amount if self.side is EntrySide.DEBIT else Decimal("0.00")

    @property
    def credit(self) -> Decimal:
        return self.amount if self.side is EntrySide.CREDIT else Decimal("0.00")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<LedgerEntry {self.side.value} {self.amount} acct={self.account_id}>"


class Attachment(Base):
    """A receipt photo (or any file) attached to a transaction."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True, index=True
    )

    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    transaction: Mapped["Transaction | None"] = relationship(back_populates="attachments")


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
class InventoryItem(Base):
    """A stocked ingredient or supply, valued at weighted-average cost."""

    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    # What the owner calls it out loud, used by the voice parser.
    local_name: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[str] = mapped_column(String(60), default="Ingredients")
    unit: Mapped[str] = mapped_column(String(20), default="kg")

    quantity_on_hand: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0.000"))
    # Weighted-average unit cost, recalculated on every purchase.
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0.0000"))

    # Stock levels that drive the colour-coded alerts in the UI.
    reorder_level: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0.000"))
    par_level: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0.000"))

    emoji: Mapped[str] = mapped_column(String(8), default="\N{PACKAGE}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    movements: Mapped[list["InventoryMovement"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="InventoryMovement.id"
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_inventory_item_name"),
        CheckConstraint("par_level >= 0", name="ck_inventory_par_non_negative"),
    )

    @property
    def stock_value(self) -> Decimal:
        """Carrying value of the stock on hand."""
        return (self.quantity_on_hand * self.unit_cost).quantize(Decimal("0.01"))

    @property
    def stock_ratio(self) -> float:
        """Fraction of the par (ideal) level currently held, capped at 1.0."""
        par = float(self.par_level or 0)
        if par <= 0:
            return 1.0
        return min(float(self.quantity_on_hand) / par, 1.0)

    @property
    def status(self) -> str:
        """Colour band used by the UI: ``ok``, ``low`` or ``critical``."""
        if self.quantity_on_hand <= 0:
            return "critical"
        if self.reorder_level and self.quantity_on_hand <= self.reorder_level:
            return "critical" if self.stock_ratio < 0.15 else "low"
        ratio = self.stock_ratio
        if ratio < 0.15:
            return "critical"
        if ratio < 0.40:
            return "low"
        return "ok"

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<InventoryItem {self.name} {self.quantity_on_hand}{self.unit}>"


class InventoryMovement(Base):
    """An immutable record of stock going in or out.

    Every movement that changes stock value also has a matching ledger posting,
    which is how inventory stays tied to Cost of Goods Sold.
    """

    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True
    )
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True, index=True
    )

    movement_type: Mapped[MovementType] = mapped_column(Enum(MovementType))
    movement_date: Mapped[date] = mapped_column(Date, index=True)

    # Positive for stock in, negative for stock out.
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0.0000"))
    total_cost: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))

    # Running balance after this movement, for a readable stock card.
    balance_after: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0.000"))

    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    item: Mapped["InventoryItem"] = relationship(back_populates="movements")
    transaction: Mapped["Transaction | None"] = relationship(back_populates="movements")


class StockCount(Base):
    """A physical count. The variance against book stock becomes COGS."""

    __tablename__ = "stock_counts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )

    count_date: Mapped[date] = mapped_column(Date, index=True)
    expected_quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    counted_quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    variance: Mapped[Decimal] = mapped_column(QUANTITY)
    variance_value: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))

    # Whether the shortfall was treated as normal usage or as spoilage.
    treated_as: Mapped[MovementType] = mapped_column(
        Enum(MovementType), default=MovementType.USAGE
    )
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    item: Mapped["InventoryItem"] = relationship()


# --------------------------------------------------------------------------- #
# Payroll
# --------------------------------------------------------------------------- #
class Employee(Base):
    """Someone on the payroll.

    The statutory flags matter more than they look. Malaysian contribution rules
    differ by age (the EPF rate changes at 60) and by whether the worker is a
    local or a foreign national (EIS does not apply to foreign workers), so both
    are stored per employee rather than assumed.
    """

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    # What the owner actually calls them.
    nickname: Mapped[str] = mapped_column(String(60), default="")
    position: Mapped[str] = mapped_column(String(80), default="Kitchen Staff")

    employment_type: Mapped[EmploymentType] = mapped_column(
        Enum(EmploymentType), default=EmploymentType.PERMANENT
    )
    pay_basis: Mapped[PayBasis] = mapped_column(Enum(PayBasis), default=PayBasis.MONTHLY)
    # Monthly salary, daily rate or hourly rate depending on ``pay_basis``.
    base_rate: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    # Fixed monthly allowances (meals, transport) paid on top of basic pay.
    fixed_allowance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    overtime_rate: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))

    # Statutory treatment.
    contributes_statutory: Mapped[bool] = mapped_column(Boolean, default=True)
    is_local: Mapped[bool] = mapped_column(Boolean, default=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Reference numbers, kept for the payslip and the statutory returns.
    ic_number: Mapped[str] = mapped_column(String(30), default="")
    epf_number: Mapped[str] = mapped_column(String(30), default="")
    socso_number: Mapped[str] = mapped_column(String(30), default="")
    tax_number: Mapped[str] = mapped_column(String(30), default="")
    bank_name: Mapped[str] = mapped_column(String(60), default="")
    bank_account: Mapped[str] = mapped_column(String(40), default="")

    joined_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    left_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    payslips: Mapped[list["Payslip"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("base_rate >= 0", name="ck_employee_base_rate_non_negative"),
    )

    def age_at(self, on: date) -> int | None:
        if self.date_of_birth is None:
            return None
        born = self.date_of_birth
        return on.year - born.year - ((on.month, on.day) < (born.month, born.day))

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Employee {self.name} {self.position}>"


class PayrollRun(Base):
    """One pay period for the whole team.

    A run stays editable while it is a draft. Approving it posts a single
    balanced accrual to the ledger; paying it settles the net wages. Statutory
    money is remitted separately, because in practice KWSP, PERKESO and LHDN are
    each paid on their own schedule.
    """

    __tablename__ = "payroll_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)

    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    pay_date: Mapped[date] = mapped_column(Date)

    status: Mapped[PayrollStatus] = mapped_column(
        Enum(PayrollStatus), default=PayrollStatus.DRAFT, index=True
    )

    accrual_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )
    payment_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )

    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payslips: Mapped[list["Payslip"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Payslip.id"
    )

    __table_args__ = (
        UniqueConstraint("period_start", "period_end", name="uq_payroll_run_period"),
    )

    @property
    def is_editable(self) -> bool:
        return self.status is PayrollStatus.DRAFT

    def total(self, field: str) -> Decimal:
        return sum(
            (getattr(slip, field) for slip in self.payslips), Decimal("0.00")
        ).quantize(Decimal("0.01"))


class Payslip(Base):
    """One employee's pay for one run, with every figure kept separately.

    Storing each component rather than only the net means a payslip can be
    reprinted, audited and explained years later, even if the contribution rates
    have changed in the meantime.
    """

    __tablename__ = "payslips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)

    # Inputs.
    days_worked: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0.000"))
    hours_worked: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0.000"))
    overtime_hours: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0.000"))

    # Earnings.
    basic_pay: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    overtime_pay: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    allowances: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    bonus: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    gross_pay: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))

    # Employee deductions.
    epf_employee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    socso_employee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    eis_employee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    tax_deduction: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    other_deductions: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))

    # Employer contributions - a cost to the business, not a deduction.
    epf_employer: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    socso_employer: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    eis_employer: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))

    net_pay: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))

    note: Mapped[str] = mapped_column(String(255), default="")

    run: Mapped["PayrollRun"] = relationship(back_populates="payslips")
    employee: Mapped["Employee"] = relationship(back_populates="payslips")

    __table_args__ = (
        UniqueConstraint("run_id", "employee_id", name="uq_payslip_run_employee"),
    )

    @property
    def total_deductions(self) -> Decimal:
        return (
            self.epf_employee
            + self.socso_employee
            + self.eis_employee
            + self.tax_deduction
            + self.other_deductions
        ).quantize(Decimal("0.01"))

    @property
    def employer_contributions(self) -> Decimal:
        return (self.epf_employer + self.socso_employer + self.eis_employer).quantize(
            Decimal("0.01")
        )

    @property
    def employer_cost(self) -> Decimal:
        """What the employee actually costs the restaurant."""
        return (self.gross_pay + self.employer_contributions).quantize(Decimal("0.01"))


# --------------------------------------------------------------------------- #
# Accounts and access
# --------------------------------------------------------------------------- #
class User(Base):
    """Someone who can sign in.

    Identity comes from Google, so there is no password here to store, reset or
    leak. What is stored is the Google subject id - a stable identifier that
    survives the person changing their email address, which the email itself
    does not.

    The PIN is separate from identity. It does not say *who* you are; it gates
    the financial side of the app on *this device*, which is the boundary that
    actually matters when a tablet sits unlocked beside the till all day.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Google's subject claim: stable across email changes, unlike the address.
    google_sub: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    picture_url: Mapped[str] = mapped_column(String(500), default="")

    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.STAFF, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # PIN gate for Accountant Mode. Never stored in the clear.
    pin_hash: Mapped[str] = mapped_column(String(255), default="")
    pin_set_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Failed attempts are counted so a four-digit PIN cannot simply be guessed.
    pin_attempts: Mapped[int] = mapped_column(Integer, default=0)
    pin_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def has_pin(self) -> bool:
        return bool(self.pin_hash)

    @property
    def can_see_finances(self) -> bool:
        return self.role in (Role.OWNER, Role.ACCOUNTANT)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User {self.email} {self.role.value}>"
