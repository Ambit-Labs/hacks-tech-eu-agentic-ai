"""Lambeth: the CSV/XLSX split, the renamed files, the quarter that is three."""

from __future__ import annotations

import logging

import httpx
import pytest

from scrooge_indexer.boroughs.lambeth import Lambeth, parse_period_for

FILES = "https://www.lambeth.gov.uk/sites/default/files"
BETA = "https://beta.lambeth.gov.uk/sites/default/files"

#: Trimmed from the live page on 2026-09-19: the tidy current CSV, the encoded
#: pound sign and en dash, the run-together financial year, the XLSX years, one
#: ODS, a file still on the beta host, the label-only quarter, the "O4" typo,
#: the three-quarters-in-one file and the monthly tail.
LANDING = f"""
<html><body>
  <a href="{FILES}/2026-07/Over_500_Transparency_Report_2026-27Q1.csv">Q1 - April to June 2026</a>
  <a href="{FILES}/2026-04/Over_%C2%A3500_Transparency_Report_2025-26%20Q4.csv">Q4 - January to March 2026</a>
  <a href="{FILES}/2025-02/Over%20%C2%A3500%20Transparency%20Report%20202425%20Q3%20%20publish.csv">Q3 - October to December 2024</a>
  <a href="{FILES}/2024-01/Over_%C2%A3500_Transparency_Report_2023-24_Q3.xlsx">Q3 - October to December 2023</a>
  <a href="{BETA}/2022-08/Over_%C2%A3500_Transparency_Report_2022-23_Q1.xlsx">Q1 - April to June 2022</a>
  <a href="{FILES}/ec-over-%C2%A3500-transparency-report-2018-19-q2.ods">Q2 - July to September 2018</a>
  <a href="{FILES}/payments%20over%20500%20-%20Q4%202017.csv">Q4 - January to March 2018</a>
  <a href="{FILES}/payments%20over%20500%20-%20Q4%202018-19.xlsx">O4 - January to March 2019</a>
  <a href="{FILES}/payments%20over%20500%20-%20Q4%202016-17.csv">Q4 - January to March</a>
  <a href="{FILES}/payments%20over%20500%20-%20Q1-2-3%202017.csv">Q1, 2 and 3 - April to December 2017</a>
  <a href="{FILES}/LambethPaymentsOver500December2010.csv">December 2010</a>
</body></html>
"""


def landing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LANDING, headers={"Content-Type": "text/html"})


def test_discover_dates_every_renaming_of_the_same_report(client_for):
    files = Lambeth().discover(client_for(landing_handler), None, None)
    assert [f.period for f in sorted(files, key=lambda f: f.period)] == [
        "2010-12",
        "2016-Q4",
        # Three quarters in one file, so a range and not a quarter.
        "2017-04_2017-12",
        "2017-Q4",
        "2018-Q2",
        "2018-Q4",
        "2022-Q1",
        "2023-Q3",
        "2024-Q3",
        "2025-Q4",
        "2026-Q1",
    ]


def test_the_format_follows_the_file_and_not_the_series(client_for):
    """Three formats in one series, each declared as what it actually is."""
    formats = {
        f.period: f.format
        for f in Lambeth().discover(client_for(landing_handler), None, None)
    }
    assert formats["2026-Q1"] == "csv"
    assert formats["2024-Q3"] == "csv"
    assert formats["2023-Q3"] == "xlsx"
    assert formats["2022-Q1"] == "xlsx"
    assert formats["2018-Q2"] == "ods"
    assert formats["2010-12"] == "csv"


def test_the_saved_name_has_the_pound_sign_back(client_for):
    """``%C2%A3`` in the URL is a £ in the publisher's own filename."""
    files = {
        f.period: f for f in Lambeth().discover(client_for(landing_handler), None, None)
    }
    assert files["2025-Q4"].filename == "Over_£500_Transparency_Report_2025-26 Q4.csv"
    # The URL itself is left exactly as published, escapes and all.
    assert "%C2%A3" in files["2025-Q4"].url


def test_the_file_still_on_the_beta_host_is_taken_as_it_stands(client_for):
    files = {
        f.period: f for f in Lambeth().discover(client_for(landing_handler), None, None)
    }
    assert files["2022-Q1"].url.startswith("https://beta.lambeth.gov.uk/")


@pytest.mark.parametrize(
    ("filename", "label", "expected"),
    [
        (
            "Over_500_Transparency_Report_2026-27Q1.csv",
            "Q1 - April to June 2026",
            "2026-Q1",
        ),
        (
            "Over £500 Transparency Report 202425 Q3  publish.csv",
            "Q3 - October to December 2024",
            "2024-Q3",
        ),
        ("ec-over-500-report-q2-2020-21.csv", "Q2 - July to September 2020", "2020-Q2"),
        (
            "ec-spend-over-£500-Jan-March-2019-20-Q4.xlsx",
            "Q4 - January to March 2020",
            "2019-Q4",
        ),
        # Label only: the filename's "Q4 2017" names one year and could be read
        # either way, so the label's months decide.
        ("payments over 500 - Q4 2017.csv", "Q4 - January to March 2018", "2017-Q4"),
        # The page's own typo, and its own missing year.
        (
            "payments over 500 - Q4 2018-19.xlsx",
            "O4 - January to March 2019",
            "2018-Q4",
        ),
        ("payments over 500 - Q4 2016-17.csv", "Q4 - January to March", "2016-Q4"),
        # Months only, from before Lambeth reported quarterly.
        ("LambethPaymentsOver500December2010.csv", "December 2010", "2010-12"),
        ("March 2015.csv", "March 2015", "2015-03"),
        # Three quarters in one file: the range its label spells out.
        (
            "payments over 500 - Q1-2-3 2017.csv",
            "Q1, 2 and 3 - April to December 2017",
            "2017-04_2017-12",
        ),
        # A label whose months lie is still the quarter it names: this file is
        # January to March 2024, whatever the label says.
        (
            "over-500-transparency-report-2023-24-q4.csv",
            "Q4 - January to April 2024",
            "2023-Q4",
        ),
    ],
)
def test_periods_survive_every_way_lambeth_has_written_them(filename, label, expected):
    assert parse_period_for(filename, label) == expected


def test_the_three_quarter_file_is_taken_as_a_range(client_for):
    """April to December 2017 used to be skipped for having no period."""
    files = {
        f.period: f for f in Lambeth().discover(client_for(landing_handler), None, None)
    }
    assert "Q1-2-3" in files["2017-04_2017-12"].url
    # A November window reaches it, and an October to December quarter does not
    # swallow it: it is one file covering all three.
    kept = Lambeth().discover(client_for(landing_handler), "2017-11", "2017-11")
    assert [f.period for f in kept] == ["2017-04_2017-12"]


def test_a_link_that_cannot_be_dated_is_skipped_and_counted(client_for, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=f'<a href="{FILES}/2026-07/transparency-report.csv">Latest report</a>',
            headers={"Content-Type": "text/html"},
        )

    with caplog.at_level(logging.WARNING):
        files = Lambeth().discover(client_for(handler), None, None)
    assert files == []
    assert "1 link(s)" in caplog.text


def test_since_and_until_run_on_financial_quarters(client_for):
    """Q4 of 2025-26 is January to March 2026: inside a March bound, not April."""
    client = client_for(landing_handler)
    assert [f.period for f in Lambeth().discover(client, "2026-04", None)] == [
        "2026-Q1"
    ]
    kept = Lambeth().discover(client_for(landing_handler), "2026-03", None)
    assert [f.period for f in kept] == ["2025-Q4", "2026-Q1"]
