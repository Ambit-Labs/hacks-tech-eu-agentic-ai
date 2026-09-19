"""Barnet: one DataPress package per financial year, one CSV per month inside it.

Barnet has no threshold. It publishes every payment down to the smallest one,
so its monthly files are three to four megabytes where a £500-threshold borough
publishes a few hundred kilobytes. Only payments to individuals (foster and
adult carers) are held back.

Two things make discovery more than a package id. First, the series is split
across fourteen packages, one per financial year, and a hard-coded list of ids
is a list that goes stale next April. Second, the portal's ``package_search``
ignores relevance and sorts by ``metadata_modified``, so searching for
"expenditure" returns the whole catalogue in the wrong order. The answer to
both is to pull the catalogue once with ``rows=1000`` and match package titles
against "Expenditure Reporting YYYY/YY" here, with :data:`KNOWN_PACKAGES` as
the floor when the catalogue call fails.

The bytes are Windows-1252, not UTF-8: a £ sign arrives as ``0xA3`` and a
supplier name can carry a 0x92 apostrophe. Nothing here re-encodes them. The
file on disk is the file Barnet published, and whatever reads it later gets to
find out from this docstring which codec to open it with.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

import httpx

from ..http import FetchError, request_with_retries
from ..models import RemoteFile, format_from_name
from .base import (
    Source,
    datapress_resources,
    fy_label,
    fy_months,
    month_period,
    parse_month_name,
    range_period,
)

PORTAL = "https://open.barnet.gov.uk"

#: Package ids seen on 2026-09-19, keyed by the first year of the financial
#: year. Not the source of truth: :meth:`Barnet.packages` reads the catalogue
#: every run and this map only fills in when that call fails, so a portal
#: outage costs the newest year rather than all fourteen.
KNOWN_PACKAGES = {
    2013: "20q1e",
    2014: "em7ge",
    2015: "2o6n2",
    2016: "vq87v",
    2017: "2lgxv",
    2018: "emjme",
    2019: "exole",
    2020: "2z8zk",
    2021: "2opln",
    2022: "e690n",
    2023: "2331d",
    2024: "2rx6m",
    2025: "e6p4n",
    2026: "2ywz8",
}

#: The title of a spending package, and nothing else. Barnet also publishes
#: "2025-26 Agency Expenditure", "Comensura Expenditure" and "Barnet Schools
#: income and expenditure", which are different datasets with different columns.
PACKAGE_TITLE = re.compile(r"^Expenditure Reporting (\d{4})/(\d{2})$")

#: A month name followed by a four-digit year, anywhere in a resource name.
MONTH_YEAR = re.compile(r"([A-Za-z]{3,9})[\s_-]+((?:19|20)\d{2})")

#: The whole catalogue in one request. Barnet has 397 packages, so this is the
#: cheap end of "enumerate everything and filter here".
CATALOGUE_ROWS = 1000


def resource_period(name: str) -> str | None:
    """``"Expenditure Report July 2026.csv"`` → ``2026-07``. None when undated.

    The first three letters decide when the whole word does not, because Barnet
    shipped January 2023 as ``Expenditure Report Janurary 2023.csv`` and a typo
    is not a reason to drop a month. ``Report 2026`` still parses as nothing:
    ``rep`` is not a month either way.
    """
    for word, year in MONTH_YEAR.findall(name):
        month = parse_month_name(word) or parse_month_name(word[:3])
        if month:
            return month_period(int(year), month)
    return None


class Barnet(Source):
    slug = "barnet"
    name = "Barnet"
    threshold = "none"
    access = "datapress-api"
    landing_page = (
        "https://open.barnet.gov.uk/dataset/expenditure-reporting-202627-2ywz8"
    )

    def packages(self, client: httpx.Client) -> dict[int, str]:
        """``{financial year start: package id}``, catalogue first, map second.

        The catalogue is authoritative when it answers, so next April's package
        is picked up without an edit here. A failure is not fatal: the known
        ids are still thirteen years of history, and losing the newest year
        loudly on the next run beats losing all of them quietly now.
        """
        found = dict(KNOWN_PACKAGES)
        try:
            response = request_with_retries(
                client,
                "GET",
                f"{PORTAL}/api/action/package_search",
                params={"rows": str(CATALOGUE_ROWS)},
            )
            body = response.json()
        except (FetchError, httpx.HTTPError, ValueError):
            return found
        result = body.get("result") or {}
        # DataPress nests the page inside result.result; plain CKAN calls it
        # result.results. Accept either rather than pin to today's portal.
        rows = result.get("result") or result.get("results") or []
        for package in rows:
            match = PACKAGE_TITLE.match((package.get("title") or "").strip())
            if match:
                identifier = package.get("id") or package.get("name")
                if identifier:
                    found[int(match.group(1))] = str(identifier)
        return found

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Every month in every financial year that overlaps ``[since, until]``.

        Narrowing by year first is what keeps an incremental run to two
        requests: the catalogue, then the one package that holds this month.
        """
        files: list[RemoteFile] = []
        for start_year, package_id in sorted(self.packages(client).items()):
            months = fy_months(start_year)
            if since and months[-1] < since:
                continue
            if until and months[0] > until:
                continue
            files.extend(self._year_files(client, start_year, package_id))
        return files

    def _year_files(
        self, client: httpx.Client, start_year: int, package_id: str
    ) -> list[RemoteFile]:
        """One financial year's package, turned into monthly files.

        A package that cannot be read costs its own year and not the borough:
        a stale id in :data:`KNOWN_PACKAGES` would otherwise take the other
        thirteen years down with it.
        """
        try:
            resources = datapress_resources(client, PORTAL, package_id)
        except (FetchError, httpx.HTTPError, RuntimeError):
            return []

        dated = [(resource_period(r.name), r) for r in resources]
        monthly = [(period, r) for period, r in dated if period]
        # An undated resource sitting next to monthly ones is one of the two
        # extras Barnet keeps there: a cumulative roll-up of the same twelve
        # months ("Expenditure reporting 2014-15"), or the below-threshold
        # remainder from the years it still split the two ("1415 Expenditure
        # below 500 & 250"). Both would double-count, so both are left alone.
        if not monthly:
            # 2013/14 is a single file for the whole year, so there is no
            # month to read in it. It takes the twelve months of the financial
            # year as a range, which is the file's real coverage. This branch
            # is only reached for a package with no monthly file at all, so a
            # roll-up sitting beside monthly files is still left alone.
            months = fy_months(start_year)
            whole_year = range_period(months[0], months[-1])
            monthly = [(whole_year, r) for _, r in dated]
        return [
            RemoteFile(
                borough=self.slug,
                period=period,
                url=resource.url,
                filename=unquote(urlsplit(resource.url).path.rsplit("/", 1)[-1]),
                format=format_from_name(resource.url),
                title=f"{resource.name} (FY {fy_label(start_year)})",
            )
            for period, resource in monthly
        ]
