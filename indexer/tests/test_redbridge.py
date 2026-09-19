"""Redbridge: the financial year decides the month, not the slug that names it."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.boroughs.redbridge import Redbridge, fy_span, period_for

INDEX = """
<html><body>
  <a href="/Download/finance/payments-over-500-2010-11-to-2012-13">Payments over &#163;500 2010-11 to 2012-13</a>
  <a href="/Download/finance/payments-over-500-2025-26">Payments over &#163;500 2025-26</a>
  <a href="/Download/finance/payments-over-500-2026-27">Payments over &#163;500 2026-27</a>
  <a href="/Download/finance/payments-within-30-days">Payments within 30 days</a>
  <a href="/Download/finance/regulation-113-7">Regulation 113(7)</a>
</body></html>
"""

#: The 2026-27 page as Redbridge serves it: five months, two of them labelled
#: with next year, and an XML link next to every CSV one. The ?version stamp
#: is today's date and appears on every link.
FY_2026_27 = """
<html><body><table><tbody>
  <tr><td class="Title">July 2026</td><td>20165</td>
    <a href="/Download/finance/payments-over-500-2026-27/july-2026/CSV?version=19/09/2026">CSV</a>
    <a href="/Download/finance/payments-over-500-2026-27/july-2026/XML?version=19/09/2026">XML</a></tr>
  <tr><td class="Title">June 2027</td><td>17801</td>
    <a href="/Download/finance/payments-over-500-2026-27/june-2027/CSV?version=19/09/2026">CSV</a>
    <a href="/Download/finance/payments-over-500-2026-27/june-2027/XML?version=19/09/2026">XML</a></tr>
  <tr><td class="Title">May 2027</td><td>17333</td>
    <a href="/Download/finance/payments-over-500-2026-27/may-2027/CSV?version=19/09/2026">CSV</a></tr>
  <tr><td class="Title">April 2026</td><td>22057</td>
    <a href="/Download/finance/payments-over-500-2026-27/april-2026/CSV?version=19/09/2026">CSV</a></tr>
  <tr><td class="Title">Aug 2026</td><td>19002</td>
    <a href="/Download/finance/payments-over-500-2026-27/aug-2026/CSV?version=19/09/2026">CSV</a></tr>
</tbody></table></body></html>
"""

#: Ten rows a page, so the 2025-26 year takes two of them.
FY_2025_26_PAGE_1 = """
<html><body><table>
  <tfoot><tr><td>1 <a href="/Download/finance/payments-over-500-2025-26?page=2">2</a>
    <a href="/Download/finance/payments-over-500-2025-26?page=2">&gt;</a></td></tr></tfoot>
  <tbody>
  <tr><a href="/Download/finance/payments-over-500-2025-26/march-2026/CSV?version=19/09/2026">CSV</a></tr>
  <tr><a href="/Download/finance/payments-over-500-2025-26/february-2026/CSV?version=19/09/2026">CSV</a></tr>
  </tbody>
</table></body></html>
"""

FY_2025_26_PAGE_2 = """
<html><body><table>
  <tfoot><tr><td><a href="/Download/finance/payments-over-500-2025-26?page=1">1</a> 2</td></tr></tfoot>
  <tbody>
  <tr><a href="/Download/finance/payments-over-500-2025-26/april-2025/CSV?version=19/09/2026">CSV</a></tr>
  </tbody>
</table></body></html>
"""

#: The three-year bundle, with the December 2021 file someone uploaded into it
#: in January 2022 and the one month whose slug repeats the dataset name.
BUNDLE = """
<html><body><table><tbody>
  <tr><a href="/Download/finance/payments-over-500-2010-11-to-2012-13/october-2012/CSV">CSV</a></tr>
  <tr><a href="/Download/finance/payments-over-500-2010-11-to-2012-13/payments-over-500-october-2011/CSV">CSV</a></tr>
  <tr><a href="/Download/finance/payments-over-500-2010-11-to-2012-13/december-2021/CSV">CSV</a></tr>
</tbody></table></body></html>
"""

PAGES = {
    "/Download/finance": INDEX,
    "/Download/finance/payments-over-500-2026-27": FY_2026_27,
    "/Download/finance/payments-over-500-2025-26": FY_2025_26_PAGE_1,
    "/Download/finance/payments-over-500-2010-11-to-2012-13": BUNDLE,
}


def site(seen: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        page = request.url.params.get("page")
        if seen is not None:
            seen.append(f"{path}?page={page}" if page else path)
        if path == "/Download/finance/payments-over-500-2025-26" and page == "2":
            body = FY_2025_26_PAGE_2
        else:
            body = PAGES.get(path)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=body, headers={"Content-Type": "text/html"})

    return handler


@pytest.mark.parametrize(
    ("dataset", "month_slug", "period"),
    [
        # One financial year leaves one candidate, so a slug saying 2027 for a
        # 2026-27 file is overruled rather than believed.
        ("payments-over-500-2026-27", "may-2027", "2026-05"),
        ("payments-over-500-2026-27", "june-2027", "2026-06"),
        ("payments-over-500-2026-27", "april-2026", "2026-04"),
        ("payments-over-500-2026-27", "aug-2026", "2026-08"),
        # January to March belong to the second calendar year of the year.
        ("payments-over-500-2025-26", "february-2026", "2026-02"),
        ("payments-over-500-2025-26", "april-2025", "2025-04"),
        # Two-digit years in the slug, also ignored.
        ("payments-over-500-2016-17", "march-17", "2017-03"),
        ("payments-over-500-2018-19", "may-18", "2018-05"),
        # A bundle of three years cannot be resolved by month alone, so the
        # slug's year is used and has to fall inside the bundle.
        ("payments-over-500-2010-11-to-2012-13", "october-2011", "2011-10"),
        (
            "payments-over-500-2010-11-to-2012-13",
            "payments-over-500-october-2011",
            "2011-10",
        ),
        ("payments-over-500-2013-14-to-2015-16", "december-2021", None),
        ("payments-over-500-2026-27", "not-a-month", None),
    ],
)
def test_period_comes_from_the_year_plus_the_month_name(dataset, month_slug, period):
    assert period_for(dataset, month_slug) == period


def test_fy_span_reads_one_year_and_a_bundle():
    assert fy_span("payments-over-500-2026-27") == (2026, 2026)
    assert fy_span("payments-over-500-2010-11-to-2012-13") == (2010, 2012)


def test_discover_takes_the_months_the_page_lists(client_for):
    client = client_for(site())
    files = Redbridge().discover(client, "2026-04", None)
    assert sorted(f.period for f in files) == [
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
    ]


def test_the_mislabelled_months_keep_redbridges_filename(client_for):
    """The period is ours, the filename is theirs, and the pair records both."""
    client = client_for(site())
    files = {f.period: f for f in Redbridge().discover(client, "2026-04", None)}
    assert files["2026-05"].filename == "may-2027.csv"
    assert files["2026-05"].url.endswith("/payments-over-500-2026-27/may-2027/CSV")
    assert files["2026-06"].filename == "june-2027.csv"
    assert files["2026-05"].format == "csv"


def test_the_version_stamp_is_dropped_from_the_url(client_for):
    """It is today's date, not the file's, so it would churn the manifest key."""
    client = client_for(site())
    files = Redbridge().discover(client, "2026-04", None)
    assert all("version=" not in f.url for f in files)


def test_the_xml_serialisation_is_not_mistaken_for_a_second_file(client_for):
    client = client_for(site())
    files = Redbridge().discover(client, "2026-04", None)
    periods = [f.period for f in files]
    assert len(periods) == len(set(periods))
    assert all(f.url.endswith("/CSV") for f in files)


def test_pagination_follows_the_windowed_page_links(client_for):
    seen: list[str] = []
    client = client_for(site(seen))
    files = Redbridge().discover(client, "2025-04", "2026-03")
    assert sorted(f.period for f in files) == ["2025-04", "2026-02", "2026-03"]
    assert seen == [
        "/Download/finance",
        "/Download/finance/payments-over-500-2025-26",
        "/Download/finance/payments-over-500-2025-26?page=2",
    ]


def test_a_file_bundled_under_a_year_it_cannot_belong_to_is_dropped(client_for):
    """A 0-row December 2021 sits in the 2010-11 to 2012-13 bundle. Not ours."""
    client = client_for(site())
    files = Redbridge().discover(client, None, "2013-03")
    assert sorted(f.period for f in files) == ["2011-10", "2012-10"]


def test_since_and_until_skip_whole_financial_years(client_for):
    seen: list[str] = []
    client = client_for(site(seen))
    Redbridge().discover(client, "2026-08", None)
    assert seen == [
        "/Download/finance",
        "/Download/finance/payments-over-500-2026-27",
    ]
