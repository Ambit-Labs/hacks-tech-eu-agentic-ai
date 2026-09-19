"""The six scraped budget-book pages: link patterns, labels, periods, fallback."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.boroughs import _budgetbook
from scrooge_indexer.boroughs.camden_budget import CamdenBudget
from scrooge_indexer.boroughs.croydon_budget import CroydonBudget
from scrooge_indexer.boroughs.lewisham_budget import LewishamBudget
from scrooge_indexer.boroughs.merton_budget import MertonBudget
from scrooge_indexer.boroughs.richmond_budget import RichmondBudget
from scrooge_indexer.boroughs.wandsworth_budget import WandsworthBudget

RICHMOND_PAGE = """
<html><body>
  <a href="/media/epafe3cl/budget_book_2026_27.pdf">Budget Book 2026/2027</a>
  <a href="/media/10875/budget_book_201415.pdf">Budget Book 2014/2015 (pdf, 1299KB)</a>
  <a href="/media/10879/budget_book_2010-14.pdf">Budget Book 2010/2011 (pdf, 2514KB)</a>
  <a href="/media/aaaa/statement_of_accounts_2025_26.pdf">Statement of Accounts 2025/26</a>
  <a href="/council/how_we_work/information_for_suppliers">Information for suppliers</a>
</body></html>
"""

CROYDON_PAGE = """
<html><body>
  <a href="/sites/default/files/2026-05/Consolidated-Budget-Books-2026-27.pdf">Budget book 2026-2027 ( PDF , 5.57MB )</a>
  <a href="/sites/default/files/articles/downloads/draft-rev-budget-capital-14-15.pdf">Budget Book 2014-15 ( PDF , 4.37MB )</a>
  <a href="/sites/default/files/articles/downloads/bbook1011.pdf">Budget Book 2010-11 ( PDF , 4.87MB )</a>
  <a href="/sites/default/files/2026-05/budget-monitoring-month-6.pdf">Budget monitoring month 6</a>
</body></html>
"""

CAMDEN_PAGE = """
<html><body>
  <a href="/documents/d/guest/2026-27-budget-book-final">Budget Book for 2026/27</a>
  <a href="/documents/20142/5611054/2016-17+Budget+Book.pdf/46e833f2-dd21">Budget Book for 2016/17</a>
  <a href="/documents/d/guest/december-2025-mtfs-report-final">Review of the Camden Medium Term Financial Strategy (PDF)</a>
</body></html>
"""

LEWISHAM_PAGE = """
<html><body>
  <a href="/-/media/mayor-and-council/about-us/finances/budgets/corporate-budget-book-2026-27.pdf">Corporate Budget Book 2026-27</a>
  <a href="/-/media/archive/files/imported/corporatebudgetbook2017-18.pdf?sc_lang=en">Corporate Budget Book 2017&#8211;18</a>
</body></html>
"""

MERTON_PAGE = """
<html><body>
  <a href="https://www.merton.gov.uk/sites/default/files/2026-08/Budget%20Book%20Detailed%2026-30_print_room.pdf">Budget Book 2026-2030</a>
  <a href="https://www.merton.gov.uk/system/files/merton_council_business_plan_2022-26.pdf">Business Plan 2022-26</a>
</body></html>
"""

WANDSWORTH_PAGE = """
<html><body>
  <a href="/media/af5d1dab/council_budget_2026_27.pdf">Council budget 2026/27</a>
  <a href="/media/2192/council_budget_200809.pdf">Council budget 2008/09</a>
</body></html>
"""

PAGES = {
    "www.richmond.gov.uk": RICHMOND_PAGE,
    "www.croydon.gov.uk": CROYDON_PAGE,
    "www.camden.gov.uk": CAMDEN_PAGE,
    "lewisham.gov.uk": LEWISHAM_PAGE,
    "www.merton.gov.uk": MERTON_PAGE,
    "www.wandsworth.gov.uk": WANDSWORTH_PAGE,
}


@pytest.fixture
def pages(client_for):
    def handler(request: httpx.Request) -> httpx.Response:
        body = PAGES.get(request.url.host)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=body, headers={"Content-Type": "text/html"})

    return client_for(handler)


def discovered(source, client):
    return {f.period: f for f in source.discover(client, None, None)}


def test_richmond_reads_the_year_off_the_label_not_the_filename(pages):
    """``budget_book_2010-14.pdf`` is the 2010/11 book; only the label says so."""
    found = discovered(RichmondBudget(), pages)
    assert set(found) == {"2026-04_2027-03", "2014-04_2015-03", "2010-04_2011-03"}
    assert found["2010-04_2011-03"].filename == "budget_book_2010-14.pdf"
    assert found["2026-04_2027-03"].url == (
        "https://www.richmond.gov.uk/media/epafe3cl/budget_book_2026_27.pdf"
    )


def test_the_label_filter_keeps_out_what_is_not_a_budget_book(pages):
    """Richmond's statement of accounts and Croydon's monitoring report."""
    richmond = RichmondBudget().discover(pages, None, None)
    assert not any("statement_of_accounts" in f.url for f in richmond)
    croydon = CroydonBudget().discover(pages, None, None)
    assert not any("monitoring" in f.url for f in croydon)


def test_croydon_survives_five_filename_conventions(pages):
    found = discovered(CroydonBudget(), pages)
    assert set(found) == {"2026-04_2027-03", "2014-04_2015-03", "2010-04_2011-03"}
    assert found["2014-04_2015-03"].filename == "draft-rev-budget-capital-14-15.pdf"


def test_camden_finds_the_filename_wherever_it_is_in_the_path(pages):
    found = discovered(CamdenBudget(), pages)
    assert found["2016-04_2017-03"].filename == "2016-17+Budget+Book.pdf"
    # No extension anywhere in the modern URL; the format supplies it on disk.
    assert found["2026-04_2027-03"].filename == "2026-27-budget-book-final"
    assert found["2026-04_2027-03"].format == "pdf"


def test_lewisham_reads_an_en_dash_and_ignores_the_query_string(pages):
    found = discovered(LewishamBudget(), pages)
    assert set(found) == {"2026-04_2027-03", "2017-04_2018-03"}
    assert found["2017-04_2018-03"].filename == "corporatebudgetbook2017-18.pdf"


def test_mertons_book_covers_four_years_and_says_so(pages):
    found = discovered(MertonBudget(), pages)
    assert set(found) == {"2026-04_2030-03", "2022-04_2026-03"}


def test_wandsworth(pages):
    found = discovered(WandsworthBudget(), pages)
    assert set(found) == {"2026-04_2027-03", "2008-04_2009-03"}


def test_every_budget_book_is_a_pdf_in_the_budget_tree(pages):
    for cls in (
        RichmondBudget,
        WandsworthBudget,
        CamdenBudget,
        CroydonBudget,
        MertonBudget,
        LewishamBudget,
    ):
        source = cls()
        assert source.kind == "budget"
        assert all(f.format == "pdf" for f in source.discover(pages, None, None))


def test_the_umbraco_fallback_only_runs_when_the_page_is_gone(client_for):
    """A rebuilt page that lists nothing must not leave the borough empty."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>rebuilt</body></html>")

    client = client_for(handler)
    found = RichmondBudget().discover(client, "2024-04", "2025-03")
    assert [f.url for f in found] == [
        "https://www.richmond.gov.uk/media/xxxxxxxx/budget_book_2024_25.pdf"
    ]
    assert found[0].period == "2024-04_2025-03"


def test_the_fallback_is_not_used_while_the_page_still_lists_books(pages):
    assert not any(
        _budgetbook.PLACEHOLDER_HASH in f.url
        for f in RichmondBudget().discover(pages, None, None)
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x/media/abc/budget_book_2026_27.pdf", "budget_book_2026_27.pdf"),
        (
            "https://x/documents/20142/5611054/2016-17+Budget+Book.pdf/46e8",
            "2016-17+Budget+Book.pdf",
        ),
        (
            "https://x/documents/d/guest/2026-27-budget-book-final",
            "2026-27-budget-book-final",
        ),
        ("https://x/a/b/book.pdf?sc_lang=en", "book.pdf"),
        ("https://x/", "document"),
    ],
)
def test_filename_from_url(url, expected):
    assert _budgetbook.filename_from_url(url) == expected
