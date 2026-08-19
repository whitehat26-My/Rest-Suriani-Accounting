"""Payroll: from hours worked to a posted, balanced ledger entry.

A payroll run moves through three states, and each one does a different job:

* **Draft** - freely editable. Nothing has touched the ledger, so a mistake here
  costs nothing and leaves no correcting entry behind.
* **Approved** - the run is recognised in the books as one balanced accrual.
  Gross pay becomes a wage cost, employer contributions become their own cost,
  and everything owed to staff and to the statutory bodies becomes a liability.
* **Paid** - the take-home pay actually leaves the bank. Statutory money is
  remitted separately, because KWSP, PERKESO and LHDN are each paid on their own
  schedule and usually after the staff are paid.

Splitting recognition from payment is what lets the Statement of Profit or Loss
show the month's true labour cost even when the wages are handed over in the
first week of the following month.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import chart_of_accounts as coa
from ..models import (
    Employee,
    EmploymentType,
    EventType,
    PayBasis,
    PaymentMethod,
    PayrollRun,
    PayrollStatus,
    Payslip,
    Transaction,
    TransactionSource,
)
from ..schemas import PayrollRunCreate, PayslipUpdate, TransactionCreate
from .ledger import ZERO, money, post_transaction
from .payroll_rules import compute_contributions

# The Employment Act's ordinary rate of pay divides a monthly wage by 26 days,
# and the hourly rate by a further 8 hours. Overtime on a normal working day is
# one and a half times that hourly rate.
DAYS_PER_MONTH = Decimal("26")
HOURS_PER_DAY = Decimal("8")
OVERTIME_MULTIPLIER = Decimal("1.5")


class PayrollError(ValueError):
    """Raised when a payroll operation is not valid in the run's current state."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Calculation
# --------------------------------------------------------------------------- #
def effective_overtime_rate(employee: Employee) -> Decimal:
    """The hourly overtime rate, derived from the pay basis when not set."""
    if employee.overtime_rate and employee.overtime_rate > 0:
        return employee.overtime_rate
    if employee.pay_basis is PayBasis.HOURLY:
        hourly = employee.base_rate
    elif employee.pay_basis is PayBasis.DAILY:
        hourly = employee.base_rate / HOURS_PER_DAY
    else:
        hourly = employee.base_rate / DAYS_PER_MONTH / HOURS_PER_DAY
    return money(hourly * OVERTIME_MULTIPLIER)


def monthly_proration(
    employee: Employee, period_start: date, period_end: date
) -> Decimal:
    """The share of a monthly salary earned over a partial period.

    Three things make a period partial: the run itself covers less than a whole
    month (a mid-month payroll, or the first run after go-live), the employee
    joined part way through, or they left part way through. All three are the
    same calculation - the overlap between the employee's service and the run,
    over the calendar days in the month.

    Returns 1 for a full month, so a normal run is unaffected.
    """
    covered_start = period_start
    covered_end = period_end
    if employee.joined_on and employee.joined_on > covered_start:
        covered_start = employee.joined_on
    if employee.left_on and employee.left_on < covered_end:
        covered_end = employee.left_on
    if covered_end < covered_start:
        return Decimal("0")

    days_in_month = Decimal(calendar.monthrange(period_start.year, period_start.month)[1])
    covered_days = Decimal((covered_end - covered_start).days + 1)
    if covered_days >= days_in_month:
        return Decimal("1")
    return covered_days / days_in_month


def calculate_payslip(
    payslip: Payslip,
    employee: Employee,
    *,
    pay_date: date,
    period_start: date | None = None,
    period_end: date | None = None,
) -> Payslip:
    """Fill in every derived figure on a payslip from its inputs.

    Contributions are computed on gross pay including allowances. That is the
    simple reading and it never under-deducts; a business that pays allowances
    which are genuinely exempt should record those separately.

    A monthly salary is prorated when the run covers less than a full month, or
    when the employee joined or left inside it.
    """
    if period_start is None or period_end is None:
        run = payslip.run
        period_start = period_start or (run.period_start if run else pay_date)
        period_end = period_end or (run.period_end if run else pay_date)

    if employee.pay_basis is PayBasis.MONTHLY:
        share = monthly_proration(employee, period_start, period_end)
        basic = money(employee.base_rate * share)
    elif employee.pay_basis is PayBasis.DAILY:
        basic = money(employee.base_rate * payslip.days_worked)
    else:
        basic = money(employee.base_rate * payslip.hours_worked)

    overtime = money(effective_overtime_rate(employee) * payslip.overtime_hours)
    gross = money(basic + overtime + payslip.allowances + payslip.bonus)

    contributions = compute_contributions(
        gross_pay=gross,
        contributes=employee.contributes_statutory,
        is_local=employee.is_local,
        age=employee.age_at(pay_date),
    )

    payslip.basic_pay = basic
    payslip.overtime_pay = overtime
    payslip.gross_pay = gross
    payslip.epf_employee = contributions.epf_employee
    payslip.epf_employer = contributions.epf_employer
    payslip.socso_employee = contributions.socso_employee
    payslip.socso_employer = contributions.socso_employer
    payslip.eis_employee = contributions.eis_employee
    payslip.eis_employer = contributions.eis_employer
    payslip.net_pay = money(gross - payslip.total_deductions)

    if payslip.net_pay < 0:
        raise PayrollError(
            f"Deductions for {employee.name} exceed gross pay "
            f"({money(payslip.total_deductions)} against {gross})."
        )
    return payslip


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
def next_run_reference(db: Session, period_end: date) -> str:
    prefix = f"PR-{period_end.year}-"
    highest = db.scalar(
        select(func.max(PayrollRun.reference)).where(PayrollRun.reference.like(f"{prefix}%"))
    )
    sequence = int(highest.rsplit("-", 1)[1]) + 1 if highest else 1
    return f"{prefix}{sequence:03d}"


def load_run(db: Session, run_id: int) -> PayrollRun | None:
    return db.scalar(
        select(PayrollRun)
        .where(PayrollRun.id == run_id)
        .options(selectinload(PayrollRun.payslips).selectinload(Payslip.employee))
    )


def create_run(db: Session, payload: PayrollRunCreate) -> PayrollRun:
    """Open a draft run with a payslip for every active employee."""
    existing = db.scalar(
        select(PayrollRun).where(
            PayrollRun.period_start == payload.period_start,
            PayrollRun.period_end == payload.period_end,
        )
    )
    if existing is not None:
        raise PayrollError(
            f"A payroll run for {payload.period_start} to {payload.period_end} "
            f"already exists ({existing.reference})."
        )
    if payload.period_end < payload.period_start:
        raise PayrollError("The period end cannot fall before the period start.")

    run = PayrollRun(
        reference=next_run_reference(db, payload.period_end),
        period_start=payload.period_start,
        period_end=payload.period_end,
        pay_date=payload.pay_date or payload.period_end,
        notes=payload.notes,
    )
    db.add(run)
    db.flush()

    employees = db.scalars(
        select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.name)
    ).all()
    if not employees:
        raise PayrollError("There are no active employees to pay.")

    working_days = payload.default_days_worked
    for employee in employees:
        # A casual worker's days are never assumed. Pre-filling a full month for
        # someone who works weekends would be an easy and expensive mistake to
        # approve without noticing.
        default_days = (
            ZERO
            if employee.employment_type is EmploymentType.CASUAL
            else working_days
        )
        # Every input is set explicitly: SQLAlchemy column defaults are applied
        # at INSERT, so a freshly constructed row would still be None here and
        # the calculation runs before the flush.
        payslip = Payslip(
            run_id=run.id,
            employee_id=employee.id,
            employee=employee,
            days_worked=default_days if employee.pay_basis is PayBasis.DAILY else ZERO,
            hours_worked=ZERO,
            overtime_hours=ZERO,
            allowances=money(
                (employee.fixed_allowance or ZERO)
                * monthly_proration(employee, run.period_start, run.period_end)
            ),
            bonus=ZERO,
            tax_deduction=ZERO,
            other_deductions=ZERO,
            note="",
        )
        calculate_payslip(
            payslip,
            employee,
            pay_date=run.pay_date,
            period_start=run.period_start,
            period_end=run.period_end,
        )
        db.add(payslip)
        run.payslips.append(payslip)

    db.flush()
    return run


def update_payslip(db: Session, payslip: Payslip, payload: PayslipUpdate) -> Payslip:
    """Edit one payslip's inputs and recompute everything that follows."""
    if not payslip.run.is_editable:
        raise PayrollError(
            f"Run {payslip.run.reference} is {payslip.run.status.value.lower()} and "
            "can no longer be edited. Reverse it if a correction is needed."
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(payslip, field, value)
    calculate_payslip(payslip, payslip.employee, pay_date=payslip.run.pay_date)
    db.flush()
    return payslip


def run_totals(run: PayrollRun) -> dict[str, Decimal]:
    """Every column total the accrual entry and the UI need."""
    fields = (
        "basic_pay",
        "overtime_pay",
        "allowances",
        "bonus",
        "gross_pay",
        "epf_employee",
        "epf_employer",
        "socso_employee",
        "socso_employer",
        "eis_employee",
        "eis_employer",
        "tax_deduction",
        "other_deductions",
        "net_pay",
    )
    totals = {field: run.total(field) for field in fields}
    totals["employer_contributions"] = money(
        totals["epf_employer"] + totals["socso_employer"] + totals["eis_employer"]
    )
    totals["employee_deductions"] = money(
        totals["epf_employee"]
        + totals["socso_employee"]
        + totals["eis_employee"]
        + totals["tax_deduction"]
        + totals["other_deductions"]
    )
    totals["employer_cost"] = money(totals["gross_pay"] + totals["employer_contributions"])
    return totals


def ad_hoc_wage_payments(db: Session, run: PayrollRun) -> list[Transaction]:
    """Cash wage payments recorded outside this run, in the same period.

    Grandma Mode's "Worker Pay" button posts straight to wages, which is right
    for a casual helper paid from the till. If those payments overlap a formal
    payroll run, the same wage is in the books twice - so the run surfaces them
    rather than letting the labour cost quietly double.
    """
    return list(
        db.scalars(
            select(Transaction).where(
                Transaction.event_type == EventType.PAY_WAGES,
                Transaction.txn_date >= run.period_start,
                Transaction.txn_date <= run.period_end,
            )
        ).all()
    )


# --------------------------------------------------------------------------- #
# Posting
# --------------------------------------------------------------------------- #
def approve_run(db: Session, run: PayrollRun) -> Transaction:
    """Recognise the run in the ledger as a single balanced accrual."""
    if run.status is not PayrollStatus.DRAFT:
        raise PayrollError(f"Run {run.reference} has already been approved.")
    if not run.payslips:
        raise PayrollError("A payroll run with no payslips cannot be approved.")

    totals = run_totals(run)
    if totals["gross_pay"] <= 0:
        raise PayrollError("Total gross pay is zero, so there is nothing to post.")

    # Accrue at the period end, but never in the future: a run approved
    # mid-month would otherwise post a cost dated past today, and month-to-date
    # reporting would show the month's labour as zero.
    accrual_date = min(run.period_end, date.today())

    txn = post_transaction(
        db,
        TransactionCreate(
            event_type=EventType.PAYROLL_ACCRUAL,
            amount=totals["employer_cost"],
            txn_date=accrual_date,
            description=f"Payroll {run.reference} ({run.period_start:%d %b} - "
            f"{run.period_end:%d %b %Y})",
            source=TransactionSource.ACCOUNTANT_UI,
            components={
                "gross": totals["gross_pay"],
                "epf_employee": totals["epf_employee"],
                "epf_employer": totals["epf_employer"],
                "socso_employee": totals["socso_employee"],
                "socso_employer": totals["socso_employer"],
                "eis_employee": totals["eis_employee"],
                "eis_employer": totals["eis_employer"],
                "tax": totals["tax_deduction"],
                "other_deductions": totals["other_deductions"],
                "net": totals["net_pay"],
            },
        ),
    )

    run.status = PayrollStatus.APPROVED
    run.accrual_transaction_id = txn.id
    run.approved_at = _utcnow()
    db.flush()
    return txn


def pay_run(
    db: Session, run: PayrollRun, *, method: PaymentMethod = PaymentMethod.BANK
) -> Transaction:
    """Hand over the take-home pay, settling the net wages liability."""
    if run.status is PayrollStatus.DRAFT:
        raise PayrollError(f"Run {run.reference} must be approved before it is paid.")
    if run.status is PayrollStatus.PAID:
        raise PayrollError(f"Run {run.reference} has already been paid.")

    net = run_totals(run)["net_pay"]
    if net <= 0:
        raise PayrollError("There is no net pay to hand over.")

    txn = post_transaction(
        db,
        TransactionCreate(
            event_type=EventType.PAY_NET_WAGES,
            amount=net,
            txn_date=run.pay_date,
            description=f"Net wages for {run.reference}",
            payment_method=method,
            source=TransactionSource.ACCOUNTANT_UI,
        ),
    )

    run.status = PayrollStatus.PAID
    run.payment_transaction_id = txn.id
    run.paid_at = _utcnow()
    db.flush()
    return txn


# Which payable each statutory body is paid from.
STATUTORY_BODIES: dict[str, tuple[str, str]] = {
    "EPF": (coa.EPF_PAYABLE, "KWSP"),
    "SOCSO": (coa.SOCSO_PAYABLE, "PERKESO"),
    "EIS": (coa.EIS_PAYABLE, "PERKESO"),
    "TAX": (coa.TAX_PAYABLE, "LHDN"),
}


def remit_statutory(
    db: Session,
    body: str,
    amount: Decimal,
    *,
    on: date | None = None,
    method: PaymentMethod = PaymentMethod.BANK,
) -> Transaction:
    """Forward withheld contributions to KWSP, PERKESO or LHDN."""
    key = body.upper()
    if key not in STATUTORY_BODIES:
        raise PayrollError(
            f"Unknown statutory body {body!r}. Expected one of "
            f"{sorted(STATUTORY_BODIES)}."
        )
    if amount <= 0:
        raise PayrollError("A remittance must be a positive amount.")

    account_code, counterparty = STATUTORY_BODIES[key]
    return post_transaction(
        db,
        TransactionCreate(
            event_type=EventType.REMIT_STATUTORY,
            amount=money(amount),
            txn_date=on or date.today(),
            description=f"{key} contributions remitted",
            counterparty=counterparty,
            payment_method=method,
            liability_account_code=account_code,
            source=TransactionSource.ACCOUNTANT_UI,
        ),
    )


def outstanding_statutory(db: Session, *, as_of: date | None = None) -> dict[str, Decimal]:
    """What is still owed to each statutory body."""
    from .ledger import account_balances

    balances = account_balances(db, end=as_of)
    return {
        body: money(balances.get(code, ZERO))
        for body, (code, _) in STATUTORY_BODIES.items()
    }
