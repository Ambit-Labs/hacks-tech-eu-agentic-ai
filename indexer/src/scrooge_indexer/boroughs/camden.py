"""Camden: Socrata, one CSV per month carved out of a single 416,000-row dataset.

Camden publishes no files at all. There is one dataset on its Socrata portal
and everything else is a query, so "discovery" here means asking the API which
months exist rather than scraping a page of links. The month split is ours: a
month is the unit every other borough publishes in, and it is what makes a
Camden file resumable and comparable with the rest of the corpus.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

import httpx

from ..http import FetchResult, part_path, request_with_retries
from ..models import RemoteFile
from .base import Source, current_month, in_range, shift_month

DOMAIN = "https://opendata.camden.gov.uk"
DATASET = "3ixw-qvb8"

#: Socrata's per-request row cap for this endpoint. Camden's busiest month is
#: 6,679 rows (measured 2026-09-19 across all 84 months), so paging is dead
#: code today and kept anyway: the dataset grows, and the failure mode of a
#: silently truncated month is a file that looks complete.
PAGE_LIMIT = 50000

#: Months still being written to. The current month is obviously unfinished;
#: the previous one is included because Camden's feed keeps receiving late
#: postings for a few weeks after month end.
MUTABLE_MONTHS = 2


def month_query_url(month: str) -> str:
    """The CSV URL for one calendar month.

    The whole query lives in the URL rather than in ``RemoteFile.params``
    because the manifest is keyed on period plus URL, and every month would
    otherwise share one URL and one manifest entry. ``$order`` is on
    ``unique_identifier`` so that paging is stable and two runs of the same
    month produce byte-identical files.
    """
    query = urlencode(
        {
            "$where": (
                f"payment_date >= '{month}-01' "
                f"AND payment_date < '{shift_month(month, 1)}-01'"
            ),
            "$order": "unique_identifier",
            "$limit": str(PAGE_LIMIT),
        }
    )
    return f"{DOMAIN}/resource/{DATASET}.csv?{query}"


class Camden(Source):
    slug = "camden"
    name = "Camden"
    threshold = "£500"
    access = "socrata-api"
    landing_page = "https://opendata.camden.gov.uk/Finance/Camden-Council-Spend-Over-500-GBP/3ixw-qvb8"

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """One SoQL aggregate tells us every month that has data.

        Cheaper and more honest than generating candidate months: Camden's
        history starts in September 2019 and a gap in the middle would show up
        here as a missing month rather than as a mystery empty file.
        """
        response = request_with_retries(
            client,
            "GET",
            f"{DOMAIN}/resource/{DATASET}.json",
            params={
                "$select": "date_trunc_ym(payment_date) AS m, count(*) AS n",
                "$group": "m",
                "$order": "m",
                "$limit": "1000",
            },
        )
        newest_mutable = shift_month(current_month(), -(MUTABLE_MONTHS - 1))
        files = []
        for row in response.json():
            raw = row.get("m") or ""
            month = raw[:7]
            if len(month) != 7 or not raw:
                continue
            if not in_range(month, since, until):
                continue
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=month,
                    url=month_query_url(month),
                    filename="camden-payments.csv",
                    format="csv",
                    title=f"Camden spend over £500, {month}",
                    mutable=month >= newest_mutable,
                )
            )
        return files

    def fetch(
        self,
        client: httpx.Client,
        remote: RemoteFile,
        dest: Path,
        *,
        on_bytes: Callable[[int], None] | None = None,
        conditional: dict[str, str] | None = None,
    ) -> FetchResult:
        """Fetch one month, following ``$offset`` pages into a single CSV.

        Each page arrives with its own header row, so the first page's header
        is kept and later ones are dropped. Written through a ``.part`` file
        like every other source, because a half-paged month must never look
        like a finished one.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = part_path(dest)
        digest = hashlib.sha256()
        written = 0
        offset = 0
        first_response: httpx.Response | None = None
        try:
            with open(part, "wb") as handle:
                while True:
                    url = (
                        remote.url if offset == 0 else f"{remote.url}&$offset={offset}"
                    )
                    response = request_with_retries(
                        client,
                        "GET",
                        url,
                        headers=conditional if offset == 0 else None,
                    )
                    if response.status_code == 304:
                        part.unlink(missing_ok=True)
                        return FetchResult(bytes=0, status="unchanged")
                    first_response = first_response or response
                    lines = response.content.splitlines(keepends=True)
                    if not lines:
                        break
                    rows = lines[1:] if offset else lines
                    chunk = b"".join(rows)
                    handle.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if on_bytes:
                        on_bytes(len(chunk))
                    if len(lines) - 1 < PAGE_LIMIT:
                        break
                    offset += len(lines) - 1
            os.replace(part, dest)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        headers = first_response.headers if first_response is not None else {}
        return FetchResult(
            bytes=written,
            sha256=digest.hexdigest(),
            content_type=headers.get("Content-Type"),
            etag=headers.get("ETag"),
            last_modified=headers.get("Last-Modified"),
        )
