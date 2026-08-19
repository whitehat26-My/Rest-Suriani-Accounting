"""Chart of accounts and general ledger endpoints."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, EntrySide, LedgerEntry, Transaction
from ..schemas import (
    AccountBalanceOut,
    AccountOut,
    GeneralLedgerOut,
    GeneralLedgerRow,
    SpendingCategoryOut,
)
from ..chart_of_accounts import SPENDING_CATEGORIES
from ..services.ledger import ZERO, account_totals, money

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountBalanceOut])
def list_accounts(
    as_of: date | None = None,
    include_zero: bool = True,
    db: Session = Depends(get_db),
) -> list[AccountBalanceOut]:
    """The full chart of accounts with balances as at a date."""
    totals = account_totals(db, end=as_of)
    accounts = db.scalars(select(Account).order_by(Account.code)).all()

    out: list[AccountBalanceOut] = []
    for account in accounts:
        debits, credits = totals.get(account.id, (ZERO, ZERO))
        balance = account.signed_balance(debits, credits)
        if not include_zero and balance == 0:
            continue
        out.append(
            AccountBalanceOut(
                **AccountOut.model_validate(account).model_dump(),
                debits=money(debits),
                credits=money(credits),
                balance=money(balance),
            )
        )
    return out


@router.get("/spending-categories", response_model=list[SpendingCategoryOut])
def spending_categories() -> list[SpendingCategoryOut]:
    """The picture-labelled buttons Grandma Mode shows for Money Out."""
    return [
        SpendingCategoryOut(slug=slug, label=label, emoji=emoji, account_code=code)
        for slug, label, emoji, code in SPENDING_CATEGORIES
    ]


@router.get("/{code}/ledger", response_model=GeneralLedgerOut)
def general_ledger(
    code: str,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> GeneralLedgerOut:
    """Every movement on one account, with a running balance."""
    account = db.scalar(select(Account).where(Account.code == code))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account {code} not found")

    end = end or date.today()
    start = start or (end - timedelta(days=30))

    opening_totals = account_totals(db, end=start - timedelta(days=1))
    o_debits, o_credits = opening_totals.get(account.id, (ZERO, ZERO))
    opening = account.signed_balance(o_debits, o_credits)

    entries = db.execute(
        select(LedgerEntry, Transaction)
        .join(Transaction, LedgerEntry.transaction_id == Transaction.id)
        .where(
            LedgerEntry.account_id == account.id,
            LedgerEntry.entry_date >= start,
            LedgerEntry.entry_date <= end,
        )
        .order_by(LedgerEntry.entry_date, LedgerEntry.id)
    ).all()

    running = opening
    rows: list[GeneralLedgerRow] = []
    for entry, txn in entries:
        change = entry.amount if entry.side is EntrySide.DEBIT else -entry.amount
        if account.normal_balance.value == "CREDIT":
            change = -change
        running = money(running + change)
        rows.append(
            GeneralLedgerRow(
                date=entry.entry_date,
                reference=txn.reference,
                description=entry.memo or txn.description,
                debit=entry.debit,
                credit=entry.credit,
                balance=running,
            )
        )

    return GeneralLedgerOut(
        account=AccountOut.model_validate(account),
        period_start=start,
        period_end=end,
        opening_balance=money(opening),
        rows=rows,
        closing_balance=money(running),
    )
