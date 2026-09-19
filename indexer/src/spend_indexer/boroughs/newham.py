"""Newham: monthly CSVs behind opaque Jadu download ids.

Every file is ``/downloads/file/{id}/{slug}`` where the id was allocated at
upload time and has no relation to the month, so there is nothing to
construct: the landing page is the only map from a month to an id. It is a
cheap map, mind. One response holds the whole series, April 2018 to last
month, which is the longest unbroken monthly run in this corpus.

The label is the only trustworthy source of the month. One slug lies outright
(``/downloads/file/376/paymentstosuppliersjuly2018`` is the June 2018 file),
one carries no year at all (``paymentstosuppliersfebruary-csv-``), and the
2018 and 2019 slugs carry no format marker either, while the label always
spells both: "Payments to suppliers June 2018 (CSV)". So the period and the
format both come from the text, and a link the text cannot date is skipped
rather than guessed at.

Two other things on that page are deliberately not in this source. The staff
purchase card files are a different dataset. The Excel twin of every month is
the same numbers in a format the CSV already gives us, and taking both would
double every period. February 2019 is why the links are read undeduplicated:
the council points its CSV link and its Excel link at the same download id,
and dropping the second anchor for a URL already seen would drop the CSV label
and lose the month. Deduplicating by period below is what keeps the twin out.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

import httpx

from ..http import request_with_retries
from ..models import RemoteFile
from .base import Source, extract_links, in_range, parse_period

log = logging.getLogger(__name__)

HOST = "https://www.newham.gov.uk"

#: Jadu serves every attachment from this path, so the pattern is the whole
#: filter the URL can offer. Everything else is decided on the label.
DOWNLOAD_LINK = re.compile(r"/downloads/file/\d+/")

#: The supplier payments series, as opposed to the staff purchase card files,
#: the contract register and the invoice payment performance PDF.
SUPPLIER_LABEL = re.compile(r"payments?\s+to\s+suppliers", re.IGNORECASE)

#: The format marker the council puts at the end of every label.
CSV_LABEL = re.compile(r"\(\s*csv\s*\)", re.IGNORECASE)

#: Zero-width characters are sprinkled through the labels by whatever pasted
#: them in. They are not whitespace, so they survive the usual collapse and
#: glue themselves into month names: "January 201<zwsp>9" parses as nothing at
#: all until they are removed.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"))


def clean_label(text: str) -> str:
    """A link label with the invisible characters out and the spaces collapsed."""
    return " ".join(text.translate(_INVISIBLE).split())


class Newham(Source):
    slug = "newham"
    name = "Newham"
    threshold = "£250"
    access = "scrape"
    landing_page = "https://www.newham.gov.uk/council/council-spending"

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """One page, ninety-odd months, everything decided on the label.

        The first link wins a period, and the page runs newest first, so a
        month the council has uploaded twice resolves to its most recent id.
        ``dedupe=False`` because the label is what decides here and two anchors
        on one id carry two different labels.
        """
        response = request_with_retries(client, "GET", self.landing_page)
        found: dict[str, str] = {}
        undated = 0
        for url, text in extract_links(
            response.text, self.landing_page, pattern=DOWNLOAD_LINK, dedupe=False
        ):
            label = clean_label(text)
            if not SUPPLIER_LABEL.search(label) or not CSV_LABEL.search(label):
                continue
            period = parse_period(label)
            if not period:
                undated += 1
                log.debug("newham: no month in %r for %s", label, url)
                continue
            found.setdefault(period, url)
        if undated:
            log.warning(
                "newham: skipped %d supplier payment link(s) with no month in "
                "the label",
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
                    filename=urlsplit(url).path.rsplit("/", 1)[-1],
                    format="csv",
                    title=f"Newham payments to suppliers over £250, {period}",
                )
            )
        return files
