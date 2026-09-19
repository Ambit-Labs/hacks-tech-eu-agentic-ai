"""Brent: one DataPress package, one CSV per quarter, twice renumbered.

Everything is in package ``vq756``, so there is nothing to search for. The work
is the period, because Brent has published quarters on two different cycles.
Until 2024 the quarters ran March to May, June to August, September to
November, December to February: three-month files that are neither financial
nor calendar quarters. Then "Dec 2024 - Mar 2025" ran four months to close the
gap, and from April 2025 the files line up with the financial year, Q1 being
April to June.

So a file only gets a ``YYYY-Qn`` period when its span really is a financial
quarter. Everything else is the range it covers, ``2020-03_2020-05`` for "Mar
2020 - May 2020" and ``2024-12_2025-03`` for the four-month file, so a window
inside the span still reaches the file. Both spellings sort chronologically
next to each other because the cycle changed at a financial year boundary:
``2024-12_2025-03`` then ``2025-Q1``.

The period is read from the resource name, never from the URL. Brent's
filenames drift ("Transparency 24 June - 24 August.csv" for the June to August
2024 quarter), while the names on the dataset have said "<Mon> <YYYY> - <Mon>
<YYYY>" for six years. That drift is also why two-digit years are refused
here: the ``24`` in that filename is as likely a day as a year.

Row 1 of every file is a title banner and the header is row 2. That is a
problem for whatever parses these, not for this, which keeps the bytes.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import httpx

from ..models import RemoteFile, format_from_name
from .base import (
    Source,
    datapress_resources,
    fy_quarter_of_span,
    month_span,
    range_period,
)

PORTAL = "https://data.brent.gov.uk"
PACKAGE = "vq756"


def span_period(text: str) -> str | None:
    """The period for a name that spells out the months it covers.

    ``YYYY-Qn`` when the span is exactly a financial quarter, otherwise the
    range itself. None when no month is named at all.
    """
    span = month_span(text, short_years=False)
    if span is None:
        return None
    return fy_quarter_of_span(*span) or range_period(*span)


class Brent(Source):
    slug = "brent"
    name = "Brent"
    threshold = "£500"
    access = "datapress-api"
    landing_page = "https://data.brent.gov.uk/dataset/what-we-spend-vq756"
    quarters = "financial"

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """One ``package_show``; the dataset is the whole history.

        The description claims only the current and two prior financial years
        are kept, and the resources say otherwise: the March to May 2020 file
        is still attached. Filtering is left to the caller's ``--since`` so
        that a claim in a description cannot quietly truncate the corpus.
        """
        files = []
        for resource in datapress_resources(client, PORTAL, PACKAGE):
            period = span_period(resource.name)
            if not period:
                continue
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=resource.url,
                    filename=unquote(urlsplit(resource.url).path.rsplit("/", 1)[-1]),
                    format=format_from_name(resource.url),
                    title=resource.name,
                )
            )
        return files
