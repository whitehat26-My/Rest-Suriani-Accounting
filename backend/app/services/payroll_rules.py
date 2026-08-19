"""Malaysian statutory contribution rules.

**Read this before trusting the numbers.** Contribution rates and wage ceilings
are set by KWSP, PERKESO and LHDN and they change - the EPF employee rate has
moved twice in recent years, and the SOCSO/EIS wage ceiling was raised. Every
rate lives in :data:`MALAYSIA_2025` below rather than being scattered through the
code, so updating them is a single edit with no logic to re-read.

Two deliberate simplifications, both visible rather than hidden:

* **EPF** is officially a banded schedule (the Third Schedule), which computes
  on RM20 wage bands and rounds the contribution up to the next ringgit. This
  module applies the headline percentage and rounds up to the next ringgit,
  which matches the schedule for the great majority of wages but can differ by
  up to a ringgit at a band edge.
* **SOCSO and EIS** are also published as banded tables. This module applies the
  headline percentage against the wage ceiling, which tracks the table closely
  but is not identical band for band.

For a restaurant paying a handful of staff this is accurate enough to run the
books and to see the true cost of labour. Before filing a statutory return,
check the figures against the official schedule for the month in question.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")


def _sen(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _up_to_ringgit(value: Decimal) -> Decimal:
    """EPF contributions are rounded up to the next whole ringgit."""
    if value <= 0:
        return ZERO
    return value.quantize(Decimal("1"), rounding=ROUND_CEILING).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class StatutoryRules:
    """Every rate the payroll calculator needs, in one place."""

    label: str

    # --- EPF (KWSP) --------------------------------------------------------
    # Below the wage threshold the employer rate is the higher one.
    epf_employee_rate: Decimal = Decimal("0.11")
    epf_employer_rate_low: Decimal = Decimal("0.13")
    epf_employer_rate_high: Decimal = Decimal("0.12")
    epf_employer_threshold: Decimal = Decimal("5000.00")
    # From age 60 the employee stops contributing and the employer rate drops.
    epf_senior_age: int = 60
    epf_employee_rate_senior: Decimal = Decimal("0.00")
    epf_employer_rate_senior: Decimal = Decimal("0.04")
    # Foreign workers who opt in: employer pays a flat amount, not a percentage.
    epf_employer_flat_foreign: Decimal = Decimal("5.00")

    # --- SOCSO (PERKESO) ---------------------------------------------------
    socso_ceiling: Decimal = Decimal("6000.00")
    socso_employee_rate: Decimal = Decimal("0.005")
    socso_employer_rate: Decimal = Decimal("0.0175")
    # Foreign workers are covered for employment injury only, employer-funded.
    socso_employer_rate_foreign: Decimal = Decimal("0.0125")
    socso_employee_rate_foreign: Decimal = Decimal("0.00")
    # From 60, only the employment-injury portion applies.
    socso_senior_age: int = 60

    # --- EIS (SIP) ---------------------------------------------------------
    eis_ceiling: Decimal = Decimal("6000.00")
    eis_employee_rate: Decimal = Decimal("0.002")
    eis_employer_rate: Decimal = Decimal("0.002")
    # EIS does not cover foreign workers, nor anyone from age 60.
    eis_max_age: int = 60


MALAYSIA_2025 = StatutoryRules(label="Malaysia (verify against current KWSP/PERKESO schedules)")

# The rule set the calculator uses. Point this at a different instance to model
# another jurisdiction, or edit MALAYSIA_2025 when the official rates change.
ACTIVE_RULES = MALAYSIA_2025


@dataclass(frozen=True)
class ContributionResult:
    epf_employee: Decimal = ZERO
    epf_employer: Decimal = ZERO
    socso_employee: Decimal = ZERO
    socso_employer: Decimal = ZERO
    eis_employee: Decimal = ZERO
    eis_employer: Decimal = ZERO

    @property
    def employee_total(self) -> Decimal:
        return _sen(self.epf_employee + self.socso_employee + self.eis_employee)

    @property
    def employer_total(self) -> Decimal:
        return _sen(self.epf_employer + self.socso_employer + self.eis_employer)


def compute_contributions(
    *,
    gross_pay: Decimal,
    contributes: bool,
    is_local: bool = True,
    age: int | None = None,
    rules: StatutoryRules = ACTIVE_RULES,
) -> ContributionResult:
    """Work out both sides of the statutory contributions for one payslip.

    ``age`` may be ``None`` when the date of birth is unknown, in which case the
    under-60 rates apply - the common case, and the one that under-deducts from
    nobody.
    """
    if not contributes or gross_pay <= 0:
        return ContributionResult()

    senior = age is not None and age >= rules.epf_senior_age

    # ---- EPF -------------------------------------------------------------
    if not is_local:
        # Foreign workers may opt in; the employer side is a flat amount.
        epf_employee = _up_to_ringgit(gross_pay * rules.epf_employee_rate)
        epf_employer = rules.epf_employer_flat_foreign
    elif senior:
        epf_employee = _up_to_ringgit(gross_pay * rules.epf_employee_rate_senior)
        epf_employer = _up_to_ringgit(gross_pay * rules.epf_employer_rate_senior)
    else:
        employer_rate = (
            rules.epf_employer_rate_low
            if gross_pay <= rules.epf_employer_threshold
            else rules.epf_employer_rate_high
        )
        epf_employee = _up_to_ringgit(gross_pay * rules.epf_employee_rate)
        epf_employer = _up_to_ringgit(gross_pay * employer_rate)

    # ---- SOCSO -----------------------------------------------------------
    socso_wage = min(gross_pay, rules.socso_ceiling)
    if not is_local:
        socso_employee = _sen(socso_wage * rules.socso_employee_rate_foreign)
        socso_employer = _sen(socso_wage * rules.socso_employer_rate_foreign)
    elif age is not None and age >= rules.socso_senior_age:
        # Employment injury only once past the invalidity scheme's age limit.
        socso_employee = ZERO
        socso_employer = _sen(socso_wage * rules.socso_employer_rate_foreign)
    else:
        socso_employee = _sen(socso_wage * rules.socso_employee_rate)
        socso_employer = _sen(socso_wage * rules.socso_employer_rate)

    # ---- EIS -------------------------------------------------------------
    eligible_for_eis = is_local and (age is None or age < rules.eis_max_age)
    if eligible_for_eis:
        eis_wage = min(gross_pay, rules.eis_ceiling)
        eis_employee = _sen(eis_wage * rules.eis_employee_rate)
        eis_employer = _sen(eis_wage * rules.eis_employer_rate)
    else:
        eis_employee = eis_employer = ZERO

    return ContributionResult(
        epf_employee=epf_employee,
        epf_employer=epf_employer,
        socso_employee=socso_employee,
        socso_employer=socso_employer,
        eis_employee=eis_employee,
        eis_employer=eis_employer,
    )
