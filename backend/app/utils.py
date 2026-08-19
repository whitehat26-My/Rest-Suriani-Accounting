"""Small shared helpers."""
from __future__ import annotations

import calendar
from datetime import date, timedelta


def month_bounds(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return first, last


def resolve_period(
    start: date | None, end: date | None, period: str = "month"
) -> tuple[date, date]:
    """Work out the reporting window from either explicit dates or a keyword.

    Explicit dates always win. Otherwise ``period`` accepts ``today``, ``week``,
    ``month``, ``quarter``, ``year`` or ``all``.
    """
    today = date.today()
    if start is not None and end is not None:
        return (start, end) if start <= end else (end, start)
    if start is not None:
        return start, today
    if end is not None:
        return end.replace(day=1), end

    period = (period or "month").lower()
    if period == "today":
        return today, today
    if period == "week":
        return today - timedelta(days=6), today
    if period == "month":
        # Month to date. Running to the end of the calendar month would pad every
        # chart with empty future days, which reads as "the business stopped".
        return month_bounds(today)[0], today
    if period == "quarter":
        return today - timedelta(days=89), today
    if period == "year":
        return date(today.year, 1, 1), today
    if period == "all":
        return date(2000, 1, 1), today
    return month_bounds(today)[0], today
