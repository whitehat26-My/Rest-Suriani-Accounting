"""Generation of the three primary financial statements.

The reporting logic reads the ledger generically. It never asks "is this the
chicken account?" - it asks each account what type it is, which statement group
it belongs to, and which cash flow section it feeds. That means the chart of
accounts can grow without any change here.

Statements produced:

* **Statement of Profit or Loss** - revenue less cost of sales gives gross
  profit; less operating expenses gives operating profit; less finance costs
  gives profit for the period.
* **Statement of Financial Position** - assets, liabilities and equity at a
  point in time. Retained earnings are derived from cumulative profit, so the
  statement balances by construction.
* **Statement of Cash Flows** - indirect method. Every non-cash balance sheet
  account contributes the negative of its movement to its own section, and
  profit for the period opens the operating section. This is algebraically
  identical to the textbook presentation and always reconciles to the actual
  movement in cash.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import chart_of_accounts as coa
from ..config import settings
from ..models import Account, AccountType, CashFlowSection
from ..schemas import (
    BalanceSheetOut,
    CashFlowOut,
    IncomeStatementOut,
    StatementLine,
    StatementSection,
    TrialBalanceOut,
    TrialBalanceRow,
)
from .ledger import ZERO, account_totals, money

# Expense accounts presented below operating profit rather than within it.
FINANCE_COST_GROUP = "Finance Costs"


def _pct(numerator: Decimal, denominator: Decimal) -> float:
    if denominator == 0:
        return 0.0
    return round(float(numerator / denominator) * 100, 2)


def _sorted_accounts(accounts: list[Account]) -> list[Account]:
    return sorted(accounts, key=lambda a: (a.sort_order, a.code))


# --------------------------------------------------------------------------- #
# Statement of Profit or Loss
# --------------------------------------------------------------------------- #
def income_statement(db: Session, start: date, end: date) -> IncomeStatementOut:
    """Profit or loss for the period between ``start`` and ``end`` inclusive."""
    totals = account_totals(db, start=start, end=end)
    accounts = db.scalars(select(Account)).all()

    revenue_lines: list[StatementLine] = []
    cos_lines: list[StatementLine] = []
    opex_lines: list[StatementLine] = []
    finance_lines: list[StatementLine] = []

    revenue = cost_of_sales = operating_expenses = finance_costs = ZERO

    for account in _sorted_accounts(accounts):
        if not account.is_nominal:
            continue
        debits, credits = totals.get(account.id, (ZERO, ZERO))
        balance = account.signed_balance(debits, credits)
        if balance == 0:
            continue

        line = StatementLine(
            label=account.name, amount=balance, account_code=account.code, level=1
        )
        if account.type is AccountType.REVENUE:
            revenue += balance
            revenue_lines.append(line)
        elif account.statement_group == "Cost of Sales":
            cost_of_sales += balance
            cos_lines.append(line)
        elif account.statement_group == FINANCE_COST_GROUP:
            finance_costs += balance
            finance_lines.append(line)
        else:
            operating_expenses += balance
            opex_lines.append(line)

    gross_profit = money(revenue - cost_of_sales)
    operating_profit = money(gross_profit - operating_expenses)
    profit = money(operating_profit - finance_costs)

    sections = [
        StatementSection(title="Revenue", lines=revenue_lines, total=money(revenue)),
        StatementSection(title="Cost of Sales", lines=cos_lines, total=money(cost_of_sales)),
        StatementSection(
            title="Gross Profit",
            lines=[StatementLine(label="Gross Profit", amount=gross_profit, is_subtotal=True)],
            total=gross_profit,
        ),
        StatementSection(
            title="Operating Expenses", lines=opex_lines, total=money(operating_expenses)
        ),
        StatementSection(
            title="Operating Profit",
            lines=[
                StatementLine(label="Operating Profit", amount=operating_profit, is_subtotal=True)
            ],
            total=operating_profit,
        ),
    ]
    if finance_lines:
        sections.append(
            StatementSection(
                title=FINANCE_COST_GROUP, lines=finance_lines, total=money(finance_costs)
            )
        )
    sections.append(
        StatementSection(
            title="Profit for the Period",
            lines=[
                StatementLine(label="Profit for the Period", amount=profit, is_total=True)
            ],
            total=profit,
        )
    )

    return IncomeStatementOut(
        business_name=settings.business_name,
        currency=settings.currency,
        period_start=start,
        period_end=end,
        sections=sections,
        revenue=money(revenue),
        cost_of_sales=money(cost_of_sales),
        gross_profit=gross_profit,
        operating_expenses=money(operating_expenses),
        operating_profit=operating_profit,
        finance_costs=money(finance_costs),
        net_profit=profit,
        gross_margin_pct=_pct(gross_profit, revenue),
        net_margin_pct=_pct(profit, revenue),
    )


# --------------------------------------------------------------------------- #
# Statement of Financial Position
# --------------------------------------------------------------------------- #
def balance_sheet(db: Session, as_of: date) -> BalanceSheetOut:
    """Assets, liabilities and equity as at ``as_of``.

    Retained earnings are not a posted account - they are the accumulated
    profit implied by every revenue and expense entry to date. Deriving them
    here is what makes the statement balance without a period-close routine.
    """
    totals = account_totals(db, end=as_of)
    accounts = db.scalars(select(Account)).all()

    grouped: dict[str, list[StatementLine]] = defaultdict(list)
    group_totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total_assets = total_liabilities = total_equity = ZERO
    retained_earnings = ZERO

    for account in _sorted_accounts(accounts):
        debits, credits = totals.get(account.id, (ZERO, ZERO))
        balance = account.signed_balance(debits, credits)

        if account.is_nominal:
            # Revenue increases accumulated profit, expenses reduce it.
            if account.type is AccountType.REVENUE:
                retained_earnings += balance
            else:
                retained_earnings -= balance
            continue

        if balance == 0:
            continue

        # Contra accounts are shown as deductions within their own group.
        display = -balance if account.is_contra else balance
        grouped[account.statement_group].append(
            StatementLine(
                label=account.name,
                amount=money(display),
                account_code=account.code,
                level=1,
                note="deduction" if account.is_contra else "",
            )
        )
        group_totals[account.statement_group] += display

        if account.type is AccountType.ASSET:
            total_assets += display
        elif account.type is AccountType.LIABILITY:
            total_liabilities += display
        else:
            total_equity += display

    retained_earnings = money(retained_earnings)
    total_equity = money(total_equity + retained_earnings)
    grouped["Equity"].append(
        StatementLine(
            label="Retained Earnings",
            amount=retained_earnings,
            level=1,
            note="accumulated profit to date",
        )
    )
    group_totals["Equity"] += retained_earnings

    order = [
        "Current Assets",
        "Non-Current Assets",
        "Current Liabilities",
        "Non-Current Liabilities",
        "Equity",
    ]
    sections: list[StatementSection] = []
    for group in order:
        if group in grouped:
            sections.append(
                StatementSection(
                    title=group, lines=grouped[group], total=money(group_totals[group])
                )
            )

    total_assets = money(total_assets)
    total_liabilities = money(total_liabilities)
    difference = money(total_assets - (total_liabilities + total_equity))

    sections.append(
        StatementSection(
            title="Summary",
            lines=[
                StatementLine(label="Total Assets", amount=total_assets, is_total=True),
                StatementLine(
                    label="Total Liabilities", amount=total_liabilities, is_total=True
                ),
                StatementLine(label="Total Equity", amount=total_equity, is_total=True),
                StatementLine(
                    label="Total Liabilities and Equity",
                    amount=money(total_liabilities + total_equity),
                    is_total=True,
                ),
            ],
            total=total_assets,
        )
    )

    return BalanceSheetOut(
        business_name=settings.business_name,
        currency=settings.currency,
        as_of=as_of,
        sections=sections,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        balances=difference == 0,
        difference=difference,
    )


# --------------------------------------------------------------------------- #
# Statement of Cash Flows
# --------------------------------------------------------------------------- #
def _cash_flow_label(account: Account) -> str:
    """Readable movement label, e.g. "Decrease in inventory"."""
    if account.code == coa.ACCUM_DEPRECIATION:
        return "Depreciation (non-cash)"
    if account.type is AccountType.EQUITY:
        return f"Movement in {account.name.lower()}"
    return f"Movement in {account.name.lower()}"


def cash_flow_statement(db: Session, start: date, end: date) -> CashFlowOut:
    """Cash flows for the period, indirect method.

    For any balance sheet account other than cash, the cash effect of its
    movement is the negative of that movement measured debit-positive. Summing
    those by cash flow section, and opening the operating section with profit
    for the period, reproduces the standard indirect presentation exactly - and
    guarantees the statement reconciles to the change in cash.
    """
    period_totals = account_totals(db, start=start, end=end)
    opening_totals = account_totals(db, end=_day_before(start))
    closing_totals = account_totals(db, end=end)

    accounts = db.scalars(select(Account)).all()

    operating: list[StatementLine] = []
    investing: list[StatementLine] = []
    financing: list[StatementLine] = []

    net_operating = net_investing = net_financing = ZERO
    revenue_total = expense_total = ZERO
    opening_cash = closing_cash = ZERO

    for account in _sorted_accounts(accounts):
        debits, credits = period_totals.get(account.id, (ZERO, ZERO))

        if account.is_nominal:
            movement = account.signed_balance(debits, credits)
            if account.type is AccountType.REVENUE:
                revenue_total += movement
            else:
                expense_total += movement
            continue

        if account.cash_flow_section is CashFlowSection.CASH:
            o_d, o_c = opening_totals.get(account.id, (ZERO, ZERO))
            c_d, c_c = closing_totals.get(account.id, (ZERO, ZERO))
            opening_cash += account.signed_balance(o_d, o_c)
            closing_cash += account.signed_balance(c_d, c_c)
            continue

        # Debit-positive movement: assets increase, liabilities go negative.
        debit_positive = money(debits - credits)
        if debit_positive == 0:
            continue
        # Spending cash on an asset is a cash outflow, hence the sign flip.
        cash_effect = money(-debit_positive)

        line = StatementLine(
            label=_cash_flow_label(account),
            amount=cash_effect,
            account_code=account.code,
            level=1,
        )
        if account.cash_flow_section is CashFlowSection.OPERATING:
            operating.append(line)
            net_operating += cash_effect
        elif account.cash_flow_section is CashFlowSection.INVESTING:
            investing.append(line)
            net_investing += cash_effect
        elif account.cash_flow_section is CashFlowSection.FINANCING:
            financing.append(line)
            net_financing += cash_effect

    profit = money(revenue_total - expense_total)
    operating.insert(
        0,
        StatementLine(label="Profit for the period", amount=profit, level=1, is_subtotal=True),
    )
    net_operating = money(net_operating + profit)

    net_investing = money(net_investing)
    net_financing = money(net_financing)
    net_change = money(net_operating + net_investing + net_financing)
    opening_cash = money(opening_cash)
    closing_cash = money(closing_cash)

    sections = [
        StatementSection(
            title="Cash Flows from Operating Activities",
            lines=operating,
            total=net_operating,
        ),
        StatementSection(
            title="Cash Flows from Investing Activities",
            lines=investing,
            total=net_investing,
        ),
        StatementSection(
            title="Cash Flows from Financing Activities",
            lines=financing,
            total=net_financing,
        ),
        StatementSection(
            title="Net Movement in Cash",
            lines=[
                StatementLine(label="Net increase in cash", amount=net_change, is_subtotal=True),
                StatementLine(label="Cash at beginning of period", amount=opening_cash),
                StatementLine(
                    label="Cash at end of period", amount=closing_cash, is_total=True
                ),
            ],
            total=closing_cash,
        ),
    ]

    return CashFlowOut(
        business_name=settings.business_name,
        currency=settings.currency,
        period_start=start,
        period_end=end,
        sections=sections,
        net_operating=net_operating,
        net_investing=net_investing,
        net_financing=net_financing,
        net_change=net_change,
        opening_cash=opening_cash,
        closing_cash=closing_cash,
        reconciles=money(opening_cash + net_change) == closing_cash,
    )


def _day_before(day: date) -> date:
    from datetime import timedelta

    return day - timedelta(days=1)


# --------------------------------------------------------------------------- #
# Trial balance - the accountant's proof that the ledger is intact
# --------------------------------------------------------------------------- #
def trial_balance(db: Session, as_of: date) -> TrialBalanceOut:
    totals = account_totals(db, end=as_of)
    accounts = db.scalars(select(Account)).all()

    rows: list[TrialBalanceRow] = []
    total_debit = total_credit = ZERO

    for account in sorted(accounts, key=lambda a: a.code):
        debits, credits = totals.get(account.id, (ZERO, ZERO))
        net = money(debits - credits)
        if net == 0:
            continue
        debit_col = net if net > 0 else ZERO
        credit_col = -net if net < 0 else ZERO
        total_debit += debit_col
        total_credit += credit_col
        rows.append(
            TrialBalanceRow(
                code=account.code,
                name=account.name,
                type=account.type,
                debit=money(debit_col),
                credit=money(credit_col),
            )
        )

    return TrialBalanceOut(
        as_of=as_of,
        rows=rows,
        total_debit=money(total_debit),
        total_credit=money(total_credit),
        balanced=money(total_debit) == money(total_credit),
    )
