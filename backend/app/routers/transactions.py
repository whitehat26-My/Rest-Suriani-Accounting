"""Transaction entry: the one-tap owner flow and the accountant's full form."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Attachment, EventType, LedgerEntry, Transaction
from ..schemas import (
    QuickEntry,
    TransactionCreate,
    TransactionListOut,
    TransactionOut,
    VoiceParseRequest,
    VoiceParseResponse,
)
from ..serializers import transaction_out
from ..services import nlp
from ..services.inventory import InventoryError, apply_purchase, get_item
from ..services.ledger import (
    LedgerError,
    load_transaction,
    post_transaction,
    quick_entry_to_transaction,
    reverse_transaction,
)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def _attach(db: Session, txn: Transaction, attachment_ids: list[int]) -> None:
    """Link already-uploaded receipt photos to the transaction."""
    if not attachment_ids:
        return
    attachments = db.scalars(
        select(Attachment).where(Attachment.id.in_(attachment_ids))
    ).all()
    for attachment in attachments:
        attachment.transaction_id = txn.id


def _link_inventory(db: Session, txn: Transaction, request: TransactionCreate) -> None:
    """When a stock purchase names an item and quantity, take it into stock.

    The ledger already debited Inventory for the money; this records the
    physical quantity and updates the weighted-average cost so the two views of
    inventory - value and quantity - stay consistent.
    """
    if request.inventory_item_id is None or request.quantity is None:
        return
    if request.event_type not in (
        EventType.PURCHASE_INVENTORY_CASH,
        EventType.PURCHASE_INVENTORY_CREDIT,
    ):
        return
    item = get_item(db, request.inventory_item_id)
    apply_purchase(
        db,
        item,
        qty=request.quantity,
        total_cost=request.amount,
        movement_date=txn.txn_date,
        transaction=txn,
        note=request.counterparty,
    )


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(
    payload: TransactionCreate, db: Session = Depends(get_db)
) -> TransactionOut:
    """Post a fully specified transaction. Used by Accountant Mode."""
    try:
        txn = post_transaction(db, payload)
        _link_inventory(db, txn, payload)
        _attach(db, txn, payload.attachment_ids)
    except (LedgerError, InventoryError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return transaction_out(load_transaction(db, txn.id))


@router.post("/quick", response_model=TransactionOut, status_code=201)
def create_quick_entry(payload: QuickEntry, db: Session = Depends(get_db)) -> TransactionOut:
    """The only write endpoint Grandma Mode uses.

    The owner sends a direction, an amount and a picture category. The backend
    works out the event type, the accounts and the double entry.
    """
    try:
        request = quick_entry_to_transaction(payload)
        txn = post_transaction(db, request)
        _link_inventory(db, txn, request)
        _attach(db, txn, payload.attachment_ids)
    except (LedgerError, InventoryError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return transaction_out(load_transaction(db, txn.id))


@router.post("/preview", response_model=list[dict])
def preview_entries(payload: TransactionCreate) -> list[dict]:
    """Show the debits and credits an event would produce, without saving.

    Accountant Mode uses this to explain the automation; it is also how the
    student sees what the owner's tap actually did to the books.
    """
    from ..services.ledger import build_legs

    try:
        legs = build_legs(payload)
    except LedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        {
            "account_code": leg.account_code,
            "side": leg.side.value,
            "amount": str(leg.amount),
            "memo": leg.memo,
        }
        for leg in legs
    ]


@router.post("/parse", response_model=VoiceParseResponse)
def parse_speech(payload: VoiceParseRequest, db: Session = Depends(get_db)) -> VoiceParseResponse:
    """Interpret a spoken sentence. Nothing is saved - the owner confirms first."""
    return nlp.parse(db, payload.text)


@router.get("", response_model=TransactionListOut)
def list_transactions(
    start: date | None = None,
    end: date | None = None,
    event_type: EventType | None = None,
    direction: str | None = Query(default=None, pattern="^(in|out|neutral)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> TransactionListOut:
    """Paginated transaction history, newest first."""
    stmt = select(Transaction).options(
        selectinload(Transaction.entries).selectinload(LedgerEntry.account),
        selectinload(Transaction.attachments),
    )
    count_stmt = select(func.count(Transaction.id))

    if start is not None:
        stmt = stmt.where(Transaction.txn_date >= start)
        count_stmt = count_stmt.where(Transaction.txn_date >= start)
    if end is not None:
        stmt = stmt.where(Transaction.txn_date <= end)
        count_stmt = count_stmt.where(Transaction.txn_date <= end)
    if event_type is not None:
        stmt = stmt.where(Transaction.event_type == event_type)
        count_stmt = count_stmt.where(Transaction.event_type == event_type)

    total = db.scalar(count_stmt) or 0
    stmt = (
        stmt.order_by(Transaction.txn_date.desc(), Transaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [transaction_out(txn) for txn in db.scalars(stmt).all()]

    # Direction is derived rather than stored, so it filters after loading.
    if direction is not None:
        items = [item for item in items if item.direction == direction]

    return TransactionListOut(items=items, total=total, page=page, page_size=page_size)


@router.get("/recent", response_model=list[TransactionOut])
def recent_transactions(
    limit: int = Query(default=10, ge=1, le=50), db: Session = Depends(get_db)
) -> list[TransactionOut]:
    """The last few entries, for the "what did I just do?" list."""
    stmt = (
        select(Transaction)
        .options(
            selectinload(Transaction.entries).selectinload(LedgerEntry.account),
            selectinload(Transaction.attachments),
        )
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(limit)
    )
    return [transaction_out(txn) for txn in db.scalars(stmt).all()]


@router.get("/{txn_id}", response_model=TransactionOut)
def get_transaction(txn_id: int, db: Session = Depends(get_db)) -> TransactionOut:
    txn = load_transaction(db, txn_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction_out(txn)


@router.post("/{txn_id}/reverse", response_model=TransactionOut, status_code=201)
def reverse(txn_id: int, reason: str = "", db: Session = Depends(get_db)) -> TransactionOut:
    """Undo a mistake by posting the mirror image, keeping the audit trail."""
    txn = load_transaction(db, txn_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        reversal = reverse_transaction(db, txn, reason=reason)
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return transaction_out(load_transaction(db, reversal.id))
