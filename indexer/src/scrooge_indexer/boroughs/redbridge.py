"""Redbridge: DataShare, the council's own platform, one ~10 MB CSV per month.

The richest schema in the corpus (thirty-odd columns, publisher URIs, company
registration numbers) and the most careless labelling. The download URL is
``/Download/finance/payments-over-500-{FY}/{month-slug}/CSV`` and the month
slug is whatever whoever uploaded it typed: ``april-2026`` and ``aug-2026`` in
the same year, ``march-17`` and ``may-18`` with two-digit years, and in the
current year ``may-2027`` and ``june-2027`` for files that are plainly May and
June 2026.

So the year in a month slug is not evidence. The dataset it sits in is: a
financial year runs April to March, and "May" inside ``payments-over-500-2026-27``
can only be May 2026. The period comes from that pairing, and the slug is kept
as the filename, so ``2026-05__may-2027.csv`` records both the period we
believe and the name Redbridge gave it.

Two datasets bundle three financial years each (2010-11 to 2012-13, 2013-14 to
2015-16). There the month name alone cannot pick a year, so the slug's year is
used after all, and a slug naming a year the bundle does not cover is dropped.
That drops exactly one file today: a 0-row "December 2021" uploaded into the
2013-14 to 2015-16 bundle in January 2022.

Nothing here constructs a URL. Every file comes from a link on a page, because
the two things that would have to be guessed (which months exist, and how each
one is spelled) are the two things Redbridge is least consistent about.
"""

from __future__ import annotations

import re

import httpx

from ..http import FetchError, request_with_retries
from ..models import RemoteFile
from .base import Source, extract_links, month_period, parse_month_name

HOST = "https://data.redbridge.gov.uk"
INDEX = f"{HOST}/Download/finance"

#: ``payments-over-500-2016-17`` and ``payments-over-500-2010-11-to-2012-13``.
DATASET = re.compile(r"/Download/finance/(payments-over-500-\d{4}-\d{2}[\w-]*)$")

#: A financial year as the slugs spell it, ``2026-27``.
FY_LABEL = re.compile(r"(\d{4})-(\d{2})(?!\d)")

#: Word or number in a month slug: ``may-2027``, ``march-17``,
#: ``payments-over-500-october-2011``.
TOKEN = re.compile(r"[A-Za-z]+|\d+")

#: The page shows ten files at a time, so the largest dataset here (a bundle
#: of three financial years, 37 files) is four pages. The cap is well above
#: that and exists so a pagination loop cannot walk forever.
MAX_PAGES = 12


def fy_span(dataset_slug: str) -> tuple[int, int] | None:
    """``payments-over-500-2010-11-to-2012-13`` → ``(2010, 2012)``, by FY start."""
    years = [int(start) for start, _ in FY_LABEL.findall(dataset_slug)]
    return (years[0], years[-1]) if years else None


def slug_month(month_slug: str) -> tuple[int, int | None] | None:
    """``may-2027`` → ``(5, 2027)``; ``march-17`` → ``(3, 2017)``; year may be None."""
    month = year = None
    for token in TOKEN.findall(month_slug):
        if month is None:
            month = parse_month_name(token)
            continue
        if token.isdigit() and len(token) in (2, 4):
            year = int(token) if len(token) == 4 else 2000 + int(token)
            break
    return (month, year) if month else None


def period_for(dataset_slug: str, month_slug: str) -> str | None:
    """The month a file covers, from the dataset it sits in and its own slug.

    One financial year leaves one candidate, and the slug's year is ignored
    because that is the half Redbridge gets wrong. A bundle of three leaves
    three, and then the slug's year is the only thing that can choose; a year
    outside the bundle means the file was filed in the wrong dataset and is
    not claimed here.
    """
    span = fy_span(dataset_slug)
    parsed = slug_month(month_slug)
    if span is None or parsed is None:
        return None
    month, year = parsed
    candidates = [
        month_period(start if month >= 4 else start + 1, month)
        for start in range(span[0], span[1] + 1)
    ]
    if len(candidates) == 1:
        return candidates[0]
    wanted = month_period(year, month) if year else None
    return wanted if wanted in candidates else None


class Redbridge(Source):
    slug = "redbridge"
    name = "Redbridge"
    threshold = "£500"
    access = "scrape"
    landing_page = "https://data.redbridge.gov.uk/View/finance/payments-over-500"

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """The finance download index, then each financial year that overlaps.

        Narrowing on the dataset is what keeps a catch-up cheap: asking for
        this April onwards is two requests, while the full history is thirteen
        datasets and about thirty pages.
        """
        files: list[RemoteFile] = []
        for dataset_url, dataset_slug in self._datasets(client):
            span = fy_span(dataset_slug)
            if span is None:
                continue
            first, last = month_period(span[0], 4), month_period(span[1] + 1, 3)
            if (since and last < since) or (until and first > until):
                continue
            files.extend(self._dataset_files(client, dataset_url, dataset_slug))
        return files

    def _datasets(self, client: httpx.Client) -> list[tuple[str, str]]:
        """``[(url, slug)]`` for every ``payments-over-500-*`` financial year."""
        try:
            response = request_with_retries(client, "GET", INDEX)
        except (FetchError, httpx.HTTPError):
            return []
        out = []
        for url, _ in extract_links(response.text, INDEX, pattern=DATASET):
            match = DATASET.search(url)
            if match:
                out.append((url, match.group(1)))
        return out

    def _dataset_files(
        self, client: httpx.Client, dataset_url: str, dataset_slug: str
    ) -> list[RemoteFile]:
        """Every CSV link on one financial year's pages, ten rows at a time."""
        files: list[RemoteFile] = []
        seen: set[str] = set()
        queue = [dataset_url]
        visited: set[str] = set()
        while queue and len(visited) < MAX_PAGES:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = request_with_retries(client, "GET", page_url)
            except (FetchError, httpx.HTTPError):
                continue
            for url, _ in extract_links(response.text, page_url, pattern=r"/CSV(\?|$)"):
                # The ?version= stamp is today's date, not the file's, and it
                # is not needed to download. Dropping it keeps the manifest key
                # stable instead of minting a new one every midnight.
                clean = url.split("?", 1)[0]
                month_slug = clean.rsplit("/", 2)[-2]
                period = period_for(dataset_slug, month_slug)
                if not period or clean in seen:
                    continue
                seen.add(clean)
                files.append(
                    RemoteFile(
                        borough=self.slug,
                        period=period,
                        url=clean,
                        filename=f"{month_slug}.csv",
                        format="csv",
                        title=f"Redbridge payments over £500, {period}",
                    )
                )
            # Pagination is a windowed "1 2 3 4 >", so later pages are only
            # reachable from the pages before them. Page 1 is the dataset URL
            # under another name, which is why it is not followed again.
            queue.extend(
                url
                for url, _ in extract_links(
                    response.text, page_url, pattern=r"[?&]page=\d+$"
                )
                if url not in visited and not url.endswith("page=1")
            )
        return files
