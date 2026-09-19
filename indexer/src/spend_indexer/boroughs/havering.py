"""Havering: one CSV per month, two hops from the landing page.

The landing page lists one collection page per financial year
(``/downloads/download/1112/spend-over-500-2026-27``) and each collection page
lists that year's months (``/downloads/file/7520/july-2026``). Both numeric ids
belong to the CMS and cannot be constructed, so both hops are scraped. Only the
year pages whose financial year overlaps the requested range are opened, which
keeps a ``--since 2026-04`` run to two requests rather than eighteen: the
history runs back to December 2010.

A month URL carries no extension at all. The body is CSV (``text/csv``, and the
server's own Content-Disposition calls it ``Transparency_Spend___July_2026.csv``),
so the saved name is the URL slug with ``.csv`` put back on the end.
"""

from __future__ import annotations

import logging
import re

import httpx

from ..http import FetchError, request_with_retries
from ..models import RemoteFile
from .base import (
    Source,
    extract_links,
    filter_files,
    month_period,
    parse_period,
)

logger = logging.getLogger(__name__)

#: A financial year's collection page, e.g. ``.../1112/spend-over-500-2026-27``.
YEAR_PATTERN = r"/downloads/download/\d+/"

#: One month inside a collection page, e.g. ``.../file/7520/july-2026``.
FILE_PATTERN = r"/downloads/file/\d+/"

#: ``2026-27`` or ``2026/27`` in a collection slug or its label.
_FY = re.compile(r"(\d{4})\s*[-/]\s*(\d{2})\b")

#: Some older month slugs end in a format marker (``december-2010-csv``) where
#: the newer ones do not (``july-2026``). Stripped so the saved filename does
#: not read ``december-2010-csv.csv``.
_TRAILING_FORMAT = re.compile(r"[-_.]csv$", re.IGNORECASE)


def csv_filename(slug: str) -> str:
    """``july-2026`` and ``december-2010-csv`` both become ``<month>.csv``."""
    return f"{_TRAILING_FORMAT.sub('', slug)}.csv"


def fy_overlaps(start_year: int, since: str | None, until: str | None) -> bool:
    """Does financial year ``start_year`` hold any month in ``[since, until]``?

    Overlap rather than containment, for the same reason
    :func:`~spend_indexer.boroughs.base.in_range` uses it: ``--since 2026-03``
    must still open the 2025-26 page that holds March 2026.
    """
    first, last = month_period(start_year, 4), month_period(start_year + 1, 3)
    if since and last < since:
        return False
    if until and first > until:
        return False
    return True


class Havering(Source):
    slug = "havering"
    name = "Havering"
    threshold = "£500"
    access = "scrape"
    landing_page = "https://www.havering.gov.uk/council-data-spending/spend-500"

    def year_pages(self, client: httpx.Client) -> list[tuple[int, str]]:
        """``[(financial year start, url)]`` from the landing page, newest first."""
        response = request_with_retries(client, "GET", self.landing_page)
        out: list[tuple[int, str]] = []
        seen: set[int] = set()
        for url, label in extract_links(
            response.text, self.landing_page, pattern=YEAR_PATTERN
        ):
            match = _FY.search(url.rsplit("/", 1)[-1]) or _FY.search(label)
            if match is None:
                logger.warning(
                    "havering: no financial year in %r (%s), page skipped", label, url
                )
                continue
            start_year = int(match.group(1))
            if start_year in seen:
                continue
            seen.add(start_year)
            out.append((start_year, url))
        return out

    def months_in(self, client: httpx.Client, url: str) -> tuple[list[RemoteFile], int]:
        """One year's months, and how many of its links could not be dated."""
        response = request_with_retries(client, "GET", url)
        files: list[RemoteFile] = []
        undated = 0
        for file_url, label in extract_links(response.text, url, pattern=FILE_PATTERN):
            slug = file_url.rsplit("/", 1)[-1]
            period = parse_period(slug) or parse_period(label)
            if period is None:
                undated += 1
                logger.warning(
                    "havering: no month in %r (%s), link skipped", label, file_url
                )
                continue
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=file_url,
                    filename=csv_filename(slug),
                    format="csv",
                    title=f"Havering spend over £500, {period}",
                )
            )
        return files, undated

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Landing page, then one collection page per financial year in range."""
        files: list[RemoteFile] = []
        undated = 0
        for start_year, url in self.year_pages(client):
            if not fy_overlaps(start_year, since, until):
                continue
            try:
                year_files, year_undated = self.months_in(client, url)
            except (FetchError, httpx.HTTPError) as exc:
                # One collection page that has moved costs its own year, not
                # the sixteen others.
                logger.warning("havering: %s could not be read: %s", url, exc)
                continue
            files.extend(year_files)
            undated += year_undated
        if undated:
            logger.warning(
                "havering: %d month link(s) could not be dated and were skipped",
                undated,
            )
        # Sorted, because the collection pages arrive newest first and a
        # month page lists its months in whatever order the CMS returns them.
        return sorted(
            filter_files(files, since, until), key=lambda f: (f.period, f.filename)
        )
