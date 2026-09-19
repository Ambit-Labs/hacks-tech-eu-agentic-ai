"""MHCLG: the national returns that carry all 33 boroughs in one file.

The only source here that is not a council. MHCLG collects a Revenue Account
(RA) budget return from every English authority every year, and the boroughs
are simply rows in it (``Class = LB``, ONS codes ``E09000001`` to
``E09000033``, plus an ``E09`` London aggregate row that double counts if you
forget to drop it). That makes one download worth 33, and it makes the budget
side of this project tractable in a way the spend side never was.

The reason this module is long is that MHCLG spreads the answer over five
collections and a live-tables page, so a family at a time:

* **RA budget** per authority, one release per year back to 2010-11. There is
  no multi-year budget series anywhere, so a time series means stacking these.
* **Revenue Outturn** multi-year CSV, which is what the budget is compared
  against. The RA asset IDs are the RO column names, so the join is exact.
* **QRU**, the quarterly in-year update, plus the mapping document that says
  which RA line feeds which QRU line.
* **Capital**, estimates (CER) forward and outturn (COR) back, plus the one
  capital file published as CSV.
* **Council tax** levels per year, and Core Spending Power from the settlement,
  which is the only central forward view past the budget year.
* **Section 251**, education and children's services planned spend.

Nothing here is a fixed asset URL. Every file is resolved at run time through
the content API, because the media hash in an ``assets.publishing.service.gov.uk``
link changes whenever a table is corrected. Only page paths are hard-coded, and
the per-year families read a collection, so the 2027-28 release appears on its
own.

Attachments are filtered by family before anything is fetched. A release page
carries statistical-release PDFs, blank forms and technical notes next to the
data, and taking the lot would be tens of megabytes of things nobody asked for.
When a filter matches nothing the release is logged rather than skipped
silently, because that is what a renamed file looks like.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable

import httpx

from ..http import FetchError
from ..models import RemoteFile, format_from_name
from . import _govuk
from .base import Source, fy_period, in_range, parse_fy_span

log = logging.getLogger(__name__)

REVENUE_COLLECTION = (
    "/government/collections/local-authority-revenue-expenditure-and-financing"
)
CAPITAL_COLLECTION = (
    "/government/collections/local-authority-capital-expenditure-receipts-and-financing"
)
COUNCIL_TAX_COLLECTION = "/government/collections/council-tax-statistics"
SECTION_251_COLLECTION = "/government/collections/section-251-materials"

#: The settlement is published one round at a time and every round gets its own
#: collection slug, so this constant moves when the next multi-year settlement
#: lands. The Core Spending Power publication inside it is found by title, so
#: only the collection path is ever edited.
SETTLEMENT_COLLECTION = (
    "/government/collections/"
    "final-local-government-finance-settlement-england-2026-2027-to-2028-2029"
)

REVENUE_OUTTURN_SERIES = (
    "/government/statistics/local-authority-revenue-expenditure-and-financing"
    "-england-revenue-outturn-multi-year-data-set"
)
QRU_FORMS = "/government/publications/quarterly-revenue-outturn"
LIVE_TABLES = (
    "/government/statistical-data-sets/live-tables-on-local-government-finance"
)
CAPITAL_SERIES = (
    "/government/statistics/local-authority-capital-expenditure-and-receipts"
    "-in-england-final-outturn-time-series"
)

#: Financial years the Revenue Outturn time series covers, verified 2026-09-19:
#: outturn 2017-18 to 2025-26. Unlike the capital series, neither the release
#: nor the attachment title states the span, and the file is 24 MB, so reading
#: it to find out would cost more than it is worth. When MHCLG adds a year the
#: file is re-downloaded anyway (it is mutable); bump this so the period on
#: disk stops understating what is in it.
REVENUE_SERIES_SPAN = (2017, 2026)

#: Same idea for capital, used only if the attachment title stops naming the
#: span. Today it says "in the financial years 2018-19 to 2024-25", so this is
#: a fallback and not the usual path.
CAPITAL_SERIES_SPAN = (2018, 2025)

#: A per-LA revenue budget return. Filename from 2016-17 onward, attachment
#: title before that, when the files were called ``1934015.xls``. ``SG`` is the
#: specific and special grants return, published alongside RA every year, and
#: ``LCTS`` is the local council tax support supplement that came with it for a
#: few years.
RA_FILES = re.compile(
    r"^(?:RA|SG)[_.]|revenue account \(ra\) budget"
    r"|specific and special revenue grants",
    re.IGNORECASE,
)
CER_FILES = re.compile(r"^CER[_.]|capital estimates return", re.IGNORECASE)
COR_FILES = re.compile(r"^COR[_.\d]|capital outturn return", re.IGNORECASE)
QRU_LIVE_TABLE = re.compile(r"^QRU\d", re.IGNORECASE)

#: The council tax tables that hold one row per authority. The table number
#: moved three times in fifteen years (Table 6, then 7, then 10) but the title
#: has always said which table it is, so match the words and not the number.
COUNCIL_TAX_TABLES = re.compile(
    r"local authority level data|individual local authorities|all authorities",
    re.IGNORECASE,
)

#: Section 251 is a DfE collection, and its per-LA planned expenditure file is
#: the multi-year one. The rest of that release is blank forms and XML
#: generators.
SECTION_251_FILES = re.compile(
    r"^Local_authority_planned_expenditure_on_education", re.IGNORECASE
)

CORE_SPENDING_POWER = re.compile(r"core spending power table", re.IGNORECASE)

#: A release page for one financial year of per-authority data. The outturn
#: releases share the slug, so the title is what tells them apart.
PER_LA_RELEASE = re.compile(r"individual-local-authority-data(?:--\d+)?$")
CER_RELEASE = re.compile(r"individual-local-authority-data-forecast$")
COUNCIL_TAX_RELEASE = re.compile(
    r"/council-tax-levels-set-by-local-authorities-in-england-\d{4}-to-\d{4}"
)


def _named(token: str, filename: str) -> str:
    """``("ra", "SG_2026-27.ods")`` → ``ra-SG_2026-27.ods``.

    A family prefix so ``ls data/budgets/mhclg`` reads as families rather than
    as MHCLG's internal form names, and so ``COR_A1.ods`` (which carries no
    year of its own) cannot be confused with the next year's. Filenames that
    already start with their family keep it: ``RA_2026-27_data_Part_1.ods``
    needs no help.
    """
    return (
        filename
        if filename.lower().startswith(token.lower())
        else f"{token}-{filename}"
    )


class MHCLG(Source):
    slug = "mhclg"
    name = "MHCLG local government finance"
    kind = "budget"
    threshold = "n/a"
    access = "govuk-content-api"
    landing_page = "https://www.gov.uk/government/collections/local-authority-revenue-expenditure-and-financing"

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Ten families, each allowed to fail on its own.

        One statistics page being moved should cost that family, not the other
        nine and not the 33 boroughs' budgets with them, so every family is
        wrapped. The failure is logged with the path that caused it, which is
        the only thing a person needs to go and look.
        """
        families: tuple[Callable[..., list[RemoteFile]], ...] = (
            self._revenue_account,
            self._revenue_outturn_series,
            self._qru_forms,
            self._qru_live_table,
            self._capital_estimates,
            self._capital_outturn,
            self._capital_series,
            self._council_tax,
            self._core_spending_power,
            self._section_251,
        )
        found: list[RemoteFile] = []
        for family in families:
            try:
                found.extend(family(client, since, until))
            except (FetchError, httpx.HTTPError, KeyError, ValueError) as exc:
                log.warning(
                    "mhclg: %s failed, skipping that family: %s",
                    family.__name__.lstrip("_"),
                    exc,
                )
        return found

    # ----------------------------------------------------------------- #
    # Building blocks
    # ----------------------------------------------------------------- #

    def _file(
        self,
        attachment: _govuk.Attachment,
        period: str,
        token: str,
        *,
        mutable: bool = False,
    ) -> RemoteFile:
        return RemoteFile(
            borough=self.slug,
            period=period,
            url=attachment.url,
            filename=_named(token, attachment.filename),
            format=format_from_name(attachment.filename, "ods"),
            title=attachment.title or None,
            mutable=mutable,
        )

    def _yearly(
        self,
        client: httpx.Client,
        since: str | None,
        until: str | None,
        *,
        collection: str,
        wanted: Callable[[str, str], bool],
        files: re.Pattern[str],
        token: str,
    ) -> list[RemoteFile]:
        """One release per financial year, from a collection that lists them.

        ``wanted`` decides which of the collection's documents are this
        family's (the revenue collection alone holds budget, outturn,
        provisional outturn and subjective analysis under similar slugs).
        ``--since`` and ``--until`` are applied to the year before the release
        is fetched, because each release is a request and a narrow window
        should not pay for sixteen of them.
        """
        found: list[RemoteFile] = []
        for path, title in _govuk.collection_documents(client, collection):
            years = _govuk.path_years(path)
            if years is None or not wanted(path, title):
                continue
            period = fy_period(years[0])
            if not in_range(period, since, until):
                continue
            try:
                release = _govuk.release(client, path)
            except (FetchError, httpx.HTTPError, KeyError, ValueError) as exc:
                # One moved or withdrawn release page costs its own year only,
                # not every other year in the family.
                log.warning(
                    "mhclg: %s release %s failed, skipping: %s", token, path, exc
                )
                continue
            matched = release.matching(files)
            if not matched:
                log.warning(
                    "mhclg: no %s files matched in %s (%d attachments present)",
                    token,
                    path,
                    len(release.attachments),
                )
                continue
            found.extend(self._file(a, period, token) for a in matched)
        return found

    def _from_release(
        self,
        release: _govuk.Release,
        *,
        token: str,
        files: re.Pattern[str] | None = None,
        mutable: bool = False,
        span: tuple[int, int] | None = None,
        warn_empty: bool = True,
    ) -> list[RemoteFile]:
        """A release whose files are not per-year, or are a series of years.

        ``span`` pins the period for a time series. Without it each file gets
        the financial years its own name or title states, which is how the QRU
        forms (one year each) come out right from a single page.

        ``warn_empty`` is off for a collection where an empty release is the
        normal state, such as the Section 251 year whose data has not been
        published yet.
        """
        matched = release.attachments if files is None else release.matching(files)
        if not matched:
            if warn_empty:
                log.warning(
                    "mhclg: no %s files matched in %s (%d attachments present)",
                    token,
                    release.path,
                    len(release.attachments),
                )
            return []
        found = []
        for attachment in matched:
            years = (
                span
                or parse_fy_span(attachment.filename)
                or parse_fy_span(attachment.title)
            )
            if years is None:
                log.warning(
                    "mhclg: no financial year in %r on %s, skipping",
                    attachment.filename,
                    release.path,
                )
                continue
            found.append(
                self._file(attachment, fy_period(*years), token, mutable=mutable)
            )
        return found

    def _one_release(
        self, client: httpx.Client, path: str, **kwargs
    ) -> list[RemoteFile]:
        """Fetch one release page and turn it into files."""
        return self._from_release(_govuk.release(client, path), **kwargs)

    # ----------------------------------------------------------------- #
    # Revenue
    # ----------------------------------------------------------------- #

    def _revenue_account(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """RA budget per authority, every year MHCLG still publishes.

        The slug says ``individual-local-authority-data`` for both budget and
        outturn; only the title carries the word "outturn", so that is the
        filter. Formats drift under it without anybody being told: ``.xls`` to
        2015-16, ``.xlsx`` to 2020-21, ``.ods`` after, and from 2023-24 the
        workbook is split into Part 1 (services and financing) and Part 2
        (reserves and the Housing Revenue Account). Both parts are saved; Part
        2 is where most London boroughs' housing stock shows up.
        """
        return self._yearly(
            client,
            since,
            until,
            collection=REVENUE_COLLECTION,
            wanted=lambda path, title: (
                bool(PER_LA_RELEASE.search(path)) and "outturn" not in title.lower()
            ),
            files=RA_FILES,
            token="ra",
        )

    def _revenue_outturn_series(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """The 24 MB CSV that makes budget comparable to what was spent.

        Kept here rather than with the spend files because it is the other half
        of the budget question: the RA asset IDs are the middle token of the RO
        column names, so ``eduerl`` in the budget is
        ``RO1_eduerl_net_cur_exp`` in the outturn. The metadata ODS beside it
        names the columns and is worth the extra 100 KB.
        """
        files = self._one_release(
            client,
            REVENUE_OUTTURN_SERIES,
            token="ro",
            mutable=True,
            span=REVENUE_SERIES_SPAN,
        )
        return [f for f in files if in_range(f.period, since, until)]

    def _qru_forms(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """The RA-to-RO-to-QRU crosswalk, and the RA re-cut into QRU categories.

        The mapping document is the citable authority for where the RA form is
        coarser than the RO form, which is the difference between a right join
        and a plausible one on central services and local tax collection.
        """
        files = self._one_release(client, QRU_FORMS, token="qru")
        return [f for f in files if in_range(f.period, since, until)]

    def _qru_live_table(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """In-year budget against actual, quarterly, filed as a live table.

        Easy to miss because it is not a statistics release. Mutable: the same
        file is republished each quarter with the next quarter's actuals and a
        revised full-year forecast, and its ``Timeseries`` sheet reaches back
        to 2017-18 Q1.
        """
        files = self._one_release(
            client, LIVE_TABLES, token="qru", files=QRU_LIVE_TABLE, mutable=True
        )
        return [f for f in files if in_range(f.period, since, until)]

    # ----------------------------------------------------------------- #
    # Capital
    # ----------------------------------------------------------------- #

    def _capital_estimates(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """CER, the forward-looking capital return, one release per year.

        Its service codes share the RA naming family but are coarser
        (``eduerlprm`` merges what RA splits into ``eduerl`` and ``eduprm``),
        so capital and revenue join at the service group and not at the line.
        """
        return self._yearly(
            client,
            since,
            until,
            collection=CAPITAL_COLLECTION,
            wanted=lambda path, _: bool(CER_RELEASE.search(path)),
            files=CER_FILES,
            token="cer",
        )

    def _capital_outturn(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """COR, what was actually spent on capital, one release per year.

        The recent files are named ``COR_A1.ods`` with no year in them at all,
        which is why the period prefix on disk is doing real work here.
        """
        return self._yearly(
            client,
            since,
            until,
            collection=CAPITAL_COLLECTION,
            wanted=lambda path, _: (
                bool(PER_LA_RELEASE.search(path)) and not CER_RELEASE.search(path)
            ),
            files=COR_FILES,
            token="cor",
        )

    def _capital_series(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """The only capital file published as CSV, plus its metadata.

        Its attachment title names the years it covers, so the period follows
        the file rather than a constant that would rot.
        """
        release = _govuk.release(client, CAPITAL_SERIES)
        spans = (parse_fy_span(a.title) for a in release.attachments)
        span = next((s for s in spans if s is not None), CAPITAL_SERIES_SPAN)
        files = self._from_release(release, token="capital", mutable=True, span=span)
        return [f for f in files if in_range(f.period, since, until)]

    # ----------------------------------------------------------------- #
    # Council tax and settlement
    # ----------------------------------------------------------------- #

    def _council_tax(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Council tax levels, the per-authority tables, one release per year.

        The current Table 10 ``Data_Billing`` sheet is the authoritative
        council tax requirement per borough: exactly 33 ``E09`` rows, current
        and previous year side by side, with the tax base and the estimated
        collection rate. The aggregate ``ILB``/``OLB`` rows carry non-ONS
        codes, so filtering on ``E09`` excludes them cleanly.
        """
        return self._yearly(
            client,
            since,
            until,
            collection=COUNCIL_TAX_COLLECTION,
            wanted=lambda path, _: bool(COUNCIL_TAX_RELEASE.search(path)),
            files=COUNCIL_TAX_TABLES,
            token="counciltax",
        )

    def _core_spending_power(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """The settlement's Core Spending Power table: the only forward view.

        The RA return covers one budget year. This table runs to 2028-29, so it
        is the only central source that says what a borough expects to have
        beyond the year it has just set. Mutable because the provisional
        settlement's table is replaced by the final one in the same round.
        """
        documents = _govuk.collection_documents(client, SETTLEMENT_COLLECTION)
        found: list[RemoteFile] = []
        for path, title in documents:
            if not CORE_SPENDING_POWER.search(title):
                continue
            span = parse_fy_span(title)
            found.extend(
                self._one_release(client, path, token="csp", mutable=True, span=span)
            )
        if not found:
            log.warning(
                "mhclg: no core spending power table in %s", SETTLEMENT_COLLECTION
            )
        return [f for f in found if in_range(f.period, since, until)]

    def _section_251(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """Education and children's services planned spend, per authority.

        Worth having because education is the largest single line in most
        borough budgets. Caveat that bites on first use: Section 251 is a DfE
        collection and it keys authorities by **DfE LA number**, not ONS code.
        City of London is 201, Camden 202, Greenwich 203. Nothing here joins to
        the MHCLG files without a DfE-to-ONS lookup, and the authority names
        are DfE style too ("Camden London Borough Council").
        """
        found: list[RemoteFile] = []
        for path, _ in _govuk.collection_documents(client, SECTION_251_COLLECTION):
            # The current year's release is guidance and blank forms until the
            # returns are in, so an empty one is expected rather than odd.
            found.extend(
                self._one_release(
                    client,
                    path,
                    token="s251",
                    files=SECTION_251_FILES,
                    mutable=True,
                    warn_empty=False,
                )
            )
        if not found:
            log.warning(
                "mhclg: no section 251 planned expenditure file in %s",
                SECTION_251_COLLECTION,
            )
        return _dedupe([f for f in found if in_range(f.period, since, until)])


def _dedupe(files: Iterable[RemoteFile]) -> list[RemoteFile]:
    """First file wins per URL. Section 251 attaches one release to two years."""
    seen: set[str] = set()
    out = []
    for remote in files:
        if remote.url in seen:
            continue
        seen.add(remote.url)
        out.append(remote)
    return out
