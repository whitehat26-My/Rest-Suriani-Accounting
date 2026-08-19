"""The three financial statements, plus the trial balance."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (
    BalanceSheetOut,
    CashFlowOut,
    IncomeStatementOut,
    TrialBalanceOut,
)
from ..services import statements
from ..utils import resolve_period

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/income-statement", response_model=IncomeStatementOut)
def income_statement(
    start: date | None = None,
    end: date | None = None,
    period: str = "month",
    db: Session = Depends(get_db),
) -> IncomeStatementOut:
    """Statement of Profit or Loss for the period."""
    start, end = resolve_period(start, end, period)
    return statements.income_statement(db, start, end)


@router.get("/balance-sheet", response_model=BalanceSheetOut)
def balance_sheet(as_of: date | None = None, db: Session = Depends(get_db)) -> BalanceSheetOut:
    """Statement of Financial Position at a point in time."""
    return statements.balance_sheet(db, as_of or date.today())


@router.get("/cash-flow", response_model=CashFlowOut)
def cash_flow(
    start: date | None = None,
    end: date | None = None,
    period: str = "month",
    db: Session = Depends(get_db),
) -> CashFlowOut:
    """Statement of Cash Flows for the period, indirect method."""
    start, end = resolve_period(start, end, period)
    return statements.cash_flow_statement(db, start, end)


@router.get("/trial-balance", response_model=TrialBalanceOut)
def trial_balance(as_of: date | None = None, db: Session = Depends(get_db)) -> TrialBalanceOut:
    """Proof that every debit has a matching credit."""
    return statements.trial_balance(db, as_of or date.today())
