"""Camden: month discovery from the SoQL aggregate, and ``$offset`` paging."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from spend_indexer.boroughs import camden
from spend_indexer.boroughs.camden import Camden
from spend_indexer.http import NotPublished, part_path

AGGREGATE = [
    {"m": "2026-06-01T00:00:00.000", "n": "5252"},
    {"m": "2026-07-01T00:00:00.000", "n": "5618"},
    {"m": "2026-08-01T00:00:00.000", "n": "4798"},
]


def aggregate_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path.endswith(".json")
    params = parse_qs(request.url.query.decode())
    assert params["$group"] == ["m"]
    return httpx.Response(200, json=AGGREGATE)


def test_discover_turns_the_aggregate_into_one_file_per_month(client_for, monkeypatch):
    monkeypatch.setattr(camden, "current_month", lambda *_: "2026-09")
    client = client_for(aggregate_handler)
    files = Camden().discover(client, None, None)

    assert [f.period for f in files] == ["2026-06", "2026-07", "2026-08"]
    assert all(f.filename == "camden-payments.csv" for f in files)
    assert all(f.borough == "camden" for f in files)


def test_the_current_and_previous_months_are_mutable(client_for, monkeypatch):
    monkeypatch.setattr(camden, "current_month", lambda *_: "2026-09")
    client = client_for(aggregate_handler)
    mutable = {f.period: f.mutable for f in Camden().discover(client, None, None)}
    assert mutable == {"2026-06": False, "2026-07": False, "2026-08": True}


def test_discover_honours_since_and_until(client_for, monkeypatch):
    monkeypatch.setattr(camden, "current_month", lambda *_: "2026-09")
    client = client_for(aggregate_handler)
    files = Camden().discover(client, "2026-07", "2026-07")
    assert [f.period for f in files] == ["2026-07"]


def test_each_month_gets_its_own_url_and_a_bounded_where():
    url = camden.month_query_url("2026-08")
    query = parse_qs(urlsplit(url).query)
    assert query["$where"] == [
        "payment_date >= '2026-08-01' AND payment_date < '2026-09-01'"
    ]
    assert query["$order"] == ["unique_identifier"]
    assert camden.month_query_url("2026-07") != url


@pytest.mark.parametrize("rows", [3, 7])
def test_fetch_pages_with_offset_and_keeps_one_header(
    client_for, tmp_path, monkeypatch, rows
):
    """A month larger than one page is stitched into a single CSV.

    The page limit is lowered here rather than faking 50,000 rows: what is
    under test is the stitching, not Socrata's cap.
    """
    monkeypatch.setattr(camden, "PAGE_LIMIT", 3)
    seen_offsets = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = parse_qs(request.url.query.decode())
        offset = int(params.get("$offset", ["0"])[0])
        seen_offsets.append(offset)
        remaining = max(rows - offset, 0)
        body = "unique_identifier,amount_gbp\n" + "".join(
            f"id{offset + i},{100 + offset + i}\n" for i in range(min(remaining, 3))
        )
        return httpx.Response(200, text=body, headers={"Content-Type": "text/csv"})

    dest = tmp_path / "2026-08__camden-payments.csv"
    client = client_for(handler)
    result = Camden().fetch(client, _remote(), dest)

    lines = dest.read_text().splitlines()
    assert lines[0] == "unique_identifier,amount_gbp"
    assert len([line for line in lines if line.startswith("id")]) == rows
    assert lines.count("unique_identifier,amount_gbp") == 1
    # A full page is always followed by one more request: a page that fills the
    # limit exactly is indistinguishable from a page with more behind it.
    assert seen_offsets == ([0, 3] if rows == 3 else [0, 3, 6])
    assert result.bytes == dest.stat().st_size
    assert not part_path(dest).exists()


def test_fetch_cleans_up_the_part_when_a_later_page_fails(
    client_for, tmp_path, monkeypatch
):
    """A month that dies halfway through paging leaves nothing behind.

    The alternative would be a ``.part`` holding two of three pages, and the
    run after it would have no way to tell that from a finished file.
    """
    monkeypatch.setattr(camden, "PAGE_LIMIT", 3)

    def handler(request: httpx.Request) -> httpx.Response:
        if "$offset" in request.url.query.decode():
            return httpx.Response(404)
        return httpx.Response(200, text="id,amount\na,1\nb,2\nc,3\n")

    dest = tmp_path / "2026-08__camden-payments.csv"
    client = client_for(handler)
    with pytest.raises(NotPublished):
        Camden().fetch(client, _remote(), dest)
    assert not dest.exists()
    assert not part_path(dest).exists()


def _remote():
    from spend_indexer.models import RemoteFile

    return RemoteFile(
        borough="camden",
        period="2026-08",
        url=camden.month_query_url("2026-08"),
        filename="camden-payments.csv",
        format="csv",
    )
