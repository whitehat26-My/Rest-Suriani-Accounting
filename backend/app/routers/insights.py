"""Dashboards: the owner's one-glance summary and the accountant's analytics."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import chart_of_accounts as coa
from ..database import get_db
from ..models import EntrySide, LedgerEntry, Transaction
from ..schemas import (
    AccountantDashboardOut,
    DailySummaryOut,
    FinancialEvaluationOut,
    TrendPoint,
)
from ..serializers import inventory_item_out, transaction_out
from ..services import analysis, inventory as inventory_service, statements
from ..services.ledger import SYSTEM_ONLY_EVENTS, ZERO, account_balances, money
from ..utils import resolve_period

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/daily", response_model=DailySummaryOut)
def daily_summary(day: date | None = None, db: Session = Depends(get_db)) -> DailySummaryOut:
    """Everything Grandma Mode needs on one screen.

    Money in and money out mean real cash movement for the day, and the verdict
    is a traffic light rather than a number, because that is what gets read.
    """
    day = day or date.today()

    cash_codes = [coa.CASH_ON_HAND, coa.BANK]
    from ..models import Account

    cash_ids = db.scalars(select(Account.id).where(Account.code.in_(cash_codes))).all()

    money_in = money_out = ZERO
    if cash_ids:
        rows = db.execute(
            select(LedgerEntry.side, LedgerEntry.amount).where(
                LedgerEntry.account_id.in_(cash_ids), LedgerEntry.entry_date == day
            )
        ).all()
        for side, amount in rows:
            if side is EntrySide.DEBIT:
                money_in += amount
            else:
                money_out += amount

    money_in = money(money_in)
    money_out = money(money_out)
    net = money(money_in - money_out)

    balances = account_balances(db, end=day)
    cash_on_hand = money(
        balances.get(coa.CASH_ON_HAND, ZERO) + balances.get(coa.BANK, ZERO)
    )

    recent = db.scalars(
        select(Transaction)
        .options(
            selectinload(Transaction.entries).selectinload(LedgerEntry.account),
            selectinload(Transaction.attachments),
        )
        .where(
            Transaction.txn_date == day,
            Transaction.event_type.not_in(SYSTEM_ONLY_EVENTS),
        )
        .order_by(Transaction.id.desc())
        .limit(8)
    ).all()

    transaction_count = (
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.txn_date == day,
                Transaction.event_type.not_in(SYSTEM_ONLY_EVENTS),
            )
        )
        or 0
    )

    low_stock = inventory_service.low_stock_items(db)

    if net > 0:
        verdict = "good"
        verdict_message = f"Good day. You kept RM{net:,.2f} more than you spent."
    elif net == 0 and transaction_count == 0:
        verdict = "watch"
        verdict_message = "Nothing recorded yet today. Tap the big green button when money comes in."
    elif net == 0:
        verdict = "watch"
        verdict_message = "Money in and money out are equal today."
    else:
        verdict = "bad"
        verdict_message = f"Careful. You spent RM{abs(net):,.2f} more than you took in today."

    return DailySummaryOut(
        day=day,
        money_in=money_in,
        money_out=money_out,
        net=net,
        cash_on_hand=cash_on_hand,
        transaction_count=transaction_count,
        verdict=verdict,
        verdict_message=verdict_message,
        low_stock_count=len(low_stock),
        recent=[transaction_out(txn) for txn in recent],
    )


@router.get("/week", response_model=list[TrendPoint])
def week_trend(days: int = 7, db: Session = Depends(get_db)) -> list[TrendPoint]:
    """A short cash trend for the owner's simple bar chart."""
    end = date.today()
    start = end - timedelta(days=max(days, 1) - 1)
    return analysis.daily_trend(db, start, end)


@router.get("/evaluation", response_model=FinancialEvaluationOut)
def evaluation(
    start: date | None = None,
    end: date | None = None,
    period: str = "month",
    db: Session = Depends(get_db),
) -> FinancialEvaluationOut:
    """Ratios, grades and plain-language advice for the period."""
    start, end = resolve_period(start, end, period)
    return analysis.evaluate(db, start, end)


@router.get("/dashboard", response_model=AccountantDashboardOut)
def accountant_dashboard(
    start: date | None = None,
    end: date | None = None,
    period: str = "month",
    db: Session = Depends(get_db),
) -> AccountantDashboardOut:
    """One call that fills the whole Accountant Mode screen."""
    start, end = resolve_period(start, end, period)
    low_stock = inventory_service.low_stock_items(db)

    return AccountantDashboardOut(
        period_start=start,
        period_end=end,
        income_statement=statements.income_statement(db, start, end),
        balance_sheet=statements.balance_sheet(db, end),
        cash_flow=statements.cash_flow_statement(db, start, end),
        evaluation=analysis.evaluate(db, start, end),
        expense_breakdown=analysis.expense_breakdown(db, start, end),
        revenue_by_day=analysis.daily_trend(db, start, end),
        inventory_value=inventory_service.total_inventory_value(db),
        low_stock=[inventory_item_out(item, db=db) for item in low_stock],
    )
