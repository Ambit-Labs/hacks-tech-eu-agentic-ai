"""Bexley: sixteen years of monthly CSVs on one page, beside the card spend.

One request gets the whole history. What it costs is three kinds of care.

The folder in the URL is the month the file was uploaded, not the month it
covers. ``/sites/default/files/2020-05/January-2019-v1.csv`` is January 2019,
and reading the path as the period would date eleven years of files to May
2020. The period comes from the link label, and from the file's own name only
when the label has none.

The same page publishes purchase card spend, section by section, under a
``<h4>Pcard</h4>`` heading between the year headings. This source is payments
over £500 only, so the card sections are dropped whole. Filtering on the file
name would not do it: the card file for November 2025 is ``november-2025.csv``
and the expenditure file for the same month is ``November-2025-v1.csv``, and
three 2025 card files are named ``Publication_payments_over_<month>.csv``. One
card file escapes the section split anyway, mislinked under a year heading,
and :func:`link_period` says how it is caught.

Before 2019 the files cover quarters, half years and financial years ("April
to September 2014", "November 2010 to March 2011"). Each one takes the range
it covers, ``2014-04_2014-09`` and ``2010-11_2011-03``, which is eight years
of history the first version of this module left on the page because the
period grammar had nowhere to put a half year.

The file itself opens with a title banner row ("July 2026 £500 Spend Report")
before the header, has a trailing empty column and a cp1252 pound sign. None
of that touches the download; it is here for the parsing stage.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote, urlsplit

import httpx

from ..http import request_with_retries
from ..models import RemoteFile
from .base import (
    Source,
    extract_links,
    in_range,
    month_span,
    parse_period,
    range_period,
)

log = logging.getLogger(__name__)

HOST = "https://www.bexley.gov.uk"

CSV_LINK = re.compile(r"\.csv$", re.IGNORECASE)

#: The page is a flat run of ``<h4>`` headings, each followed by its own list
#: of links: a year heading introduces that year's expenditure files, a card
#: heading introduces the purchase card files.
_HEADING = re.compile(r"<h4\b[^>]*>(?P<title>.*?)</h4>", re.IGNORECASE | re.DOTALL)

#: "Pcard", "PCard", "P-Card", "P card". All of them mean purchase card, in a
#: heading and in a file name alike. Matching the file name catches a card
#: link that ends up under a year heading; it is not enough on its own, which
#: is what the section split is for.
_CARD = re.compile(r"p\W?card", re.IGNORECASE)


def expenditure_sections(html: str) -> list[str]:
    """The page's HTML with every purchase card block cut out.

    A section is the markup between one ``<h4>`` and the next, so dropping the
    card sections drops exactly the links that sit under a card heading and
    nothing else.
    """
    headings = list(_HEADING.finditer(html))
    sections = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(html)
        if _CARD.search(heading.group("title")):
            continue
        sections.append(html[heading.end() : end])
    return sections


def link_period(label: str, name: str) -> str | None:
    """The period one link covers, from its label first and its file name second.

    A label naming two months is a range: "October to December (CSV)" carries
    no year and its file name ``October-December-2018.csv`` does, which is why
    both are tried. Without reading the span, that file name would parse as
    December 2018 and a quarter of spending would be filed as a month.

    When the label and the file name both name a span and the two disagree,
    the link is one Bexley has got wrong and neither period can be believed.
    There is one on the page today: "April to June 2017 (CSV)" points at
    ``April-to-December-2018-v1.csv``, which is a purchase card file that the
    section split cannot catch because it is sitting under a year heading. So
    April to June 2017 is missing from this source, which is the truth: the
    council does not currently link it anywhere.
    """
    from_label, from_name = month_span(label), month_span(name)
    if from_label and from_name and from_label != from_name:
        return None
    span = from_label or from_name
    if span:
        return range_period(*span)
    return parse_period(label) or parse_period(name)


class Bexley(Source):
    slug = "bexley"
    name = "Bexley"
    threshold = "£500"
    access = "scrape"
    landing_page = (
        "https://www.bexley.gov.uk/bexley-business-employment/business-services"
        "/contracts-tenders-and-procurement/expenditure-records"
    )

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Every dated CSV under a year heading, newest link winning.

        Sections run newest first, so when a period appears twice (Bexley
        reposts a corrected file as ``-v2``) the first link found is the one
        the council currently shows at the top.
        """
        response = request_with_retries(client, "GET", self.landing_page)
        found: dict[str, str] = {}
        undated = 0
        for section in expenditure_sections(response.text):
            for url, text in extract_links(
                section, self.landing_page, pattern=CSV_LINK
            ):
                name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
                if _CARD.search(name):
                    log.debug("bexley: card file under a year heading: %s", url)
                    continue
                period = link_period(text, name)
                if not period:
                    undated += 1
                    log.debug("bexley: cannot date %r (%s)", text, url)
                    continue
                found.setdefault(period, url)
        if undated:
            log.warning(
                "bexley: skipped %d link(s) whose label and file name name no "
                "period, or disagree about it",
                undated,
            )
        files = []
        for period in sorted(found):
            if not in_range(period, since, until):
                continue
            url = found[period]
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=url,
                    filename=unquote(urlsplit(url).path.rsplit("/", 1)[-1]),
                    format="csv",
                    title=f"Bexley payments over £500, {period}",
                )
            )
        return files
