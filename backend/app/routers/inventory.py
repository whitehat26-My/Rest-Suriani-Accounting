"""Smart inventory endpoints: stock levels, purchases and counts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import InventoryItem, InventoryMovement
from ..schemas import (
    InventoryItemCreate,
    InventoryItemOut,
    InventoryItemUpdate,
    InventoryMovementOut,
    StockCountCreate,
    StockCountResultOut,
    StockPurchase,
    TransactionOut,
)
from ..serializers import inventory_item_out, transaction_out
from ..services import inventory as inventory_service
from ..services.inventory import InventoryError
from ..services.ledger import LedgerError, load_transaction

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("", response_model=list[InventoryItemOut])
def list_items(
    only_active: bool = True,
    low_only: bool = False,
    db: Session = Depends(get_db),
) -> list[InventoryItemOut]:
    """Stock on hand, with the colour band and days of cover for each item."""
    stmt = select(InventoryItem)
    if only_active:
        stmt = stmt.where(InventoryItem.is_active.is_(True))
    items = db.scalars(stmt.order_by(InventoryItem.category, InventoryItem.name)).all()
    if low_only:
        items = [item for item in items if item.status in ("low", "critical")]
    # Worst-stocked first: that is the order the owner needs to act in.
    items = sorted(items, key=lambda i: i.stock_ratio)
    return [inventory_item_out(item, db=db) for item in items]


@router.post("", response_model=InventoryItemOut, status_code=201)
def create_item(payload: InventoryItemCreate, db: Session = Depends(get_db)) -> InventoryItemOut:
    try:
        item = inventory_service.create_item(db, payload)
    except (InventoryError, LedgerError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return inventory_item_out(item, db=db)


@router.get("/{item_id}", response_model=InventoryItemOut)
def get_item(item_id: int, db: Session = Depends(get_db)) -> InventoryItemOut:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return inventory_item_out(item, db=db)


@router.patch("/{item_id}", response_model=InventoryItemOut)
def update_item(
    item_id: int, payload: InventoryItemUpdate, db: Session = Depends(get_db)
) -> InventoryItemOut:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    return inventory_item_out(item, db=db)


@router.get("/{item_id}/movements", response_model=list[InventoryMovementOut])
def item_movements(
    item_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[InventoryMovementOut]:
    """The stock card: every movement in and out, newest first."""
    if db.get(InventoryItem, item_id) is None:
        raise HTTPException(status_code=404, detail="Item not found")
    movements = db.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.item_id == item_id)
        .order_by(InventoryMovement.id.desc())
        .limit(limit)
    ).all()
    return [InventoryMovementOut.model_validate(m) for m in movements]


@router.post("/purchase", response_model=TransactionOut, status_code=201)
def purchase(payload: StockPurchase, db: Session = Depends(get_db)) -> TransactionOut:
    """Buy stock: posts to the ledger and updates quantity and average cost."""
    try:
        txn, _ = inventory_service.purchase_stock(db, payload)
    except (InventoryError, LedgerError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return transaction_out(load_transaction(db, txn.id))


@router.post("/count", response_model=list[StockCountResultOut], status_code=201)
def stock_count(payload: StockCountCreate, db: Session = Depends(get_db)) -> list[StockCountResultOut]:
    """The "Count Stock" button. Shortfalls become Cost of Goods Sold."""
    try:
        results = inventory_service.record_stock_count(db, payload)
    except (InventoryError, LedgerError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return results
