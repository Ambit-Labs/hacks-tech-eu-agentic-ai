"""Lewisham: one data file a month, and a PDF of the same month next to it.

Every payment over £250, published as a CSV (XLSX for the 2023 and 2024
months) with a PDF twin. The PDFs are ignored: they are the same numbers set
for printing, and nothing downstream would read one that could read the
spreadsheet instead. Format therefore comes from the URL rather than from the
label, which is wrong often enough to matter: the September 2025 CSV is
labelled "(pdf)" and the December 2024 CSV is labelled "(Excel)".

The file has two preamble rows before its header: a title row and a blank one,
so the column names sit on row three. That costs the download nothing and is
recorded here for the parsing stage, which will also meet a cp1252 pound sign
in the header and amounts quoted with thousands separators.

Filenames are inconsistent to the point of comedy. Five consecutive months are
jul2026paymentsover250.csv, jun2026paymentsover250.csv,
may2026_paymentsover250.csv, apr2026paymentsover_250.csv and, further back,
lewishamover250oct.csv. So the page is scraped for real links and
:func:`candidate_url` only fills holes the page leaves inside its own span.

The months before February 2023 are Sitecore ``.ashx`` media links whose
payload format is nowhere in the URL, and most of those hrefs on the page are
broken anyway (a curly quote is glued into the path). They are left alone.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

import httpx

from ..http import request_with_retries
from ..models import RemoteFile, format_from_name
from .base import (
    Source,
    extract_links,
    fy_of_month,
    in_range,
    month_name,
    months_between,
    parse_period,
    shift_month,
)

log = logging.getLogger(__name__)

HOST = "https://lewisham.gov.uk"

MEDIA_ROOT = f"{HOST}/-/media/mayor-and-council/about-us/finances/spending-over-250"

#: A data file rather than the PDF twin. Anchored at the end of the URL, so a
#: query string or a link to the page itself cannot sneak in.
DATA_LINK = re.compile(r"\.(csv|xlsx)$", re.IGNORECASE)

#: The first financial year in which :func:`candidate_url` is Lewisham's own
#: naming rather than a guess. Earlier years live under three different media
#: folders with three different spellings, and a constructed URL for one of
#: them would be an invented link, not a fallback.
PATTERN_EARLIEST_FY = 2025

#: The longest run of missing months still treated as a hole in the page. One
#: or two months absent between months that are there is a link the council
#: dropped; a longer run is an era the page does not cover, and filling it
#: would be a speculative request a month for as long as the run lasts.
MAX_GAP = 2


def candidate_url(month: str) -> str:
    """The URL Lewisham would give ``month`` under its current naming.

    ``2026-07`` becomes ``.../spending-over-250/26-27/jul2026paymentsover250.csv``:
    the folder is the financial year in two-digit form, and the file name runs
    the short month, the calendar year and the rest together with no separator.
    """
    year, number = month.split("-")
    start = fy_of_month(month)
    folder = f"{start % 100:02d}-{(start + 1) % 100:02d}"
    name = f"{month_name(int(number), short=True)}{year}paymentsover250.csv"
    return f"{MEDIA_ROOT}/{folder}/{name}"


def _basename(url: str) -> str:
    return urlsplit(url).path.rsplit("/", 1)[-1]


def holes(published: list[str]) -> list[str]:
    """Months missing between two months that are there, in short runs only.

    ``["2026-04", "2026-06", "2026-07"]`` gives ``["2026-05"]``. A ten month
    jump gives nothing: the page ends one era and starts another there, and
    the months in between were never published in the shape we could build.
    """
    out: list[str] = []
    for first, second in zip(published, published[1:], strict=False):
        missing = months_between(shift_month(first, 1), shift_month(second, -1))
        if 0 < len(missing) <= MAX_GAP:
            out.extend(missing)
    return out


class Lewisham(Source):
    slug = "lewisham"
    name = "Lewisham"
    threshold = "£250"
    access = "scrape"
    landing_page = (
        "https://lewisham.gov.uk/mayorandcouncil/aboutthecouncil/finances"
        "/council-spending-over-250"
    )

    def scrape(self, client: httpx.Client) -> dict[str, str]:
        """``{period: url}`` for every dated CSV or XLSX on the landing page.

        The label is read before the URL because it is the one part of a
        Lewisham link that is written by a person: "March 2025 payments over
        £250 (csv)" is unambiguous where mar-2025-paymentsover250.csv,
        mar2026paymentsover_250.csv and lewishamover250oct.csv are three
        different puzzles. A link that neither spells is counted and dropped.
        """
        response = request_with_retries(client, "GET", self.landing_page)
        found: dict[str, str] = {}
        undated = 0
        for url, text in extract_links(
            response.text, self.landing_page, pattern=DATA_LINK
        ):
            period = parse_period(text) or parse_period(_basename(url))
            if not period:
                undated += 1
                log.debug("lewisham: no month in %r for %s", text, url)
                continue
            found.setdefault(period, url)
        if undated:
            log.warning(
                "lewisham: skipped %d data link(s) with no month in the label "
                "or the file name",
                undated,
            )
        return found

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """The months the page lists, plus the short holes it has left in them.

        A month after the newest link is not a hole, it is a month the council
        has not published yet, and asking for it on every run would be a 404 a
        month for nothing. A month before FY 2025-26 is not a hole either: the
        pattern is not the naming those years used.
        """
        published = self.scrape(client)
        periods = dict(published)
        for month in holes(sorted(published)):
            if fy_of_month(month) < PATTERN_EARLIEST_FY:
                continue
            periods[month] = candidate_url(month)
            log.debug(
                "lewisham: %s is missing from the page, trying the pattern", month
            )
        files = []
        for period in sorted(periods):
            if not in_range(period, since, until):
                continue
            url = periods[period]
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=url,
                    filename=_basename(url),
                    format=format_from_name(url),
                    title=f"Lewisham payments over £250, {period}",
                )
            )
        return files
