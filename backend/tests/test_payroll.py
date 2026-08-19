"""Payroll: statutory calculation, proration, and how a run reaches the ledger."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app import chart_of_accounts as coa
from app.models import Employee, EmploymentType, PayBasis, PayrollStatus
from app.schemas import PayrollRunCreate, PayslipUpdate, TransactionCreate
from app.services.ledger import account_balances, post_transaction
from app.services.payroll import (
    PayrollError,
    approve_run,
    calculate_payslip,
    create_run,
    effective_overtime_rate,
    monthly_proration,
    outstanding_statutory,
    pay_run,
    remit_statutory,
    run_totals,
    update_payslip,
)
from app.services.payroll_rules import compute_contributions

JUNE = (date(2026, 6, 1), date(2026, 6, 30))


def add_employee(db, **overrides) -> Employee:
    defaults = dict(
        name="Nurul Aina",
        position="Cook",
        employment_type=EmploymentType.PERMANENT,
        pay_basis=PayBasis.MONTHLY,
        base_rate=Decimal("2000.00"),
        fixed_allowance=Decimal("0.00"),
        overtime_rate=Decimal("0.00"),
        contributes_statutory=True,
        is_local=True,
        is_active=True,
    )
    defaults.update(overrides)
    employee = Employee(**defaults)
    db.add(employee)
    db.flush()
    return employee


def make_run(db, start=JUNE[0], end=JUNE[1]) -> object:
    run = create_run(db, PayrollRunCreate(period_start=start, period_end=end))
    db.commit()
    return run


# --------------------------------------------------------------------------- #
# Statutory contributions
# --------------------------------------------------------------------------- #
class TestStatutoryContributions:
    def test_standard_local_employee(self):
        """11% employee, 13% employer below the threshold, rounded up to RM1."""
        result = compute_contributions(gross_pay=Decimal("2000.00"), contributes=True)
        assert result.epf_employee == Decimal("220.00")
        assert result.epf_employer == Decimal("260.00")
        assert result.socso_employee == Decimal("10.00")   # 0.5%
        assert result.socso_employer == Decimal("35.00")   # 1.75%
        assert result.eis_employee == Decimal("4.00")      # 0.2%
        assert result.eis_employer == Decimal("4.00")

    def test_epf_contributions_round_up_to_the_next_ringgit(self):
        """The EPF schedule never leaves sen on a contribution."""
        result = compute_contributions(gross_pay=Decimal("1855.50"), contributes=True)
        # 11% of 1855.50 is 204.105, which rounds up to 205.
        assert result.epf_employee == Decimal("205.00")
        assert result.epf_employee % 1 == 0

    def test_employer_rate_drops_above_the_wage_threshold(self):
        low = compute_contributions(gross_pay=Decimal("5000.00"), contributes=True)
        high = compute_contributions(gross_pay=Decimal("5001.00"), contributes=True)
        assert low.epf_employer == Decimal("650.00")   # 13%
        assert high.epf_employer == Decimal("601.00")  # 12%, rounded up

    def test_socso_and_eis_stop_at_the_wage_ceiling(self):
        """A high earner contributes on the ceiling, not on the full wage."""
        result = compute_contributions(gross_pay=Decimal("9000.00"), contributes=True)
        assert result.socso_employee == Decimal("30.00")  # 0.5% of the 6,000 ceiling
        assert result.eis_employee == Decimal("12.00")    # 0.2% of the 6,000 ceiling

    def test_employees_from_sixty_stop_contributing_to_epf(self):
        result = compute_contributions(
            gross_pay=Decimal("2000.00"), contributes=True, age=63
        )
        assert result.epf_employee == Decimal("0.00")
        assert result.epf_employer == Decimal("80.00")  # the reduced 4% rate
        assert result.eis_employee == Decimal("0.00")   # EIS does not apply from 60

    def test_foreign_workers_pay_a_flat_employer_epf_and_no_eis(self):
        result = compute_contributions(
            gross_pay=Decimal("2000.00"), contributes=True, is_local=False
        )
        assert result.epf_employer == Decimal("5.00")
        assert result.eis_employee == Decimal("0.00")
        assert result.eis_employer == Decimal("0.00")
        assert result.socso_employer == Decimal("25.00")  # injury scheme only

    def test_an_employee_outside_the_schemes_contributes_nothing(self):
        result = compute_contributions(gross_pay=Decimal("900.00"), contributes=False)
        assert result.employee_total == Decimal("0.00")
        assert result.employer_total == Decimal("0.00")

    def test_unknown_age_uses_the_under_sixty_rates(self):
        """Missing a date of birth must never under-deduct."""
        known = compute_contributions(gross_pay=Decimal("2000.00"), contributes=True, age=40)
        unknown = compute_contributions(gross_pay=Decimal("2000.00"), contributes=True)
        assert unknown == known


# --------------------------------------------------------------------------- #
# Pay calculation
# --------------------------------------------------------------------------- #
class TestPayCalculation:
    def test_a_monthly_payslip_nets_off_the_deductions(self, db):
        add_employee(db)
        run = make_run(db)
        slip = run.payslips[0]

        assert slip.basic_pay == Decimal("2000.00")
        assert slip.gross_pay == Decimal("2000.00")
        assert slip.total_deductions == Decimal("234.00")  # 220 + 10 + 4
        assert slip.net_pay == Decimal("1766.00")

    def test_employer_cost_exceeds_gross_by_the_contributions(self, db):
        """The figure the owner should budget for, not the salary."""
        add_employee(db)
        run = make_run(db)
        slip = run.payslips[0]
        assert slip.employer_contributions == Decimal("299.00")  # 260 + 35 + 4
        assert slip.employer_cost == Decimal("2299.00")

    def test_a_daily_rate_multiplies_by_days_worked(self, db):
        add_employee(
            db,
            name="Rina",
            pay_basis=PayBasis.DAILY,
            base_rate=Decimal("90.00"),
            employment_type=EmploymentType.PART_TIME,
            contributes_statutory=False,
        )
        run = create_run(
            db,
            PayrollRunCreate(
                period_start=JUNE[0], period_end=JUNE[1], default_days_worked=Decimal("12")
            ),
        )
        db.commit()
        assert run.payslips[0].gross_pay == Decimal("1080.00")
        assert run.payslips[0].net_pay == Decimal("1080.00")

    def test_casual_staff_start_at_zero_days(self, db):
        """Never pre-fill a month of work for someone who comes in occasionally.

        Approving that by accident would pay a weekend helper for a full month.
        """
        add_employee(
            db,
            name="Rina",
            pay_basis=PayBasis.DAILY,
            base_rate=Decimal("90.00"),
            employment_type=EmploymentType.CASUAL,
            contributes_statutory=False,
        )
        run = create_run(
            db,
            PayrollRunCreate(
                period_start=JUNE[0], period_end=JUNE[1], default_days_worked=Decimal("26")
            ),
        )
        db.commit()
        assert run.payslips[0].days_worked == Decimal("0.000")
        assert run.payslips[0].gross_pay == Decimal("0.00")

    def test_a_run_of_only_unworked_casuals_cannot_be_approved(self, db):
        """Zero gross means there is nothing to recognise."""
        add_employee(
            db,
            name="Rina",
            pay_basis=PayBasis.DAILY,
            base_rate=Decimal("90.00"),
            employment_type=EmploymentType.CASUAL,
            contributes_statutory=False,
        )
        run = make_run(db)
        with pytest.raises(PayrollError, match="nothing to post"):
            approve_run(db, run)

    def test_overtime_uses_the_statutory_hourly_formula(self, db):
        """Monthly wage / 26 days / 8 hours, at one and a half times."""
        employee = add_employee(db, base_rate=Decimal("2080.00"))
        # 2080 / 26 / 8 = 10.00 per hour, so overtime is 15.00.
        assert effective_overtime_rate(employee) == Decimal("15.00")

        run = make_run(db)
        update_payslip(db, run.payslips[0], PayslipUpdate(overtime_hours=Decimal("10")))
        db.commit()
        assert run.payslips[0].overtime_pay == Decimal("150.00")
        assert run.payslips[0].gross_pay == Decimal("2230.00")

    def test_an_explicit_overtime_rate_wins(self, db):
        employee = add_employee(db, overtime_rate=Decimal("20.00"))
        assert effective_overtime_rate(employee) == Decimal("20.00")

    def test_deductions_larger_than_gross_are_refused(self, db):
        add_employee(db)
        run = make_run(db)
        with pytest.raises(PayrollError, match="exceed gross pay"):
            update_payslip(
                db, run.payslips[0], PayslipUpdate(other_deductions=Decimal("5000.00"))
            )


class TestProration:
    def test_a_full_month_is_never_prorated(self, db):
        employee = add_employee(db)
        assert monthly_proration(employee, *JUNE) == Decimal("1")

    def test_a_partial_period_scales_the_salary(self, db):
        """A run covering 15 of June's 30 days pays half a month."""
        add_employee(db)
        run = make_run(db, date(2026, 6, 1), date(2026, 6, 15))
        assert run.payslips[0].basic_pay == Decimal("1000.00")

    def test_joining_mid_month_only_pays_from_the_join_date(self, db):
        add_employee(db, joined_on=date(2026, 6, 16))
        run = make_run(db)
        # 15 days of a 30-day month.
        assert run.payslips[0].basic_pay == Decimal("1000.00")

    def test_leaving_mid_month_stops_the_pay(self, db):
        add_employee(db, left_on=date(2026, 6, 10))
        run = make_run(db)
        # 10 days of a 30-day month.
        assert run.payslips[0].basic_pay == Decimal("666.67")

    def test_allowances_are_prorated_with_the_salary(self, db):
        add_employee(db, fixed_allowance=Decimal("300.00"))
        run = make_run(db, date(2026, 6, 1), date(2026, 6, 15))
        assert run.payslips[0].allowances == Decimal("150.00")


# --------------------------------------------------------------------------- #
# Runs and the ledger
# --------------------------------------------------------------------------- #
class TestRunLifecycle:
    def test_a_new_run_covers_every_active_employee(self, db):
        add_employee(db, name="Aina")
        add_employee(db, name="Faiz")
        add_employee(db, name="Departed", is_active=False)
        run = make_run(db)
        assert [slip.employee.name for slip in run.payslips] == ["Aina", "Faiz"]
        assert run.status is PayrollStatus.DRAFT
        assert run.reference.startswith("PR-2026-")

    def test_duplicate_periods_are_refused(self, db):
        add_employee(db)
        make_run(db)
        with pytest.raises(PayrollError, match="already exists"):
            create_run(db, PayrollRunCreate(period_start=JUNE[0], period_end=JUNE[1]))

    def test_a_run_with_no_employees_is_refused(self, db):
        with pytest.raises(PayrollError, match="no active employees"):
            create_run(db, PayrollRunCreate(period_start=JUNE[0], period_end=JUNE[1]))

    def test_an_inverted_period_is_refused(self, db):
        add_employee(db)
        with pytest.raises(PayrollError, match="period end cannot fall before"):
            create_run(db, PayrollRunCreate(period_start=JUNE[1], period_end=JUNE[0]))

    def test_a_draft_writes_nothing_to_the_ledger(self, db):
        """Editing a draft must be free of consequences."""
        add_employee(db)
        make_run(db)
        balances = account_balances(db)
        assert balances[coa.WAGES] == Decimal("0.00")
        assert balances[coa.NET_WAGES_PAYABLE] == Decimal("0.00")

    def test_approving_posts_one_balanced_accrual(self, db):
        add_employee(db)
        run = make_run(db)
        txn = approve_run(db, run)
        db.commit()

        assert txn.is_balanced
        assert run.status is PayrollStatus.APPROVED
        assert run.accrual_transaction_id == txn.id

        balances = account_balances(db)
        # Gross is the wage cost; the employer's contributions sit separately.
        assert balances[coa.WAGES] == Decimal("2000.00")
        assert balances[coa.EMPLOYER_STATUTORY] == Decimal("299.00")
        # Everything owed is a liability until the money actually moves.
        assert balances[coa.NET_WAGES_PAYABLE] == Decimal("1766.00")
        assert balances[coa.EPF_PAYABLE] == Decimal("480.00")    # 220 + 260
        assert balances[coa.SOCSO_PAYABLE] == Decimal("45.00")   # 10 + 35
        assert balances[coa.EIS_PAYABLE] == Decimal("8.00")      # 4 + 4

    def test_approving_moves_no_cash(self, db):
        """Recognising a cost is not the same as paying it."""
        add_employee(db)
        run = make_run(db)
        approve_run(db, run)
        db.commit()
        balances = account_balances(db)
        assert balances[coa.BANK] == Decimal("0.00")
        assert balances[coa.CASH_ON_HAND] == Decimal("0.00")

    def test_an_approved_run_can_no_longer_be_edited(self, db):
        add_employee(db)
        run = make_run(db)
        approve_run(db, run)
        db.commit()
        with pytest.raises(PayrollError, match="can no longer be edited"):
            update_payslip(db, run.payslips[0], PayslipUpdate(bonus=Decimal("100.00")))

    def test_a_run_cannot_be_approved_twice(self, db):
        add_employee(db)
        run = make_run(db)
        approve_run(db, run)
        db.commit()
        with pytest.raises(PayrollError, match="already been approved"):
            approve_run(db, run)

    def test_paying_settles_the_net_wages_liability(self, db):
        add_employee(db)
        run = make_run(db)
        approve_run(db, run)
        pay_run(db, run)
        db.commit()

        balances = account_balances(db)
        assert run.status is PayrollStatus.PAID
        assert balances[coa.NET_WAGES_PAYABLE] == Decimal("0.00")
        assert balances[coa.BANK] == Decimal("-1766.00")
        # The statutory money is still held, not yet remitted.
        assert balances[coa.EPF_PAYABLE] == Decimal("480.00")

    def test_a_run_must_be_approved_before_it_is_paid(self, db):
        add_employee(db)
        run = make_run(db)
        with pytest.raises(PayrollError, match="must be approved"):
            pay_run(db, run)

    def test_a_run_cannot_be_paid_twice(self, db):
        add_employee(db)
        run = make_run(db)
        approve_run(db, run)
        pay_run(db, run)
        db.commit()
        with pytest.raises(PayrollError, match="already been paid"):
            pay_run(db, run)


class TestRemittance:
    def test_remitting_clears_the_statutory_payable(self, db):
        add_employee(db)
        run = make_run(db)
        approve_run(db, run)
        db.commit()

        assert outstanding_statutory(db)["EPF"] == Decimal("480.00")
        remit_statutory(db, "EPF", Decimal("480.00"))
        db.commit()

        assert outstanding_statutory(db)["EPF"] == Decimal("0.00")
        assert account_balances(db)[coa.BANK] == Decimal("-480.00")

    def test_an_unknown_body_is_refused(self, db):
        with pytest.raises(PayrollError, match="Unknown statutory body"):
            remit_statutory(db, "KWSP-ish", Decimal("100.00"))

    def test_a_non_positive_remittance_is_refused(self, db):
        with pytest.raises(PayrollError, match="positive amount"):
            remit_statutory(db, "EPF", Decimal("0.00"))


class TestTotalsAndIntegrity:
    def test_the_accrual_leaves_the_books_balanced(self, db):
        from app.services.statements import balance_sheet, trial_balance

        add_employee(db, name="Aina", base_rate=Decimal("2400.00"))
        add_employee(db, name="Faiz", base_rate=Decimal("1800.00"))
        add_employee(
            db, name="Rina", pay_basis=PayBasis.DAILY, base_rate=Decimal("90.00"),
            contributes_statutory=False,
        )
        run = make_run(db)
        approve_run(db, run)
        pay_run(db, run)
        db.commit()

        assert trial_balance(db, date(2026, 6, 30)).balanced is True
        assert balance_sheet(db, date(2026, 6, 30)).balances is True

    def test_run_totals_add_up_across_the_team(self, db):
        add_employee(db, name="Aina", base_rate=Decimal("2400.00"))
        add_employee(db, name="Faiz", base_rate=Decimal("1800.00"))
        run = make_run(db)
        totals = run_totals(run)

        assert totals["gross_pay"] == Decimal("4200.00")
        assert totals["net_pay"] == sum(s.net_pay for s in run.payslips)
        assert totals["employer_cost"] == (
            totals["gross_pay"] + totals["employer_contributions"]
        )
        # Gross less what the employee gives up is exactly the take-home.
        assert totals["gross_pay"] - totals["employee_deductions"] == totals["net_pay"]

    def test_ad_hoc_cash_wages_in_the_period_are_flagged(self, db):
        """The one way this module could silently double-count labour."""
        from app.models import EventType
        from app.services.payroll import ad_hoc_wage_payments

        add_employee(db)
        post_transaction(
            db,
            TransactionCreate(
                event_type=EventType.PAY_WAGES,
                amount=Decimal("300.00"),
                txn_date=date(2026, 6, 12),
                description="Paid weekend helper cash",
            ),
        )
        run = make_run(db)
        clashes = ad_hoc_wage_payments(db, run)
        assert len(clashes) == 1
        assert clashes[0].amount == Decimal("300.00")

    def test_payments_outside_the_period_are_not_flagged(self, db):
        from app.models import EventType
        from app.services.payroll import ad_hoc_wage_payments

        add_employee(db)
        post_transaction(
            db,
            TransactionCreate(
                event_type=EventType.PAY_WAGES,
                amount=Decimal("300.00"),
                txn_date=date(2026, 5, 12),
            ),
        )
        run = make_run(db)
        assert ad_hoc_wage_payments(db, run) == []


# --------------------------------------------------------------------------- #
# Printable documents
# --------------------------------------------------------------------------- #
class TestYearToDate:
    def test_it_totals_approved_runs_only(self, db):
        """A draft is not yet a fact about the year."""
        from app.services.payroll import year_to_date

        add_employee(db)
        june = make_run(db, date(2026, 6, 1), date(2026, 6, 30))
        approve_run(db, june)
        db.commit()

        july = make_run(db, date(2026, 7, 1), date(2026, 7, 31))
        db.commit()
        assert july.status is PayrollStatus.DRAFT

        employee_id = june.payslips[0].employee_id
        totals = year_to_date(db, employee_id, date(2026, 7, 31))
        # Only June counts, even though July's draft exists.
        assert totals["gross"] == Decimal("2000.00")
        assert totals["net"] == Decimal("1766.00")

        approve_run(db, july)
        db.commit()
        assert year_to_date(db, employee_id, date(2026, 7, 31))["gross"] == Decimal("4000.00")

    def test_it_stops_at_the_run_being_printed(self, db):
        """Reprinting June's payslip must not show July's figures."""
        from app.services.payroll import year_to_date

        add_employee(db)
        for start, end in ((date(2026, 6, 1), date(2026, 6, 30)),
                           (date(2026, 7, 1), date(2026, 7, 31))):
            run = make_run(db, start, end)
            approve_run(db, run)
            db.commit()

        employee_id = run.payslips[0].employee_id
        assert year_to_date(db, employee_id, date(2026, 6, 30))["gross"] == Decimal("2000.00")

    def test_a_previous_year_does_not_leak_in(self, db):
        from app.services.payroll import year_to_date

        add_employee(db)
        old = make_run(db, date(2025, 12, 1), date(2025, 12, 31))
        approve_run(db, old)
        db.commit()
        new = make_run(db, date(2026, 1, 1), date(2026, 1, 31))
        approve_run(db, new)
        db.commit()

        employee_id = new.payslips[0].employee_id
        assert year_to_date(db, employee_id, date(2026, 1, 31))["gross"] == Decimal("2000.00")


class TestPayrollDocuments:
    """The PDFs are checked by reading their text back, not by eyeballing them."""

    @staticmethod
    def text_of(pdf_bytes: bytes) -> str:
        import subprocess
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.pdf"
            path.write_bytes(pdf_bytes)
            result = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                check=True,
            )
        return result.stdout

    @pytest.fixture()
    def approved_run(self, db):
        add_employee(
            db,
            name="Nurul Aina",
            base_rate=Decimal("2400.00"),
            ic_number="880615-10-5522",
            epf_number="12345678",
            bank_name="Maybank",
            bank_account="5140 2233 4455",
        )
        add_employee(db, name="Mohd Faiz", base_rate=Decimal("1800.00"))
        run = make_run(db)
        approve_run(db, run)
        db.commit()
        return run

    def test_a_payslip_carries_the_figures_the_reader_needs(self, db, approved_run):
        from app.services.payroll_pdf import payslips_pdf

        slip = next(s for s in approved_run.payslips if s.employee.name == "Nurul Aina")
        text = self.text_of(payslips_pdf(approved_run, [slip]))

        assert slip.employee.name in text
        assert "PAYSLIP" in text
        assert "NET PAY" in text
        assert f"RM{slip.net_pay:,.2f}" in text
        assert f"RM{slip.gross_pay:,.2f}" in text
        # The reference numbers an employee checks against their own records.
        assert "880615-10-5522" in text
        assert "Maybank" in text

    def test_a_payslip_says_employer_contributions_are_not_deductions(self, db, approved_run):
        """The most commonly misread line on a Malaysian payslip."""
        from app.services.payroll_pdf import payslips_pdf

        text = self.text_of(payslips_pdf(approved_run, [approved_run.payslips[0]]))
        assert "PAID BY THE RESTAURANT FOR YOU" in text
        assert "not taken out of your pay" in text

    def test_one_page_per_employee(self, db, approved_run):
        from pypdf import PdfReader
        import io

        from app.services.payroll_pdf import payslips_pdf

        reader = PdfReader(io.BytesIO(payslips_pdf(approved_run)))
        assert len(reader.pages) == len(approved_run.payslips) == 2

    def test_a_draft_is_stamped_so_it_cannot_be_handed_out_by_mistake(self, db):
        from app.services.payroll_pdf import payslips_pdf, summary_pdf

        add_employee(db)
        run = make_run(db)
        assert run.status is PayrollStatus.DRAFT

        # The diagonal wash is what the eye catches, but rotated text does not
        # survive extraction, so the horizontal banner is what gets asserted -
        # and it is also what survives a greyscale printer.
        assert "NOT YET APPROVED" in self.text_of(payslips_pdf(run))
        assert "NOT FOR ISSUE" in self.text_of(payslips_pdf(run))
        assert "NOT YET APPROVED" in self.text_of(summary_pdf(run))

    def test_an_approved_document_carries_no_stamp(self, db, approved_run):
        from app.services.payroll_pdf import payslips_pdf

        assert "NOT YET APPROVED" not in self.text_of(payslips_pdf(approved_run))

    def test_the_summary_lists_everyone_with_totals_and_bank_details(self, db, approved_run):
        from app.services.payroll_pdf import summary_pdf

        text = self.text_of(summary_pdf(approved_run))
        totals = run_totals(approved_run)

        for slip in approved_run.payslips:
            assert slip.employee.name in text
        assert "TOTAL" in text
        assert f"RM{totals['gross_pay']:,.2f}" in text
        assert f"RM{totals['net_pay']:,.2f}" in text
        # The account the transfer is keyed from must never be clipped.
        assert "5140 2233 4455" in text

    def test_the_summary_shows_what_is_owed_to_each_body(self, db, approved_run):
        from app.services.payroll_pdf import summary_pdf

        text = self.text_of(summary_pdf(approved_run))
        assert "TO REMIT FROM THIS RUN" in text
        for body in ("KWSP", "PERKESO", "LHDN"):
            assert body in text

    def test_the_year_to_date_block_appears_when_supplied(self, db, approved_run):
        from app.services.payroll import year_to_date
        from app.services.payroll_pdf import payslips_pdf

        slip = approved_run.payslips[0]
        ytd = {slip.employee_id: year_to_date(db, slip.employee_id, approved_run.period_end)}
        text = self.text_of(payslips_pdf(approved_run, [slip], ytd_by_employee=ytd))
        assert "YEAR TO DATE" in text
