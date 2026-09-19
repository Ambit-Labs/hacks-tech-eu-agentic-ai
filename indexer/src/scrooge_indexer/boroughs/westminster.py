"""Westminster: one CSV a quarter, at a URL with no file extension on it.

The only quarterly publisher in this corpus and the shallowest history: four
files a year, Q1 2021/22 onwards. The quarters are the UK financial year's, so
"Q1 2026/27" covers April to June 2026 and lands as the period ``2026-Q1``.
``quarters = "financial"`` is what tells ``--since`` and ``--until`` that.

The download URL ends in a document slug with no extension at all and the body
is ``text/csv``, so ``format`` is stated here instead of being inferred, and
``filename`` carries the slug: the core appends the extension from ``format``
when the publisher's own name has none, which is how the file lands on disk as
``2026-Q1__q1-2026-27-expenditure-over-500.csv``.

The landing page is read rather than assumed because the slug changed shape
midway: from Q1 2021/22 to Q4 2024/25 there are three hyphens before
"expenditure", from Q1 2025/26 there is one, and three quarters carry extra
debris (a trailing hyphen, a zero-width space, the word "report"). The
generated URLs in :func:`file_url` follow the two-hyphen-shapes rule and are
only used when the page cannot be read at all.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote, urlsplit

import httpx

from ..http import FetchError, request_with_retries
from ..models import RemoteFile
from .base import (
    Source,
    current_month,
    extract_links,
    fy_label,
    fy_quarter_from_label,
    fy_quarter_of_month,
    fy_quarter_period,
    in_range,
)

log = logging.getLogger(__name__)

HOST = "https://www.westminster.gov.uk"

#: The quarter files, and nothing else on a page that also links to the
#: procurement card transactions and the contracts register.
QUARTER_LINK = re.compile(r"/media/document/q[1-4][^/]*expenditure", re.IGNORECASE)

#: Westminster's first published quarter, as (financial year, quarter).
EARLIEST = (2021, 1)

#: From this financial year the slug has one hyphen before "expenditure";
#: before it, three. Read off the live page on 2026-09-19.
SINGLE_HYPHEN_FY = 2025

#: A page yielding fewer quarters than this has been rebuilt, and trusting it
#: would silently drop years of history. Below the floor the generated URLs
#: take over, exactly as Richmond's scrape does.
MIN_SCRAPED_LINKS = 8

#: A bare "Q1 2026", which on this page means the financial year starting in
#: 2026 and not the calendar quarter. The shared helper refuses a single year
#: on purpose, because it reads the same shape for councils that mean the
#: other thing; Westminster labels its whole series this way, so here the year
#: after the quarter is the financial year and nothing else.
_QUARTER_AND_YEAR = re.compile(
    r"q(?P<quarter>[1-4])\W{0,3}(?P<year>(?:19|20)\d{2})", re.IGNORECASE
)


def parse_quarter(text: str) -> tuple[int, int] | None:
    """``(financial year, quarter)`` from a label, or None when it is unreadable.

    ``"Q1 2026/27"`` and ``"April to June 2026"`` both give ``(2026, 1)``. A
    month range is accepted only when it is exactly a financial quarter:
    "April to September" is a half year and returns None here rather than
    being filed under one of the six months it contains. Westminster publishes
    quarters, so a half year on this page would be a link to something else.
    """
    period = fy_quarter_from_label(text)
    if period is None:
        match = _QUARTER_AND_YEAR.search(text)
        if match is None:
            return None
        period = fy_quarter_period(
            int(match.group("year")), int(match.group("quarter"))
        )
    start_year, number = period.split("-Q")
    return int(start_year), int(number)


def file_url(start_year: int, quarter: int) -> str:
    """The document URL for one financial-year quarter.

    The pound sign has to arrive percent-encoded as ``%C2%A3``: it is part of
    the slug the CMS stored, not decoration.
    """
    separator = "-" if start_year >= SINGLE_HYPHEN_FY else "---"
    return (
        f"{HOST}/media/document/q{quarter}-{fy_label(start_year)}"
        f"{separator}expenditure-over-%C2%A3500"
    )


def _index(start_year: int, quarter: int) -> int:
    return start_year * 4 + quarter - 1


def _from_index(index: int) -> tuple[int, int]:
    return index // 4, index % 4 + 1


def latest_complete(today: str | None = None) -> tuple[int, int]:
    """The most recent quarter that has finished, so that we never ask for one
    that is still being spent in."""
    start, quarter = fy_quarter_of_month(today or current_month())
    return _from_index(_index(start, quarter) - 1)


class Westminster(Source):
    slug = "westminster"
    name = "Westminster"
    threshold = "£500"
    access = "scrape"
    quarters = "financial"
    landing_page = (
        "https://www.westminster.gov.uk/about-council/transparency"
        "/spending-procurement-and-data-transparency/expenditure-over-ps500"
    )

    def scrape(self, client: httpx.Client) -> dict[str, str]:
        """``{period: url}`` from the landing page, empty when it cannot be read.

        Empty rather than an exception, because the generated URLs below are a
        real fallback here: the council's own naming rule is known for both
        eras of the slug, and a CMS rebuild should cost a redirect, not the
        whole borough.
        """
        try:
            response = request_with_retries(client, "GET", self.landing_page)
        except (FetchError, httpx.HTTPError) as exc:
            log.warning(
                "westminster: landing page unreadable (%s), using the pattern", exc
            )
            return {}
        found: dict[str, str] = {}
        undated = 0
        for url, text in extract_links(
            response.text, self.landing_page, pattern=QUARTER_LINK
        ):
            quarter = parse_quarter(unquote(urlsplit(url).path)) or parse_quarter(text)
            if quarter is None:
                undated += 1
                log.debug("westminster: no quarter in %r for %s", text, url)
                continue
            found.setdefault(fy_quarter_period(*quarter), url)
        if undated:
            log.warning(
                "westminster: skipped %d expenditure link(s) with no readable "
                "quarter in the URL or the label",
                undated,
            )
        return found if len(found) >= MIN_SCRAPED_LINKS else {}

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Every quarter the page lists, or every quarter Westminster has had.

        On the generated path the three quarters whose slug carries extra
        debris (Q2, Q3 and Q4 of 2022/23) will 404 and be recorded as not
        published. That is the honest answer from a guessed URL, and it is
        only reached when the page itself is gone.
        """
        published = self.scrape(client)
        if not published:
            last = _index(*latest_complete())
            published = {
                fy_quarter_period(*_from_index(index)): file_url(*_from_index(index))
                for index in range(_index(*EARLIEST), last + 1)
            }
        files = []
        for period in sorted(published):
            if not in_range(period, since, until, quarters=self.quarters):
                continue
            url = published[period]
            filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=url,
                    filename=filename,
                    format="csv",
                    title=f"Westminster expenditure over £500, {period}",
                )
            )
        return files
