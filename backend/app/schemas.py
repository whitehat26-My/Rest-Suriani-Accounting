"""Pydantic request/response models for the API layer."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import (
    AccountType,
    CashFlowSection,
    EmploymentType,
    EntrySide,
    EventType,
    MovementType,
    NormalBalance,
    PayBasis,
    PaymentMethod,
    PayrollStatus,
    Role,
    TransactionSource,
)

ORM = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
class AccountOut(BaseModel):
    model_config = ORM

    id: int
    code: str
    name: str
    friendly_name: str
    type: AccountType
    normal_balance: NormalBalance
    cash_flow_section: CashFlowSection
    statement_group: str
    is_contra: bool
    is_active: bool


class AccountBalanceOut(AccountOut):
    debits: Decimal
    credits: Decimal
    balance: Decimal


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
class LedgerEntryOut(BaseModel):
    model_config = ORM

    id: int
    account_id: int
    account_code: str
    account_name: str
    side: EntrySide
    amount: Decimal
    memo: str


class AttachmentOut(BaseModel):
    model_config = ORM

    id: int
    filename: str
    content_type: str
    size_bytes: int
    url: str


class TransactionCreate(BaseModel):
    """Full-control transaction entry, used by Accountant Mode and internally.

    Grandma Mode never builds one of these by hand - :class:`QuickEntry` is
    translated into one by the backend.
    """

    event_type: EventType
    amount: Decimal = Field(gt=0, description="Headline amount, always positive")
    txn_date: date | None = None
    description: str = ""
    counterparty: str = ""
    payment_method: PaymentMethod | None = None
    source: TransactionSource = TransactionSource.ACCOUNTANT_UI

    # Optional refinements consumed by specific posting rules.
    expense_account_code: str | None = Field(
        default=None, description="Which expense account to hit for EXPENSE_* events"
    )
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    fee_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    cogs_amount: Decimal = Field(
        default=Decimal("0.00"), ge=0, description="Cost of the goods sold in this sale"
    )
    interest_amount: Decimal = Field(default=Decimal("0.00"), ge=0)

    # Inventory linkage for purchase events.
    inventory_item_id: int | None = None
    quantity: Decimal | None = Field(default=None, gt=0)

    # Which liability a REMIT_STATUTORY payment settles.
    liability_account_code: str | None = None
    # Named component amounts for multi-leg events such as PAYROLL_ACCRUAL,
    # where a single headline figure cannot describe the entry.
    components: dict[str, Decimal] = Field(default_factory=dict)

    raw_input: str = ""
    notes: str = ""
    attachment_ids: list[int] = Field(default_factory=list)

    @field_validator("amount", "tax_amount", "fee_amount", "cogs_amount", "interest_amount")
    @classmethod
    def _quantize(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))


class TransactionOut(BaseModel):
    model_config = ORM

    id: int
    reference: str
    event_type: EventType
    txn_date: date
    amount: Decimal
    description: str
    counterparty: str
    payment_method: PaymentMethod | None
    source: TransactionSource
    raw_input: str
    notes: str
    is_reversed: bool
    created_at: datetime
    entries: list[LedgerEntryOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)

    # Plain-language summary for Grandma Mode ("Money in - RM120 from customers").
    friendly_summary: str = ""
    # The same thing without the amount, for lists that show the figure alongside.
    friendly_label: str = ""
    direction: str = "neutral"  # "in", "out" or "neutral"


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- #
# Grandma Mode: quick entry
# --------------------------------------------------------------------------- #
class QuickEntry(BaseModel):
    """The only shape Grandma Mode ever sends.

    ``kind`` is "in" or "out"; everything else is optional. The backend picks the
    event type, the accounts and the double entry.
    """

    kind: str = Field(pattern="^(in|out)$")
    amount: Decimal = Field(gt=0)
    # For money in: how the customer paid. For money out: how we paid.
    method: PaymentMethod = PaymentMethod.CASH
    # For money out: one of the friendly slugs in SPENDING_CATEGORIES.
    category: str | None = None
    note: str = ""
    counterparty: str = ""
    txn_date: date | None = None
    raw_input: str = ""
    source: TransactionSource = TransactionSource.GRANDMA_UI
    attachment_ids: list[int] = Field(default_factory=list)
    # Optional: link a "Food & Ingredients" spend to a stock item so the
    # quantity bought is added to inventory.
    inventory_item_id: int | None = None
    quantity: Decimal | None = Field(default=None, gt=0)

    @field_validator("amount")
    @classmethod
    def _quantize(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))


class SpendingCategoryOut(BaseModel):
    slug: str
    label: str
    emoji: str
    account_code: str


# --------------------------------------------------------------------------- #
# Voice / natural language
# --------------------------------------------------------------------------- #
class VoiceParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class VoiceParseResponse(BaseModel):
    understood: bool
    confidence: float
    kind: str | None = None          # "in" | "out"
    amount: Decimal | None = None
    category: str | None = None
    category_label: str | None = None
    method: PaymentMethod = PaymentMethod.CASH
    inventory_item_id: int | None = None
    inventory_item_name: str | None = None
    inventory_item_unit: str | None = None
    quantity: Decimal | None = None
    note: str = ""
    # A sentence read back to the owner for confirmation.
    confirmation: str = ""
    original_text: str = ""


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
class InventoryItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    local_name: str = ""
    category: str = "Ingredients"
    unit: str = "kg"
    reorder_level: Decimal = Field(default=Decimal("0"), ge=0)
    par_level: Decimal = Field(default=Decimal("0"), ge=0)
    emoji: str = "\N{PACKAGE}"


class InventoryItemCreate(InventoryItemBase):
    opening_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    opening_unit_cost: Decimal = Field(default=Decimal("0"), ge=0)


class InventoryItemUpdate(BaseModel):
    name: str | None = None
    local_name: str | None = None
    category: str | None = None
    unit: str | None = None
    reorder_level: Decimal | None = Field(default=None, ge=0)
    par_level: Decimal | None = Field(default=None, ge=0)
    emoji: str | None = None
    is_active: bool | None = None


class InventoryItemOut(BaseModel):
    model_config = ORM

    id: int
    name: str
    local_name: str
    category: str
    unit: str
    quantity_on_hand: Decimal
    unit_cost: Decimal
    reorder_level: Decimal
    par_level: Decimal
    emoji: str
    is_active: bool
    stock_value: Decimal
    stock_ratio: float
    status: str
    days_of_cover: float | None = None


class InventoryMovementOut(BaseModel):
    model_config = ORM

    id: int
    item_id: int
    movement_type: MovementType
    movement_date: date
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    balance_after: Decimal
    note: str
    transaction_id: int | None


class StockPurchase(BaseModel):
    """Buying stock: increases quantity and recalculates weighted-average cost."""

    item_id: int
    quantity: Decimal = Field(gt=0)
    total_cost: Decimal = Field(gt=0)
    paid: bool = True
    method: PaymentMethod = PaymentMethod.CASH
    supplier: str = ""
    txn_date: date | None = None
    note: str = ""


class StockCountEntry(BaseModel):
    item_id: int
    counted_quantity: Decimal = Field(ge=0)
    treat_shortfall_as: MovementType = MovementType.USAGE


class StockCountCreate(BaseModel):
    """A physical count of one or more items. Shortfalls post to COGS/wastage."""

    counts: list[StockCountEntry] = Field(min_length=1)
    count_date: date | None = None
    note: str = ""


class StockCountResultOut(BaseModel):
    item_id: int
    item_name: str
    expected_quantity: Decimal
    counted_quantity: Decimal
    variance: Decimal
    variance_value: Decimal
    treated_as: MovementType
    transaction_reference: str | None = None


# --------------------------------------------------------------------------- #
# Financial statements
# --------------------------------------------------------------------------- #
class StatementLine(BaseModel):
    label: str
    amount: Decimal
    account_code: str | None = None
    # Presentation hints for the frontend.
    level: int = 0
    is_total: bool = False
    is_subtotal: bool = False
    note: str = ""


class StatementSection(BaseModel):
    title: str
    lines: list[StatementLine] = Field(default_factory=list)
    total: Decimal = Decimal("0.00")


class IncomeStatementOut(BaseModel):
    business_name: str
    currency: str
    period_start: date
    period_end: date
    sections: list[StatementSection]
    revenue: Decimal
    cost_of_sales: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    operating_profit: Decimal
    finance_costs: Decimal
    net_profit: Decimal
    gross_margin_pct: float
    net_margin_pct: float


class BalanceSheetOut(BaseModel):
    business_name: str
    currency: str
    as_of: date
    sections: list[StatementSection]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    balances: bool
    difference: Decimal


class CashFlowOut(BaseModel):
    business_name: str
    currency: str
    period_start: date
    period_end: date
    sections: list[StatementSection]
    net_operating: Decimal
    net_investing: Decimal
    net_financing: Decimal
    net_change: Decimal
    opening_cash: Decimal
    closing_cash: Decimal
    reconciles: bool


class TrialBalanceRow(BaseModel):
    code: str
    name: str
    type: AccountType
    debit: Decimal
    credit: Decimal


class TrialBalanceOut(BaseModel):
    as_of: date
    rows: list[TrialBalanceRow]
    total_debit: Decimal
    total_credit: Decimal
    balanced: bool


class GeneralLedgerRow(BaseModel):
    date: date
    reference: str
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


class GeneralLedgerOut(BaseModel):
    account: AccountOut
    period_start: date
    period_end: date
    opening_balance: Decimal
    rows: list[GeneralLedgerRow]
    closing_balance: Decimal


# --------------------------------------------------------------------------- #
# Dashboards and financial evaluation
# --------------------------------------------------------------------------- #
class DailySummaryOut(BaseModel):
    """The single screen Grandma Mode shows: today at a glance."""

    day: date
    money_in: Decimal
    money_out: Decimal
    net: Decimal
    cash_on_hand: Decimal
    transaction_count: int
    # Traffic-light verdict: "good", "watch", "bad".
    verdict: str
    verdict_message: str
    low_stock_count: int
    recent: list[TransactionOut] = Field(default_factory=list)


class TrendPoint(BaseModel):
    day: date
    money_in: Decimal
    money_out: Decimal
    net: Decimal
    cumulative_cash: Decimal


class MetricOut(BaseModel):
    key: str
    label: str
    value: float | None
    display: str
    unit: str = ""
    # "good" | "watch" | "bad" | "neutral"
    rating: str = "neutral"
    benchmark: str = ""
    explanation: str = ""


class SuggestionOut(BaseModel):
    severity: str  # "critical" | "warning" | "info" | "positive"
    title: str
    message: str
    action: str = ""
    metric_key: str = ""


class FinancialEvaluationOut(BaseModel):
    period_start: date
    period_end: date
    health_score: int = Field(ge=0, le=100)
    health_grade: str
    headline: str
    working_capital: Decimal
    current_ratio: float | None
    quick_ratio: float | None
    cash_runway_days: float | None
    average_daily_burn: Decimal
    metrics: list[MetricOut]
    suggestions: list[SuggestionOut]
    trend: list[TrendPoint]


class ExpenseBreakdownItem(BaseModel):
    account_code: str
    label: str
    friendly_label: str
    amount: Decimal
    percentage: float


class AccountantDashboardOut(BaseModel):
    period_start: date
    period_end: date
    income_statement: IncomeStatementOut
    balance_sheet: BalanceSheetOut
    cash_flow: CashFlowOut
    evaluation: FinancialEvaluationOut
    expense_breakdown: list[ExpenseBreakdownItem]
    revenue_by_day: list[TrendPoint]
    inventory_value: Decimal
    low_stock: list[InventoryItemOut]


# --------------------------------------------------------------------------- #
# Payroll
# --------------------------------------------------------------------------- #
class EmployeeBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    nickname: str = ""
    position: str = "Kitchen Staff"
    employment_type: EmploymentType = EmploymentType.PERMANENT
    pay_basis: PayBasis = PayBasis.MONTHLY
    base_rate: Decimal = Field(default=Decimal("0.00"), ge=0)
    fixed_allowance: Decimal = Field(default=Decimal("0.00"), ge=0)
    overtime_rate: Decimal = Field(default=Decimal("0.00"), ge=0)
    contributes_statutory: bool = True
    is_local: bool = True
    date_of_birth: date | None = None
    ic_number: str = ""
    epf_number: str = ""
    socso_number: str = ""
    tax_number: str = ""
    bank_name: str = ""
    bank_account: str = ""
    joined_on: date | None = None


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    name: str | None = None
    nickname: str | None = None
    position: str | None = None
    employment_type: EmploymentType | None = None
    pay_basis: PayBasis | None = None
    base_rate: Decimal | None = Field(default=None, ge=0)
    fixed_allowance: Decimal | None = Field(default=None, ge=0)
    overtime_rate: Decimal | None = Field(default=None, ge=0)
    contributes_statutory: bool | None = None
    is_local: bool | None = None
    date_of_birth: date | None = None
    ic_number: str | None = None
    epf_number: str | None = None
    socso_number: str | None = None
    tax_number: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    joined_on: date | None = None
    left_on: date | None = None
    is_active: bool | None = None


class EmployeeOut(EmployeeBase):
    model_config = ORM

    id: int
    left_on: date | None = None
    is_active: bool


class PayslipUpdate(BaseModel):
    """The only fields a payroll clerk edits; everything else is derived."""

    days_worked: Decimal | None = Field(default=None, ge=0)
    hours_worked: Decimal | None = Field(default=None, ge=0)
    overtime_hours: Decimal | None = Field(default=None, ge=0)
    allowances: Decimal | None = Field(default=None, ge=0)
    bonus: Decimal | None = Field(default=None, ge=0)
    tax_deduction: Decimal | None = Field(default=None, ge=0)
    other_deductions: Decimal | None = Field(default=None, ge=0)
    note: str | None = None


class PayslipOut(BaseModel):
    model_config = ORM

    id: int
    employee_id: int
    employee_name: str
    position: str
    pay_basis: PayBasis

    days_worked: Decimal
    hours_worked: Decimal
    overtime_hours: Decimal

    basic_pay: Decimal
    overtime_pay: Decimal
    allowances: Decimal
    bonus: Decimal
    gross_pay: Decimal

    epf_employee: Decimal
    socso_employee: Decimal
    eis_employee: Decimal
    tax_deduction: Decimal
    other_deductions: Decimal
    total_deductions: Decimal

    epf_employer: Decimal
    socso_employer: Decimal
    eis_employer: Decimal
    employer_contributions: Decimal
    employer_cost: Decimal

    net_pay: Decimal
    note: str


class PayrollRunCreate(BaseModel):
    period_start: date
    period_end: date
    pay_date: date | None = None
    # Pre-fills the days column for anyone paid a daily rate.
    default_days_worked: Decimal = Field(default=Decimal("26"), ge=0)
    notes: str = ""


class PayrollTotals(BaseModel):
    basic_pay: Decimal
    overtime_pay: Decimal
    allowances: Decimal
    bonus: Decimal
    gross_pay: Decimal
    epf_employee: Decimal
    epf_employer: Decimal
    socso_employee: Decimal
    socso_employer: Decimal
    eis_employee: Decimal
    eis_employer: Decimal
    tax_deduction: Decimal
    other_deductions: Decimal
    employee_deductions: Decimal
    employer_contributions: Decimal
    employer_cost: Decimal
    net_pay: Decimal


class PayrollRunOut(BaseModel):
    model_config = ORM

    id: int
    reference: str
    period_start: date
    period_end: date
    pay_date: date
    status: PayrollStatus
    notes: str
    accrual_transaction_id: int | None
    payment_transaction_id: int | None
    headcount: int
    payslips: list[PayslipOut]
    totals: PayrollTotals
    # Cash wage payments recorded outside this run in the same period, which
    # would otherwise be counted twice.
    ad_hoc_wage_warnings: list[str] = Field(default_factory=list)


class PayrollRunSummary(BaseModel):
    id: int
    reference: str
    period_start: date
    period_end: date
    pay_date: date
    status: PayrollStatus
    headcount: int
    gross_pay: Decimal
    employer_cost: Decimal
    net_pay: Decimal


class StatutoryRemittance(BaseModel):
    body: str = Field(pattern="^(EPF|SOCSO|EIS|TAX)$")
    amount: Decimal = Field(gt=0)
    on: date | None = None
    method: PaymentMethod = PaymentMethod.BANK


class PayrollOverviewOut(BaseModel):
    """What the payroll panel needs in a single call."""

    runs: list[PayrollRunSummary]
    current: PayrollRunOut | None
    employees: list[EmployeeOut]
    outstanding_statutory: dict[str, Decimal]
    # Labour cost for the reporting period, straight from the ledger.
    period_wage_cost: Decimal
    period_employer_contributions: Decimal
    rules_label: str


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
class UserOut(BaseModel):
    model_config = ORM

    id: int
    email: str
    name: str
    picture_url: str
    role: Role
    is_active: bool
    has_pin: bool
    can_see_finances: bool


class AuthStatusOut(BaseModel):
    """Everything the frontend needs to decide what to show."""

    # False when Google sign-in is not configured, in which case the app runs
    # open as a single-user local tool.
    auth_enabled: bool
    signed_in: bool
    user: UserOut | None = None
    # Whether Accountant Mode is currently unlocked on this device.
    unlocked: bool = False
    # Whether a PIN has to be entered to open Accountant Mode at all.
    pin_required: bool = False
    login_url: str = "/api/auth/google/login"


class PinSet(BaseModel):
    new_pin: str = Field(min_length=4, max_length=8)
    current_pin: str | None = None


class PinVerify(BaseModel):
    pin: str = Field(min_length=4, max_length=8)


class RoleUpdate(BaseModel):
    role: Role
