"""Hounslow: a Next.js portal with no public API, read through its own data route.

The classic CKAN endpoints (``/api/3/action/package_show`` and friends) all 404
on this portal. What does answer is the JSON the front end fetches for itself:
``/_next/data/<buildId>/@london-borough-of-hounslow/council-spending-over-500.json``,
which carries all 140 resources with their titles, formats and blob URLs. The
``buildId`` changes on every deploy, so it is read out of the dataset page HTML
on every run rather than remembered. That is one 2.5 MB page plus one 2.2 MB
JSON per run, which is the price of this portal.

The series runs from September 2010 and the labelling changes with whoever was
posting that year: ``council-spending-over-500-may-2015``,
``invoices-over-500-feb-2018``, ``Invoices Over £500 Jul 2025-Dd99UO.xlsx``.
The period is read from the blob filename, which stayed sane through the one
resource whose title did not ("invoices-20over-20500-20april-202026-pglmul",
where a percent-escape was swallowed and April 2026 reads as 2020).

Three shapes need more than a month name:

* A file covering several months takes the range it covers: "september 2010 to
  march 2011" is ``2010-09_2011-03`` and "october-november-2015" is
  ``2015-10_2015-11``, so a ``--since`` anywhere inside the span still reaches
  the file.
* The four whole-year files (``council-spending-over-500-2011-12`` through
  ``2014-15``) are financial years, so they become the twelve months they
  hold, ``2011-04_2012-03``. Reading the label as a range is also what stops
  ``2011-12`` being taken for December 2011.
* ``july-over-500-report`` carries no year at all. It takes the year the
  resource before it ended in, which is June 2020, and lands on 2020-07.

Formats alternate between CSV and XLSX without warning, sometimes month to
month, so the format is taken from the URL rather than assumed.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

import httpx

from ..http import FetchError, request_with_retries
from ..models import RemoteFile, format_from_name
from .base import (
    Source,
    month_period,
    month_span,
    parse_month_name,
    period_bounds,
    range_period,
)

HOST = "https://data.hounslow.gov.uk"
DATASET_PATH = "/@london-borough-of-hounslow/council-spending-over-500"

#: The Next.js build hash, inlined in the page as ``"buildId":"PTSbv9Gst0..."``.
BUILD_ID = re.compile(r'"buildId"\s*:\s*"([^"]+)"')

#: ``2011-12`` as a financial year: the second half has to be the next year.
FY_LABEL = re.compile(r"((?:19|20)\d{2})-(\d{2})(?!\d)")

#: Words, for the last-resort pass that lends a yearless name its neighbour's
#: year.
WORD = re.compile(r"[A-Za-z]+")


def resource_period(text: str, fallback_year: int | None = None) -> str | None:
    """The period one resource covers, read from its filename.

    ``fallback_year`` rescues a name with a month and no year by lending it the
    year of the resource before it in the dataset's own order.
    """
    financial_year = FY_LABEL.search(text)
    if financial_year:
        start, end = int(financial_year.group(1)), int(financial_year.group(2))
        if end == (start + 1) % 100:
            return range_period(month_period(start, 4), month_period(start + 1, 3))
    span = month_span(text)
    if span:
        return range_period(*span)
    if fallback_year:
        for token in WORD.findall(text):
            month = parse_month_name(token)
            if month:
                return month_period(fallback_year, month)
    return None


class Hounslow(Source):
    slug = "hounslow"
    name = "Hounslow"
    threshold = "£500"
    # Not an API: the route is the front end's own, and a redeploy that
    # changes it breaks this the way a CMS rebuild breaks a scrape.
    access = "scrape"
    landing_page = f"{HOST}{DATASET_PATH}"

    def build_id(self, client: httpx.Client) -> str:
        """Today's build hash, from the page the data route belongs to.

        Read every run and never cached: a deploy between two runs would
        otherwise turn every request into a 404, and the page has to be fetched
        anyway to know the route still exists.
        """
        response = request_with_retries(client, "GET", self.landing_page)
        match = BUILD_ID.search(response.text)
        if not match:
            raise FetchError(f"no buildId in {self.landing_page}")
        return match.group(1)

    def resources(self, client: httpx.Client) -> list[dict]:
        """The dataset record the front end reads, resources and all."""
        url = f"{HOST}/_next/data/{self.build_id(client)}{DATASET_PATH}.json"
        response = request_with_retries(client, "GET", url)
        dataset = (response.json().get("pageProps") or {}).get("dataset") or {}
        return dataset.get("resources") or []

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Every resource on the dataset, in the order the portal lists them.

        The order matters twice: it is roughly chronological, which is what
        lets a yearless name borrow its neighbour's year, and it is the order
        Hounslow itself uses, so a resource added out of sequence stays where
        the publisher put it.
        """
        files = []
        year: int | None = None
        for resource in self.resources(client):
            url = resource.get("url") or ""
            if not url:
                continue
            filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            period = resource_period(filename, year) or resource_period(
                resource.get("name") or "", year
            )
            if not period:
                continue
            # The year a yearless neighbour borrows is the one this resource
            # ends in, which for a range is its last month and not its first.
            year = int(period_bounds(period)[1][:4])
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=url,
                    filename=filename,
                    format=format_from_name(url),
                    title=resource.get("name") or None,
                )
            )
        return files
