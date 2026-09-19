"""Westminster: financial-year quarters, a slug that changed shape, no extension."""

from __future__ import annotations

import logging

import httpx
import pytest

from scrooge_indexer import manifest
from scrooge_indexer.boroughs import westminster
from scrooge_indexer.boroughs.base import period_bounds
from scrooge_indexer.boroughs.westminster import Westminster, file_url, parse_quarter

POUND = "%C2%A3"

#: Ten of the twenty-one links on the live page, keeping both slug shapes and
#: the one quarter whose slug ends in "report".
LANDING = f"""
<html><body>
  <a href="/media/document/q1-2026-27-expenditure-over-{POUND}500">Q1 2026/27 - Expenditure over £500</a>
  <a href="/media/document/q4-2025-26-expenditure-over-{POUND}500">Q4 2025/26 - Expenditure over £500</a>
  <a href="/media/document/q3-2025-26-expenditure-over-{POUND}500">Q3 2025/26 - Expenditure over £500</a>
  <a href="/media/document/q2-2025-26-expenditure-over-{POUND}500">Q2 2025/26 - Expenditure over £500</a>
  <a href="/media/document/q1-2025-26-expenditure-over-{POUND}500">Q1 2025/26 - Expenditure over £500</a>
  <a href="/media/document/q4-2024-25---expenditure-over-{POUND}500">Q4 2024/25 - expenditure over £500</a>
  <a href="/media/document/q3-2024-25---expenditure-over-{POUND}500">Q3 2024/25 - expenditure over £500</a>
  <a href="/media/document/q2-2024-25---expenditure-over-{POUND}500">Q2 2024/25 - expenditure over £500</a>
  <a href="/media/document/q1-2024-25---expenditure-over-{POUND}500">Q1 2024/25 - expenditure over £500</a>
  <a href="/media/document/q4-2023-24---expenditure-over-{POUND}500-report">Q4 2023/24 - expenditure over £500 report</a>
  <a href="/about-council/transparency/procurement-card-transactions">Procurement card transactions</a>
</body></html>
"""


def landing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LANDING, headers={"Content-Type": "text/html"})


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(westminster, "current_month", lambda *_: "2026-09")


def test_discovery_lists_one_file_a_quarter(client_for):
    files = Westminster().discover(client_for(landing_handler), None, None)
    assert [f.period for f in files] == [
        "2023-Q4",
        "2024-Q1",
        "2024-Q2",
        "2024-Q3",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
        "2025-Q4",
        "2026-Q1",
    ]
    assert all(f.format == "csv" for f in files)


def test_the_card_transactions_link_is_not_a_quarter(client_for):
    files = Westminster().discover(client_for(landing_handler), None, None)
    assert all("/media/document/q" in f.url for f in files)


def test_q1_is_april_to_june_of_the_year_on_the_label(client_for):
    """ "Q1 2026/27" is 2026-Q1 and it holds April, May and June 2026."""
    assert period_bounds("2026-Q1", quarters=Westminster.quarters) == (
        "2026-04",
        "2026-06",
    )
    client = client_for(landing_handler)
    assert "2026-Q1" in {
        f.period for f in Westminster().discover(client, "2026-06", None)
    }


def test_a_quarter_that_ended_before_since_is_dropped(client_for):
    """Nothing in Q1 2026/27 was spent in July, so --since 2026-07 excludes it."""
    files = Westminster().discover(client_for(landing_handler), "2026-07", None)
    assert files == []


def test_the_saved_file_gets_a_csv_extension_it_never_had(client_for):
    """The URL ends in a slug with no dot in it. The core supplies the suffix."""
    files = Westminster().discover(client_for(landing_handler), "2026-04", None)
    assert files[0].filename == "q1-2026-27-expenditure-over-£500"
    assert (
        manifest.relative_path(files[0])
        == "raw/westminster/2026-Q1__q1-2026-27-expenditure-over-500.csv"
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Q1 2026/27 - Expenditure over £500", (2026, 1)),
        ("Q1 2026-27", (2026, 1)),
        ("/media/document/q1-2026-27-expenditure-over-£500", (2026, 1)),
        ("Q1 2026", (2026, 1)),
        ("q4 2023/24 report", (2023, 4)),
        ("April to June 2026", (2026, 1)),
        ("April - June 2026", (2026, 1)),
        ("January to March 2027", (2026, 4)),
        ("October to December 2026", (2026, 3)),
    ],
)
def test_parse_quarter_reads_the_labels_a_council_writes(label, expected):
    assert parse_quarter(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        "April to September 2026",  # a half year, which has no period string
        "Expenditure over £500",
        "Q5 2026/27",
        "Spend data 2026",
    ],
)
def test_parse_quarter_returns_none_rather_than_guessing(label):
    assert parse_quarter(label) is None


def test_a_label_with_no_quarter_is_counted_not_guessed_at(client_for, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        page = LANDING.replace(
            f'<a href="/media/document/q1-2026-27-expenditure-over-{POUND}500">'
            "Q1 2026/27 - Expenditure over £500</a>",
            f'<a href="/media/document/q1-expenditure-over-{POUND}500">'
            "Expenditure over £500</a>",
        )
        return httpx.Response(200, text=page, headers={"Content-Type": "text/html"})

    with caplog.at_level(logging.WARNING, logger="scrooge_indexer.boroughs.westminster"):
        files = Westminster().discover(client_for(handler), None, None)
    assert "skipped 1 expenditure link(s)" in caplog.text
    assert "2026-Q1" not in {f.period for f in files}


def test_a_rebuilt_page_falls_back_to_the_generated_urls(client_for):
    """Two links is a page that has been redesigned, not a history that shrank.

    The generated series runs from Westminster's first quarter to the last one
    that has finished, so a quarter still being spent in is never requested.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=f'<a href="/media/document/q1-2026-27-expenditure-over-{POUND}500">Q1</a>',
            headers={"Content-Type": "text/html"},
        )

    files = Westminster().discover(client_for(handler), None, None)
    assert [f.period for f in files][:2] == ["2021-Q1", "2021-Q2"]
    assert [f.period for f in files][-1] == "2026-Q1"
    assert len(files) == 21


def test_the_generated_slug_changes_shape_with_the_year():
    """One hyphen from 2025-26, three before it. Read off the live page."""
    assert file_url(2026, 1).endswith(f"/q1-2026-27-expenditure-over-{POUND}500")
    assert file_url(2024, 1).endswith(f"/q1-2024-25---expenditure-over-{POUND}500")


def test_the_quarter_in_progress_is_not_offered():
    """September 2026 sits in Q2 2026/27, so Q1 is the newest complete one."""
    assert westminster.latest_complete("2026-09") == (2026, 1)
    assert westminster.latest_complete("2026-04") == (2025, 4)
