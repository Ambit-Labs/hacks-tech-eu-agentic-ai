"""Richmond and Wandsworth: landing-page scrape, placeholder fallback, 404s."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.boroughs import _umbraco
from scrooge_indexer.boroughs.richmond import Richmond
from scrooge_indexer.boroughs.wandsworth import Wandsworth
from scrooge_indexer.http import NotPublished, download_to

LANDING = """
<html><body>
  <a href="/media/ke3cwzd4/council_expenditure_july_2026.csv">July 2026 (CSV)</a>
  <a href="/media/fphpsvls/council_expenditure_july_2026.pdf">July 2026 (PDF)</a>
  <a href="/media/pxtmtkm2/council_expenditure_june_2026.csv">June 2026 (CSV)</a>
  <a href="/media/s3plzfw2/council_expenditure_may_2026.csv">May 2026 (CSV)</a>
  <a href="/media/djklgc40/council_expenditure_april_2026.csv">April 2026 (CSV)</a>
  <a href="/media/iyyhs0hd/council_expenditure_march_2026.csv">March 2026 (CSV)</a>
  <a href="/media/ktsdrmnb/council_expenditure_february_2026.csv">February 2026</a>
  <a href="/media/yagn24m1/procurement_card_spend_2026_27_q1.csv">Card spend Q1</a>
</body></html>
"""


def landing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LANDING, headers={"Content-Type": "text/html"})


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(_umbraco, "current_month", lambda *_: "2026-09")


def test_scrape_gives_real_hashes_and_only_published_months(client_for):
    client = client_for(landing_handler)
    files = Richmond().discover(client, "2026-05", None)

    assert [f.period for f in files] == ["2026-05", "2026-06", "2026-07"]
    assert files[-1].url == (
        "https://www.richmond.gov.uk/media/ke3cwzd4/council_expenditure_july_2026.csv"
    )
    # August and September 2026 are not on the page, so they are never requested.
    assert "2026-08" not in {f.period for f in files}


def test_the_procurement_card_file_is_not_mistaken_for_a_month(client_for):
    client = client_for(landing_handler)
    periods = {f.period for f in Richmond().discover(client, "2026-01", None)}
    assert all(len(period) == 7 for period in periods)


def test_filenames_stay_the_publishers_own(client_for):
    client = client_for(landing_handler)
    files = Richmond().discover(client, "2026-07", "2026-07")
    assert files[0].filename == "council_expenditure_july_2026.csv"


def test_falls_back_to_the_placeholder_hash_when_the_page_cannot_be_read(client_for):
    """The hash segment is ignored by the server, so a generated URL still works.

    Verified on both hosts: a bogus hash 301s to the canonical URL and returns
    the same bytes, while an unpublished month 404s whatever the hash. The
    fallback keeps a CMS redesign from stopping the download.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<html>page moved</html>")

    client = client_for(handler)
    files = Richmond().discover(client, "2026-06", "2026-07")
    assert [f.period for f in files] == ["2026-06", "2026-07"]
    assert files[0].url == (
        "https://www.richmond.gov.uk/media/xxxxxxxx/council_expenditure_june_2026.csv"
    )


def test_a_thin_page_is_treated_as_broken_rather_than_authoritative(client_for):
    """A page listing two months has been rebuilt, not emptied of history."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='<a href="/media/aaaa1111/council_expenditure_july_2026.csv">July</a>',
            headers={"Content-Type": "text/html"},
        )

    client = client_for(handler)
    files = Richmond().discover(client, "2026-05", "2026-07")
    assert [f.period for f in files] == ["2026-05", "2026-06", "2026-07"]
    assert _umbraco.PLACEHOLDER_HASH in files[0].url


def test_discovery_never_reaches_before_january_2019(client_for):
    """Neither council published anything before January 2019, so nothing asks.

    Exercised on the fallback path, where the months are generated: on the
    scrape path the page itself is the bound.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<html>page moved</html>")

    client = client_for(handler)
    files = Wandsworth().discover(client, "2017-01", "2019-02")
    assert [f.period for f in files] == ["2019-01", "2019-02"]


def test_wandsworth_uses_its_own_host(client_for):
    client = client_for(landing_handler)
    files = Wandsworth().discover(client, "2026-07", "2026-07")
    assert files[0].url.startswith("https://www.wandsworth.gov.uk/")


def test_an_unpublished_month_is_a_404_not_a_failure(client_for, tmp_path):
    """The 404 body is a 22 KB HTML page, so only the status code can decide."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            text="<html>" + "not found " * 2000 + "</html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    client = client_for(handler)
    remote = Richmond().discover(client, "2026-06", "2026-06")[0]
    with pytest.raises(NotPublished):
        download_to(client, remote, tmp_path / "x.csv")
    assert not (tmp_path / "x.csv").exists()
