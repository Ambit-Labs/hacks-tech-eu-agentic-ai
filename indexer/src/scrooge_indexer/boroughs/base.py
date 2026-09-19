"""The interface a source module implements, and the helpers it can reuse.

Adding a borough, or a budget publisher, is one new file in this package.
Subclass :class:`Source`, fill in the five class attributes, write
``discover()``, and the registry finds it. Nothing else in the codebase is
edited, which is the point: several people add sources at the same time and
none of them should have to touch a shared file.

Everything below :class:`Source` is shared plumbing, kept here because the
first three boroughs already needed it twice: month names as councils spell
them, UK financial-year arithmetic, period filtering, a link scraper, and a
DataPress client. The underscore-prefixed modules beside this one hold the
machinery a handful of sources share rather than all of them: an Umbraco media
host, the GOV.UK content API, Modern.Gov, a budget-book page.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import ClassVar
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..http import FetchResult, download_to, request_with_retries
from ..models import RemoteFile, SourceKind, format_from_name

MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

#: Quarter convention assumed when nothing says otherwise. Every London
#: borough that publishes quarterly spending numbers its quarters on the UK
#: financial year: Q1 is April to June. See :class:`RemoteFile` for how that
#: lands in a period string.
DEFAULT_QUARTERS = "financial"


class Source(ABC):
    """One publisher's files: a borough's spending, or somebody's budget.

    Subclasses set the five class attributes and implement :meth:`discover`.
    ``fetch`` already works for the common case (a plain GET that returns the
    file) and only needs overriding when the file has to be assembled, as
    Camden's does from a paged API.
    """

    slug: ClassVar[str]
    """Directory name and CLI argument, e.g. ``camden``. Lowercase, hyphens."""

    kind: ClassVar[SourceKind] = "spend"
    """``spend`` for what a council actually paid, ``budget`` for what it
    planned to. The default keeps every borough written before budgets existed
    unchanged, and it decides both the tree the files land in
    (``data/raw/`` or ``data/budgets/``) and whether ``--kind`` selects this
    source. A budget source is not a borough: ``mhclg`` covers all 33 at once.
    """

    name: ClassVar[str]
    """The council's own name, e.g. ``Richmond upon Thames``."""

    threshold: ClassVar[str]
    """Publication threshold as the council states it: ``£500``, ``£250``,
    or ``none`` when it publishes everything."""

    access: ClassVar[str]
    """How the files are reached: ``socrata-api``, ``datapress-api``,
    ``govuk-content-api``, ``moderngov-api``, ``url-pattern``, ``scrape``.
    Shown by ``scrooge list`` so an operator can see at a glance which sources
    will break when a CMS is rebuilt."""

    landing_page: ClassVar[str]
    """The human page a person should open to check what we are doing."""

    quarters: ClassVar[str] = DEFAULT_QUARTERS
    """``financial`` (Q1 = April to June) or ``calendar``. Only consulted when
    this borough emits ``YYYY-Qn`` periods."""

    @abstractmethod
    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """List the files this borough publishes in ``[since, until]``.

        Both bounds are ``YYYY-MM`` or None. Returning files outside them is
        harmless (the CLI filters again), so a source may ignore the bounds
        when narrowing costs an extra request. Network calls go through
        ``client``. Raising here fails the whole borough, so a source that can
        partially enumerate should return what it has.
        """

    def fetch(
        self,
        client: httpx.Client,
        remote: RemoteFile,
        dest: Path,
        *,
        on_bytes: Callable[[int], None] | None = None,
        conditional: dict[str, str] | None = None,
    ) -> FetchResult:
        """Put one file on disk. Override only when a GET is not enough.

        The default streams to ``dest.part`` and renames, so the caller's
        resume logic can trust that a file that exists is a file that is
        complete. An override must keep that promise.
        """
        return download_to(
            client, remote, dest, on_bytes=on_bytes, conditional=conditional
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return f"<{type(self).__name__} {self.slug}>"


# --------------------------------------------------------------------------- #
# Months and periods
# --------------------------------------------------------------------------- #


def parse_month_name(text: str) -> int | None:
    """``"Jan"``, ``"JANUARY"``, ``"Sept"`` → 1, 1, 9. None when it is not a month.

    Any unambiguous prefix of three letters or more is accepted, because
    councils spell the same month three ways across one page: ``Sept 2019``,
    ``September 2019`` and ``SEP 19`` all appear in this corpus.
    """
    token = text.strip().lower().rstrip(".")
    if len(token) < 3:
        return None
    matches = [i for i, name in enumerate(MONTH_NAMES, 1) if name.startswith(token)]
    return matches[0] if len(matches) == 1 else None


def month_name(month: int, *, short: bool = False) -> str:
    """1 → ``january`` (or ``jan``). Lowercase, which is what URLs want."""
    name = MONTH_NAMES[month - 1]
    return name[:3] if short else name


_PERIOD_TEXT = re.compile(
    r"(?P<name>[A-Za-z]{3,9})[\s_-]+(?P<year1>\d{4})"
    r"|(?P<year2>\d{4})[\s_-]+(?P<name2>[A-Za-z]{3,9})"
    r"|(?P<year3>\d{4})-(?P<num>0[1-9]|1[0-2])"
)


def parse_period(text: str) -> str | None:
    """Pull a ``YYYY-MM`` out of free text such as a link label or a filename.

    Handles ``January 2025``, ``council_expenditure_july_2026.csv``,
    ``2025 March`` and ``2025-03``. Returns None rather than guessing, so a
    caller can fall back to its own naming rules.
    """
    for match in _PERIOD_TEXT.finditer(text):
        if match.group("num"):
            return f"{match.group('year3')}-{match.group('num')}"
        name = match.group("name") or match.group("name2")
        year = match.group("year1") or match.group("year2")
        month = parse_month_name(name) if name else None
        if month and year:
            return f"{year}-{month:02d}"
    return None


def month_period(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def range_period(first: str, last: str) -> str:
    """``("2010-09", "2011-03")`` → ``2010-09_2011-03``, the period for a span.

    A span of one month is a month: the range form exists to say that a file
    covers several, and ``2011-03_2011-03`` would only be a longer way of
    writing ``2011-03``. Callers can therefore hand this the output of
    :func:`month_span` without checking first.
    """
    return first if first == last else f"{first}_{last}"


#: A word or a run of digits. Years are the only numbers that matter here, and
#: the ``500`` in half the filenames in this corpus is not one; :func:`_year_of`
#: is what tells them apart.
_SPAN_TOKEN = re.compile(r"[A-Za-z]+|\d+")


def _year_of(token: str) -> int | None:
    """A token read as a year: ``2010`` as itself, ``24`` as 2024, else None.

    Two digits are a year because councils write "Dec 24" and "June 26"; three
    are never one, which is how ``over-500-july-2026`` keeps its 500 out of the
    arithmetic.
    """
    if not token.isdigit():
        return None
    if len(token) == 2:
        return 2000 + int(token)
    if len(token) == 4 and token[:2] in ("19", "20"):
        return int(token)
    return None


def month_span(text: str, *, short_years: bool = True) -> tuple[str, str] | None:
    """The first and last month named in ``text``, as ``(YYYY-MM, YYYY-MM)``.

    "Dec 2024 - Mar 2025" gives ``("2024-12", "2025-03")``, "April to December
    2017" gives ``("2017-04", "2017-12")``, and a label naming one month gives
    that month twice. None when no month carries a year, directly or by
    borrowing one.

    A month written without a year takes the year of the month beside it and
    steps a year when that would run the sequence backwards, which is what
    "september 2010 to march 2011" needs in one direction and
    "october-november-2015" in the other.

    ``short_years=False`` refuses two-digit years. Brent needs it: the ``24``
    in "Transparency 24 June - 24 August" could be a year or a day, and its
    resource names spell the years out anyway.
    """
    tokens = _SPAN_TOKEN.findall(text)
    found: list[tuple[int | None, int]] = []
    for index, token in enumerate(tokens):
        month = parse_month_name(token)
        if month is None:
            continue
        # Only the token immediately after the month counts as its year. In
        # "Dec-Feb 2022" the 2022 belongs to February, and reaching past one
        # month to the next month's year is how December ends up in the wrong
        # one.
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        year = _year_of(following)
        if year is not None and not short_years and len(following) != 4:
            year = None
        found.append((year, month))
    # Backwards first ("December through February 2020" hangs on February),
    # then forwards for anything still without a year ("March 2023 through to
    # June" hangs on March).
    for index in range(len(found) - 2, -1, -1):
        year, month = found[index]
        next_year, next_month = found[index + 1]
        if year is None and next_year is not None:
            found[index] = (next_year - 1 if month > next_month else next_year, month)
    for index in range(1, len(found)):
        year, month = found[index]
        previous_year, previous_month = found[index - 1]
        if year is None and previous_year is not None:
            found[index] = (
                previous_year + 1 if month < previous_month else previous_year,
                month,
            )
    dated = [(year, month) for year, month in found if year is not None]
    if not dated:
        return None
    return month_period(*dated[0]), month_period(*dated[-1])


def current_month(today: date | None = None) -> str:
    today = today or date.today()
    return month_period(today.year, today.month)


def shift_month(period: str, months: int) -> str:
    """``("2026-01", -1)`` → ``2025-12``. Month arithmetic without a dependency."""
    year, month = (int(part) for part in period.split("-")[:2])
    index = (year * 12 + month - 1) + months
    return month_period(index // 12, index % 12 + 1)


def months_between(since: str, until: str) -> list[str]:
    """Every ``YYYY-MM`` from ``since`` to ``until`` inclusive, ascending."""
    if since > until:
        return []
    out, cursor = [], since
    while cursor <= until:
        out.append(cursor)
        cursor = shift_month(cursor, 1)
    return out


def period_bounds(period: str, *, quarters: str = DEFAULT_QUARTERS) -> tuple[str, str]:
    """The first and last calendar month a period covers.

    ``2026-08`` is one month, ``2026-08_2026-11`` is August to November, and
    ``2026-Q1`` is April to June 2026 under the financial convention or January
    to March under the calendar one.
    """
    if "_" in period:
        first, last = period.split("_")
        return first, last
    if "-Q" in period:
        year, quarter = period.split("-Q")
        return fy_quarter_bounds(int(year), int(quarter), quarters=quarters)
    return period, period


def in_range(
    period: str,
    since: str | None,
    until: str | None,
    *,
    quarters: str = DEFAULT_QUARTERS,
) -> bool:
    """Does ``period`` overlap ``[since, until]``? Overlap, not containment.

    A quarter or a month range that straddles the boundary is kept: asking for
    ``--since 2026-06`` and silently dropping the quarter that contains June
    would be the wrong answer, and so would dropping the half year that holds
    it.
    """
    first, last = period_bounds(period, quarters=quarters)
    if since and last < since:
        return False
    if until and first > until:
        return False
    return True


def filter_files(
    files: Iterable[RemoteFile],
    since: str | None,
    until: str | None,
    *,
    quarters: str = DEFAULT_QUARTERS,
) -> list[RemoteFile]:
    """Apply ``--since`` / ``--until`` to a discovery result."""
    return [f for f in files if in_range(f.period, since, until, quarters=quarters)]


# --------------------------------------------------------------------------- #
# UK financial years
# --------------------------------------------------------------------------- #


def fy_label(start_year: int) -> str:
    """2026 → ``2026-27``, the label councils print on a financial year."""
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def fy_of_month(period: str) -> int:
    """The financial year a month belongs to, as its start year.

    ``2026-03`` is in FY 2025-26, ``2026-04`` starts FY 2026-27.
    """
    year, month = (int(part) for part in period.split("-")[:2])
    return year if month >= 4 else year - 1


def fy_months(start_year: int) -> list[str]:
    """April of ``start_year`` through March of the next, twelve months."""
    return months_between(month_period(start_year, 4), month_period(start_year + 1, 3))


def fy_period(start_year: int, end_year: int | None = None) -> str:
    """The period for one financial year, or for a run of them.

    ``2026`` is ``2026-04_2027-03``. ``(2026, 2030)`` is April 2026 to March
    2030, which is what a borough that publishes one budget book covering four
    years needs, and what MHCLG's multi-year time series needs. ``end_year`` is
    the calendar year the last financial year *ends* in, the second half of the
    label the publisher writes, so ``2026-27 to 2029-30`` is ``(2026, 2030)``.
    """
    end = end_year if end_year is not None else start_year + 1
    if end <= start_year:
        raise ValueError(
            f"financial year span {start_year}-{end} does not run forwards"
        )
    return f"{month_period(start_year, 4)}_{month_period(end, 3)}"


#: ``2026-27``, ``2026/2027``, ``2026 to 2027``, ``2026_27``, ``2026–30``: a
#: four-digit year, a separator, then the other half written long or short.
#: Councils and MHCLG use every one of these, sometimes two of them on one page.
_FY_LABEL = re.compile(
    r"(?<!\d)(?P<first>\d{4})\s*(?:[-/_–—]|to)\s*(?P<second>\d{4}|\d{2})(?!\d)",
    re.IGNORECASE,
)

#: Longest span a label may claim before we stop believing it is one. Merton's
#: rolling budget book runs four years; anything past a decade is two unrelated
#: numbers that happen to sit next to each other.
MAX_FY_SPAN = 10


def _fy_pair(first: str, second: str) -> tuple[int, int] | None:
    """``("2026", "27")`` → ``(2026, 2027)``, the years a label's halves mean."""
    start = int(first)
    end = int(second) if len(second) == 4 else start - start % 100 + int(second)
    if len(second) == 2 and end < start:
        end += 100  # "1999-00" crosses a century.
    if not 1990 <= start <= 2100 or not 0 < end - start <= MAX_FY_SPAN:
        return None
    return start, end


def parse_fy_span(text: str) -> tuple[int, int] | None:
    """The financial years a label names, as ``(first start year, last end year)``.

    "Budget Book 2026/2027" is ``(2026, 2027)``, "Budget Book 2026-2030" is
    ``(2026, 2030)``, and a title that names two spans, as MHCLG's "2015 to
    2016 financial year to 2025 to 2026 financial year" does, is read from the
    start of the first to the end of the last. Pass the result to
    :func:`fy_period`.

    None when nothing in the text reads as a financial year. A single bare year
    is deliberately None: "Budget 2026" could be either financial year and the
    publisher has not said which.
    """
    pairs = [
        pair
        for match in _FY_LABEL.finditer(text)
        if (pair := _fy_pair(match.group("first"), match.group("second"))) is not None
    ]
    if not pairs:
        return None
    return pairs[0][0], max(end for _, end in pairs)


def fy_quarter_of_month(period: str) -> tuple[int, int]:
    """``2026-08`` → ``(2026, 2)``: FY start year and quarter number, Q1 = Apr-Jun."""
    month = int(period.split("-")[1])
    start = fy_of_month(period)
    return start, ((month - 4) % 12) // 3 + 1


def fy_quarter_months(start_year: int, quarter: int) -> list[str]:
    """The three months of FY ``start_year`` quarter ``quarter``."""
    first = fy_months(start_year)[(quarter - 1) * 3]
    return [shift_month(first, offset) for offset in range(3)]


def fy_quarter_bounds(
    year: int, quarter: int, *, quarters: str = DEFAULT_QUARTERS
) -> tuple[str, str]:
    """First and last month of a ``YYYY-Qn`` period under either convention."""
    if quarters == "calendar":
        first = month_period(year, (quarter - 1) * 3 + 1)
        return first, shift_month(first, 2)
    months = fy_quarter_months(year, quarter)
    return months[0], months[-1]


def fy_quarter_period(start_year: int, quarter: int) -> str:
    """The period string for a financial-year quarter: ``(2026, 1)`` → ``2026-Q1``.

    Westminster's "Q1 2026-27" file is ``2026-Q1`` and holds April to June
    2026. Its Q4 is ``2026-Q4`` and holds January to March 2027, which is why
    the year in the string is the financial year's first year and not the
    calendar year the quarter falls in.
    """
    return f"{start_year}-Q{quarter}"


def fy_quarter_of_span(first: str, last: str) -> str | None:
    """``("2026-04", "2026-06")`` → ``2026-Q1``, or None when it is not a quarter.

    Exact match only. A half year, a four-month span and a quarter that runs
    March to May are all None, because calling any of them ``YYYY-Qn`` would
    claim months the file does not hold or hide months it does.
    """
    start, quarter = fy_quarter_of_month(first)
    months = fy_quarter_months(start, quarter)
    if (months[0], months[-1]) == (first, last):
        return fy_quarter_period(start, quarter)
    return None


#: "Q1 2026/27", "q1-2026-27", "quarter 1, financial year 2025/26", "q1_23-24".
#: The quarter number comes first and both halves of the financial year follow,
#: within 30 characters so a run-on label cannot pair a quarter with a distant
#: year.
_QUARTER_THEN_FY = re.compile(
    r"q(?:uarter)?\s*(?P<quarter>[1-4])(?!\d).{0,30}?"
    r"(?<!\d)(?P<year>\d{2,4})\s*[-/_]\s*\d{2}(?!\d)",
    re.IGNORECASE | re.DOTALL,
)

#: ``2026-27Q1``, ``2025-26 Q4``, ``202425 Q3``, ``2019-20-Q4``: the same pair
#: of years with the quarter after them. The lookarounds keep the pair from
#: starting or ending mid-number.
_FY_THEN_QUARTER = re.compile(
    r"(?<!\d)(?P<year>\d{4})\s*[-_]?\s*\d{2}\s*[-_]?\s*q\s*(?P<quarter>[1-4])(?!\d)",
    re.IGNORECASE,
)


def _fy_start(year: str) -> int:
    """``"2025"`` or ``"25"`` to 2025. Councils abbreviate either half."""
    value = int(year)
    return value if value > 99 else 2000 + value


def fy_quarter_from_label(text: str) -> str | None:
    """The financial-year quarter a label or a filename names, as ``YYYY-Qn``.

    Reads the shapes five councils write between them: a quarter number beside
    both halves of a financial year in either order ("Q1 2026/27",
    "2026-27Q1", "quarter 1, financial year 2025/26", "q1_23-24"), and a month
    range that is exactly a quarter ("April - June 2026",
    "april-through-to-june-26").

    None when the text names no quarter, and deliberately None when it names
    only one year: "q1-2025" is Q1 of 2025-26 on one council's page and Q1 of
    2024-25 on another's, and a caller that knows which is which can say so
    itself. A month range that is not exactly one quarter is None too; use
    :func:`month_span` and :func:`range_period` for those.
    """
    for pattern in (_QUARTER_THEN_FY, _FY_THEN_QUARTER):
        match = pattern.search(text)
        if match:
            return fy_quarter_period(
                _fy_start(match.group("year")), int(match.group("quarter"))
            )
    span = month_span(text)
    return fy_quarter_of_span(*span) if span else None


def calendar_quarter_period(year: int, quarter: int) -> str:
    """The period string for a calendar quarter: ``(2026, 1)`` → ``2026-Q1``.

    Spelled the same as a financial quarter on purpose. A borough uses one
    convention or the other for its whole series, and ``Source.quarters`` says
    which, so the strings still sort chronologically within a borough.
    """
    return f"{year}-Q{quarter}"


# --------------------------------------------------------------------------- #
# Scraping helpers
# --------------------------------------------------------------------------- #


def extract_links(
    html: str,
    base_url: str,
    *,
    pattern: str | re.Pattern | None = None,
    dedupe: bool = True,
) -> list[tuple[str, str]]:
    """``[(absolute_url, link_text)]`` from a page, optionally filtered.

    ``pattern`` is matched with ``re.search`` against the absolute URL, so a
    borough asks for ``r"\\.csv$"`` or ``r"/media/.*expenditure"`` and gets back
    the hrefs it cares about with the label next to them. The label is the only
    place a period often appears (``Expenditure July 2026``), which is why the
    text comes back rather than just the URL.

    ``dedupe`` keeps the first anchor for a repeated URL, which is what a page
    that links the same file twice usually means. Pass ``dedupe=False`` when
    the label is doing the work and two anchors disagree about it: Newham
    points its Excel link and its CSV link at one download id, the Excel label
    comes first, and dropping the second anchor loses that month entirely.
    """
    soup = BeautifulSoup(html, "html.parser")
    matcher = re.compile(pattern) if isinstance(pattern, str) else pattern
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, anchor["href"].strip())
        if matcher is not None and not matcher.search(url):
            continue
        if dedupe:
            if url in seen:
                continue
            seen.add(url)
        out.append((url, " ".join(anchor.get_text(" ", strip=True).split())))
    return out


# --------------------------------------------------------------------------- #
# DataPress (Barnet, Brent, and the London Datastore)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DataPressResource:
    """One downloadable file in a DataPress dataset."""

    id: str
    name: str
    url: str
    format: str
    size: int | None = None
    last_modified: str | None = None


def datapress_resources(
    client: httpx.Client, base_url: str, package_id: str
) -> list[DataPressResource]:
    """``package_show`` on a DataPress portal, which speaks the CKAN action API.

    Verified against ``open.barnet.gov.uk`` on 2026-09-19: the response is
    ``{"success": true, "result": {..., "resources": [...]}}``, and a resource
    carries ``id``, ``url``, ``name`` and ``size`` but often no ``format``, so
    the format is inferred from the URL when the field is empty.
    """
    response = request_with_retries(
        client,
        "GET",
        f"{base_url.rstrip('/')}/api/action/package_show",
        params={"id": package_id},
    )
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(f"package_show failed for {package_id}: {body.get('error')}")
    out = []
    for raw in body.get("result", {}).get("resources", []):
        url = raw.get("url") or ""
        declared = (raw.get("format") or "").strip().lower()
        size = raw.get("size")
        out.append(
            DataPressResource(
                id=str(raw.get("id") or ""),
                name=raw.get("name") or "",
                url=url,
                format=declared or format_from_name(url),
                size=int(size)
                if isinstance(size, int | str) and str(size).isdigit()
                else None,
                last_modified=raw.get("last_modified") or raw.get("created"),
            )
        )
    return out
