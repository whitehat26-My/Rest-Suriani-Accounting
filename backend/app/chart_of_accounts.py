"""The default chart of accounts for a small restaurant.

Codes follow the conventional blocks: 1xxx assets, 2xxx liabilities, 3xxx
equity, 4xxx revenue, 5xxx cost of sales, 6xxx operating expenses. Every
account carries a ``friendly_name`` so Grandma Mode can show "Money in the till"
where the accountant sees "Cash on Hand".

The ``cash_flow_section`` on each balance sheet account is what lets the
Statement of Cash Flows be generated generically - see
:mod:`app.services.statements`.
"""
from __future__ import annotations

from typing import NamedTuple

from .models import AccountType, CashFlowSection, NormalBalance

A, L, E, R, X = (
    AccountType.ASSET,
    AccountType.LIABILITY,
    AccountType.EQUITY,
    AccountType.REVENUE,
    AccountType.EXPENSE,
)
DR, CR = NormalBalance.DEBIT, NormalBalance.CREDIT
CASH, OPS, INV, FIN, NONE = (
    CashFlowSection.CASH,
    CashFlowSection.OPERATING,
    CashFlowSection.INVESTING,
    CashFlowSection.FINANCING,
    CashFlowSection.NONE,
)


class AccountSpec(NamedTuple):
    code: str
    name: str
    type: AccountType
    normal_balance: NormalBalance
    cash_flow_section: CashFlowSection
    statement_group: str
    friendly_name: str
    is_contra: bool = False
    sort_order: int = 0


# Well-known codes referenced by the posting rules. Keeping them as named
# constants means a rename in the chart never silently breaks the ledger.
CASH_ON_HAND = "1000"
BANK = "1010"
ACCOUNTS_RECEIVABLE = "1100"
INVENTORY = "1200"
PREPAID_EXPENSES = "1300"
EQUIPMENT = "1500"
ACCUM_DEPRECIATION = "1510"

STAFF_ADVANCES = "1150"

ACCOUNTS_PAYABLE = "2000"
ACCRUED_EXPENSES = "2100"
SST_PAYABLE = "2200"
NET_WAGES_PAYABLE = "2300"
EPF_PAYABLE = "2310"
SOCSO_PAYABLE = "2320"
EIS_PAYABLE = "2330"
TAX_PAYABLE = "2340"
LOAN_PAYABLE = "2500"

OWNER_CAPITAL = "3000"
OWNER_DRAWINGS = "3100"

SALES = "4000"
OTHER_INCOME = "4100"

COGS = "5000"
WASTAGE = "5010"

WAGES = "6000"
EMPLOYER_STATUTORY = "6010"
RENT = "6100"
UTILITIES = "6200"
SUPPLIES = "6300"
REPAIRS = "6400"
MARKETING = "6500"
LICENSES = "6600"
DEPRECIATION_EXPENSE = "6700"
BANK_FEES = "6800"
TRANSPORT = "6850"
INTEREST_EXPENSE = "6880"
OTHER_EXPENSE = "6900"


DEFAULT_ACCOUNTS: list[AccountSpec] = [
    # ---------------- Assets ----------------
    AccountSpec(CASH_ON_HAND, "Cash on Hand", A, DR, CASH, "Current Assets", "Money in the till", sort_order=10),
    AccountSpec(BANK, "Bank Account", A, DR, CASH, "Current Assets", "Money in the bank", sort_order=20),
    AccountSpec(ACCOUNTS_RECEIVABLE, "Accounts Receivable", A, DR, OPS, "Current Assets", "Money customers owe us", sort_order=30),
    AccountSpec(INVENTORY, "Inventory - Food & Beverage", A, DR, OPS, "Current Assets", "Food in the store room", sort_order=40),
    AccountSpec(STAFF_ADVANCES, "Staff Advances", A, DR, OPS, "Current Assets", "Money lent to workers", sort_order=45),
    AccountSpec(PREPAID_EXPENSES, "Prepaid Expenses", A, DR, OPS, "Current Assets", "Things paid for early", sort_order=50),
    AccountSpec(EQUIPMENT, "Kitchen Equipment", A, DR, INV, "Non-Current Assets", "Kitchen machines", sort_order=60),
    AccountSpec(
        ACCUM_DEPRECIATION, "Accumulated Depreciation - Equipment", A, CR, OPS,
        "Non-Current Assets", "Wear and tear on machines", is_contra=True, sort_order=70,
    ),
    # ---------------- Liabilities ----------------
    AccountSpec(ACCOUNTS_PAYABLE, "Accounts Payable", L, CR, OPS, "Current Liabilities", "Money we owe suppliers", sort_order=10),
    AccountSpec(ACCRUED_EXPENSES, "Accrued Expenses", L, CR, OPS, "Current Liabilities", "Bills not paid yet", sort_order=20),
    AccountSpec(SST_PAYABLE, "SST Payable", L, CR, OPS, "Current Liabilities", "Tax we collected for the government", sort_order=30),
    AccountSpec(NET_WAGES_PAYABLE, "Net Wages Payable", L, CR, OPS, "Current Liabilities", "Wages not handed over yet", sort_order=32),
    AccountSpec(EPF_PAYABLE, "EPF Payable", L, CR, OPS, "Current Liabilities", "EPF to send to KWSP", sort_order=33),
    AccountSpec(SOCSO_PAYABLE, "SOCSO Payable", L, CR, OPS, "Current Liabilities", "SOCSO to send to PERKESO", sort_order=34),
    AccountSpec(EIS_PAYABLE, "EIS Payable", L, CR, OPS, "Current Liabilities", "EIS to send to PERKESO", sort_order=35),
    AccountSpec(TAX_PAYABLE, "PCB / Income Tax Payable", L, CR, OPS, "Current Liabilities", "Worker tax to send to LHDN", sort_order=36),
    AccountSpec(LOAN_PAYABLE, "Loan Payable", L, CR, FIN, "Non-Current Liabilities", "Bank loan", sort_order=40),
    # ---------------- Equity ----------------
    AccountSpec(OWNER_CAPITAL, "Owner's Capital", E, CR, FIN, "Equity", "Money I put in", sort_order=10),
    AccountSpec(
        OWNER_DRAWINGS, "Owner's Drawings", E, DR, FIN, "Equity",
        "Money I took out", is_contra=True, sort_order=20,
    ),
    # ---------------- Revenue ----------------
    AccountSpec(SALES, "Food & Beverage Sales", R, CR, NONE, "Revenue", "Money from customers", sort_order=10),
    AccountSpec(OTHER_INCOME, "Other Income", R, CR, NONE, "Revenue", "Other money in", sort_order=20),
    # ---------------- Cost of sales ----------------
    AccountSpec(COGS, "Cost of Goods Sold", X, DR, NONE, "Cost of Sales", "Cost of the food we sold", sort_order=10),
    AccountSpec(WASTAGE, "Inventory Wastage & Spoilage", X, DR, NONE, "Cost of Sales", "Food thrown away", sort_order=20),
    # ---------------- Operating expenses ----------------
    AccountSpec(WAGES, "Salaries & Wages", X, DR, NONE, "Operating Expenses", "Pay for workers", sort_order=10),
    AccountSpec(EMPLOYER_STATUTORY, "Employer Statutory Contributions", X, DR, NONE, "Operating Expenses", "EPF and SOCSO we pay for workers", sort_order=15),
    AccountSpec(RENT, "Rent Expense", X, DR, NONE, "Operating Expenses", "Shop rent", sort_order=20),
    AccountSpec(UTILITIES, "Utilities Expense", X, DR, NONE, "Operating Expenses", "Electric, water, gas", sort_order=30),
    AccountSpec(SUPPLIES, "Supplies & Consumables", X, DR, NONE, "Operating Expenses", "Packaging, soap, gloves", sort_order=40),
    AccountSpec(REPAIRS, "Repairs & Maintenance", X, DR, NONE, "Operating Expenses", "Fixing things", sort_order=50),
    AccountSpec(MARKETING, "Marketing & Promotion", X, DR, NONE, "Operating Expenses", "Advertising", sort_order=60),
    AccountSpec(LICENSES, "Licenses & Permits", X, DR, NONE, "Operating Expenses", "Council licence", sort_order=70),
    AccountSpec(DEPRECIATION_EXPENSE, "Depreciation Expense", X, DR, NONE, "Operating Expenses", "Machines getting old", sort_order=80),
    AccountSpec(BANK_FEES, "Bank & Payment Fees", X, DR, NONE, "Operating Expenses", "Card machine charges", sort_order=90),
    AccountSpec(TRANSPORT, "Transport & Delivery", X, DR, NONE, "Operating Expenses", "Petrol and delivery", sort_order=100),
    AccountSpec(INTEREST_EXPENSE, "Interest Expense", X, DR, NONE, "Finance Costs", "Loan interest", sort_order=110),
    AccountSpec(OTHER_EXPENSE, "Other Operating Expense", X, DR, NONE, "Operating Expenses", "Anything else", sort_order=120),
]


# Friendly spending categories offered in Grandma Mode, mapped to real accounts.
# Each tuple is (slug, button label, emoji, account code).
SPENDING_CATEGORIES: list[tuple[str, str, str, str]] = [
    ("ingredients", "Food & Ingredients", "\N{POULTRY LEG}", INVENTORY),
    ("wages", "Worker Pay", "\N{BUST IN SILHOUETTE}", WAGES),
    ("rent", "Shop Rent", "\N{HOUSE BUILDING}", RENT),
    ("utilities", "Electric & Water", "\N{HIGH VOLTAGE SIGN}", UTILITIES),
    ("gas", "Cooking Gas", "\N{FIRE}", UTILITIES),
    ("supplies", "Packaging & Supplies", "\N{SHOPPING BAGS}", SUPPLIES),
    ("repairs", "Repairs", "\N{HAMMER AND WRENCH}", REPAIRS),
    ("transport", "Petrol & Delivery", "\N{DELIVERY TRUCK}", TRANSPORT),
    ("marketing", "Advertising", "\N{PUBLIC ADDRESS LOUDSPEAKER}", MARKETING),
    ("licenses", "Licence & Permit", "\N{SCROLL}", LICENSES),
    ("other", "Something Else", "\N{MEMO}", OTHER_EXPENSE),
]

CATEGORY_TO_ACCOUNT: dict[str, str] = {slug: code for slug, _, _, code in SPENDING_CATEGORIES}
