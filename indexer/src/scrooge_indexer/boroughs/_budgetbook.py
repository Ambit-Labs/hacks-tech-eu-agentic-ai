"""The shape six boroughs share: a page that lists one budget book per year.

A budget book is the council's own account of what it plans to spend, service
by service, and every borough here puts the whole back catalogue on one page.
So the work is not finding the files, it is reading the year off them, and the
year is in the link text rather than the filename: Croydon's 2014-15 book is
``draft-rev-budget-capital-14-15.pdf`` and Richmond's 2010-11 book is
``budget_book_2010-14.pdf``, both of which a filename parser would get wrong,
and both of which are labelled plainly on the page.

Some books cover more than one year. Merton publishes a rolling four-year book
and the period says so (``2026-04_2030-03``), so a query for any year inside
the span still reaches the file.

Underscore-prefixed so the registry skips it: shared machinery, not a source.
"""

from __future__ import annotations

import re
from typing import ClassVar
from urllib.parse import unquote, urlsplit

import httpx

from ..http import request_with_retries
from ..models import RemoteFile
from .base import (
    Source,
    current_month,
    extract_links,
    fy_of_month,
    fy_period,
    in_range,
    parse_fy_span,
)

#: Any eight characters resolve an Umbraco media URL: the server looks the
#: document up by filename and 301s a wrong hash to the canonical one. Verified
#: on richmond.gov.uk and wandsworth.gov.uk on 2026-09-19, where a bogus hash
#: redirected to the real file. The same finding the monthly spend modules rely
#: on, and for the same reason: it is the lookup the real link performs, not a
#: way around anything.
PLACEHOLDER_HASH = "xxxxxxxx"


def filename_from_url(url: str) -> str:
    """The publisher's filename, from a URL that may bury it mid-path.

    Camden serves ``/documents/20142/5611054/2016-17+Budget+Book.pdf/<uuid>``,
    where the last segment is an opaque id and the useful name is the one
    before it, and ``/documents/d/guest/2026-27-budget-book-final``, where
    there is no extension anywhere. Take the last segment that looks like a
    file, else the last segment and let the format supply the extension.
    """
    segments = [s for s in unquote(urlsplit(url).path).split("/") if s]
    if not segments:
        return "document"
    for segment in reversed(segments):
        if "." in segment:
            return segment
    return segments[-1]


class BudgetBookSource(Source):
    """One page, one PDF per financial year, the year read from the label."""

    kind = "budget"
    threshold = "n/a"
    access = "scrape"

    link_pattern: ClassVar[str]
    """Matched against the absolute URL, to keep the page's other links out."""

    label_pattern: ClassVar[re.Pattern[str]]
    """Matched against the link text. This is what says "budget book" rather
    than "budget monitoring report", on pages that carry both."""

    def document_title(self, label: str) -> str:
        return f"{self.name}: {label}"

    def candidate_links(self, html: str) -> list[tuple[str, str]]:
        return extract_links(html, self.landing_page, pattern=self.link_pattern)

    def fallback_files(self, since: str | None, until: str | None) -> list[RemoteFile]:
        """Files to use when the page yields nothing. Empty unless overridden."""
        return []

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Scrape the page; fall back only when it has stopped being a page.

        The page is the publisher's own list, so it is always preferred: it
        says which years exist, and no request is spent on a year that does
        not. A rebuild that leaves no matching link at all is the only case
        where a generated URL is better than nothing.
        """
        response = request_with_retries(client, "GET", self.landing_page)
        found: list[RemoteFile] = []
        for url, label in self.candidate_links(response.text):
            if not self.label_pattern.search(label):
                continue
            span = parse_fy_span(label) or parse_fy_span(url)
            if span is None:
                continue
            found.append(
                RemoteFile(
                    borough=self.slug,
                    period=fy_period(*span),
                    url=url,
                    filename=filename_from_url(url),
                    format="pdf",
                    title=self.document_title(" ".join(label.split())),
                )
            )
        return found or self.fallback_files(since, until)


class UmbracoBudgetBookSource(BudgetBookSource):
    """Richmond and Wandsworth: one Umbraco host, one filename per year.

    The two councils share a finance team and a CMS, and their budget books sit
    at ``/media/{hash}/{stem}_{yyyy}_{yy}.pdf``. The hash is a display artefact
    the server ignores, so a rebuilt landing page is survivable: the modern
    years can still be addressed by name.
    """

    access = "url-pattern"

    host: ClassVar[str]
    """e.g. ``https://www.richmond.gov.uk``."""

    stem: ClassVar[str]
    """Filename before the year: ``budget_book`` or ``council_budget``."""

    pattern_from: ClassVar[int]
    """First financial year whose filename follows the modern pattern. Older
    books are on the page under names that do not (``budget_book_201415.pdf``,
    ``council_budget_200910.pdf``), so the fallback stops there rather than
    generating URLs that 404."""

    def file_url(self, start_year: int, media_hash: str = PLACEHOLDER_HASH) -> str:
        name = f"{self.stem}_{start_year}_{(start_year + 1) % 100:02d}.pdf"
        return f"{self.host}/media/{media_hash}/{name}"

    def fallback_files(self, since: str | None, until: str | None) -> list[RemoteFile]:
        latest = fy_of_month(current_month())
        files = []
        for start in range(self.pattern_from, latest + 1):
            period = fy_period(start)
            if not in_range(period, since, until):
                continue
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=self.file_url(start),
                    filename=self.file_url(start).rsplit("/", 1)[-1],
                    format="pdf",
                    title=self.document_title(f"budget book {start}-{start + 1}"),
                )
            )
        return files
