"""Budget Council papers through the Modern.Gov web service.

Four London boroughs run a Modern.Gov committee system that answers a plain
request, and Modern.Gov exposes ``/mgWebService.asmx``, which returns XML to an
ordinary GET. That is worth more than scraping the agenda pages: the budget
report, its appendices and the medium-term financial strategy are attached to
one meeting, and the service names the meeting outright.

Two calls per borough per run of the list, then one per budget meeting:

1. ``GetAllMeetingsByDate`` for the committee that sets the budget, over the
   whole history in one request. Each meeting carries a ``meetingstatus``, and
   the budget meeting says so in it: "Confirmed; Budget Council" at Lambeth,
   "Confirmed; Budget & Council Tax Setting Meeting" at Brent, "Confirmed;
   Budget Setting Meeting" at Hounslow, "Confirmed; Budget" at Haringey. That
   label is the publisher's own and it is the only reliable way in: document
   ids are opaque and change every meeting, and the sibling ``GetMeetings``
   call ignores its date arguments entirely.
2. ``GetMeeting`` for each of those, which returns the agenda with every
   attachment.

What that misses is years the council did not label. Lambeth's 2012 to 2018
budget meetings are plain "Confirmed", so they are not picked up, and guessing
which February meeting was the budget one would mean fetching every agenda to
find out. Taking the label at face value is the honest version, and a missing
year is visible in ``scrooge status`` rather than silently wrong.

Underscore-prefixed so the registry skips it: shared machinery, not a source.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

import httpx

from ..http import request_with_retries
from ..models import RemoteFile
from .base import Source, current_month, fy_of_month, fy_period, in_range

#: ``dd/mm/yyyy``, the only date format the service speaks, in or out.
DATE_FORMAT = "%d/%m/%Y"

#: A budget meeting sets the year that starts in April, so it sits in the
#: winter before it. Anything outside this window with "budget" in its status
#: is a scrutiny or monitoring meeting, not the setting one.
BUDGET_MONTHS = (1, 2, 3, 4)

#: Earliest year worth asking for. Modern.Gov archives go back further, but
#: nothing before this has a budget-labelled meeting on any of the four hosts.
EARLIEST_YEAR = 2010


@dataclass(frozen=True)
class Meeting:
    """One committee meeting, as ``GetAllMeetingsByDate`` describes it."""

    id: str
    date: date
    status: str

    @property
    def financial_year(self) -> int:
        """The financial year this meeting sets, as its start year.

        A budget meeting on 23 February 2026 sets 2026-27. One held in April
        is late and sets the year that has just started, so April 2026 is
        still 2026-27. Anything later in the calendar year is setting the next
        one; no council in this corpus has done that, so the branch is there
        to be correct rather than because it fires.
        """
        return self.date.year if self.date.month <= 4 else self.date.year + 1


@dataclass(frozen=True)
class Document:
    """One attachment on an agenda item."""

    title: str
    url: str


def _text(node: ET.Element, tag: str) -> str:
    """One child element's text, with the HTML entities Modern.Gov leaves in.

    The service escapes its strings for HTML before it escapes them for XML,
    so "Budget & Council Tax" arrives as ``Budget &amp;amp; Council Tax`` and
    ElementTree hands back ``&amp;``. One more unescape gives the title back.
    """
    found = node.find(tag)
    return html.unescape((found.text or "").strip()) if found is not None else ""


def _parse(xml: str) -> ET.Element:
    """Parse one web service response.

    The standard library parser, not ``defusedxml``: since Python 3.7.1
    ``ElementTree`` does not resolve external entities or fetch DTDs, which is
    the part that would matter for a remote document. What remains is entity
    expansion, and the bodies here come from a council's own HTTPS endpoint
    into a local CLI that writes files and nothing else.
    """
    return ET.fromstring(xml)


def meetings(
    client: httpx.Client, host: str, committee_id: int, first_year: int, last_year: int
) -> list[Meeting]:
    """Every meeting of one committee between two calendar years."""
    response = request_with_retries(
        client,
        "GET",
        f"{host}/mgWebService.asmx/GetAllMeetingsByDate",
        params={
            "lCommitteeId": str(committee_id),
            "sFromDate": f"01/01/{first_year}",
            "sToDate": f"31/12/{last_year}",
            "sAllOrNone": "none",
            "bIsAscendingDateOrder": "true",
        },
    )
    found = []
    for node in _parse(response.text).iter("meeting"):
        raw = _text(node, "meetingdate")
        try:
            day, month, year = (int(part) for part in raw.split("/"))
        except ValueError:
            continue
        found.append(
            Meeting(
                id=_text(node, "meetingid"),
                date=date(year, month, day),
                status=_text(node, "meetingstatus"),
            )
        )
    return found


def meeting_documents(
    client: httpx.Client, host: str, meeting_id: str, item_pattern: re.Pattern[str]
) -> list[Document]:
    """Attachments on the agenda items whose titles match, without duplicates.

    Modern.Gov attaches the same PDF to more than one item when a report is
    referred from Cabinet to Council, so the same URL comes back twice on the
    meetings that matter most. Restricted attachments are skipped: they are
    exempt papers and the link would be a login page, not a document.
    """
    response = request_with_retries(
        client,
        "GET",
        f"{host}/mgWebService.asmx/GetMeeting",
        params={"lMeetingId": meeting_id},
    )
    found: list[Document] = []
    seen: set[str] = set()
    for item in _parse(response.text).iter("agendaitem"):
        if not item_pattern.search(_text(item, "agendaitemtitle")):
            continue
        for doc in item.iter("linkeddoc"):
            url = _text(doc, "url")
            if not url or url in seen:
                continue
            if _text(doc, "isrestricted").lower() == "true":
                continue
            seen.add(url)
            found.append(Document(title=_text(doc, "title"), url=url))
    return found


class ModernGovBudgetSource(Source):
    """One committee's budget-setting meetings, and everything attached."""

    kind = "budget"
    threshold = "n/a"
    access = "moderngov-api"

    host: ClassVar[str]
    """e.g. ``https://moderngov.lambeth.gov.uk``, no trailing slash."""

    committee_id: ClassVar[int]
    """The committee that sets the budget, from ``GetCommittees``."""

    earliest_year: ClassVar[int] = EARLIEST_YEAR

    #: The agenda items worth taking. Wide on purpose: at a budget meeting
    #: "Budget and Council Tax 2026 - 2027" and "2026/27 Budget and 2026/2031
    #: Medium Term Financial Strategy Report" are the same thing under two
    #: house styles, and both carry 20-odd appendices.
    item_pattern: ClassVar[re.Pattern[str]] = re.compile(r"budget", re.IGNORECASE)

    budget_status: ClassVar[re.Pattern[str]] = re.compile(r"budget", re.IGNORECASE)

    def budget_meetings(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[Meeting]:
        latest = fy_of_month(current_month()) + 1
        found = [
            meeting
            for meeting in meetings(
                client, self.host, self.committee_id, self.earliest_year, latest
            )
            if meeting.date.month in BUDGET_MONTHS
            and self.budget_status.search(meeting.status)
        ]
        # Filtered before the agendas are fetched: each meeting is a request,
        # and a narrow window should not pay for ten of them.
        return [m for m in found if in_range(fy_period(m.financial_year), since, until)]

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        files: list[RemoteFile] = []
        for meeting in self.budget_meetings(client, since, until):
            period = fy_period(meeting.financial_year)
            for document in meeting_documents(
                client, self.host, meeting.id, self.item_pattern
            ):
                # The URL is ``mgConvert2PDF.aspx?ID=174193``: no filename in
                # it at all, so the document's own title becomes the name and
                # the manifest cleans it on the way to disk.
                files.append(
                    RemoteFile(
                        borough=self.slug,
                        period=period,
                        url=document.url,
                        filename=f"{document.title or document.url}.pdf",
                        format="pdf",
                        title=f"{self.name}: {document.title}",
                    )
                )
        return files
