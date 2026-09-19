"""Islington: one quarterly CSV per SharePoint media link, dated from its label.

The directory is predictable and useless. Files live under
``/~/media/sharepoint-lists/public-records/finance/financialmanagement/
expenditure/<8 digits>/``, but those eight digits are the financial year the
file was *published* in, not the one it covers: December 2019 to February 2020
sits in ``20202021`` because it went up in June 2020. The slug is free text and
has been written five different ways, from
``20200603expenditurefordecemberthroughfebruary2020.csv`` to
``april-through-to-june-26-expenditure-report.csv``.

So the period is read out of the month range in the link label, and the file is
filed under the financial-year quarter its **last** month falls in. That rule
survives Islington's own drift: its quarters ran March-May, June-August,
September-November and December-February until 2023, one month ahead of the
financial-year quarters, and the end month puts each of those in the quarter
the council itself files it under. "March 2023 through to June 2023" is four
months and lands in Q1 2023-24, which is where Islington puts it too.

The label also carries a "Last updated Aug 05, 2026" stamp. That month is cut
off before any parsing, or every file would be dated to the day it was posted.
"""

from __future__ import annotations

import logging
import re

import httpx

from ..http import request_with_retries
from ..models import RemoteFile
from .base import (
    Source,
    extract_links,
    filter_files,
    fy_label,
    fy_quarter_of_month,
    fy_quarter_period,
    month_span,
)

logger = logging.getLogger(__name__)

#: The expenditure media folder, one directory per published financial year.
LINK_PATTERN = r"/finance/financialmanagement/expenditure/\d{8}/[^/]+\.csv$"

#: Everything from "Last updated" onwards is a posting date, not a period.
_LAST_UPDATED = re.compile(r"\blast\s+updated\b", re.IGNORECASE)


def end_month(label: str) -> str | None:
    """The last month a label names, as ``YYYY-MM``, or None.

    "April to June 2026" and "December 21 through February 22" both give their
    closing month. This is the one place a borough wants half of
    :func:`month_span`: Islington files a report under the quarter its **last**
    month falls in, so the opening month of the span is read only to make sense
    of the closing one ("December through February 2020" is December 2019).
    """
    span = month_span(_LAST_UPDATED.split(label)[0])
    return span[1] if span else None


def label_text(url: str, label: str) -> str:
    """The label, with the slug as a fallback once its hyphens are spaces.

    Two files on the page carry no year in the slug at all
    (``expenditure-report-for-july-to-september.csv``) and several older ones
    are unspaced runs of letters, so the label leads. The slug rescues the case
    where a page rebuild drops the text.
    """
    if end_month(label) is not None:
        return label
    slug = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return re.sub(r"[^A-Za-z0-9]+", " ", slug)


class Islington(Source):
    slug = "islington"
    name = "Islington"
    # Islington states £500 and does not apply it: the April-June 2026 file
    # has rows down to £0.01. Stated as nominal so nobody downstream treats
    # the threshold as a guarantee about what is in the rows.
    threshold = "£500 (nominal)"
    access = "scrape"
    landing_page = (
        "https://www.islington.gov.uk/about-the-council/information-governance/"
        "freedom-of-information/publication-scheme/"
        "what-we-spend-and-how-we-spend-it/council-spending"
    )
    quarters = "financial"

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Every expenditure CSV linked from the landing page."""
        response = request_with_retries(client, "GET", self.landing_page)
        files: list[RemoteFile] = []
        undated = 0
        for url, label in extract_links(
            response.text, self.landing_page, pattern=LINK_PATTERN
        ):
            last = end_month(label_text(url, label))
            if last is None:
                undated += 1
                logger.warning(
                    "islington: no month range in %r (%s), link skipped", label, url
                )
                continue
            start_year, number = fy_quarter_of_month(last)
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=fy_quarter_period(start_year, number),
                    url=url,
                    filename=url.rsplit("/", 1)[-1],
                    format="csv",
                    title=(
                        f"Islington expenditure report, "
                        f"{fy_label(start_year)} Q{number}"
                    ),
                )
            )
        if undated:
            logger.warning(
                "islington: %d CSV link(s) on %s could not be dated and were skipped",
                undated,
                self.landing_page,
            )
        # Sorted, because the page runs newest first and a discovery result
        # that arrives in period order is easier to read in a log and in a test.
        kept = filter_files(files, since, until, quarters=self.quarters)
        return sorted(kept, key=lambda f: (f.period, f.filename))
