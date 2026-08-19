"""Financial health evaluation.

This is the module that answers "how is the restaurant actually doing?". It
computes the ratios an accountant would compute by hand, grades each against a
published food-service benchmark, and then writes the conclusion in plain
sentences the owner can act on.

A note on what "AI" means here: this is a deterministic expert system, not a
language model. Every number and every sentence is traceable to a rule you can
read below. For a small business's books that is a feature - the advice is
reproducible, it never invents a figure, it costs nothing to run, and an
accounting student can check the working. :func:`evaluate` returns structured
metrics alongside the prose, so an LLM layer can be added on top later without
changing any of the arithmetic.

Benchmarks used are standard for independent food service:

===========================  ==================  ==========================
Metric                       Healthy             Source of the convention
===========================  ==================  ==========================
Food cost / revenue          28% - 35%           restaurant industry norm
Labour cost / revenue        25% - 35%           restaurant industry norm
Prime cost (food + labour)   at or below 65%     the classic operator's rule
Rent / revenue               at or below 10%     independent food service
Current ratio                1.5 - 3.0           general liquidity guidance
Net margin                   at or above 5%      independent restaurants
Wastage / food cost          at or below 5%      kitchen efficiency target
===========================  ==================  ==========================
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import chart_of_accounts as coa
from ..models import Account, AccountType, EntrySide, EventType, LedgerEntry, Transaction
from ..schemas import (
    ExpenseBreakdownItem,
    FinancialEvaluationOut,
    MetricOut,
    SuggestionOut,
    TrendPoint,
)
from .ledger import ZERO, account_balances, account_totals, money
from .statements import balance_sheet, income_statement

GOOD, WATCH, BAD, NEUTRAL = "good", "watch", "bad", "neutral"

# Ratings are scored so a single composite health score can be derived.
_RATING_SCORE = {GOOD: 1.0, WATCH: 0.5, BAD: 0.0, NEUTRAL: 0.5}


def _safe_ratio(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator / denominator), 4)


def _pct(numerator: Decimal, denominator: Decimal) -> float | None:
    ratio = _safe_ratio(numerator, denominator)
    return None if ratio is None else round(ratio * 100, 2)


def _band(
    value: float | None, *, good: tuple[float, float], watch: tuple[float, float]
) -> str:
    """Rate a value against an ideal band and a tolerable band."""
    if value is None:
        return NEUTRAL
    if good[0] <= value <= good[1]:
        return GOOD
    if watch[0] <= value <= watch[1]:
        return WATCH
    return BAD


def _fmt_money(value: Decimal) -> str:
    return f"RM{value:,.2f}"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _fmt_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}x"


# --------------------------------------------------------------------------- #
# Trend series
# --------------------------------------------------------------------------- #
def daily_trend(db: Session, start: date, end: date) -> list[TrendPoint]:
    """Money in, money out and running cash for each day in the period.

    "Money in" and "money out" here mean actual cash movement through the till
    and the bank, which is what the owner recognises - not accrual revenue.
    """
    cash_accounts = db.scalars(
        select(Account.id).where(Account.code.in_([coa.CASH_ON_HAND, coa.BANK]))
    ).all()
    if not cash_accounts:
        return []

    rows = db.execute(
        select(LedgerEntry.entry_date, LedgerEntry.side, LedgerEntry.amount).where(
            LedgerEntry.account_id.in_(cash_accounts),
            LedgerEntry.entry_date >= start,
            LedgerEntry.entry_date <= end,
        )
    ).all()

    by_day: dict[date, list[Decimal]] = {}
    for entry_date, side, amount in rows:
        bucket = by_day.setdefault(entry_date, [ZERO, ZERO])
        if side is EntrySide.DEBIT:
            bucket[0] += amount
        else:
            bucket[1] += amount

    # Opening cash before the window, so the running line is on the right level.
    balances = account_balances(db, end=start - timedelta(days=1))
    running = money(balances.get(coa.CASH_ON_HAND, ZERO) + balances.get(coa.BANK, ZERO))

    points: list[TrendPoint] = []
    day = start
    while day <= end:
        money_in, money_out = by_day.get(day, [ZERO, ZERO])
        net = money(money_in - money_out)
        running = money(running + net)
        points.append(
            TrendPoint(
                day=day,
                money_in=money(money_in),
                money_out=money(money_out),
                net=net,
                cumulative_cash=running,
            )
        )
        day += timedelta(days=1)
    return points


def expense_breakdown(db: Session, start: date, end: date) -> list[ExpenseBreakdownItem]:
    """Every expense account for the period, largest first, with its share."""
    totals = account_totals(db, start=start, end=end)
    accounts = db.scalars(select(Account).where(Account.type == AccountType.EXPENSE)).all()

    rows: list[tuple[Account, Decimal]] = []
    grand_total = ZERO
    for account in accounts:
        debits, credits = totals.get(account.id, (ZERO, ZERO))
        balance = account.signed_balance(debits, credits)
        if balance <= 0:
            continue
        rows.append((account, balance))
        grand_total += balance

    rows.sort(key=lambda pair: pair[1], reverse=True)
    return [
        ExpenseBreakdownItem(
            account_code=account.code,
            label=account.name,
            friendly_label=account.friendly_name or account.name,
            amount=money(balance),
            percentage=round(float(balance / grand_total) * 100, 2) if grand_total else 0.0,
        )
        for account, balance in rows
    ]


# --------------------------------------------------------------------------- #
# The evaluation itself
# --------------------------------------------------------------------------- #
def evaluate(db: Session, start: date, end: date) -> FinancialEvaluationOut:
    """Compute the ratios, grade them and write the advice."""
    profit_loss = income_statement(db, start, end)
    position = balance_sheet(db, end)
    balances = account_balances(db, end=end)
    period_balances = account_balances(db, start=start, end=end)
    days = max((end - start).days + 1, 1)

    revenue = profit_loss.revenue
    food_cost = period_balances.get(coa.COGS, ZERO)
    wastage = period_balances.get(coa.WASTAGE, ZERO)
    labour = period_balances.get(coa.WAGES, ZERO)
    rent = period_balances.get(coa.RENT, ZERO)

    cash = money(balances.get(coa.CASH_ON_HAND, ZERO) + balances.get(coa.BANK, ZERO))
    receivables = balances.get(coa.ACCOUNTS_RECEIVABLE, ZERO)
    inventory = balances.get(coa.INVENTORY, ZERO)
    prepaid = balances.get(coa.PREPAID_EXPENSES, ZERO)
    payables = balances.get(coa.ACCOUNTS_PAYABLE, ZERO)
    accrued = balances.get(coa.ACCRUED_EXPENSES, ZERO)
    sst = balances.get(coa.SST_PAYABLE, ZERO)

    current_assets = money(cash + receivables + inventory + prepaid)
    current_liabilities = money(payables + accrued + sst)
    working_capital = money(current_assets - current_liabilities)

    current_ratio = _safe_ratio(current_assets, current_liabilities)
    quick_ratio = _safe_ratio(money(current_assets - inventory), current_liabilities)

    # Cash burn: total operating cash spend per day over the window.
    total_cash_out = _cash_outflow(db, start, end)
    average_daily_burn = money(total_cash_out / days)
    cash_runway_days = (
        round(float(cash / average_daily_burn), 1) if average_daily_burn > 0 else None
    )

    food_cost_pct = _pct(food_cost, revenue)
    labour_pct = _pct(labour, revenue)
    prime_cost_pct = _pct(money(food_cost + labour), revenue)
    rent_pct = _pct(rent, revenue)
    wastage_pct = _pct(wastage, food_cost) if food_cost > 0 else None
    inventory_days = (
        round(float(inventory / food_cost) * days, 1) if food_cost > 0 else None
    )
    receivable_days = round(float(receivables / revenue) * days, 1) if revenue > 0 else None
    payable_days = round(float(payables / food_cost) * days, 1) if food_cost > 0 else None

    metrics = [
        MetricOut(
            key="net_margin",
            label="Net Profit Margin",
            value=profit_loss.net_margin_pct,
            display=_fmt_pct(profit_loss.net_margin_pct),
            unit="%",
            rating=_band(profit_loss.net_margin_pct, good=(5, 100), watch=(0, 5)),
            benchmark="5% or better",
            explanation="What is left from every ringgit of sales after all costs.",
        ),
        MetricOut(
            key="gross_margin",
            label="Gross Margin",
            value=profit_loss.gross_margin_pct,
            display=_fmt_pct(profit_loss.gross_margin_pct),
            unit="%",
            rating=_band(profit_loss.gross_margin_pct, good=(60, 100), watch=(50, 60)),
            benchmark="60% or better",
            explanation="Sales less the cost of the food sold.",
        ),
        MetricOut(
            key="food_cost",
            label="Food Cost Ratio",
            value=food_cost_pct,
            display=_fmt_pct(food_cost_pct),
            unit="%",
            rating=_band(food_cost_pct, good=(0, 35), watch=(35, 40)),
            benchmark="28% - 35% of sales",
            explanation="How much of each ringgit of sales is spent on ingredients.",
        ),
        MetricOut(
            key="labour_cost",
            label="Labour Cost Ratio",
            value=labour_pct,
            display=_fmt_pct(labour_pct),
            unit="%",
            rating=_band(labour_pct, good=(0, 35), watch=(35, 42)),
            benchmark="25% - 35% of sales",
            explanation="Wages as a share of sales.",
        ),
        MetricOut(
            key="prime_cost",
            label="Prime Cost",
            value=prime_cost_pct,
            display=_fmt_pct(prime_cost_pct),
            unit="%",
            rating=_band(prime_cost_pct, good=(0, 65), watch=(65, 72)),
            benchmark="65% or below",
            explanation="Food plus labour. The single number operators watch most.",
        ),
        MetricOut(
            key="rent_ratio",
            label="Rent to Sales",
            value=rent_pct,
            display=_fmt_pct(rent_pct),
            unit="%",
            rating=_band(rent_pct, good=(0, 10), watch=(10, 15)),
            benchmark="10% or below",
            explanation="Rent as a share of sales.",
        ),
        MetricOut(
            key="current_ratio",
            label="Current Ratio",
            value=current_ratio,
            display=_fmt_ratio(current_ratio),
            unit="x",
            rating=_band(current_ratio, good=(1.5, 3.0), watch=(1.0, 1e9)),
            benchmark="1.5x - 3.0x",
            explanation="Short-term assets against short-term debts. Below 1.0x is a "
            "warning sign; far above 3.0x means cash is sitting idle.",
        ),
        MetricOut(
            key="quick_ratio",
            label="Quick Ratio",
            value=quick_ratio,
            display=_fmt_ratio(quick_ratio),
            unit="x",
            rating=_band(quick_ratio, good=(1.0, 3.0), watch=(0.7, 1e9)),
            benchmark="1.0x or better",
            explanation="Liquidity ignoring stock, which cannot be sold instantly.",
        ),
        MetricOut(
            key="wastage",
            label="Wastage Ratio",
            value=wastage_pct,
            display=_fmt_pct(wastage_pct),
            unit="%",
            rating=_band(wastage_pct, good=(0, 5), watch=(5, 10)),
            benchmark="5% of food cost or below",
            explanation="Spoiled stock as a share of food cost.",
        ),
        MetricOut(
            key="inventory_days",
            label="Days of Stock Held",
            value=inventory_days,
            display="n/a" if inventory_days is None else f"{inventory_days:.1f} days",
            unit="days",
            rating=_band(inventory_days, good=(2, 10), watch=(0, 21)),
            benchmark="2 - 10 days for fresh food",
            explanation="How long the store room would last at the current usage rate.",
        ),
        MetricOut(
            key="receivable_days",
            label="Collection Period",
            value=receivable_days,
            display="n/a" if receivable_days is None else f"{receivable_days:.1f} days",
            unit="days",
            rating=_band(receivable_days, good=(0, 14), watch=(14, 30)),
            benchmark="14 days or fewer",
            explanation="How long customers take to pay their bills.",
        ),
        MetricOut(
            key="payable_days",
            label="Supplier Payment Period",
            value=payable_days,
            display="n/a" if payable_days is None else f"{payable_days:.1f} days",
            unit="days",
            rating=_band(payable_days, good=(14, 45), watch=(0, 60)),
            benchmark="14 - 45 days",
            explanation="How long we take to pay suppliers.",
        ),
        MetricOut(
            key="cash_runway",
            label="Cash Runway",
            value=cash_runway_days,
            display="n/a" if cash_runway_days is None else f"{cash_runway_days:.0f} days",
            unit="days",
            rating=_band(cash_runway_days, good=(60, 100000), watch=(30, 60)),
            benchmark="60 days or more",
            explanation="How long the cash lasts if nothing more comes in.",
        ),
    ]

    suggestions = _build_suggestions(
        profit_loss=profit_loss,
        working_capital=working_capital,
        current_ratio=current_ratio,
        cash=cash,
        cash_runway_days=cash_runway_days,
        food_cost_pct=food_cost_pct,
        labour_pct=labour_pct,
        prime_cost_pct=prime_cost_pct,
        rent_pct=rent_pct,
        wastage_pct=wastage_pct,
        receivable_days=receivable_days,
        receivables=receivables,
        inventory_days=inventory_days,
        payables=payables,
        revenue=revenue,
    )

    score = _health_score(metrics)
    grade, headline = _grade(score, profit_loss.net_profit, cash_runway_days)

    return FinancialEvaluationOut(
        period_start=start,
        period_end=end,
        health_score=score,
        health_grade=grade,
        headline=headline,
        working_capital=working_capital,
        current_ratio=current_ratio,
        quick_ratio=quick_ratio,
        cash_runway_days=cash_runway_days,
        average_daily_burn=average_daily_burn,
        metrics=metrics,
        suggestions=suggestions,
        trend=daily_trend(db, start, end),
    )


# Cash leaving through these events is not day-to-day running cost, so it must
# not inflate the burn rate. Deposits and withdrawals in particular only move
# money between the till and the bank - nothing actually leaves the business.
NON_OPERATING_EVENTS = (
    EventType.BUY_EQUIPMENT,
    EventType.LOAN_RECEIVED,
    EventType.LOAN_REPAYMENT,
    EventType.OWNER_CONTRIBUTION,
    EventType.OWNER_DRAWINGS,
    EventType.BANK_DEPOSIT,
    EventType.CASH_WITHDRAWAL,
)


def _cash_outflow(db: Session, start: date, end: date) -> Decimal:
    """Operating cash that genuinely left the business during the period."""
    cash_ids = db.scalars(
        select(Account.id).where(Account.code.in_([coa.CASH_ON_HAND, coa.BANK]))
    ).all()
    if not cash_ids:
        return ZERO
    rows = db.scalars(
        select(LedgerEntry.amount)
        .join(Transaction, LedgerEntry.transaction_id == Transaction.id)
        .where(
            LedgerEntry.account_id.in_(cash_ids),
            LedgerEntry.side == EntrySide.CREDIT,
            LedgerEntry.entry_date >= start,
            LedgerEntry.entry_date <= end,
            Transaction.event_type.not_in(NON_OPERATING_EVENTS),
        )
    ).all()
    return money(sum(rows, ZERO))


def _health_score(metrics: list[MetricOut]) -> int:
    """Weighted composite of every rated metric, expressed out of 100."""
    weights = {
        "net_margin": 3.0,
        "prime_cost": 3.0,
        "cash_runway": 2.5,
        "current_ratio": 2.0,
        "food_cost": 2.0,
        "labour_cost": 1.5,
        "gross_margin": 1.5,
        "quick_ratio": 1.0,
        "wastage": 1.0,
        "rent_ratio": 1.0,
        "inventory_days": 0.5,
        "receivable_days": 0.5,
        "payable_days": 0.5,
    }
    total_weight = 0.0
    total_score = 0.0
    for metric in metrics:
        # Metrics that could not be computed carry no weight rather than
        # dragging the score toward the middle.
        if metric.value is None:
            continue
        weight = weights.get(metric.key, 0.5)
        total_weight += weight
        total_score += weight * _RATING_SCORE.get(metric.rating, 0.5)
    if total_weight == 0:
        return 50
    return int(round(total_score / total_weight * 100))


def _grade(score: int, net_profit: Decimal, runway: float | None) -> tuple[str, str]:
    if score >= 85:
        grade = "Excellent"
    elif score >= 70:
        grade = "Healthy"
    elif score >= 55:
        grade = "Fair"
    elif score >= 40:
        grade = "Needs Attention"
    else:
        grade = "At Risk"

    if net_profit > 0 and (runway is None or runway >= 60):
        headline = (
            f"The restaurant made a profit of {_fmt_money(net_profit)} this period "
            f"and has comfortable cash cover."
        )
    elif net_profit > 0:
        headline = (
            f"Profitable at {_fmt_money(net_profit)}, but the cash cushion is thin - "
            f"watch the timing of payments."
        )
    elif net_profit == 0:
        headline = "The restaurant broke even this period."
    else:
        headline = (
            f"The restaurant lost {_fmt_money(abs(net_profit))} this period. "
            f"The suggestions below start with the biggest cause."
        )
    return grade, headline


def _build_suggestions(  # noqa: PLR0913 - one argument per signal is the clearest form
    *,
    profit_loss,
    working_capital: Decimal,
    current_ratio: float | None,
    cash: Decimal,
    cash_runway_days: float | None,
    food_cost_pct: float | None,
    labour_pct: float | None,
    prime_cost_pct: float | None,
    rent_pct: float | None,
    wastage_pct: float | None,
    receivable_days: float | None,
    receivables: Decimal,
    inventory_days: float | None,
    payables: Decimal,
    revenue: Decimal,
) -> list[SuggestionOut]:
    """Turn the ratios into ranked, plain-language advice."""
    out: list[SuggestionOut] = []

    if revenue == 0:
        out.append(
            SuggestionOut(
                severity="info",
                title="No sales recorded yet",
                message="There are no sales in this period, so the ratios cannot be "
                "calculated. Record the day's takings and the numbers will fill in.",
                action="Tap Money In on the daily screen.",
            )
        )
        return out

    # --- Cash first: it is what closes a restaurant, not profit. ---
    if cash < 0:
        out.append(
            SuggestionOut(
                severity="critical",
                title="Cash has gone negative",
                message=f"The books show {_fmt_money(cash)} in cash, which means more has "
                "been paid out than came in. Check for a payment recorded twice.",
                action="Review this period's Money Out entries.",
                metric_key="cash_runway",
            )
        )
    elif cash_runway_days is not None and cash_runway_days < 30:
        out.append(
            SuggestionOut(
                severity="critical",
                title="Less than a month of cash left",
                message=f"At the current spending rate the {_fmt_money(cash)} on hand lasts "
                f"about {cash_runway_days:.0f} days. Slow down non-urgent buying and "
                "collect anything customers still owe.",
                action="Chase outstanding customer bills this week.",
                metric_key="cash_runway",
            )
        )
    elif cash_runway_days is not None and cash_runway_days < 60:
        out.append(
            SuggestionOut(
                severity="warning",
                title="Cash cover is getting thin",
                message=f"The cash on hand covers about {cash_runway_days:.0f} days of "
                "spending. Two months of cover is the comfortable level.",
                action="Hold off on large purchases until takings improve.",
                metric_key="cash_runway",
            )
        )

    if working_capital < 0:
        out.append(
            SuggestionOut(
                severity="critical",
                title="Short-term debts exceed short-term assets",
                message=f"Working capital is {_fmt_money(working_capital)}. Bills falling due "
                "are larger than the cash, stock and money owed to the restaurant.",
                action="Agree longer payment terms with suppliers.",
                metric_key="current_ratio",
            )
        )
    elif current_ratio is not None and current_ratio > 4.0:
        out.append(
            SuggestionOut(
                severity="info",
                title="A lot of cash is sitting idle",
                message=f"The current ratio is {current_ratio:.1f}x, well above the 1.5x - 3.0x "
                "range. The restaurant is safe, but money doing nothing earns nothing.",
                action="Consider paying down the loan or upgrading equipment.",
                metric_key="current_ratio",
            )
        )
    elif current_ratio is not None and current_ratio < 1.0:
        out.append(
            SuggestionOut(
                severity="warning",
                title="Liquidity is tight",
                message=f"The current ratio is {current_ratio:.2f}x. Below 1.0x means the "
                "restaurant would struggle to pay everything due at once.",
                metric_key="current_ratio",
            )
        )

    # --- Profitability ---
    if profit_loss.net_profit < 0:
        out.append(
            SuggestionOut(
                severity="critical",
                title="Operating at a loss",
                message=f"Costs exceeded sales by {_fmt_money(abs(profit_loss.net_profit))}. "
                f"Sales were {_fmt_money(profit_loss.revenue)} against total costs of "
                f"{_fmt_money(profit_loss.revenue - profit_loss.net_profit)}.",
                action="Look at the two largest expense lines below.",
                metric_key="net_margin",
            )
        )

    if prime_cost_pct is not None and prime_cost_pct > 65:
        out.append(
            SuggestionOut(
                severity="warning" if prime_cost_pct <= 72 else "critical",
                title="Prime cost is above the safe line",
                message=f"Food and labour together take {prime_cost_pct:.1f}% of sales. "
                "Above 65% leaves too little for rent, utilities and profit.",
                action="Reduce whichever is higher: portion sizes or shift hours.",
                metric_key="prime_cost",
            )
        )

    if food_cost_pct is not None and food_cost_pct > 35:
        out.append(
            SuggestionOut(
                severity="warning",
                title="Ingredients cost too much per ringgit of sales",
                message=f"Food cost is {food_cost_pct:.1f}% of sales against a 28-35% "
                "benchmark. Either supplier prices have risen or menu prices have not.",
                action="Compare supplier prices, or raise the price of the top sellers.",
                metric_key="food_cost",
            )
        )
    elif food_cost_pct is not None and food_cost_pct < 20 and food_cost_pct > 0:
        out.append(
            SuggestionOut(
                severity="info",
                title="Food cost looks unusually low",
                message=f"Food cost is only {food_cost_pct:.1f}% of sales. That is good news "
                "if real, but often it means stock used has not been counted yet.",
                action="Do a stock count so used ingredients reach the accounts.",
                metric_key="food_cost",
            )
        )

    if labour_pct is not None and labour_pct > 35:
        out.append(
            SuggestionOut(
                severity="warning",
                title="Wages are high relative to sales",
                message=f"Labour is {labour_pct:.1f}% of sales against a 25-35% benchmark. "
                "Check whether the quiet hours need as many staff.",
                action="Review the roster for the slowest two hours of each day.",
                metric_key="labour_cost",
            )
        )

    if rent_pct is not None and rent_pct > 10:
        out.append(
            SuggestionOut(
                severity="warning" if rent_pct <= 15 else "critical",
                title="Rent is a heavy share of sales",
                message=f"Rent takes {rent_pct:.1f}% of sales; 10% or less is the healthy "
                "range. The premises need more turnover to justify the cost.",
                action="Consider extending trading hours or adding takeaway.",
                metric_key="rent_ratio",
            )
        )

    if wastage_pct is not None and wastage_pct > 5:
        out.append(
            SuggestionOut(
                severity="warning",
                title="Too much food is being thrown away",
                message=f"Wastage is {wastage_pct:.1f}% of food cost against a 5% target. "
                "Buying smaller amounts more often usually fixes this.",
                action="Order fresh items twice a week instead of once.",
                metric_key="wastage",
            )
        )

    if inventory_days is not None and inventory_days > 21:
        out.append(
            SuggestionOut(
                severity="warning",
                title="Too much stock is sitting in the store room",
                message=f"There is about {inventory_days:.0f} days of stock on hand. For fresh "
                "food that is money tied up, and some of it will spoil.",
                action="Buy less on the next order and use what is there.",
                metric_key="inventory_days",
            )
        )

    if receivable_days is not None and receivable_days > 30 and receivables > 0:
        out.append(
            SuggestionOut(
                severity="warning",
                title="Customers are slow to pay",
                message=f"{_fmt_money(receivables)} is still owed, taking about "
                f"{receivable_days:.0f} days to collect. That is cash the restaurant "
                "has earned but cannot use.",
                action="Call the largest unpaid account this week.",
                metric_key="receivable_days",
            )
        )

    # --- Positives, so the screen is not only bad news. ---
    if profit_loss.net_profit > 0 and profit_loss.net_margin_pct >= 10:
        out.append(
            SuggestionOut(
                severity="positive",
                title="Strong profit margin",
                message=f"The restaurant kept {profit_loss.net_margin_pct:.1f} sen of every "
                f"ringgit sold, a profit of {_fmt_money(profit_loss.net_profit)}. "
                "Anything above 10% is strong for independent food service.",
                metric_key="net_margin",
            )
        )
    if prime_cost_pct is not None and prime_cost_pct <= 60:
        out.append(
            SuggestionOut(
                severity="positive",
                title="Costs are well controlled",
                message=f"Prime cost is {prime_cost_pct:.1f}% of sales, comfortably inside the "
                "65% line. Food and labour are both being managed well.",
                metric_key="prime_cost",
            )
        )
    if cash_runway_days is not None and cash_runway_days >= 90:
        out.append(
            SuggestionOut(
                severity="positive",
                title="Healthy cash buffer",
                message=f"There is roughly {cash_runway_days:.0f} days of spending held in "
                "cash. That is enough to absorb a slow month.",
                metric_key="cash_runway",
            )
        )

    if not out:
        out.append(
            SuggestionOut(
                severity="positive",
                title="Nothing needs attention",
                message="Every measured ratio is inside its healthy range for this period.",
            )
        )

    severity_rank = {"critical": 0, "warning": 1, "info": 2, "positive": 3}
    out.sort(key=lambda s: severity_rank.get(s.severity, 4))
    return out
