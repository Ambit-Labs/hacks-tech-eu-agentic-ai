"""Hounslow: the rotating buildId, and fifteen years of inconsistent labels."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.boroughs.base import filter_files
from scrooge_indexer.boroughs.hounslow import Hounslow, resource_period
from scrooge_indexer.http import NotPublished

BUILD = "PTSbv9Gst0ETBizzaJIsa"

#: What matters in the 2.5 MB dataset page: the build hash the data route
#: needs, inlined in __NEXT_DATA__.
PAGE = (
    '<html><body><div id="__next">Council spending over &#163;500</div>'
    '<script id="__NEXT_DATA__" type="application/json">'
    '{"props":{},"page":"/[org]/[dataset]",'
    f'"buildId":"{BUILD}","isFallback":false}}'
    "</script></body></html>"
)

BLOB = "https://blob.datopian.com/resources"

#: One resource of each shape the series has thrown up, in the portal's order.
RESOURCES = [
    {
        "name": "council_spending_over_500_september_2010_to_march_2011",
        "format": "CSV",
        "url": f"{BLOB}/41e9e6be/council-spending-over-500-september-2010-to-march-2011.csv",
    },
    {
        "name": "council-spending-over-500-2011-12",
        "format": "CSV",
        "url": f"{BLOB}/258e5703/council-spending-over-500-2011-12.csv",
    },
    {
        "name": "council-spending-over-500-october-november-2015",
        "format": "CSV",
        "url": f"{BLOB}/787432d7/council-spending-over-500-october-november-2015.csv",
    },
    {
        "name": "invoices-over-500-june-2020",
        "format": "CSV",
        "url": f"{BLOB}/4d0a1f22/invoices-over-500-june-2020.csv",
    },
    # No year anywhere in the name or the file.
    {
        "name": "july-over-500-report",
        "format": "CSV",
        "url": f"{BLOB}/8c19a7bb/july-over-500-report.csv",
    },
    {
        "name": "invoices-over-500-aug-2020",
        "format": "CSV",
        "url": f"{BLOB}/91bd4410/invoices-over-500-aug-2020.csv",
    },
    {
        "name": "Invoice over £500 May 2026",
        "format": "XLSX",
        "url": f"{BLOB}/a4c1f0e7/Invoices%20Over%20500%20May%202026-suHeLH.xlsx",
    },
    # A percent-escape was swallowed when this one was titled, so the title
    # reads April 2020 and the file does not.
    {
        "name": "invoices-20over-20500-20april-202026-pglmul",
        "format": "CSV",
        "url": f"{BLOB}/c3f5a190/Invoices%20Over%20500%20April%202026-PgLmul.csv",
    },
    {
        "name": "Invoices Over 500 July 2026",
        "format": "CSV",
        "url": f"{BLOB}/07f66603/Invoices%20Over%20500%20July%202026-iB3hoV.csv",
    },
]


def site(build: str = BUILD, resources=RESOURCES, seen: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if seen is not None:
            seen.append(path)
        if path.startswith("/_next/data/"):
            if f"/_next/data/{build}/" not in path:
                return httpx.Response(404, text="stale build")
            return httpx.Response(
                200, json={"pageProps": {"dataset": {"resources": resources}}}
            )
        return httpx.Response(200, text=PAGE, headers={"Content-Type": "text/html"})

    return handler


@pytest.mark.parametrize(
    ("filename", "period"),
    [
        ("Invoices Over 500 July 2026-iB3hoV.csv", "2026-07"),
        ("Invoices Over £500 Sept 2025-WfswPI.csv", "2025-09"),
        ("invoices-over-500-feb-2018.csv", "2018-02"),
        # Several months in one file: the period is the span they cover.
        (
            "council-spending-over-500-september-2010-to-march-2011.csv",
            "2010-09_2011-03",
        ),
        ("council-spending-over-500-october-november-2015.csv", "2015-10_2015-11"),
        # A financial year, not December 2011: twelve months from April.
        ("council-spending-over-500-2011-12.csv", "2011-04_2012-03"),
        ("council-spending-over-500-2014-15.csv", "2014-04_2015-03"),
        # "500" is in every filename and is never a year.
        ("july-over-500-report.csv", None),
    ],
)
def test_resource_period_handles_fifteen_years_of_naming(filename, period):
    assert resource_period(filename) == period


def test_a_name_with_no_year_borrows_the_one_before_it():
    assert resource_period("july-over-500-report.csv", 2020) == "2020-07"


def test_discover_reads_the_build_id_out_of_the_page(client_for):
    seen: list[str] = []
    client = client_for(site(seen=seen))
    files = Hounslow().discover(client, None, None)
    assert seen[0] == "/@london-borough-of-hounslow/council-spending-over-500"
    assert seen[1] == (
        f"/_next/data/{BUILD}/@london-borough-of-hounslow/council-spending-over-500.json"
    )
    assert len(files) == len(RESOURCES)


def test_the_build_id_is_read_on_every_run(client_for):
    """It rotates on deploy, so a remembered one would 404 by the morning."""
    seen: list[str] = []
    client = client_for(site(seen=seen))
    source = Hounslow()
    source.discover(client, None, None)
    source.discover(client, None, None)
    assert seen.count("/@london-borough-of-hounslow/council-spending-over-500") == 2


def test_a_stale_build_id_fails_loudly(client_for):
    """A 404 on the data route is reported, not turned into an empty borough."""
    client = client_for(site(build="A1newBuildAfterDeploy"))
    with pytest.raises(NotPublished):
        Hounslow().discover(client, None, None)


def test_periods_cover_the_whole_series(client_for):
    client = client_for(site())
    assert [f.period for f in Hounslow().discover(client, None, None)] == [
        "2010-09_2011-03",
        "2011-04_2012-03",
        "2015-10_2015-11",
        "2020-06",
        "2020-07",
        "2020-08",
        "2026-05",
        "2026-04",
        "2026-07",
    ]


def test_a_window_inside_a_span_still_finds_the_file(client_for):
    """The half year that runs into 2011 is reachable from a 2011 window."""
    client = client_for(site())
    files = Hounslow().discover(client, None, None)
    kept = filter_files(files, "2011-01", "2011-02")
    assert [f.period for f in kept] == ["2010-09_2011-03"]


def test_the_period_comes_from_the_file_not_the_title(client_for):
    """April 2026 is titled "...april-202026...", which reads as 2020."""
    client = client_for(site())
    files = {f.filename: f for f in Hounslow().discover(client, None, None)}
    assert files["Invoices Over 500 April 2026-PgLmul.csv"].period == "2026-04"


def test_the_format_is_whatever_that_month_happened_to_be(client_for):
    client = client_for(site())
    files = {f.period: f for f in Hounslow().discover(client, None, None)}
    assert files["2026-05"].format == "xlsx"
    assert files["2026-07"].format == "csv"
    assert files["2026-05"].filename == "Invoices Over 500 May 2026-suHeLH.xlsx"


def test_discover_honours_since_and_until(client_for):
    client = client_for(site())
    files = Hounslow().discover(client, "2020-07", "2026-04")
    kept = filter_files(files, "2020-07", "2026-04")
    assert [f.period for f in kept] == ["2020-07", "2020-08", "2026-04"]


def test_nothing_is_mutable(client_for):
    """Hounslow posts a new resource per month and does not rewrite one."""
    client = client_for(site())
    assert not any(f.mutable for f in Hounslow().discover(client, None, None))
