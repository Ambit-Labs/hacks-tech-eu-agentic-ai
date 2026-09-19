"""Value rules: dates, amounts, VAT, supplier and the financial year.

Every date form docs/payments-schema.md lists, plus the ones that turned up on
disk and are named in `values.py`. No database and no files.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from scrooge_indexer.loader.values import (
    ValueError_,
    clean_text,
    financial_year,
    parse_amount,
    parse_date,
    parse_optional_amount,
    slash_parts,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The forms the schema doc lists, in its order.
        ("30/09/2019", date(2019, 9, 30)),
        ("27/10/2010 00:00:00", date(2010, 10, 27)),
        ("03-08-2020", date(2020, 8, 3)),
        ("14-Jul-15", date(2015, 7, 14)),
        ("23-Apr-2024", date(2024, 4, 23)),
        ("4 Oct 2019", date(2019, 10, 4)),
        ("01 February 2021", date(2021, 2, 1)),
        ("2019-09-30T00:00:00.000", date(2019, 9, 30)),
        # Forms found on disk that the doc does not list.
        ("22/12/14", date(2014, 12, 22)),
        ("14.06.2018", date(2018, 6, 14)),
        ("15.3.18", date(2018, 3, 15)),
        ("3 Aug 23", date(2023, 8, 3)),
        ("23/Nov/2023", date(2023, 11, 23)),
        ("20190220", date(2019, 2, 20)),
        ("2021-01-29T00:00:00", date(2021, 1, 29)),
        ("40511", date(2010, 11, 29)),
        # Whitespace and the odd quote a council leaves behind.
        (" 01-07-2020 ", date(2020, 7, 1)),
        ("01 July 2024", date(2024, 7, 1)),
    ],
)
def test_date_forms(text, expected):
    assert parse_date(text) == expected


def test_day_comes_before_month():
    """`05/08` is 5 August, never 8 May. No borough here writes month first."""
    assert parse_date("05/08/2019") == date(2019, 8, 5)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "empty date"),
        ("   ", "empty date"),
        ("N/A", "bad date"),
        ("#N/A", "bad date"),
        ("Oct-14", "bad date"),  # Bexley's month-only half year
        ("APRIL", "bad date"),  # a section marker in the date column
        ("31/02/2019", "bad date"),
        ("not a date", "bad date"),
        ("123456789", "bad date"),  # too long to be an Excel day number
        ("12345", "bad date"),  # too small to be one either
        ("09/18/2020", "month-first date"),  # Lambeth 2020-Q2
    ],
)
def test_bad_dates(text, reason):
    with pytest.raises(ValueError_) as caught:
        parse_date(text)
    assert caught.value.reason == reason


def test_month_first_swaps_only_the_slash_form():
    """`--` and `.` dates are day first in every file, so they never swap."""
    assert parse_date("09/18/2020", month_first=True) == date(2020, 9, 18)
    assert parse_date("07/03/2020", month_first=True) == date(2020, 7, 3)
    assert parse_date("03-08-2020", month_first=True) == date(2020, 8, 3)
    assert parse_date("14.06.2018", month_first=True) == date(2018, 6, 14)


def test_slash_parts_picks_out_the_two_numbers():
    assert slash_parts("09/18/2020") == (9, 18)
    assert slash_parts(" 30/09/2019 00:00:00 ") == (30, 9)
    assert slash_parts("03-08-2020") is None  # dash form is never month first
    assert slash_parts("23/Nov/2023") is None
    assert slash_parts(date(2019, 9, 30)) is None


def test_excel_datetime_cells_pass_through():
    assert parse_date(datetime(2019, 4, 2, 0, 0)) == date(2019, 4, 2)
    assert parse_date(date(2019, 4, 2)) == date(2019, 4, 2)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500", "500.00"),
        ("1,644.77", "1644.77"),
        ("£594.00", "594.00"),
        ("œ10312", "10312.00"),  # cp1252 mojibake for £
        (" £998,934.32 ", "998934.32"),
        ("-1,040.22", "-1040.22"),
        ("-£177,790.95", "-177790.95"),
        ("-£25.60", "-25.60"),
        ("£-25.60", "-25.60"),
        ("1699.5", "1699.50"),
        ("0", "0.00"),
    ],
)
def test_amounts(text, expected):
    assert parse_amount(text) == Decimal(expected)


def test_amount_from_a_spreadsheet_cell():
    assert parse_amount(7246.8) == Decimal("7246.80")
    assert parse_amount(400) == Decimal("400.00")


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "empty amount"),
        ("n/a", "bad amount"),
        ("()", "bad amount"),
        ("(abc)", "bad amount"),
    ],
)
def test_bad_amounts(text, reason):
    with pytest.raises(ValueError_) as caught:
        parse_amount(text)
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    "text",
    [
        "1.234,56",  # continental: would read as 1.23
        "1,23",  # decimal comma: would read as 123.00
        "1 040,22",
        "1,0,0",
        "12,34.50",
        "-",
        " -   ",  # Islington's zero
        "1,040.22-",
        "1e5",
    ],
)
def test_an_amount_in_another_notation_is_refused_not_guessed(text):
    """A comma has to sit in front of exactly three digits to be dropped."""
    with pytest.raises(ValueError_) as caught:
        parse_amount(text)
    assert caught.value.reason == "bad amount"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (".5", "0.50"),
        ("-.5", "-0.50"),
        ("£.75", "0.75"),
        ("(.25)", "-0.25"),
        ("1,234,567.891", "1234567.89"),
    ],
)
def test_a_leading_decimal_point_is_part_of_the_number(text, expected):
    assert parse_amount(text) == Decimal(expected)


def test_a_half_penny_rounds_the_way_postgres_rounds_numeric():
    assert parse_amount("2.665") == Decimal("2.67")
    assert parse_amount("-2.665") == Decimal("-2.67")
    assert parse_amount(0.125) == Decimal("0.13")


@pytest.mark.parametrize("cell", [True, float("nan"), float("inf"), 1e20, "1" * 13])
def test_a_cell_the_amount_column_cannot_hold_fails_its_row_only(cell):
    """Any of these reaching the COPY would abort it and fail the whole file."""
    with pytest.raises(ValueError_):
        parse_amount(cell)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(1,040.22)", "-1040.22"),
        ("(£1,040.22)", "-1040.22"),
        ("(œ1,040.22)", "-1040.22"),
        ("(559.33)", "-559.33"),
        (" ( £541.29 ) ", "-541.29"),
        ("(500)", "-500.00"),
    ],
)
def test_parentheses_are_the_accounting_negative(text, expected):
    """Lambeth's 2015-16 quarters and Barnet 2017-06 to 2018-06 write them."""
    assert parse_amount(text) == Decimal(expected)


def test_vat_is_optional_and_never_fails_a_row():
    assert parse_optional_amount("") is None
    assert parse_optional_amount(None) is None
    assert parse_optional_amount("rubbish") is None
    assert parse_optional_amount("0.00") == Decimal("0.00")


def test_supplier_is_trimmed_and_nothing_else():
    assert clean_text("  Veolia ES (UK) Ltd  ") == "Veolia ES (UK) Ltd"
    assert clean_text("") is None
    assert clean_text(None) is None


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2019, 9, 30), "2019/20"),
        (date(2020, 3, 31), "2019/20"),
        (date(2020, 4, 1), "2020/21"),
        (date(2019, 3, 31), "2018/19"),
        (date(1999, 4, 1), "1999/00"),
        (date(2000, 3, 31), "1999/00"),
    ],
)
def test_financial_year(day, expected):
    assert financial_year(day) == expected
