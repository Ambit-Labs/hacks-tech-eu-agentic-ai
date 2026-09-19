"""Lewisham: label-first month parsing, PDFs ignored, holes rebuilt."""

from __future__ import annotations

import logging

import httpx
import pytest

from scrooge_indexer.boroughs.lewisham import Lewisham, candidate_url, holes

MEDIA = "/-/media/mayor-and-council/about-us/finances/spending-over-250"

#: Ten links trimmed from the live page on 2026-09-19. May 2026 is left out on
#: purpose: it is on the real page, and its absence here is the hole the
#: pattern fallback is for.
LANDING = f"""
<html><body>
  <a href="{MEDIA}/26-27/jul2026_paymentsover250.pdf">July 2026 payments over £250 (pdf)</a>
  <a href="{MEDIA}/26-27/jul2026paymentsover250.csv">July 2026 payments over £250 (csv)</a>
  <a href="{MEDIA}/26-27/jun2026paymentsover250.csv">June 2026 payments over £250 (csv)</a>
  <a href="{MEDIA}/26-27/apr2026paymentsover_250.csv">April 2026 payments over £250 (csv)</a>
  <a href="{MEDIA}/25-26/mar2026paymentsover250.csv">March 2026 payments over £250 (csv)</a>
  <a href="{MEDIA}/25-26/lewishamover250oct.csv">October 2025 payments over £250 (csv)</a>
  <a href="{MEDIA}/24-25/dec2024paymentsover250_excel.csv">December 2024 payments over £250 (Excel)</a>
  <a href="{MEDIA}/24-25/sep2024_paymentsover250.xlsx">September 2024 payments over £250 (Excel)</a>
  <a href="/-/media/files/imported/january2018paymentsover250.ashx">January 2018 payments over £250 (csv)</a>
  <a href="{MEDIA}/how-we-publish.csv">How we publish payments over £250</a>
</body></html>
"""


def landing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LANDING, headers={"Content-Type": "text/html"})


def test_discovery_reads_the_month_from_the_label(client_for):
    """Seven links carry a month; none of the file names spells one the same way."""
    files = Lewisham().discover(client_for(landing_handler), None, None)
    periods = [f.period for f in files]

    assert periods == [
        "2024-09",
        "2024-12",
        "2025-10",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
    ]
    assert all(f.borough == "lewisham" for f in files)
    assert files[-1].filename == "jul2026paymentsover250.csv"


def test_october_2025_survives_a_file_name_that_says_nothing(client_for):
    """``lewishamover250oct.csv`` has no year in it at all. The label does."""
    files = Lewisham().discover(client_for(landing_handler), "2025-10", "2025-10")
    assert files[0].url.endswith("/25-26/lewishamover250oct.csv")


def test_the_pdf_twin_is_never_taken(client_for):
    files = Lewisham().discover(client_for(landing_handler), None, None)
    assert not any(f.url.endswith(".pdf") for f in files)
    # July has both a PDF and a CSV, and only one of them is a file we want.
    july = [f for f in files if f.period == "2026-07"]
    assert len(july) == 1 and july[0].format == "csv"


def test_the_format_comes_from_the_url_not_from_the_label(client_for):
    """Two labels lie. ``dec2024...csv`` is called Excel and it is a CSV."""
    formats = {
        f.period: f.format
        for f in Lewisham().discover(client_for(landing_handler), None, None)
    }
    assert formats["2024-12"] == "csv"
    assert formats["2024-09"] == "xlsx"


def test_a_month_the_page_dropped_is_rebuilt_from_the_pattern(client_for):
    files = {
        f.period: f.url
        for f in Lewisham().discover(client_for(landing_handler), None, None)
    }
    assert files["2026-05"].endswith("/26-27/may2026paymentsover250.csv")


def test_nothing_is_invented_outside_the_pattern_years(client_for):
    """October and November 2024 are a hole too, in a year the pattern predates.

    Generating them would be a guess at a naming Lewisham was not using yet,
    and the 2024 months on the real page are XLSX under two other folders.
    """
    periods = {
        f.period for f in Lewisham().discover(client_for(landing_handler), None, None)
    }
    assert "2024-10" not in periods and "2024-11" not in periods


def test_the_ashx_archive_is_left_alone(client_for):
    """A Sitecore media handler URL says nothing about what it serves."""
    files = Lewisham().discover(client_for(landing_handler), None, None)
    assert not any(".ashx" in f.url for f in files)


def test_a_link_with_no_month_is_counted_not_guessed_at(client_for, caplog):
    with caplog.at_level(logging.WARNING, logger="scrooge_indexer.boroughs.lewisham"):
        Lewisham().discover(client_for(landing_handler), None, None)
    assert "skipped 1 data link(s)" in caplog.text


def test_discover_honours_since_and_until(client_for):
    files = Lewisham().discover(client_for(landing_handler), "2026-04", "2026-06")
    assert [f.period for f in files] == ["2026-04", "2026-05", "2026-06"]


@pytest.mark.parametrize(
    ("month", "tail"),
    [
        ("2026-07", "/26-27/jul2026paymentsover250.csv"),
        ("2026-03", "/25-26/mar2026paymentsover250.csv"),
        ("2025-04", "/25-26/apr2025paymentsover250.csv"),
    ],
)
def test_the_folder_is_the_financial_year_not_the_calendar_one(month, tail):
    """March 2026 belongs to FY 2025-26, and the folder has to agree."""
    assert candidate_url(month).endswith(tail)


def test_only_short_holes_count_as_holes():
    assert holes(["2026-04", "2026-06", "2026-07"]) == ["2026-05"]
    assert holes(["2026-01", "2026-04"]) == ["2026-02", "2026-03"]
    assert holes(["2025-01", "2026-04"]) == []
    assert holes([]) == []
