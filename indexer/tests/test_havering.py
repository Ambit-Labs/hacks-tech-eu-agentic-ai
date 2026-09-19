"""Havering: the two-hop scrape, the missing extension, the year pages skipped."""

from __future__ import annotations

import logging

import httpx

from spend_indexer.boroughs.havering import Havering, csv_filename

#: The landing page, trimmed to three of its seventeen financial years.
LANDING = """
<html><body>
  <a href="https://www.havering.gov.uk/downloads/download/1112/spend-over-500-2026-27">2026/27</a>
  <a href="https://www.havering.gov.uk/downloads/download/1069/spend-over-500-2025-26">2025/26</a>
  <a href="https://www.havering.gov.uk/downloads/download/191/spend-over-500-2010-11">2010/11</a>
</body></html>
"""

#: A collection page. The month URLs carry no extension at all.
YEAR_2026 = """
<html><body>
  <a href="/downloads/file/7421/april-2026">April 2026 CSV 1.1MB download</a>
  <a href="/downloads/file/7448/may-2026">May 2026 CSV 1.11MB download</a>
  <a href="/downloads/file/7519/june-2026">June 2026 CSV 1.06MB download</a>
  <a href="/downloads/file/7520/july-2026">July 2026 CSV 986kB download</a>
</body></html>
"""

#: The oldest year, where the slugs still end in a format marker.
YEAR_2010 = """
<html><body>
  <a href="/downloads/file/476/december-2010-csv">December 2010.csv CSV 1.03MB</a>
  <a href="/downloads/file/477/january-2011-csv">January 2011.csv CSV 1.19MB</a>
  <a href="/downloads/file/478/march-2011-csv">March 2011.csv CSV 1.51MB</a>
</body></html>
"""

PAGES = {
    "/council-data-spending/spend-500": LANDING,
    "/downloads/download/1112/spend-over-500-2026-27": YEAR_2026,
    "/downloads/download/191/spend-over-500-2010-11": YEAR_2010,
}


def site(seen: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url.path)
        body = PAGES.get(request.url.path)
        if body is None:
            return httpx.Response(404, text="<html>not found</html>")
        return httpx.Response(200, text=body, headers={"Content-Type": "text/html"})

    return handler


def test_the_second_hop_finds_the_months(client_for):
    files = Havering().discover(client_for(site()), "2026-04", None)
    assert [f.period for f in files] == ["2026-04", "2026-05", "2026-06", "2026-07"]
    assert files[-1].url == "https://www.havering.gov.uk/downloads/file/7520/july-2026"


def test_only_the_year_pages_in_range_are_opened(client_for):
    """A ``--since 2026-04`` run is two requests, not eighteen."""
    seen: list[str] = []
    Havering().discover(client_for(site(seen)), "2026-04", None)
    assert seen == [
        "/council-data-spending/spend-500",
        "/downloads/download/1112/spend-over-500-2026-27",
    ]


def test_a_march_bound_still_opens_the_financial_year_that_holds_march(client_for):
    """FY 2010-11 runs to March 2011, so asking for March 2011 must open it."""
    seen: list[str] = []
    files = Havering().discover(client_for(site(seen)), "2011-03", "2011-03")
    assert "/downloads/download/191/spend-over-500-2010-11" in seen
    assert [f.period for f in files] == ["2011-03"]


def test_the_saved_name_ends_in_csv_although_the_url_does_not(client_for):
    files = Havering().discover(client_for(site()), "2026-07", "2026-07")
    assert files[0].filename == "july-2026.csv"
    assert files[0].format == "csv"


def test_an_old_slug_does_not_end_up_named_twice():
    assert csv_filename("december-2010-csv") == "december-2010.csv"
    assert csv_filename("july-2026") == "july-2026.csv"


def test_the_oldest_year_is_dated_from_its_slug(client_for):
    files = Havering().discover(client_for(site()), None, "2011-03")
    assert [f.period for f in files] == ["2010-12", "2011-01", "2011-03"]


def test_one_unreadable_year_page_costs_only_its_own_year(client_for, caplog):
    """2025-26 is not in ``PAGES``, so it 404s while 2026-27 still downloads."""
    with caplog.at_level(logging.WARNING):
        files = Havering().discover(client_for(site()), "2025-04", None)
    assert [f.period for f in files] == ["2026-04", "2026-05", "2026-06", "2026-07"]
    assert "spend-over-500-2025-26 could not be read" in caplog.text


def test_a_month_link_that_cannot_be_dated_is_skipped_and_counted(client_for, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/council-data-spending/spend-500":
            body = LANDING
        else:
            body = (
                '<a href="/downloads/file/7520/july-2026">July 2026 CSV</a>'
                '<a href="/downloads/file/7599/latest-spend">Latest spend CSV</a>'
            )
        return httpx.Response(200, text=body, headers={"Content-Type": "text/html"})

    with caplog.at_level(logging.WARNING):
        files = Havering().discover(client_for(handler), "2026-04", None)
    assert [f.period for f in files] == ["2026-07"]
    assert "1 month link(s)" in caplog.text
