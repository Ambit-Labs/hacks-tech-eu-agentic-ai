"""The HTTP layer, driven entirely by ``httpx.MockTransport``. No network."""

from __future__ import annotations

import httpx
import pytest

from spend_indexer.http import (
    Blocked,
    FetchError,
    NotPublished,
    PoliteTransport,
    download_to,
    part_path,
    request_with_retries,
)
from spend_indexer.models import RemoteFile


def _remote(url="https://example.invalid/a.csv", **kwargs) -> RemoteFile:
    return RemoteFile(
        borough="testborough",
        period="2026-07",
        url=url,
        filename="a.csv",
        format="csv",
        **kwargs,
    )


def test_user_agent_names_the_tool(client_for):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, text="ok")

    client = client_for(handler)
    request_with_retries(client, "GET", "https://example.invalid/")
    assert seen["ua"].startswith("spend-indexer/")
    assert "Mozilla" not in seen["ua"]


def test_retries_a_503_then_succeeds(client_for):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200 if len(calls) == 3 else 503, text="body")

    client = client_for(handler)
    response = request_with_retries(
        client, "GET", "https://example.invalid/", sleep=lambda _: None
    )
    assert response.status_code == 200
    assert len(calls) == 3


def test_gives_up_after_four_tries(client_for):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    client = client_for(handler)
    with pytest.raises(FetchError):
        request_with_retries(
            client, "GET", "https://example.invalid/", sleep=lambda _: None
        )
    assert len(calls) == 4


def test_transport_errors_are_retried_then_raised(client_for):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("boom")

    client = client_for(handler)
    with pytest.raises(FetchError):
        request_with_retries(
            client, "GET", "https://example.invalid/", sleep=lambda _: None
        )
    assert len(calls) == 4


def test_403_is_blocked_and_not_retried(client_for):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403)

    client = client_for(handler)
    with pytest.raises(Blocked):
        request_with_retries(client, "GET", "https://example.invalid/")
    assert len(calls) == 1


def test_404_is_not_published_and_not_retried(client_for):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404, text="<html>404 page</html>")

    client = client_for(handler)
    with pytest.raises(NotPublished):
        request_with_retries(client, "GET", "https://example.invalid/")
    assert len(calls) == 1


def test_download_to_writes_atomically_and_leaves_no_part(client_for, tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            content=b"Directorate,Payment Date\nA,01/07/2026\n",
            headers={
                "Content-Type": "text/csv",
                "ETag": 'W/"abc"',
                "Last-Modified": "Wed, 02 Sep 2026 00:00:00 GMT",
            },
        )

    dest = tmp_path / "2026-07__a.csv"
    client = client_for(handler)
    result = download_to(client, _remote(), dest)

    assert dest.read_bytes().startswith(b"Directorate")
    assert not part_path(dest).exists()
    assert result.bytes == 38
    assert result.content_type == "text/csv"
    assert result.etag == 'W/"abc"'
    assert result.last_modified == "Wed, 02 Sep 2026 00:00:00 GMT"
    assert len(result.sha256) == 64


def test_a_failed_download_removes_the_part_and_writes_no_file(client_for, tmp_path):
    def handler(request):
        return httpx.Response(500)

    dest = tmp_path / "2026-07__a.csv"
    client = client_for(handler)
    with pytest.raises(FetchError):
        download_to(client, _remote(), dest, sleep=lambda _: None)

    assert not dest.exists()
    assert not part_path(dest).exists()


def test_an_interrupt_mid_stream_removes_the_part(client_for, tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"x" * 4096)

    dest = tmp_path / "2026-07__a.csv"

    def explode(_n):
        raise KeyboardInterrupt

    client = client_for(handler)
    with pytest.raises(KeyboardInterrupt):
        download_to(client, _remote(), dest, on_bytes=explode)

    assert not dest.exists()
    assert not part_path(dest).exists()


def test_304_leaves_the_file_alone(client_for, tmp_path):
    def handler(request):
        assert request.headers["If-None-Match"] == 'W/"abc"'
        return httpx.Response(304)

    dest = tmp_path / "2026-07__a.csv"
    dest.write_bytes(b"old but current")
    client = client_for(handler)
    result = download_to(
        client, _remote(mutable=True), dest, conditional={"If-None-Match": 'W/"abc"'}
    )

    assert result.status == "unchanged"
    assert dest.read_bytes() == b"old but current"


def test_a_bot_challenge_body_is_blocked_not_saved(client_for, tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            content=b"<html><title>Just a moment...</title></html>",
            headers={"Content-Type": "text/html"},
        )

    dest = tmp_path / "2026-07__a.csv"
    client = client_for(handler)
    with pytest.raises(Blocked):
        download_to(client, _remote(), dest)
    assert not dest.exists()
    assert not part_path(dest).exists()


def test_polite_transport_spaces_requests_per_host():
    slept: list[float] = []
    clock = {"t": 0.0}

    def handler(request):
        return httpx.Response(200)

    transport = PoliteTransport(
        httpx.MockTransport(handler),
        delay=0.5,
        sleep=slept.append,
        clock=lambda: clock["t"],
    )
    with httpx.Client(transport=transport) as client:
        client.get("https://a.invalid/1")
        client.get("https://a.invalid/2")
        client.get("https://b.invalid/1")

    # First call to each host is free, the second to the same host waits.
    assert slept == [0.5]
