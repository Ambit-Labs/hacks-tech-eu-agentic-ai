"""Lambeth: quarterly reports since 2015, monthly ones before that, all scraped.

The newest file is tidy (``Over_500_Transparency_Report_2026-27Q1.csv``) and
nothing behind it is. The same report has been named with spaces, with a
URL-encoded pound sign, with a trailing en dash, with the financial year run
together as ``202425``, and with the quarter before the year rather than after
it. Three formats are in the series (CSV now, XLSX for 2020 to 2023, one ODS in
2018) and some older files are still served from ``beta.lambeth.gov.uk``. Every
one of them is taken as published, bytes untouched: these files are cp1252, not
UTF-8, and the pound sign in the header is a single 0xA3 byte that a re-encode
would quietly change.

Periods come from the filename when it spells out a financial year and a
quarter, and otherwise from the label, which has kept one shape throughout:
"Q1 - April to June 2026". The label's quarter number is trusted over its month
names because two of them are wrong ("Q4 - January to April 2024" is January to
March), while the quarter number has never disagreed with the filename.

The 2017 file covering April to December is three quarters in one. It gets the
range its label spells out, ``2017-04_2017-12``, which is only reached once no
single quarter can be read: a label that names one quarter is that quarter even
when its months say otherwise.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote

import httpx

from ..http import request_with_retries
from ..models import RemoteFile, format_from_name
from .base import (
    Source,
    extract_links,
    filter_files,
    fy_label,
    fy_quarter_from_label,
    fy_quarter_period,
    month_span,
    parse_period,
    range_period,
)

logger = logging.getLogger(__name__)

#: Drupal uploads on either host. The formats are the three Lambeth has used.
LINK_PATTERN = r"/sites/default/files/.*\.(csv|xlsx|xls|ods)$"

#: "Q1 - April to June 2026", and the page's one "O4 - January to March 2019"
#: typo. The dash is required: "Q1, 2 and 3 - April to December 2017" covers
#: three quarters and must not be read as Q1. Lambeth writes the separator as
#: a hyphen, an en dash or an em dash depending on the year, so all three are
#: spelled out here by codepoint rather than pasted in.
_LABEL_QUARTER = re.compile(r"^\s*[QO]\s*([1-4])\s*[-–—]", re.IGNORECASE)

#: Anything that claims a quarter at all. A file carrying one of these is
#: quarterly, so the monthly fallback stays switched off for it even when the
#: quarter itself cannot be pinned down.
_ANY_QUARTER = re.compile(r"\b[QO]\s*[1-4]\b", re.IGNORECASE)

_YEAR = re.compile(r"\b(\d{4})\b")


def _fy_of_quarter(quarter: int, year: int) -> int:
    """The financial year a "Q3 ... 2023" label belongs to.

    Q1 to Q3 fall in the calendar year the financial year starts in; Q4 runs
    January to March and falls in the next one, so its label year is one ahead.
    """
    return year if quarter <= 3 else year - 1


def parse_quarter(filename: str, label: str) -> tuple[int, int] | None:
    """``(financial year start, quarter)`` from a filename or label, or None.

    The filename goes through the shared reader, which wants both halves of a
    financial year and so refuses the several ways Lambeth has of writing one
    year. The label keeps its own rule: its quarter number is the reliable
    half, its month names are not, and a label year is the calendar year the
    quarter's months fall in rather than the financial year's first.
    """
    period = fy_quarter_from_label(filename)
    if period is not None:
        start_year, number = period.split("-Q")
        return int(start_year), int(number)
    match = _LABEL_QUARTER.search(label)
    if match:
        years = _YEAR.findall(label)
        if years:
            quarter = int(match.group(1))
            return _fy_of_quarter(quarter, int(years[-1])), quarter
    return None


def parse_period_for(filename: str, label: str) -> str | None:
    """The period for one link: a quarter, else a range, else a month, else None.

    The range branch is what holds the 2017 file covering three quarters at
    once, and it sits below the quarter branch so that a label naming one
    quarter still wins over the months it misspells. The monthly branch is
    only reached by a file that claims no quarter anywhere; without that guard
    a three-quarter file with no months in its label would be dated to
    whichever month the label happened to mention.
    """
    quarter = parse_quarter(filename, label)
    if quarter is not None:
        return fy_quarter_period(*quarter)
    span = month_span(label) or month_span(filename)
    if span and span[0] != span[1]:
        return range_period(*span)
    if _ANY_QUARTER.search(filename) or _ANY_QUARTER.search(label):
        return None
    return parse_period(label) or parse_period(filename)


class Lambeth(Source):
    slug = "lambeth"
    name = "Lambeth"
    threshold = "£500"
    access = "scrape"
    landing_page = (
        "https://www.lambeth.gov.uk/about-council/transparency-open-data/"
        "financial-information/expenditure-over-ps500"
    )
    quarters = "financial"

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Every spending file linked from the landing page, back to 2010."""
        response = request_with_retries(client, "GET", self.landing_page)
        files: list[RemoteFile] = []
        undated = 0
        for url, label in extract_links(
            response.text, self.landing_page, pattern=LINK_PATTERN
        ):
            # Percent-escapes are decoded for parsing and for the saved name:
            # the pound sign in these filenames arrives as %C2%A3 and would
            # otherwise be kept on disk as the literal escape.
            filename = unquote(url.rsplit("/", 1)[-1])
            period = parse_period_for(filename, label)
            if period is None:
                undated += 1
                logger.warning(
                    "lambeth: no single period in %r (%s), link skipped", label, url
                )
                continue
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=url,
                    filename=filename,
                    format=format_from_name(filename),
                    title=f"Lambeth payments over £500, {_title_period(period)}",
                )
            )
        if undated:
            logger.warning(
                "lambeth: %d link(s) on %s could not be dated and were skipped",
                undated,
                self.landing_page,
            )
        # Sorted, because the page runs newest first and a discovery result
        # that arrives in period order is easier to read in a log and in a test.
        kept = filter_files(files, since, until, quarters=self.quarters)
        return sorted(kept, key=lambda f: (f.period, f.filename))


def _title_period(period: str) -> str:
    """``2026-Q1`` reads as ``2026-27 Q1``, a range as "first to last"."""
    if "_" in period:
        return " to ".join(period.split("_"))
    if "-Q" not in period:
        return period
    start_year, number = period.split("-Q")
    return f"{fy_label(int(start_year))} Q{number}"
