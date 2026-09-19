"""Period parsing and financial-year arithmetic, the helpers every borough uses."""

from __future__ import annotations

from datetime import date

import pytest

from spend_indexer.boroughs.base import (
    calendar_quarter_period,
    current_month,
    filter_files,
    fy_label,
    fy_months,
    fy_of_month,
    fy_quarter_bounds,
    fy_quarter_from_label,
    fy_quarter_months,
    fy_quarter_of_month,
    fy_quarter_of_span,
    fy_quarter_period,
    in_range,
    month_name,
    month_span,
    months_between,
    parse_month_name,
    parse_period,
    period_bounds,
    range_period,
    shift_month,
)
from spend_indexer.models import RemoteFile


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("January", 1),
        ("january", 1),
        ("JAN", 1),
        ("Jan.", 1),
        ("Sept", 9),
        ("sep", 9),
        ("December", 12),
        ("  March  ", 3),
        ("ma", None),
        ("mar", 3),
        ("banana", None),
        ("", None),
    ],
)
def test_parse_month_name(text, expected):
    assert parse_month_name(text) == expected


def test_parse_month_name_rejects_ambiguous_prefix():
    """``ju`` could be June or July, and ``j`` could be three months."""
    assert parse_month_name("ju") is None
    assert parse_month_name("jun") == 6
    assert parse_month_name("jul") == 7


def test_month_name():
    assert month_name(7) == "july"
    assert month_name(7, short=True) == "jul"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("council_expenditure_july_2026.csv", "2026-07"),
        ("Expenditure Report July 2026", "2026-07"),
        ("Payments over 500 - Sept 2019", "2019-09"),
        ("2025 March spend", "2025-03"),
        ("/sites/default/files/2026-02/report.csv", "2026-02"),
        ("procurement_card_spend_2026_27_q1.csv", None),
        ("nothing dated here", None),
    ],
)
def test_parse_period(text, expected):
    assert parse_period(text) == expected


def test_shift_month_crosses_years():
    assert shift_month("2026-01", -1) == "2025-12"
    assert shift_month("2025-12", 1) == "2026-01"
    assert shift_month("2026-06", 12) == "2027-06"


def test_months_between():
    assert months_between("2026-06", "2026-08") == ["2026-06", "2026-07", "2026-08"]
    assert months_between("2026-06", "2026-06") == ["2026-06"]
    assert months_between("2026-08", "2026-06") == []


def test_current_month():
    assert current_month(date(2026, 9, 19)) == "2026-09"


def test_fy_helpers():
    assert fy_label(2026) == "2026-27"
    assert fy_label(2009) == "2009-10"
    assert fy_of_month("2026-03") == 2025
    assert fy_of_month("2026-04") == 2026
    assert fy_months(2026)[0] == "2026-04"
    assert fy_months(2026)[-1] == "2027-03"
    assert len(fy_months(2026)) == 12


def test_fy_quarters_start_in_april():
    assert fy_quarter_of_month("2026-04") == (2026, 1)
    assert fy_quarter_of_month("2026-08") == (2026, 2)
    assert fy_quarter_of_month("2027-01") == (2026, 4)
    assert fy_quarter_months(2026, 1) == ["2026-04", "2026-05", "2026-06"]
    assert fy_quarter_months(2026, 4) == ["2027-01", "2027-02", "2027-03"]
    assert fy_quarter_period(2026, 1) == "2026-Q1"
    assert calendar_quarter_period(2026, 1) == "2026-Q1"


def test_fy_quarter_bounds_by_convention():
    assert fy_quarter_bounds(2026, 1) == ("2026-04", "2026-06")
    assert fy_quarter_bounds(2026, 1, quarters="calendar") == ("2026-01", "2026-03")


def test_period_bounds_covers_all_three_spellings():
    assert period_bounds("2026-08") == ("2026-08", "2026-08")
    assert period_bounds("2026-08_2026-11") == ("2026-08", "2026-11")
    assert period_bounds("2026-Q4") == ("2027-01", "2027-03")


def test_in_range_uses_overlap_not_containment():
    # A quarter that straddles the --since boundary is kept: dropping the
    # quarter that contains June when asked for June would be the wrong answer.
    assert in_range("2026-Q1", "2026-06", None) is True
    assert in_range("2026-Q1", "2026-07", None) is False
    assert in_range("2026-08", "2026-06", "2026-09") is True
    assert in_range("2026-05", "2026-06", None) is False
    assert in_range("2026-10", None, "2026-09") is False
    assert in_range("2026-10", None, None) is True


def test_in_range_reaches_inside_a_span():
    """The point of the range form: a window inside the span still finds it."""
    whole_year = "2013-04_2014-03"
    assert in_range(whole_year, "2013-09", "2013-09") is True
    assert in_range(whole_year, "2014-04", None) is False
    assert in_range(whole_year, None, "2013-03") is False


def test_a_range_sorts_by_the_month_it_opens_in():
    """Lexical order is chronological, which is what the CLI's sort relies on."""
    periods = ["2011-04_2012-03", "2010-09_2011-03", "2010-12", "2015-10_2015-11"]
    assert sorted(periods) == [
        "2010-09_2011-03",
        "2010-12",
        "2011-04_2012-03",
        "2015-10_2015-11",
    ]


def test_range_period_collapses_a_single_month():
    assert range_period("2010-09", "2011-03") == "2010-09_2011-03"
    assert range_period("2026-07", "2026-07") == "2026-07"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Transparency Report Dec 2024 - Mar 2025.csv", ("2024-12", "2025-03")),
        ("Q1, 2 and 3 - April to December 2017", ("2017-04", "2017-12")),
        (
            "council-spending-over-500-september-2010-to-march-2011",
            ("2010-09", "2011-03"),
        ),
        # A month with no year borrows its neighbour's, forwards...
        ("october-november-2015", ("2015-10", "2015-11")),
        # ...and backwards over a year boundary.
        ("Expenditure for December through February 2020", ("2019-12", "2020-02")),
        ("Transparency-report-Mar-May 2020", ("2020-03", "2020-05")),
        # Two-digit years, as Islington and Bexley write them.
        ("Expenditure for December 21 through February 22", ("2021-12", "2022-02")),
        ("april-through-to-june-26", ("2026-04", "2026-06")),
        # One month is a span of one month, and the caller decides what to do.
        ("July 2026 (CSV)", ("2026-07", "2026-07")),
        # The 500 in every filename in this corpus is not a year.
        ("Invoices Over 500 July 2026-iB3hoV.csv", ("2026-07", "2026-07")),
        ("October to December (CSV)", None),
        ("Transparency Report", None),
    ],
)
def test_month_span_reads_the_ranges_councils_write(text, expected):
    assert month_span(text) == expected


def test_month_span_can_refuse_two_digit_years():
    """Brent's "Transparency 24 June - 24 August" is June to August 2024.

    The 24 could be a day just as easily, so the module that meets it asks for
    four-digit years and reads the period off the resource name instead.
    """
    assert month_span("Transparency 24 June - 24 August") == ("2024-06", "2024-08")
    assert month_span("Transparency 24 June - 24 August", short_years=False) is None
    assert month_span("Mar-May 2020", short_years=False) == ("2020-03", "2020-05")


def test_fy_quarter_of_span_is_an_exact_match():
    assert fy_quarter_of_span("2026-04", "2026-06") == "2026-Q1"
    assert fy_quarter_of_span("2026-01", "2026-03") == "2025-Q4"
    # A half year, a four-month span and an off-cycle quarter are not quarters.
    assert fy_quarter_of_span("2026-04", "2026-09") is None
    assert fy_quarter_of_span("2024-12", "2025-03") is None
    assert fy_quarter_of_span("2020-03", "2020-05") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Q1 2026/27 - Expenditure over £500", "2026-Q1"),
        ("/media/document/q1-2026-27-expenditure-over-£500", "2026-Q1"),
        ("council expenditure - quarter 4, financial year 2025/26 ( csv )", "2025-Q4"),
        ("council_expenditure_q1_23-24.csv", "2023-Q1"),
        ("lbh-expenditure-q4-2024-25_0.csv", "2024-Q4"),
        ("Over_500_Transparency_Report_2026-27Q1.csv", "2026-Q1"),
        ("Over £500 Transparency Report 202425 Q3 publish.csv", "2024-Q3"),
        ("ec-spend-over-£500-Jan-March-2019-20-Q4.xlsx", "2019-Q4"),
        # A month range, but only when it is exactly a quarter.
        ("April - June 2026", "2026-Q1"),
        ("January to March 2027", "2026-Q4"),
        ("april-through-to-june-26", "2026-Q1"),
        ("April to September 2026", None),
        # One year is not enough: "q1-2025" is 2025-26 on one council's page
        # and could be 2024-25 on another's.
        ("lbh-expenditure-q1-2025.csv", None),
        ("payments over 500 - Q4 2017.csv", None),
        # Three quarters in one file names no single quarter.
        ("Q1, 2 and 3 - April to December 2017", None),
        ("Q5 2026/27", None),
        ("Expenditure over £500", None),
    ],
)
def test_fy_quarter_from_label(text, expected):
    assert fy_quarter_from_label(text) == expected


def _file(period: str) -> RemoteFile:
    return RemoteFile(
        borough="x",
        period=period,
        url=f"https://example.invalid/{period}.csv",
        filename=f"{period}.csv",
        format="csv",
    )


def test_filter_files():
    files = [_file(p) for p in ("2026-05", "2026-06", "2026-07")]
    kept = [f.period for f in filter_files(files, "2026-06", "2026-06")]
    assert kept == ["2026-06"]


def test_filter_files_keeps_a_range_that_overlaps_the_window():
    files = [_file(p) for p in ("2010-09_2011-03", "2011-04_2012-03")]
    kept = [f.period for f in filter_files(files, "2011-02", "2011-05")]
    assert kept == ["2010-09_2011-03", "2011-04_2012-03"]


def test_remote_file_rejects_a_malformed_period():
    with pytest.raises(ValueError):
        _file("2026-13")
    with pytest.raises(ValueError):
        _file("August 2026")
    # A bare year said nothing about which twelve months it held, and every
    # file that used to need one is a range now.
    with pytest.raises(ValueError):
        _file("2026")


def test_remote_file_rejects_a_range_that_does_not_run_forwards():
    with pytest.raises(ValueError):
        _file("2011-03_2010-09")
    # A one-month range is a month, and range_period writes it that way.
    with pytest.raises(ValueError):
        _file("2026-07_2026-07")
