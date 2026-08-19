"""Statement generation, including the accounting identities that must hold."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app import chart_of_accounts as coa
from app.models import EventType, PaymentMethod
from app.schemas import TransactionCreate
from app.services.ledger import post_transaction
from app.services.statements import (
    balance_sheet,
    cash_flow_statement,
    income_statement,
    trial_balance,
)

TODAY = date.today()
MONTH_AGO = TODAY - timedelta(days=30)


def build_a_trading_month(db) -> None:
    """A small but complete month: capital, equipment, sales, costs, drawings."""
    entries = [
        (EventType.OWNER_CONTRIBUTION, "10000.00", {"payment_method": PaymentMethod.BANK}),
        (EventType.BUY_EQUIPMENT, "4000.00", {"payment_method": PaymentMethod.BANK}),
        (EventType.PURCHASE_INVENTORY_CASH, "2000.00", {}),
        (EventType.CASH_SALE, "5000.00", {}),
        (EventType.CREDIT_SALE, "1000.00", {"payment_method": PaymentMethod.CREDIT}),
        (EventType.COGS_USAGE, "1800.00", {}),
        (EventType.PAY_WAGES, "1200.00", {"payment_method": PaymentMethod.BANK}),
        (EventType.EXPENSE_CASH, "600.00", {"expense_account_code": coa.RENT}),
        (EventType.EXPENSE_CREDIT, "250.00", {"expense_account_code": coa.UTILITIES}),
        (EventType.DEPRECIATION, "100.00", {}),
        (EventType.OWNER_DRAWINGS, "500.00", {"payment_method": PaymentMethod.BANK}),
    ]
    for event_type, amount, extra in entries:
        post_transaction(
            db,
            TransactionCreate(
                event_type=event_type,
                amount=Decimal(amount),
                txn_date=MONTH_AGO + timedelta(days=1),
                **extra,
            ),
        )
    db.commit()


class TestIncomeStatement:
    def test_profit_is_revenue_less_every_cost(self, db):
        build_a_trading_month(db)
        report = income_statement(db, MONTH_AGO, TODAY)

        assert report.revenue == Decimal("6000.00")
        assert report.cost_of_sales == Decimal("1800.00")
        assert report.gross_profit == Decimal("4200.00")
        # Wages 1200 + rent 600 + utilities 250 + depreciation 100
        assert report.operating_expenses == Decimal("2150.00")
        assert report.operating_profit == Decimal("2050.00")
        assert report.net_profit == Decimal("2050.00")

    def test_margins_are_reported_as_percentages(self, db):
        build_a_trading_month(db)
        report = income_statement(db, MONTH_AGO, TODAY)
        assert report.gross_margin_pct == 70.0
        assert round(report.net_margin_pct, 1) == 34.2

    def test_drawings_never_reach_the_profit_statement(self, db):
        """Money the owner takes out is not a business cost."""
        build_a_trading_month(db)
        report = income_statement(db, MONTH_AGO, TODAY)
        labels = [line.label for section in report.sections for line in section.lines]
        assert not any("Drawings" in label for label in labels)

    def test_interest_sits_below_operating_profit(self, db):
        post_transaction(
            db,
            TransactionCreate(event_type=EventType.CASH_SALE, amount=Decimal("1000.00")),
        )
        post_transaction(
            db,
            TransactionCreate(
                event_type=EventType.LOAN_REPAYMENT,
                amount=Decimal("500.00"),
                interest_amount=Decimal("50.00"),
            ),
        )
        db.commit()
        report = income_statement(db, MONTH_AGO, TODAY)
        assert report.finance_costs == Decimal("50.00")
        assert report.operating_profit == Decimal("1000.00")
        assert report.net_profit == Decimal("950.00")

    def test_empty_period_reports_zero_rather_than_failing(self, db):
        report = income_statement(db, MONTH_AGO, TODAY)
        assert report.revenue == Decimal("0.00")
        assert report.net_profit == Decimal("0.00")
        assert report.gross_margin_pct == 0.0


class TestBalanceSheet:
    def test_the_accounting_equation_holds(self, db):
        """Assets = Liabilities + Equity. If this fails, nothing else matters."""
        build_a_trading_month(db)
        report = balance_sheet(db, TODAY)
        assert report.balances is True
        assert report.difference == Decimal("0.00")
        assert report.total_assets == report.total_liabilities + report.total_equity

    def test_retained_earnings_are_derived_from_profit(self, db):
        build_a_trading_month(db)
        profit = income_statement(db, MONTH_AGO, TODAY).net_profit
        report = balance_sheet(db, TODAY)
        equity_lines = {
            line.label: line.amount
            for section in report.sections
            if section.title == "Equity"
            for line in section.lines
        }
        assert equity_lines["Retained Earnings"] == profit

    def test_accumulated_depreciation_is_shown_as_a_deduction(self, db):
        build_a_trading_month(db)
        report = balance_sheet(db, TODAY)
        lines = {
            line.account_code: line
            for section in report.sections
            for line in section.lines
        }
        assert lines[coa.ACCUM_DEPRECIATION].amount == Decimal("-100.00")
        assert lines[coa.EQUIPMENT].amount == Decimal("4000.00")

    def test_equation_still_holds_after_a_loss(self, db):
        """A loss-making period is the case most likely to break the identity."""
        post_transaction(
            db, TransactionCreate(event_type=EventType.CASH_SALE, amount=Decimal("100.00"))
        )
        post_transaction(
            db,
            TransactionCreate(
                event_type=EventType.EXPENSE_CASH,
                amount=Decimal("900.00"),
                expense_account_code=coa.RENT,
            ),
        )
        db.commit()
        report = balance_sheet(db, TODAY)
        assert report.balances is True


class TestCashFlow:
    def test_the_statement_reconciles_to_the_movement_in_cash(self, db):
        build_a_trading_month(db)
        report = cash_flow_statement(db, MONTH_AGO, TODAY)
        assert report.reconciles is True
        assert report.opening_cash + report.net_change == report.closing_cash

    def test_equipment_purchases_are_investing_not_operating(self, db):
        build_a_trading_month(db)
        report = cash_flow_statement(db, MONTH_AGO, TODAY)
        assert report.net_investing == Decimal("-4000.00")

    def test_capital_and_drawings_are_financing(self, db):
        build_a_trading_month(db)
        report = cash_flow_statement(db, MONTH_AGO, TODAY)
        # 10,000 contributed less 500 drawn out.
        assert report.net_financing == Decimal("9500.00")

    def test_depreciation_is_added_back_as_a_non_cash_charge(self, db):
        build_a_trading_month(db)
        report = cash_flow_statement(db, MONTH_AGO, TODAY)
        operating = next(s for s in report.sections if "Operating" in s.title)
        addback = next(
            line for line in operating.lines if line.account_code == coa.ACCUM_DEPRECIATION
        )
        assert addback.amount == Decimal("100.00")

    def test_closing_cash_matches_the_balance_sheet(self, db):
        build_a_trading_month(db)
        cash_flow = cash_flow_statement(db, MONTH_AGO, TODAY)
        sheet = balance_sheet(db, TODAY)
        cash_lines = sum(
            line.amount
            for section in sheet.sections
            for line in section.lines
            if line.account_code in (coa.CASH_ON_HAND, coa.BANK)
        )
        assert cash_flow.closing_cash == cash_lines


class TestTrialBalance:
    def test_total_debits_equal_total_credits(self, db):
        build_a_trading_month(db)
        report = trial_balance(db, TODAY)
        assert report.balanced is True
        assert report.total_debit == report.total_credit

    def test_it_stays_balanced_after_a_reversal(self, db):
        from app.services.ledger import reverse_transaction

        txn = post_transaction(
            db, TransactionCreate(event_type=EventType.CASH_SALE, amount=Decimal("77.00"))
        )
        db.commit()
        reverse_transaction(db, txn)
        db.commit()
        assert trial_balance(db, TODAY).balanced is True
