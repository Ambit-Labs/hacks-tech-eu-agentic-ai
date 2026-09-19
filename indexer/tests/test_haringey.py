"""Haringey: quarters read from labels, PDFs ignored, upload months ignored."""

from __future__ import annotations

import logging

import httpx

from spend_indexer.boroughs.haringey import Haringey, parse_quarter

#: Trimmed from the live page on 2026-09-19. Kept: the PDF twin that must not
#: be picked up, the two upload months that would misdate the series, the
#: single-year slug whose label is the only honest source, the ``_0`` re-upload
#: and the older ``council_expenditure`` naming.
LANDING = """
<html><body>
  <a href="/sites/default/files/2026-09/lbh-expenditure-q4-2025-26.pdf">council
    expenditure - quarter 4, financial year 2025/26 ( pdf , 107 page(s) )</a>
  <a href="/sites/default/files/2026-09/lbh-expenditure-q4-2025-26.csv">council
    expenditure - quarter 4, financial year 2025/26 ( csv , 1 page(s) )</a>
  <a href="/sites/default/files/2026-09/lbh-expenditure-q3-2025-26.csv">council
    expenditure - quarter 3, financial year 2025/26 ( csv , 1 page(s) )</a>
  <a href="/sites/default/files/2026-02/lbh-expenditure-q2-2025.csv">council
    expenditure - quarter 2, financial year 2025/26 ( csv , 1 page(s) )</a>
  <a href="/sites/default/files/2025-07/lbh-expenditure-q1-2025.csv">council
    expenditure - quarter 1, financial year 2025/26 ( csv , 1 page(s) )</a>
  <a href="/sites/default/files/2025-05/lbh-expenditure-q4-2024-25_0.csv">council
    expenditure - quarter 4, financial year 2024/25 ( csv , 1 page(s) )</a>
  <a href="/sites/default/files/2024-07/council_expenditure_q1_23-24.csv">council
    expenditure - quarter 1, financial year 2023/24 ( csv , 1 page(s) )</a>
</body></html>
"""


def landing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LANDING, headers={"Content-Type": "text/html"})


def test_discover_dates_every_quarter_from_its_label(client_for):
    files = Haringey().discover(client_for(landing_handler), None, None)
    assert [f.period for f in sorted(files, key=lambda f: f.period)] == [
        "2023-Q1",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
        "2025-Q4",
    ]


def test_the_upload_month_in_the_path_is_not_the_period(client_for):
    """Q3 and Q4 of 2025-26 both went up in 2026-09 and are six months apart.

    Reading a period out of ``/sites/default/files/2026-09/`` would file them
    together, in a quarter neither of them covers.
    """
    files = {
        f.period: f
        for f in Haringey().discover(client_for(landing_handler), None, None)
    }
    assert "2026-09" not in files
    assert files["2025-Q3"].url.endswith("2026-09/lbh-expenditure-q3-2025-26.csv")
    assert files["2025-Q4"].url.endswith("2026-09/lbh-expenditure-q4-2025-26.csv")


def test_the_pdf_twin_is_left_alone(client_for):
    files = Haringey().discover(client_for(landing_handler), None, None)
    assert all(f.format == "csv" for f in files)
    assert all(f.filename.endswith(".csv") for f in files)


def test_a_slug_naming_one_year_is_dated_by_its_label():
    """``lbh-expenditure-q1-2025`` is Q1 of 2025-26, which only the label says."""
    assert parse_quarter(
        "council expenditure - quarter 1, financial year 2025/26 ( csv )",
        "lbh-expenditure-q1-2025.csv",
    ) == (2025, 1)
    # Without the label there is nothing to tell 2025-26 Q1 from 2024-25 Q1.
    assert parse_quarter("", "lbh-expenditure-q1-2025.csv") is None


def test_the_old_slug_still_dates_itself_when_the_label_goes():
    """``council_expenditure_q1_23-24`` spells both years, so it needs no label."""
    assert parse_quarter("", "council_expenditure_q1_23-24.csv") == (2023, 1)
    assert parse_quarter("", "lbh-expenditure-q4-2024-25_0.csv") == (2024, 4)


def test_since_and_until_run_on_financial_quarters(client_for):
    """Q4 of 2025-26 is January to March 2026, so a March bound keeps it."""
    client = client_for(landing_handler)
    assert [f.period for f in Haringey().discover(client, "2026-04", None)] == []
    kept = Haringey().discover(client_for(landing_handler), "2026-03", None)
    assert [f.period for f in kept] == ["2025-Q4"]


def test_a_link_that_cannot_be_dated_is_skipped_and_counted(client_for, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                '<a href="/sites/default/files/2026-09/lbh-expenditure-q4-2025-26.csv">'
                "council expenditure - quarter 4, financial year 2025/26</a>"
                '<a href="/sites/default/files/2026-09/lbh-expenditure-latest.csv">'
                "council expenditure (csv)</a>"
            ),
            headers={"Content-Type": "text/html"},
        )

    with caplog.at_level(logging.WARNING):
        files = Haringey().discover(client_for(handler), None, None)
    assert [f.period for f in files] == ["2025-Q4"]
    assert "1 CSV link(s)" in caplog.text


def test_a_re_upload_of_a_quarter_does_not_become_a_second_file(client_for, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                '<a href="/sites/default/files/2026-09/lbh-expenditure-q4-2025-26.csv">'
                "council expenditure - quarter 4, financial year 2025/26</a>"
                '<a href="/sites/default/files/2026-09/lbh-expenditure-q4-2025-26_0.csv">'
                "council expenditure - quarter 4, financial year 2025/26</a>"
            ),
            headers={"Content-Type": "text/html"},
        )

    with caplog.at_level(logging.WARNING):
        files = Haringey().discover(client_for(handler), None, None)
    assert [f.period for f in files] == ["2025-Q4"]
    assert "already taken" in caplog.text
