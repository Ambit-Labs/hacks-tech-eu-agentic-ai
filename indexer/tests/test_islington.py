"""Islington: month ranges parsed out of free-text labels, posting dates ignored."""

from __future__ import annotations

import logging

import httpx
import pytest

from spend_indexer.boroughs.islington import Islington, end_month

MEDIA = (
    "/~/media/sharepoint-lists/public-records/finance/financialmanagement/expenditure"
)

#: Trimmed from the live page on 2026-09-19, keeping one file from each naming
#: era: the current one, the one whose slug carries no year, the four-month
#: quarter, the two-digit years, and the oldest unspaced slug. Every label ends
#: in a "Last updated" stamp naming a different month from the period.
LANDING = f"""
<html><body>
  <a href="{MEDIA}/20262027/april-through-to-june-26-expenditure-report.csv">
    Expenditure Report for April to June 2026 (csv, 1 MB)
    Last updated Aug 05, 2026, 10:35AM</a>
  <a href="{MEDIA}/20252026/expenditure-report-january-to-march-2026-without-summary-csv.csv">
    Expenditure Report January to March 2026 (csv, 2 MB)
    Last updated Apr 29, 2026, 10:39AM</a>
  <a href="{MEDIA}/20242025/expenditure-report-for-july-to-september.csv">
    Expenditure Report for July to September 2024 (csv, 2 MB)
    Last updated Oct 31, 2024, 01:00PM</a>
  <a href="{MEDIA}/20232024/expenditure-for-march-2023-through-to-june-2023.csv">
    Expenditure for March 2023 through to June 2023 (csv, 2 MB)
    Last updated Jul 24, 2023, 05:00PM</a>
  <a href="{MEDIA}/20222023/expenditure-for-december-21-though-february-22.csv">
    Expenditure for December 21 through February 22 (csv, 1 MB)
    Last updated Nov 10, 2022, 02:00PM</a>
  <a href="{MEDIA}/20202021/20200603expenditurefordecemberthroughfebruary2020.csv">
    Expenditure for December through February 2020 (csv, 1 MB)
    Last updated Jun 03, 2020, 11:52AM</a>
</body></html>
"""


def landing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LANDING, headers={"Content-Type": "text/html"})


def test_discover_files_each_quarter_by_its_closing_month(client_for):
    files = Islington().discover(client_for(landing_handler), None, None)
    assert [f.period for f in files] == [
        # December 2019 to February 2020, closing in the last quarter of 2019-20.
        "2019-Q4",
        # December 2021 to February 2022, the same shape four years later.
        "2021-Q4",
        # Four months, March to June 2023, closing in the first of 2023-24.
        "2023-Q1",
        "2024-Q2",
        # January to March 2026 is the last quarter of 2025-26, not of 2026-27.
        "2025-Q4",
        "2026-Q1",
    ]


def test_the_last_updated_stamp_is_not_the_period(client_for):
    """A file for April to June 2026 posted in August is still Q1, not Q2."""
    files = {
        f.period: f
        for f in Islington().discover(client_for(landing_handler), None, None)
    }
    assert "2026-Q2" not in files
    assert (
        files["2026-Q1"].filename == "april-through-to-june-26-expenditure-report.csv"
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Expenditure Report for April to June 2026 (csv, 1 MB)", "2026-06"),
        ("Expenditure for December 21 through February 22", "2022-02"),
        ("Expenditure for December through February 2020", "2020-02"),
        ("Expenditure for March through May 21 (csv, 1 MB)", "2021-05"),
        ("Expenditure for June - August 2020 (csv, 1 MB)", "2020-08"),
        ("Expenditure for Sept through Nov 2019 (csv, 1 MB)", "2019-11"),
        ("Council expenditure for December 2022 to February 2023", "2023-02"),
        (
            "Expenditure Report for April to June 2026 Last updated Aug 05, 2026",
            "2026-06",
        ),
        ("Expenditure Report (csv, 2 MB)", None),
    ],
)
def test_the_closing_month_survives_every_spelling(label, expected):
    assert end_month(label) == expected


def test_a_quarter_that_drifted_off_the_financial_year_still_lands():
    """Islington's quarters ran March to May until 2023, and it files them as Q1.

    The rule is the closing month: March-May 2022 closes in May, which is in
    Q1 of 2022-23, which is where Islington itself puts the file.
    """
    assert end_month("Expenditure for March through to May 2022") == "2022-05"


def test_a_slug_with_no_year_is_rescued_by_its_label(client_for):
    """``expenditure-report-for-july-to-september.csv`` names no year at all."""
    files = {
        f.period: f
        for f in Islington().discover(client_for(landing_handler), None, None)
    }
    assert files["2024-Q2"].filename == "expenditure-report-for-july-to-september.csv"


def test_since_and_until_run_on_financial_quarters(client_for):
    client = client_for(landing_handler)
    kept = Islington().discover(client, "2026-04", None)
    assert [f.period for f in kept] == ["2026-Q1"]
    # Q1 of 2023-24 closes in June 2023, so a June bound keeps it.
    kept = Islington().discover(client_for(landing_handler), "2023-06", "2023-06")
    assert [f.period for f in kept] == ["2023-Q1"]


def test_a_link_that_cannot_be_dated_is_skipped_and_counted(client_for, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                f'<a href="{MEDIA}/20262027/april-through-to-june-26-expenditure-report.csv">'
                "Expenditure Report for April to June 2026 (csv, 1 MB)</a>"
                f'<a href="{MEDIA}/20262027/expenditure-report-latest.csv">'
                "Expenditure Report (csv, 1 MB)</a>"
            ),
            headers={"Content-Type": "text/html"},
        )

    with caplog.at_level(logging.WARNING):
        files = Islington().discover(client_for(handler), None, None)
    assert [f.period for f in files] == ["2026-Q1"]
    assert "1 CSV link(s)" in caplog.text
