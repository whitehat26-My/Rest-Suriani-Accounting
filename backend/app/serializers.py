"""Turning ORM objects into API responses, including the plain-language layer."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from .config import settings
from .models import Attachment, InventoryItem, PayrollRun, Payslip, Transaction
from .schemas import (
    AttachmentOut,
    InventoryItemOut,
    LedgerEntryOut,
    PayrollRunOut,
    PayrollRunSummary,
    PayrollTotals,
    PayslipOut,
    TransactionOut,
)
from .services.ledger import EVENT_DIRECTION, EVENT_FRIENDLY


def attachment_out(attachment: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        url=f"/api/uploads/{attachment.id}/file",
    )


def friendly_label(txn: Transaction) -> str:
    """Short plain-language name, for lists that display the amount separately."""
    label = EVENT_FRIENDLY.get(txn.event_type, txn.event_type.value.replace("_", " ").title())
    if txn.counterparty:
        direction = EVENT_DIRECTION.get(txn.event_type, "neutral")
        return f"{label} {'from' if direction == 'in' else 'to'} {txn.counterparty}"
    return label


def friendly_summary(txn: Transaction) -> str:
    """One sentence an owner can read without knowing any accounting.

    Example: "Bought food and ingredients - RM50.00 to Pasar Borong".
    """
    label = EVENT_FRIENDLY.get(txn.event_type, txn.event_type.value.replace("_", " ").title())
    amount = f"{settings.currency}{txn.amount:,.2f}"
    parts = [f"{label} - {amount}"]
    if txn.counterparty:
        direction = EVENT_DIRECTION.get(txn.event_type, "neutral")
        parts.append(f"{'from' if direction == 'in' else 'to'} {txn.counterparty}")
    if txn.description and txn.description.lower() not in label.lower():
        parts.append(f"({txn.description})")
    return " ".join(parts)


def transaction_out(txn: Transaction) -> TransactionOut:
    return TransactionOut(
        id=txn.id,
        reference=txn.reference,
        event_type=txn.event_type,
        txn_date=txn.txn_date,
        amount=txn.amount,
        description=txn.description,
        counterparty=txn.counterparty,
        payment_method=txn.payment_method,
        source=txn.source,
        raw_input=txn.raw_input,
        notes=txn.notes,
        is_reversed=txn.is_reversed,
        created_at=txn.created_at,
        entries=[
            LedgerEntryOut(
                id=entry.id,
                account_id=entry.account_id,
                account_code=entry.account.code,
                account_name=entry.account.name,
                side=entry.side,
                amount=entry.amount,
                memo=entry.memo,
            )
            for entry in txn.entries
        ],
        attachments=[attachment_out(a) for a in txn.attachments],
        friendly_summary=friendly_summary(txn),
        friendly_label=friendly_label(txn),
        direction=EVENT_DIRECTION.get(txn.event_type, "neutral"),
    )


def inventory_item_out(
    item: InventoryItem, *, db: Session | None = None, cover: float | None = None
) -> InventoryItemOut:
    if cover is None and db is not None:
        from .services.inventory import days_of_cover

        cover = days_of_cover(db, item)
    return InventoryItemOut(
        id=item.id,
        name=item.name,
        local_name=item.local_name,
        category=item.category,
        unit=item.unit,
        quantity_on_hand=item.quantity_on_hand,
        unit_cost=item.unit_cost,
        reorder_level=item.reorder_level,
        par_level=item.par_level,
        emoji=item.emoji,
        is_active=item.is_active,
        stock_value=item.stock_value,
        stock_ratio=item.stock_ratio,
        status=item.status,
        days_of_cover=cover,
    )


def decimal_or_zero(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0.00")


# --------------------------------------------------------------------------- #
# Payroll
# --------------------------------------------------------------------------- #
def payslip_out(payslip: Payslip) -> PayslipOut:
    return PayslipOut(
        id=payslip.id,
        employee_id=payslip.employee_id,
        employee_name=payslip.employee.name,
        position=payslip.employee.position,
        pay_basis=payslip.employee.pay_basis,
        days_worked=payslip.days_worked,
        hours_worked=payslip.hours_worked,
        overtime_hours=payslip.overtime_hours,
        basic_pay=payslip.basic_pay,
        overtime_pay=payslip.overtime_pay,
        allowances=payslip.allowances,
        bonus=payslip.bonus,
        gross_pay=payslip.gross_pay,
        epf_employee=payslip.epf_employee,
        socso_employee=payslip.socso_employee,
        eis_employee=payslip.eis_employee,
        tax_deduction=payslip.tax_deduction,
        other_deductions=payslip.other_deductions,
        total_deductions=payslip.total_deductions,
        epf_employer=payslip.epf_employer,
        socso_employer=payslip.socso_employer,
        eis_employer=payslip.eis_employer,
        employer_contributions=payslip.employer_contributions,
        employer_cost=payslip.employer_cost,
        net_pay=payslip.net_pay,
        note=payslip.note,
    )


def payroll_run_out(run: PayrollRun, *, warnings: list[str] | None = None) -> PayrollRunOut:
    from .services.payroll import run_totals

    return PayrollRunOut(
        id=run.id,
        reference=run.reference,
        period_start=run.period_start,
        period_end=run.period_end,
        pay_date=run.pay_date,
        status=run.status,
        notes=run.notes,
        accrual_transaction_id=run.accrual_transaction_id,
        payment_transaction_id=run.payment_transaction_id,
        headcount=len(run.payslips),
        payslips=[payslip_out(slip) for slip in run.payslips],
        totals=PayrollTotals(**run_totals(run)),
        ad_hoc_wage_warnings=warnings or [],
    )


def payroll_run_summary(run: PayrollRun) -> PayrollRunSummary:
    from .services.payroll import run_totals

    totals = run_totals(run)
    return PayrollRunSummary(
        id=run.id,
        reference=run.reference,
        period_start=run.period_start,
        period_end=run.period_end,
        pay_date=run.pay_date,
        status=run.status,
        headcount=len(run.payslips),
        gross_pay=totals["gross_pay"],
        employer_cost=totals["employer_cost"],
        net_pay=totals["net_pay"],
    )
