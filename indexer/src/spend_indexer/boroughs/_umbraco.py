"""The publication system Richmond and Wandsworth share.

The two councils share staff and share a CMS: the same Umbraco site, the same
``/media/{hash}/council_expenditure_{month}_{yyyy}.csv`` URLs, the same six
column headers and the same January 2019 start date, on two separate media
stores so each host serves its own borough's data. One base class, two borough
modules, two registry entries.

Underscore-prefixed so the registry skips it: this file defines shared
machinery, not a borough.
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from ..http import FetchError, request_with_retries
from ..models import RemoteFile
from .base import (
    Source,
    current_month,
    extract_links,
    month_name,
    months_between,
    parse_period,
)

#: Any eight characters resolve the file. The media hash in these URLs is a
#: display artefact: the server looks the document up by filename and 301s a
#: wrong hash to the canonical URL, while a month that was never published
#: 404s whatever the hash. Verified on both hosts on 2026-09-19 (a bogus hash
#: redirected to the real one and returned byte-identical CSV). So the
#: fallback below is not a trick and not a guess, it is the same lookup the
#: real link performs, minus the link.
PLACEHOLDER_HASH = "xxxxxxxx"

#: A landing page that yields fewer CSV links than this has been rebuilt, and
#: trusting it would silently drop months. Below the floor we ignore the scrape
#: and fall back to generated candidates.
MIN_SCRAPED_LINKS = 6


class UmbracoExpenditureSource(Source):
    """Monthly ``council_expenditure_{month}_{yyyy}.csv`` on an Umbraco host."""

    host: ClassVar[str]
    """e.g. ``https://www.richmond.gov.uk``."""

    earliest: ClassVar[str] = "2019-01"
    threshold: ClassVar[str] = "£500"
    access: ClassVar[str] = "url-pattern"

    def file_url(self, month: str, media_hash: str = PLACEHOLDER_HASH) -> str:
        year, number = month.split("-")
        name = f"council_expenditure_{month_name(int(number))}_{year}.csv"
        return f"{self.host}/media/{media_hash}/{name}"

    def scrape_months(self, client: httpx.Client) -> dict[str, str]:
        """``{period: url}`` from the landing page, empty when it cannot be read.

        Preferred over generated URLs because the page is the publisher's own
        list: it gives the real media hash (one round trip instead of a
        redirect) and, more importantly, it says which months exist, which
        turns a backfill from 92 speculative requests into one page plus the
        files that are really there.
        """
        try:
            response = request_with_retries(client, "GET", self.landing_page)
        except (FetchError, httpx.HTTPError):
            return {}
        found: dict[str, str] = {}
        links = extract_links(
            response.text, self.landing_page, pattern=r"council_expenditure_.*\.csv$"
        )
        for url, text in links:
            period = parse_period(url) or parse_period(text)
            if period:
                found.setdefault(period, url)
        return found if len(found) >= MIN_SCRAPED_LINKS else {}

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        start = max(since or self.earliest, self.earliest)
        end = min(until or current_month(), current_month())
        published = self.scrape_months(client)
        files = []
        for month in months_between(start, end):
            url = published.get(month)
            if published and url is None:
                # The page lists every month it has, so an absent month is one
                # the council has not published. No request, no 404 to record.
                continue
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=month,
                    url=url or self.file_url(month),
                    filename=f"council_expenditure_{month_name(int(month[5:]))}_{month[:4]}.csv",
                    format="csv",
                    title=f"{self.name} expenditure over £500, {month}",
                )
            )
        return files
