"""Haringey: one CSV per financial-year quarter, scraped from the landing page.

Every quarter is published twice, as a CSV and as the same numbers typeset into
a PDF. Only the CSV is taken.

Two traps live in the URL. The ``/sites/default/files/YYYY-MM/`` segment is the
month the file was uploaded, not the months it reports: Q3 and Q4 of 2025-26
both went up in September 2026, so reading a period out of the path would date
half the series to 2026-09. And the filename has been renamed three times
(``council_expenditure_q1_23-24``, then ``lbh-expenditure-q3-2024-25``, then
``lbh-expenditure-q1-2025``), the newest style naming a financial year by its
first year alone. The link label has said "quarter N, financial year YYYY/YY"
throughout, so the period comes from there and the filename is only a fallback
for the labels that spell both years out.

Only three financial years are kept on the page, so discovery here is a window
on the present, not the archive. Nothing older is reachable without the
Wayback Machine.
"""

from __future__ import annotations

import logging

import httpx

from ..http import request_with_retries
from ..models import RemoteFile
from .base import (
    Source,
    extract_links,
    filter_files,
    fy_label,
    fy_quarter_from_label,
    fy_quarter_period,
)

logger = logging.getLogger(__name__)

#: Every spending file on the page is a Drupal upload. The PDF twin of each
#: quarter is left alone.
LINK_PATTERN = r"/sites/default/files/.*\.csv$"


def parse_quarter(label: str, filename: str) -> tuple[int, int] | None:
    """``(financial year start, quarter)`` for one link, or None.

    The label is tried first because it is the only place both halves of the
    financial year are always written out: "quarter 4, financial year 2025/26".
    The filename answers only when it spells both halves too
    (``council_expenditure_q1_23-24``, ``lbh-expenditure-q4-2024-25``), which
    is the shared helper's own rule and exactly the rule Haringey needs.
    ``lbh-expenditure-q1-2025`` names one year, its label calls that quarter
    2025/26, and a slug with a single year is a coin toss best left to the
    label.
    """
    period = fy_quarter_from_label(label) or fy_quarter_from_label(filename)
    if period is None:
        return None
    start_year, number = period.split("-Q")
    return int(start_year), int(number)


class Haringey(Source):
    slug = "haringey"
    name = "Haringey"
    threshold = "not stated"
    access = "scrape"
    landing_page = (
        "https://haringey.gov.uk/business/selling-to-council/council-expenditure"
    )
    quarters = "financial"

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Every CSV on the landing page, dated from its own label."""
        response = request_with_retries(client, "GET", self.landing_page)
        found: dict[str, RemoteFile] = {}
        undated = 0
        for url, label in extract_links(
            response.text, self.landing_page, pattern=LINK_PATTERN
        ):
            filename = url.rsplit("/", 1)[-1]
            quarter = parse_quarter(label, filename)
            if quarter is None:
                undated += 1
                logger.warning(
                    "haringey: no quarter in %r (%s), link skipped", label, url
                )
                continue
            start_year, number = quarter
            period = fy_quarter_period(start_year, number)
            if period in found:
                # One quarter, one file. A second link for a period that
                # already has one is a re-upload the page never removed, and
                # downloading both would put two files for one quarter on disk.
                logger.warning(
                    "haringey: %s already taken from %s, ignoring %s",
                    period,
                    found[period].url,
                    url,
                )
                continue
            found[period] = RemoteFile(
                borough=self.slug,
                period=period,
                url=url,
                filename=filename,
                format="csv",
                title=(
                    f"Haringey council expenditure, {fy_label(start_year)} Q{number}"
                ),
            )
        if undated:
            logger.warning(
                "haringey: %d CSV link(s) on %s could not be dated and were skipped",
                undated,
                self.landing_page,
            )
        # Sorted, because the page runs newest first and a discovery result
        # that arrives in period order is easier to read in a log and in a test.
        kept = filter_files(found.values(), since, until, quarters=self.quarters)
        return sorted(kept, key=lambda f: (f.period, f.filename))
