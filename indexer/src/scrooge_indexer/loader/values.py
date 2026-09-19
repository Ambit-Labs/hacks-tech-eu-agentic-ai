"""Turning a published cell into a typed value, or refusing it.

The rules are in docs/payments-schema.md under "Value rules". Everything here
is deliberately strict: a cell that does not match one of the listed forms
fails its row rather than being coerced into something plausible, because a
wrong date in `payments` is worse than a missing row and impossible to spot
later.

Where a form appears on disk that the schema doc does not list, it is added
here with a comment naming the borough it came from. That keeps the widening
visible instead of hiding it behind a permissive parser.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..boroughs.base import parse_month_name

#: Cells that say "there is no date here" rather than being a broken one.
#: Havering publishes both spellings in its 2011 files.
NULL_DATES = frozenset({"n/a", "#n/a", "na", "null", "-", "none"})

#: ISO, with or without a time, with or without milliseconds. Camden writes
#: `2019-09-30T00:00:00.000`; Hounslow's 2021 CSV export drops the milliseconds.
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$")

#: Day first, separator repeated, two or four digit year, optional time after.
#: Covers `DD/MM/YYYY`, `DD/MM/YYYY HH:MM:SS` and `DD-MM-YYYY` from the doc.
#: The two-digit year (`22/12/14`, Barnet 2014-12 and Havering 2011-03) and the
#: dotted separator (`14.06.2018`, six Barnet rows) are not in the doc.
_NUMERIC = re.compile(r"^(\d{1,2})([/.-])(\d{1,2})\2(\d{2}|\d{4})(?:[T ].*)?$")

#: `DD-Mon-YY`, `DD-Mon-YYYY`, `D Mon YYYY` and `DD Month YYYY` from the doc.
#: `3 Aug 23` (Islington) and `23/Nov/2023` (Wandsworth 2023-11) are not.
_MONTH_NAME = re.compile(r"^(\d{1,2})[ /-]([A-Za-z]{3,9})\.?[ /-](\d{2}|\d{4})$")

#: `20190220`, 352 rows in Richmond's 2019 files. Not in the doc.
_COMPACT = re.compile(r"^(\d{8})$")

#: A bare Excel day number that reached a CSV without being formatted, as in
#: Havering 2011-02 (`40511`) and a handful of Barnet rows. The doc allows
#: "Excel datetime cells", which is the same number read from an xlsx.
_SERIAL = re.compile(r"^(\d{5})(?:\.0+)?$")

#: Excel counts days from this day, one short because it believes 1900 was a
#: leap year. Every spreadsheet reader uses the same wrong epoch.
_EXCEL_EPOCH = date(1899, 12, 30)

#: The window a bare five-digit number is read as a day count in: 1954 to 2064.
#: Outside it the number is far more likely to be a reference than a date.
_SERIAL_MIN, _SERIAL_MAX = 20000, 60000

#: Everything before the first digit, minus or decimal point goes, which is
#: what strips `£`, the `œ` that cp1252 makes of it, spaces and stray quotes in
#: one rule. The point stays because `.50` is fifty pence, not fifty pounds.
_AMOUNT_LEAD = re.compile(r"^[^\d.-]*")
#: What is left after that, between the minus and the number. Barnet and
#: Newham write `-£25.60`, so the sign comes before the currency symbol and one
#: pass at the front of the string is not enough.
_AMOUNT_AFTER_SIGN = re.compile(r"^-[^\d.]*")
#: Digits with optional thousands commas, each in front of exactly three
#: digits. `1.234,56` and `1,23` are another notation, and dropping their
#: commas would give 1.23 and 123.00 without a word, so they fail the row.
_AMOUNT_OK = re.compile(r"^-?(?:\d{1,3}(?:,\d{3})+|\d+|(?=\.\d))(?:\.\d+)?$")

#: Half a penny rounds away from zero, which is what Postgres does when it
#: stores a longer number in `numeric(14, 2)`.
_PENCE = Decimal("0.01")
#: `numeric(14, 2)` holds twelve digits before the point.
_AMOUNT_LIMIT = Decimal(10) ** 12

#: An accounting negative, `(1,040.22)` or `(£1,040.22)`. Lambeth's four
#: 2015-16 quarters and Barnet's months from 2017-06 to 2018-06 write them,
#: 5,967 rows in all.
_AMOUNT_PARENS = re.compile(r"^\(\s*[£œ]?\s*([\d,]+(?:\.\d+)?|\.\d+)\s*\)$")


class ValueError_(ValueError):
    """A cell that fails a value rule. Carries the short reason for `reason`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _four_digit_year(value: int) -> int:
    """``24`` → 2024, ``98`` → 1998. The same pivot ``strptime`` uses for ``%y``."""
    if value >= 100:
        return value
    return 2000 + value if value < 70 else 1900 + value


def slash_parts(cell: object) -> tuple[int, int] | None:
    """The first two numbers of a slash date, or None when it is not one.

    Only the slash form, because that is the only one any borough here writes
    month first. `03-08-2020` and `14.06.2018` are always read day first.
    """
    if isinstance(cell, (date, datetime)):
        return None
    text = re.sub(r"\s+", " ", str(cell or "").strip().strip('"'))
    match = _NUMERIC.match(text)
    if match is None or match.group(2) != "/":
        return None
    return int(match.group(1)), int(match.group(3))


def parse_date(cell: object, *, month_first: bool = False) -> date:
    """One published date cell as a :class:`date`, day before month by default.

    Raises :class:`ValueError_` with a short reason when the cell is empty, is
    a literal `N/A`, or matches none of the forms above. `month_first` swaps
    the first two numbers of a slash date and nothing else; it is set per file
    by :func:`~scrooge_indexer.loader.rows.detect_date_order` and never
    guessed from a single cell.
    """
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    text = str(cell or "").strip().strip('"').replace(" ", " ")
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise ValueError_("empty date")
    if text.lower() in NULL_DATES:
        raise ValueError_("bad date")

    if match := _ISO.match(text):
        year, month, day = (int(g) for g in match.groups())
        return _build(year, month, day)
    if match := _NUMERIC.match(text):
        day, separator, month, year = match.groups()
        if month_first and separator == "/":
            day, month = month, day
        if int(month) > 12:
            # `09/18/2020` read day first. There is no such month, so the file
            # is either month first or mixed, and one cell cannot tell which.
            # The runner catches this and scans the whole date column.
            raise ValueError_("month-first date")
        return _build(_four_digit_year(int(year)), int(month), int(day))
    if match := _MONTH_NAME.match(text):
        day, name, year = match.groups()
        month = parse_month_name(name)
        if month is None:
            raise ValueError_("bad date")
        return _build(_four_digit_year(int(year)), month, int(day))
    if match := _COMPACT.match(text):
        digits = match.group(1)
        return _build(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    if match := _SERIAL.match(text):
        days = int(match.group(1))
        if _SERIAL_MIN <= days <= _SERIAL_MAX:
            return _EXCEL_EPOCH + timedelta(days=days)
    raise ValueError_("bad date")


def _build(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError_("bad date") from exc


def parse_amount(cell: object) -> Decimal:
    """One published amount as a :class:`Decimal` with two decimals.

    `£1,040.22`, `-£177,790.95`, `-1,040.22` and the `œ1,040.22` that a cp1252
    file turns into all reduce to the same number, sign kept. `(1,040.22)` and
    `(£1,040.22)` are the accounting negative and give -1040.22.
    """
    if isinstance(cell, bool):
        raise ValueError_("bad amount")
    if isinstance(cell, (int, float)):
        return _pence(Decimal(str(cell)))
    if isinstance(cell, Decimal):
        return _pence(cell)
    text = str(cell or "").strip().replace("\xa0", "")
    if not text:
        raise ValueError_("empty amount")
    if parens := _AMOUNT_PARENS.match(text):
        text = "-" + parens.group(1)
    text = _AMOUNT_LEAD.sub("", text, count=1)
    text = _AMOUNT_AFTER_SIGN.sub("-", text, count=1)
    text = text.rstrip('"').rstrip()
    if not _AMOUNT_OK.match(text):
        raise ValueError_("bad amount")
    try:
        return _pence(Decimal(text.replace(",", "")))
    except InvalidOperation as exc:
        raise ValueError_("bad amount") from exc


def _pence(value: Decimal) -> Decimal:
    """Two decimals, or a failed row for what `numeric(14, 2)` cannot hold.

    One NaN or one twenty-digit number reaching the COPY would abort it and
    fail the whole file, so they stop here and cost one row instead.
    """
    if not value.is_finite() or abs(value) >= _AMOUNT_LIMIT:
        raise ValueError_("bad amount")
    return value.quantize(_PENCE, rounding=ROUND_HALF_UP)


def parse_optional_amount(cell: object) -> Decimal | None:
    """VAT as published, or None. A blank VAT cell is normal, not a failure.

    Only six boroughs publish irrecoverable VAT at all, and several of those
    leave the cell empty on rows where it does not apply. An unparseable VAT
    does not fail the row either: the payment is still a payment.
    """
    if cell is None or str(cell).strip() == "":
        return None
    try:
        return parse_amount(cell)
    except ValueError_:
        return None


def clean_text(cell: object) -> str | None:
    """Trim, collapse nothing else, and turn an empty cell into NULL.

    Supplier in particular is stored exactly as published apart from the trim,
    because `supplier_norm` is the generated column that does the upper-casing
    and the punctuation stripping for matching.
    """
    if cell is None:
        return None
    text = str(cell).strip()
    return text or None


def financial_year(day: date) -> str:
    """``2019/20`` for anything from 1 April 2019 to 31 March 2020."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}/{(start + 1) % 100:02d}"
