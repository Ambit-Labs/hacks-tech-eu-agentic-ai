"""The Modern.Gov two-call flow: find the budget meeting, then take its pack."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.boroughs import _moderngov
from scrooge_indexer.boroughs.lambeth_budget import LambethBudget

MEETINGS = """<?xml version="1.0" encoding="utf-8"?>
<getmeetingsbydate>
  <meetingscount>4</meetingscount>
  <meetings>
    <meeting>
      <meetingid>17354</meetingid>
      <meetingdate>21/01/2026</meetingdate>
      <meetingstatus>Confirmed</meetingstatus>
      <committeeid>142</committeeid>
    </meeting>
    <meeting>
      <meetingid>17355</meetingid>
      <meetingdate>04/03/2026</meetingdate>
      <meetingstatus>Confirmed; Budget Council</meetingstatus>
      <committeeid>142</committeeid>
    </meeting>
    <meeting>
      <meetingid>16966</meetingid>
      <meetingdate>05/03/2025</meetingdate>
      <meetingstatus>Confirmed; Budget Council</meetingstatus>
      <committeeid>142</committeeid>
    </meeting>
    <meeting>
      <meetingid>17100</meetingid>
      <meetingdate>15/09/2025</meetingdate>
      <meetingstatus>Confirmed; Budget Scrutiny</meetingstatus>
      <committeeid>142</committeeid>
    </meeting>
  </meetings>
</getmeetingsbydate>
"""

MEETING = """<?xml version="1.0" encoding="utf-8"?>
<meeting>
  <meetingid>17355</meetingid>
  <meetingdate>04/03/2026</meetingdate>
  <agendaitems>
    <agendaitem>
      <agendaitemtitle>Minutes of the Previous Meeting</agendaitemtitle>
      <linkeddocuments>
        <linkeddoc>
          <title>Minutes</title>
          <url>https://moderngov.lambeth.gov.uk/mgConvert2PDF.aspx?ID=1</url>
          <isrestricted>False</isrestricted>
        </linkeddoc>
      </linkeddocuments>
    </agendaitem>
    <agendaitem>
      <agendaitemtitle>Revenue and Capital Budget 2026/27</agendaitemtitle>
      <linkeddocuments>
        <linkeddoc>
          <title>Budget Report 2026-27 - COUNCIL</title>
          <url>https://moderngov.lambeth.gov.uk/mgConvert2PDF.aspx?ID=174193</url>
          <isrestricted>False</isrestricted>
        </linkeddoc>
        <linkeddoc>
          <title>Appendix 01 - MTFS 2026-30</title>
          <url>https://moderngov.lambeth.gov.uk/mgConvert2PDF.aspx?ID=174195</url>
          <isrestricted>False</isrestricted>
        </linkeddoc>
        <linkeddoc>
          <title>Appendix 02 - Fees &amp;amp; Charges</title>
          <url>https://moderngov.lambeth.gov.uk/mgConvert2PDF.aspx?ID=174196</url>
          <isrestricted>False</isrestricted>
        </linkeddoc>
        <linkeddoc>
          <title>Exempt appendix</title>
          <url>https://moderngov.lambeth.gov.uk/mgConvert2PDF.aspx?ID=174199</url>
          <isrestricted>True</isrestricted>
        </linkeddoc>
        <linkeddoc>
          <title>Budget Report 2026-27 - COUNCIL</title>
          <url>https://moderngov.lambeth.gov.uk/mgConvert2PDF.aspx?ID=174193</url>
          <isrestricted>False</isrestricted>
        </linkeddoc>
      </linkeddocuments>
    </agendaitem>
  </agendaitems>
</meeting>
"""

EMPTY_MEETING = "<?xml version='1.0'?><meeting><agendaitems/></meeting>"


def make_handler(calls: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("GetAllMeetingsByDate"):
            return httpx.Response(200, text=MEETINGS)
        if request.url.params.get("lMeetingId") == "17355":
            return httpx.Response(200, text=MEETING)
        return httpx.Response(200, text=EMPTY_MEETING)

    return handler


@pytest.fixture
def source():
    return LambethBudget()


def test_the_budget_meeting_is_found_by_its_status(client_for, source):
    calls: list[httpx.Request] = []
    client = client_for(make_handler(calls))
    meetings = source.budget_meetings(client, None, None)
    assert [m.id for m in meetings] == ["17355", "16966"]
    # One list call covers the whole history, so the second call is the agenda.
    assert len(calls) == 1
    assert calls[0].url.params["lCommitteeId"] == "142"
    assert calls[0].url.params["sFromDate"] == "01/01/2010"


def test_a_budget_meeting_outside_the_setting_window_is_not_one(client_for, source):
    """September's "Budget Scrutiny" reviews the year; it does not set it."""
    client = client_for(make_handler([]))
    assert "17100" not in {m.id for m in source.budget_meetings(client, None, None)}


def test_a_february_meeting_sets_the_year_that_starts_in_april(client_for, source):
    client = client_for(make_handler([]))
    meetings = {m.id: m for m in source.budget_meetings(client, None, None)}
    assert meetings["17355"].financial_year == 2026
    assert meetings["16966"].financial_year == 2025


def test_a_late_april_budget_meeting_sets_the_year_that_has_just_started():
    """April is inside the setting window, and a budget set then is for the
    year that began that month, not the one after."""
    from datetime import date

    april = _moderngov.Meeting(id="1", date=date(2026, 4, 14), status="Budget")
    assert april.financial_year == 2026
    december = _moderngov.Meeting(id="2", date=date(2026, 12, 1), status="Budget")
    assert december.financial_year == 2027


def test_double_escaped_titles_come_back_as_the_council_wrote_them(client_for):
    """Modern.Gov HTML-escapes before it XML-escapes, so ``&`` arrives as
    ``&amp;amp;``. Left alone it lands on disk as ``Fees-amp-Charges``."""
    client = client_for(make_handler([]))
    docs = _moderngov.meeting_documents(
        client,
        "https://moderngov.lambeth.gov.uk",
        "17355",
        LambethBudget.item_pattern,
    )
    assert "Appendix 02 - Fees & Charges" in {d.title for d in docs}


def test_discover_takes_the_budget_item_and_drops_the_rest(client_for, source):
    calls: list[httpx.Request] = []
    client = client_for(make_handler(calls))
    files = source.discover(client, "2026-04", None)

    assert [f.filename for f in files] == [
        "Budget Report 2026-27 - COUNCIL.pdf",
        "Appendix 01 - MTFS 2026-30.pdf",
        "Appendix 02 - Fees & Charges.pdf",
    ]
    assert {f.period for f in files} == {"2026-04_2027-03"}
    assert {f.format for f in files} == {"pdf"}
    assert files[0].borough == "lambeth-budget"
    # Two calls: the meeting list, then one agenda. 2025 was filtered out
    # before its agenda was fetched.
    assert len(calls) == 2


def test_restricted_and_repeated_attachments_are_skipped(client_for, source):
    client = client_for(make_handler([]))
    urls = [f.url for f in source.discover(client, "2026-04", None)]
    assert len(urls) == len(set(urls))
    assert not any(url.endswith("174199") for url in urls)


def test_every_moderngov_source_names_a_host_and_a_committee():
    from scrooge_indexer.boroughs.brent_budget import BrentBudget
    from scrooge_indexer.boroughs.haringey_budget import HaringeyBudget
    from scrooge_indexer.boroughs.hounslow_budget import HounslowBudget

    for cls in (BrentBudget, HaringeyBudget, HounslowBudget, LambethBudget):
        assert cls.host.startswith("https://") and not cls.host.endswith("/")
        assert isinstance(cls.committee_id, int)
        assert cls.kind == "budget"


def test_a_malformed_meeting_date_is_skipped_not_fatal(client_for):
    broken = MEETINGS.replace("04/03/2026", "not a date")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=broken)

    client = client_for(handler)
    found = _moderngov.meetings(
        client, "https://moderngov.lambeth.gov.uk", 142, 2010, 2027
    )
    assert "17355" not in {m.id for m in found}
    assert "16966" in {m.id for m in found}
