"""Payroll endpoints: employees, runs, approval, payment and remittances."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import chart_of_accounts as coa
from ..database import get_db
from ..dependencies import require_finance
from ..models import Employee, PayrollRun, Payslip
from ..schemas import (
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    PayrollOverviewOut,
    PayrollRunCreate,
    PayrollRunOut,
    PayslipUpdate,
    StatutoryRemittance,
    TransactionOut,
)
from ..serializers import payroll_run_out, payroll_run_summary, transaction_out
from ..services import payroll as payroll_service
from ..services.ledger import LedgerError, account_balances, load_transaction
from ..services.payroll import PayrollError
from ..services.payroll_rules import ACTIVE_RULES
from ..utils import resolve_period

router = APIRouter(dependencies=[Depends(require_finance)], prefix="/api/payroll", tags=["payroll"])


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _warnings(db: Session, run: PayrollRun) -> list[str]:
    """Flag cash wage payments that would double-count against this run."""
    clashes = payroll_service.ad_hoc_wage_payments(db, run)
    return [
        f"{txn.reference}: {txn.description or 'Worker Pay'} of RM{txn.amount:,.2f} on "
        f"{txn.txn_date:%d %b} was recorded outside this run. If it is part of this "
        f"payroll, reverse it so the wage is not counted twice."
        for txn in clashes
    ]


# --------------------------------------------------------------------------- #
# Employees
# --------------------------------------------------------------------------- #
@router.get("/employees", response_model=list[EmployeeOut])
def list_employees(
    include_inactive: bool = False, db: Session = Depends(get_db)
) -> list[EmployeeOut]:
    stmt = select(Employee).order_by(Employee.name)
    if not include_inactive:
        stmt = stmt.where(Employee.is_active.is_(True))
    return [EmployeeOut.model_validate(e) for e in db.scalars(stmt).all()]


@router.post("/employees", response_model=EmployeeOut, status_code=201)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db)) -> EmployeeOut:
    employee = Employee(**payload.model_dump())
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return EmployeeOut.model_validate(employee)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: int, payload: EmployeeUpdate, db: Session = Depends(get_db)
) -> EmployeeOut:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(employee, field, value)
    db.commit()
    db.refresh(employee)
    return EmployeeOut.model_validate(employee)


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
@router.get("/runs", response_model=list[dict])
def list_runs(
    limit: int = Query(default=12, ge=1, le=100), db: Session = Depends(get_db)
) -> list[dict]:
    runs = db.scalars(
        select(PayrollRun)
        .options(selectinload(PayrollRun.payslips))
        .order_by(PayrollRun.period_start.desc())
        .limit(limit)
    ).all()
    return [payroll_run_summary(run).model_dump(mode="json") for run in runs]


@router.post("/runs", response_model=PayrollRunOut, status_code=201)
def create_run(payload: PayrollRunCreate, db: Session = Depends(get_db)) -> PayrollRunOut:
    """Open a draft run with a payslip for every active employee."""
    try:
        run = payroll_service.create_run(db, payload)
    except PayrollError as exc:
        db.rollback()
        raise _fail(exc) from exc
    db.commit()
    run = payroll_service.load_run(db, run.id)
    return payroll_run_out(run, warnings=_warnings(db, run))


@router.get("/runs/{run_id}", response_model=PayrollRunOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> PayrollRunOut:
    run = payroll_service.load_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return payroll_run_out(run, warnings=_warnings(db, run))


@router.patch("/payslips/{payslip_id}", response_model=PayrollRunOut)
def update_payslip(
    payslip_id: int, payload: PayslipUpdate, db: Session = Depends(get_db)
) -> PayrollRunOut:
    """Edit one payslip's inputs. Returns the whole run so totals stay in step."""
    payslip = db.get(Payslip, payslip_id)
    if payslip is None:
        raise HTTPException(status_code=404, detail="Payslip not found")
    try:
        payroll_service.update_payslip(db, payslip, payload)
    except PayrollError as exc:
        db.rollback()
        raise _fail(exc) from exc
    db.commit()
    run = payroll_service.load_run(db, payslip.run_id)
    return payroll_run_out(run, warnings=_warnings(db, run))


@router.post("/runs/{run_id}/approve", response_model=PayrollRunOut)
def approve_run(run_id: int, db: Session = Depends(get_db)) -> PayrollRunOut:
    """Post the run to the ledger as one balanced accrual."""
    run = payroll_service.load_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    try:
        payroll_service.approve_run(db, run)
    except (PayrollError, LedgerError) as exc:
        db.rollback()
        raise _fail(exc) from exc
    db.commit()
    run = payroll_service.load_run(db, run_id)
    return payroll_run_out(run, warnings=_warnings(db, run))


@router.post("/runs/{run_id}/pay", response_model=PayrollRunOut)
def pay_run(
    run_id: int, method: str = "BANK", db: Session = Depends(get_db)
) -> PayrollRunOut:
    """Hand over the take-home pay, settling the net wages liability."""
    from ..models import PaymentMethod

    run = payroll_service.load_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    try:
        payroll_service.pay_run(db, run, method=PaymentMethod(method))
    except (PayrollError, LedgerError, ValueError) as exc:
        db.rollback()
        raise _fail(exc) from exc
    db.commit()
    run = payroll_service.load_run(db, run_id)
    return payroll_run_out(run, warnings=_warnings(db, run))


@router.post("/remit", response_model=TransactionOut, status_code=201)
def remit(payload: StatutoryRemittance, db: Session = Depends(get_db)) -> TransactionOut:
    """Forward withheld contributions to KWSP, PERKESO or LHDN."""
    try:
        txn = payroll_service.remit_statutory(
            db, payload.body, payload.amount, on=payload.on, method=payload.method
        )
    except (PayrollError, LedgerError) as exc:
        db.rollback()
        raise _fail(exc) from exc
    db.commit()
    return transaction_out(load_transaction(db, txn.id))


# --------------------------------------------------------------------------- #
# Overview - one call for the payroll panel
# --------------------------------------------------------------------------- #
@router.get("/overview", response_model=PayrollOverviewOut)
def overview(
    start: date | None = None,
    end: date | None = None,
    period: str = "month",
    db: Session = Depends(get_db),
) -> PayrollOverviewOut:
    start, end = resolve_period(start, end, period)

    runs = db.scalars(
        select(PayrollRun)
        .options(selectinload(PayrollRun.payslips).selectinload(Payslip.employee))
        .order_by(PayrollRun.period_start.desc())
        .limit(12)
    ).all()

    # The run to show open on the panel: the newest one overlapping the period,
    # falling back to the newest overall.
    current = next(
        (r for r in runs if r.period_start <= end and r.period_end >= start),
        runs[0] if runs else None,
    )

    employees = db.scalars(
        select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.name)
    ).all()

    period_balances = account_balances(db, start=start, end=end)

    return PayrollOverviewOut(
        runs=[payroll_run_summary(run) for run in runs],
        current=payroll_run_out(current, warnings=_warnings(db, current))
        if current
        else None,
        employees=[EmployeeOut.model_validate(e) for e in employees],
        outstanding_statutory=payroll_service.outstanding_statutory(db, as_of=end),
        period_wage_cost=period_balances.get(coa.WAGES, Decimal("0.00")),
        period_employer_contributions=period_balances.get(
            coa.EMPLOYER_STATUTORY, Decimal("0.00")
        ),
        rules_label=ACTIVE_RULES.label,
    )
