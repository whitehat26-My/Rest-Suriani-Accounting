"""Printable payroll documents.

Two documents, because two different people need them:

* **Payslips** - one page each, handed to the member of staff. They answer
  "what did I earn, what was taken off, and why", and they say plainly that the
  employer's EPF and SOCSO are paid *on top* rather than deducted, which is the
  thing people most often misread on a payslip.
* **The run summary** - one landscape page for the owner and the accountant,
  with every payslip on it, the totals, what is owed to each statutory body, and
  the bank details needed to actually pay everyone.

Both are laid out on the canvas directly rather than as flowing documents. A
payslip is a fixed form, not an article: the net pay box belongs in the same
place on every page so it can be found at a glance across a stack of them.

A run that has not been approved is stamped DRAFT across the page. An
unapproved payslip handed out by mistake is a hard thing to take back.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

from ..branding import (
    BAND,
    CREAM,
    GOLD,
    INK,
    INK_FAINT,
    INK_SOFT,
    LOGO_ASPECT,
    LOGO_MARK_PATH,
    MAROON,
    NEGATIVE,
    POSITIVE,
    RULE,
    WHITE,
)
from ..config import settings
from ..models import PayrollRun, PayrollStatus, Payslip
from .payroll import run_totals

PORTRAIT = A4
LANDSCAPE = landscape(A4)

MARGIN = 16 * mm
BAND_HEIGHT = 26 * mm


def rm(value: Decimal | float | int | None) -> str:
    """Money, always with the currency and always to the sen."""
    if value is None:
        return "-"
    return f"{settings.currency}{Decimal(str(value)):,.2f}"


def _qty(value: Decimal | None, decimals: int = 0) -> str:
    if value is None:
        return "-"
    number = Decimal(str(value))
    return f"{number:,.{decimals}f}"


def _period(run: PayrollRun) -> str:
    return f"{run.period_start:%d %b %Y} to {run.period_end:%d %b %Y}"


# --------------------------------------------------------------------------- #
# Shared furniture
# --------------------------------------------------------------------------- #
def _letterhead(c: pdf_canvas.Canvas, width: float, height: float, title: str, subtitle: str) -> float:
    """Draw the branded band. Returns the y coordinate to carry on below it."""
    c.setFillColor(MAROON)
    c.rect(0, height - BAND_HEIGHT, width, BAND_HEIGHT, stroke=0, fill=1)

    # The mark has no background of its own, so it sits directly on the band
    # with no seam at any size.
    if LOGO_MARK_PATH.exists():
        logo_width = 56 * mm
        logo_height = logo_width / LOGO_ASPECT
        c.drawImage(
            str(LOGO_MARK_PATH),
            MARGIN,
            height - BAND_HEIGHT + (BAND_HEIGHT - logo_height) / 2,
            width=logo_width,
            height=logo_height,
            preserveAspectRatio=True,
            anchor="w",
            mask="auto",
        )
    else:  # pragma: no cover - the artwork ships with the app
        c.setFillColor(CREAM)
        c.setFont("Times-Bold", 20)
        c.drawString(MARGIN, height - BAND_HEIGHT + 9 * mm, settings.business_name)

    c.setFillColor(CREAM)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(width - MARGIN, height - BAND_HEIGHT + 14 * mm, title)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(GOLD)
    c.drawRightString(width - MARGIN, height - BAND_HEIGHT + 9 * mm, subtitle)

    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2)
    c.line(0, height - BAND_HEIGHT, width, height - BAND_HEIGHT)

    return height - BAND_HEIGHT - 12 * mm


def _footer(c: pdf_canvas.Canvas, width: float, note: str, page_label: str = "") -> None:
    c.setStrokeColor(RULE)
    c.setLineWidth(0.5)
    c.line(MARGIN, 14 * mm, width - MARGIN, 14 * mm)
    c.setFillColor(INK_FAINT)
    c.setFont("Helvetica", 7)
    c.drawString(MARGIN, 10 * mm, note)
    if page_label:
        c.drawRightString(width - MARGIN, 10 * mm, page_label)


def _draft_stamp(c: pdf_canvas.Canvas, width: float, height: float) -> float:
    """Make an unapproved document impossible to mistake for a final one.

    Two marks, because one is not reliable. The diagonal wash is what the eye
    catches, but it can wash out on a greyscale printer, so a horizontal banner
    states it in plain running text as well.

    Returns the y offset the caller should subtract from its content start.
    """
    c.saveState()
    c.translate(width / 2, height / 2)
    c.rotate(32)
    c.setFont("Helvetica-Bold", 76)
    c.setFillColor(MAROON, alpha=0.11)
    c.drawCentredString(0, 0, "DRAFT")
    c.restoreState()

    banner_height = 7 * mm
    banner_y = height - BAND_HEIGHT - banner_height
    c.setFillColor(MAROON, alpha=0.10)
    c.rect(0, banner_y, width, banner_height, stroke=0, fill=1)
    c.setFillColor(MAROON, alpha=1)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(
        width / 2,
        banner_y + 2.3 * mm,
        "DRAFT - NOT YET APPROVED - NOT FOR ISSUE",
    )
    return banner_height + 2 * mm


def _label(c: pdf_canvas.Canvas, x: float, y: float, text: str) -> None:
    c.setFillColor(INK_FAINT)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawString(x, y, text.upper())


def _value(c: pdf_canvas.Canvas, x: float, y: float, text: str, size: float = 9.5) -> None:
    c.setFillColor(INK)
    c.setFont("Helvetica", size)
    c.drawString(x, y, text or "-")


# --------------------------------------------------------------------------- #
# Payslip
# --------------------------------------------------------------------------- #
def _payslip_page(
    c: pdf_canvas.Canvas,
    payslip: Payslip,
    run: PayrollRun,
    ytd: dict[str, Decimal] | None = None,
) -> None:
    width, height = PORTRAIT
    employee = payslip.employee
    draft = run.status is PayrollStatus.DRAFT

    y = _letterhead(c, width, height, "PAYSLIP", _period(run))
    if draft:
        y -= _draft_stamp(c, width, height)

    # --- Who and when -----------------------------------------------------
    c.setFillColor(BAND)
    c.rect(MARGIN, y - 26 * mm, width - 2 * MARGIN, 26 * mm, stroke=0, fill=1)

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN + 6 * mm, y - 9 * mm, employee.name)
    c.setFillColor(INK_SOFT)
    c.setFont("Helvetica", 9.5)
    c.drawString(
        MARGIN + 6 * mm,
        y - 14 * mm,
        f"{employee.position} · {employee.employment_type.value.replace('_', ' ').title()}",
    )

    right = width - MARGIN - 6 * mm
    c.setFillColor(INK_FAINT)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawRightString(right, y - 8 * mm, "PAYSLIP NO.")
    c.drawRightString(right, y - 15 * mm, "PAY DATE")
    c.setFillColor(INK)
    c.setFont("Helvetica", 9.5)
    c.drawRightString(right, y - 12 * mm, f"{run.reference}-{payslip.id:03d}")
    c.drawRightString(right, y - 19 * mm, f"{run.pay_date:%d %B %Y}")

    # Reference numbers, in the smallest type that still prints cleanly.
    detail_y = y - 22 * mm
    for index, (label, value) in enumerate(
        [
            ("I/C NO.", employee.ic_number),
            ("EPF NO.", employee.epf_number),
            ("SOCSO NO.", employee.socso_number),
            ("BANK", f"{employee.bank_name} {employee.bank_account}".strip()),
        ]
    ):
        column_x = MARGIN + 6 * mm + index * ((width - 2 * MARGIN - 12 * mm) / 4)
        _label(c, column_x, detail_y, label)
        c.setFillColor(INK_SOFT)
        c.setFont("Helvetica", 8)
        c.drawString(column_x, detail_y - 4 * mm, value or "-")

    y -= 34 * mm

    # --- Earnings and deductions, side by side ----------------------------
    column_width = (width - 2 * MARGIN - 6 * mm) / 2
    left_x, right_x = MARGIN, MARGIN + column_width + 6 * mm

    earnings: list[tuple[str, Decimal]] = [("Basic pay", payslip.basic_pay)]
    if payslip.overtime_pay > 0:
        earnings.append(
            (f"Overtime ({_qty(payslip.overtime_hours, 1)} hours)", payslip.overtime_pay)
        )
    if payslip.allowances > 0:
        earnings.append(("Allowances", payslip.allowances))
    if payslip.bonus > 0:
        earnings.append(("Bonus", payslip.bonus))

    deductions: list[tuple[str, Decimal]] = []
    if payslip.epf_employee > 0:
        deductions.append(("EPF (KWSP)", payslip.epf_employee))
    if payslip.socso_employee > 0:
        deductions.append(("SOCSO (PERKESO)", payslip.socso_employee))
    if payslip.eis_employee > 0:
        deductions.append(("EIS (SIP)", payslip.eis_employee))
    if payslip.tax_deduction > 0:
        deductions.append(("Income tax (PCB)", payslip.tax_deduction))
    if payslip.other_deductions > 0:
        deductions.append(("Other deductions", payslip.other_deductions))
    if not deductions:
        deductions.append(("No deductions", Decimal("0.00")))

    rows = max(len(earnings), len(deductions))
    table_height = 10 * mm + rows * 6 * mm + 9 * mm

    for x, heading, items, total, tone in (
        (left_x, "EARNINGS", earnings, payslip.gross_pay, POSITIVE),
        (right_x, "DEDUCTIONS", deductions, payslip.total_deductions, NEGATIVE),
    ):
        c.setFillColor(MAROON)
        c.rect(x, y - 7 * mm, column_width, 7 * mm, stroke=0, fill=1)
        c.setFillColor(CREAM)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 3 * mm, y - 4.8 * mm, heading)

        row_y = y - 13 * mm
        for index, (name, amount) in enumerate(items):
            if index % 2 == 1:
                c.setFillColor(BAND)
                c.rect(x, row_y - 1.8 * mm, column_width, 6 * mm, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont("Helvetica", 9)
            c.drawString(x + 3 * mm, row_y, name)
            c.drawRightString(x + column_width - 3 * mm, row_y, rm(amount))
            row_y -= 6 * mm

        line_y = y - table_height + 7 * mm
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(x, line_y, x + column_width, line_y)
        c.setFillColor(tone)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(x + 3 * mm, line_y - 5 * mm, f"Total {heading.lower()}")
        c.drawRightString(x + column_width - 3 * mm, line_y - 5 * mm, rm(total))

    y -= table_height + 8 * mm

    # --- Net pay: the one number the reader came for ----------------------
    box_height = 20 * mm
    c.setFillColor(MAROON)
    c.rect(MARGIN, y - box_height, width - 2 * MARGIN, box_height, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN + 6 * mm, y - 8 * mm, "NET PAY")
    c.setFillColor(CREAM)
    c.setFont("Helvetica", 7.5)
    c.drawString(MARGIN + 6 * mm, y - 13.5 * mm, "Amount paid to you")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 24)
    c.drawRightString(width - MARGIN - 6 * mm, y - 13 * mm, rm(payslip.net_pay))

    y -= box_height + 8 * mm

    # --- What the employer pays on top ------------------------------------
    # The most commonly misread part of a Malaysian payslip: these are not
    # deductions, and saying so plainly saves the owner the same conversation
    # every month.
    contributions = [
        ("EPF (KWSP)", payslip.epf_employer),
        ("SOCSO (PERKESO)", payslip.socso_employer),
        ("EIS (SIP)", payslip.eis_employer),
    ]
    if payslip.employer_contributions > 0:
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.rect(MARGIN, y - 22 * mm, width - 2 * MARGIN, 22 * mm, stroke=1, fill=0)

        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(MARGIN + 6 * mm, y - 6 * mm, "PAID BY THE RESTAURANT FOR YOU")
        c.setFillColor(INK_SOFT)
        c.setFont("Helvetica", 7.5)
        c.drawString(
            MARGIN + 6 * mm,
            y - 10 * mm,
            "These are contributions your employer pays on top of your salary. "
            "They are not taken out of your pay.",
        )

        for index, (name, amount) in enumerate(contributions):
            column_x = MARGIN + 6 * mm + index * 52 * mm
            c.setFillColor(INK_FAINT)
            c.setFont("Helvetica", 7.5)
            c.drawString(column_x, y - 16 * mm, name)
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(column_x, y - 20 * mm, rm(amount))

        c.setFillColor(INK_FAINT)
        c.setFont("Helvetica", 7.5)
        c.drawRightString(width - MARGIN - 6 * mm, y - 16 * mm, "Total cost to employer")
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(width - MARGIN - 6 * mm, y - 20 * mm, rm(payslip.employer_cost))

    y -= 30 * mm

    # --- Year to date -----------------------------------------------------
    # Standard on a payslip and genuinely useful: it is what someone needs when
    # they apply for a loan or check their own EPF statement.
    if ytd:
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(MARGIN, y, f"YEAR TO DATE {run.period_end:%Y}")
        c.setFillColor(INK_SOFT)
        c.setFont("Helvetica", 7.5)
        c.drawString(
            MARGIN + 34 * mm, y, "Approved payroll runs from January up to this one."
        )
        y -= 6 * mm

        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(MARGIN, y + 3 * mm, width - MARGIN, y + 3 * mm)

        ytd_columns = [
            ("Gross pay", ytd["gross"]),
            ("EPF", ytd["epf"]),
            ("SOCSO", ytd["socso"]),
            ("EIS", ytd["eis"]),
            ("Tax (PCB)", ytd["tax"]),
            ("Net pay", ytd["net"]),
        ]
        column_span = (width - 2 * MARGIN) / len(ytd_columns)
        for index, (name, amount) in enumerate(ytd_columns):
            column_x = MARGIN + index * column_span
            c.setFillColor(INK_FAINT)
            c.setFont("Helvetica", 7)
            c.drawString(column_x, y - 3 * mm, name)
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(column_x, y - 8 * mm, rm(amount))
        y -= 14 * mm

    if payslip.note:
        c.setFillColor(INK_SOFT)
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(MARGIN, y, f"Note: {payslip.note}")

    # --- Acknowledgement, anchored to the foot of the page ----------------
    # Some staff are paid in cash, and a signed line is the only record that the
    # money was handed over. Fixing its position means it is in the same place
    # on every payslip in a stack.
    ack_y = 34 * mm
    c.setFillColor(INK_FAINT)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawString(MARGIN, ack_y + 8 * mm, "RECEIVED BY")
    for index, (label, span) in enumerate(
        [("Signature", 70 * mm), ("Date", 40 * mm)]
    ):
        x = MARGIN + index * 80 * mm
        c.setStrokeColor(INK_FAINT)
        c.setLineWidth(0.5)
        c.line(x, ack_y, x + span, ack_y)
        c.setFillColor(INK_FAINT)
        c.setFont("Helvetica", 7)
        c.drawString(x, ack_y - 4 * mm, label)

    _footer(
        c,
        width,
        f"{settings.business_name} · Generated {date.today():%d %B %Y} · "
        "This payslip is computer generated and does not require a signature.",
    )


def payslips_pdf(
    run: PayrollRun,
    payslips: list[Payslip] | None = None,
    ytd_by_employee: dict[int, dict[str, Decimal]] | None = None,
) -> bytes:
    """One page per employee, ready to print and hand out."""
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=PORTRAIT)
    c.setTitle(f"Payslips {run.reference}")
    c.setAuthor(settings.business_name)
    c.setSubject(f"Payslips for {_period(run)}")

    chosen = payslips if payslips is not None else list(run.payslips)
    for index, payslip in enumerate(chosen):
        if index:
            c.showPage()
        _payslip_page(
            c, payslip, run, (ytd_by_employee or {}).get(payslip.employee_id)
        )

    c.save()
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Run summary
# --------------------------------------------------------------------------- #
# name, relative width, alignment, font size
SUMMARY_COLUMNS: list[tuple[str, float, str, float]] = [
    ("Employee", 42, "left", 7.6),
    ("Position", 22, "left", 7.0),
    ("Days", 12, "right", 7.6),
    ("OT hrs", 13, "right", 7.6),
    ("Basic", 22, "right", 7.6),
    ("Overtime", 22, "right", 7.6),
    ("Allow.", 20, "right", 7.6),
    ("Gross", 24, "right", 7.6),
    ("EPF", 19, "right", 7.6),
    ("SOCSO", 19, "right", 7.6),
    ("EIS", 17, "right", 7.6),
    ("Other", 19, "right", 7.6),
    ("Net pay", 25, "right", 7.6),
    ("Bank account", 46, "left", 6.8),
]


def _summary_row_values(payslip: Payslip) -> list[str]:
    employee = payslip.employee
    daily = employee.pay_basis.value == "DAILY"
    return [
        employee.name,
        employee.position,
        _qty(payslip.days_worked) if daily else "-",
        _qty(payslip.overtime_hours, 1),
        rm(payslip.basic_pay),
        rm(payslip.overtime_pay),
        rm(payslip.allowances),
        rm(payslip.gross_pay),
        rm(payslip.epf_employee),
        rm(payslip.socso_employee),
        rm(payslip.eis_employee),
        rm(payslip.other_deductions),
        rm(payslip.net_pay),
        f"{employee.bank_name} {employee.bank_account}".strip() or "-",
    ]


def summary_pdf(run: PayrollRun) -> bytes:
    """The whole run on one landscape page, with the totals and what is owed."""
    width, height = LANDSCAPE
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=LANDSCAPE)
    c.setTitle(f"Payroll summary {run.reference}")
    c.setAuthor(settings.business_name)

    totals = run_totals(run)
    draft = run.status is PayrollStatus.DRAFT

    y = _letterhead(c, width, height, "PAYROLL SUMMARY", _period(run))
    if draft:
        y -= _draft_stamp(c, width, height)

    # --- Run header -------------------------------------------------------
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN, y, f"{run.reference}")
    c.setFillColor(INK_SOFT)
    c.setFont("Helvetica", 9)
    c.drawString(
        MARGIN + 30 * mm,
        y,
        f"{len(run.payslips)} staff · paid {run.pay_date:%d %B %Y} · {run.status.value.title()}",
    )
    y -= 9 * mm

    # --- The table --------------------------------------------------------
    total_units = sum(w for _, w, _, _ in SUMMARY_COLUMNS)
    available = width - 2 * MARGIN
    scale = available / total_units

    def draw_row(
        values: list[str], row_y: float, *, bold: bool = False, size: float | None = None
    ) -> None:
        font = "Helvetica-Bold" if bold else "Helvetica"
        x = MARGIN
        for (_, unit_width, align, column_size), value in zip(SUMMARY_COLUMNS, values):
            point_size = size if size is not None else column_size
            c.setFont(font, point_size)
            column_width = unit_width * scale
            if align == "right":
                c.drawRightString(x + column_width - 1.5 * mm, row_y, value)
            else:
                # Clip a long name rather than letting it run into the next
                # column, which would make the whole row unreadable.
                text = value
                if c.stringWidth(text, font, point_size) > column_width - 3 * mm:
                    while (
                        len(text) > 1
                        and c.stringWidth(text + "…", font, point_size)
                        > column_width - 3 * mm
                    ):
                        text = text[:-1]
                    text += "…"
                c.drawString(x + 1.5 * mm, row_y, text)
            x += column_width

    header_y = y
    c.setFillColor(MAROON)
    c.rect(MARGIN, header_y - 6.5 * mm, available, 6.5 * mm, stroke=0, fill=1)
    c.setFillColor(CREAM)
    draw_row([name for name, _, _, _ in SUMMARY_COLUMNS], header_y - 4.4 * mm, bold=True, size=7)

    row_y = header_y - 12 * mm
    for index, payslip in enumerate(run.payslips):
        if index % 2 == 1:
            c.setFillColor(BAND)
            c.rect(MARGIN, row_y - 1.9 * mm, available, 6.2 * mm, stroke=0, fill=1)
        c.setFillColor(INK)
        draw_row(_summary_row_values(payslip), row_y)
        row_y -= 6.2 * mm

    # Totals
    c.setStrokeColor(MAROON)
    c.setLineWidth(0.9)
    c.line(MARGIN, row_y + 3 * mm, MARGIN + available, row_y + 3 * mm)
    c.setFillColor(MAROON)
    draw_row(
        [
            "TOTAL",
            f"{len(run.payslips)} staff",
            "",
            "",
            rm(totals["basic_pay"]),
            rm(totals["overtime_pay"]),
            rm(totals["allowances"]),
            rm(totals["gross_pay"]),
            rm(totals["epf_employee"]),
            rm(totals["socso_employee"]),
            rm(totals["eis_employee"]),
            rm(totals["other_deductions"]),
            rm(totals["net_pay"]),
            "",
        ],
        row_y - 2 * mm,
        bold=True,
        size=7.8,
    )

    y = row_y - 12 * mm

    # --- What this run costs, and what is owed to whom --------------------
    card_width = (width - 2 * MARGIN - 3 * 4 * mm) / 4
    cards = [
        ("Gross pay", rm(totals["gross_pay"]), "Charged to Salaries & Wages"),
        ("Net pay to staff", rm(totals["net_pay"]), "Transferred on the pay date"),
        (
            "Employer contributions",
            rm(totals["employer_contributions"]),
            "EPF and SOCSO paid on top",
        ),
        (
            "Total cost to restaurant",
            rm(totals["employer_cost"]),
            "Gross plus employer contributions",
        ),
    ]
    for index, (label, value, note) in enumerate(cards):
        x = MARGIN + index * (card_width + 4 * mm)
        c.setFillColor(BAND)
        c.rect(x, y - 18 * mm, card_width, 18 * mm, stroke=0, fill=1)
        c.setFillColor(INK_FAINT)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(x + 3 * mm, y - 5 * mm, label.upper())
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(x + 3 * mm, y - 11.5 * mm, value)
        c.setFillColor(INK_SOFT)
        c.setFont("Helvetica", 6.5)
        c.drawString(x + 3 * mm, y - 15.5 * mm, note)

    y -= 25 * mm

    # --- Statutory remittances -------------------------------------------
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(MARGIN, y, "TO REMIT FROM THIS RUN")
    c.setFillColor(INK_SOFT)
    c.setFont("Helvetica", 7.5)
    c.drawString(
        MARGIN + 48 * mm,
        y,
        "Employee and employer portions combined. Each body is paid separately.",
    )
    y -= 6 * mm

    remittances = [
        ("EPF · KWSP", totals["epf_employee"] + totals["epf_employer"]),
        ("SOCSO · PERKESO", totals["socso_employee"] + totals["socso_employer"]),
        ("EIS · PERKESO", totals["eis_employee"] + totals["eis_employer"]),
        ("PCB · LHDN", totals["tax_deduction"]),
    ]
    for index, (body, amount) in enumerate(remittances):
        x = MARGIN + index * 48 * mm
        c.setFillColor(INK_SOFT)
        c.setFont("Helvetica", 7.5)
        c.drawString(x, y, body)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y - 5 * mm, rm(amount))

    # --- Signatures -------------------------------------------------------
    sign_y = 26 * mm
    for index, role in enumerate(["Prepared by", "Approved by"]):
        x = MARGIN + index * 70 * mm
        c.setStrokeColor(INK_FAINT)
        c.setLineWidth(0.5)
        c.line(x, sign_y, x + 55 * mm, sign_y)
        c.setFillColor(INK_FAINT)
        c.setFont("Helvetica", 7)
        c.drawString(x, sign_y - 4 * mm, f"{role} · name, signature and date")

    _footer(
        c,
        width,
        f"{settings.business_name} · Generated {date.today():%d %B %Y} · "
        "Contribution figures follow the published headline rates; verify against "
        "the official KWSP and PERKESO schedules before filing.",
    )

    c.save()
    return buffer.getvalue()
