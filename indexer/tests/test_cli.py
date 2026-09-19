"""Exit codes, resume, and the download loop end to end over a mocked network."""

from __future__ import annotations

import httpx
import pytest

from spend_indexer import cli, manifest
from spend_indexer.boroughs import _umbraco, camden

CAMDEN_AGGREGATE = [
    {"m": "2026-06-01T00:00:00.000", "n": "3"},
    {"m": "2026-07-01T00:00:00.000", "n": "2"},
]

RICHMOND_LANDING = """
<html><body>
  <a href="/media/aaaa1111/council_expenditure_july_2026.csv">July 2026</a>
  <a href="/media/bbbb2222/council_expenditure_june_2026.csv">June 2026</a>
  <a href="/media/cccc3333/council_expenditure_may_2026.csv">May 2026</a>
  <a href="/media/dddd4444/council_expenditure_april_2026.csv">April 2026</a>
  <a href="/media/eeee5555/council_expenditure_march_2026.csv">March 2026</a>
  <a href="/media/ffff6666/council_expenditure_february_2026.csv">February 2026</a>
</body></html>
"""


def fake_london(request: httpx.Request) -> httpx.Response:
    """One handler standing in for three councils."""
    host, path = request.url.host, request.url.path
    if host == "opendata.camden.gov.uk":
        if path.endswith(".json"):
            return httpx.Response(200, json=CAMDEN_AGGREGATE)
        return httpx.Response(
            200,
            text="unique_identifier,amount_gbp\nid1,100\n",
            headers={"Content-Type": "text/csv"},
        )
    if path.endswith(".csv"):
        return httpx.Response(
            200,
            text="Directorate,Payment Date\nAdults,01/07/2026\n",
            headers={"Content-Type": "text/csv"},
        )
    return httpx.Response(
        200, text=RICHMOND_LANDING, headers={"Content-Type": "text/html"}
    )


@pytest.fixture
def offline(monkeypatch, client_for):
    """Point the CLI at a mocked network and a fixed 'today'."""
    monkeypatch.setattr(cli, "make_client", lambda **_: client_for(fake_london))
    monkeypatch.setattr(camden, "current_month", lambda *_: "2026-09")
    monkeypatch.setattr(_umbraco, "current_month", lambda *_: "2026-09")


def test_download_without_a_borough_is_a_usage_error(capsys):
    assert cli.main(["download"]) == cli.EXIT_USAGE
    assert "spend list" in capsys.readouterr().err


def test_an_unknown_borough_is_a_usage_error(capsys, tmp_path):
    code = cli.main(["download", "atlantis", "--data-dir", str(tmp_path)])
    assert code == cli.EXIT_USAGE
    assert "unknown borough" in capsys.readouterr().err


def test_a_malformed_since_is_a_usage_error(capsys, tmp_path):
    code = cli.main(
        ["download", "camden", "--since", "June 2026", "--data-dir", str(tmp_path)]
    )
    assert code == cli.EXIT_USAGE
    assert "--since must be YYYY-MM" in capsys.readouterr().err


def test_list_and_status_exit_zero(capsys, tmp_path):
    assert cli.main(["list", "--data-dir", str(tmp_path)]) == cli.EXIT_OK
    assert cli.main(["status", "--data-dir", str(tmp_path)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "camden" in out


def test_download_then_resume(offline, capsys, tmp_path):
    argv = [
        "download",
        "camden",
        "richmond",
        "--since",
        "2026-06",
        "--until",
        "2026-07",
        "--data-dir",
        str(tmp_path),
    ]
    assert cli.main(argv) == cli.EXIT_OK
    capsys.readouterr()

    names = sorted(p.name for p in (tmp_path / "raw/camden").glob("*.csv"))
    assert names == ["2026-06__camden-payments.csv", "2026-07__camden-payments.csv"]
    assert (
        tmp_path / "raw/richmond/2026-07__council_expenditure_july_2026.csv"
    ).exists()
    assert not list(tmp_path.rglob("*.part"))

    # Second run: everything is already on disk and nothing is fetched again.
    assert cli.main(argv) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert "4 already on disk" in captured.err
    assert "skipped=4" in captured.err


def test_a_mutable_month_is_rechecked_on_every_run(offline, capsys, tmp_path):
    """August is the current-ish month, so Camden keeps adding to it.

    A mutable file is never "already on disk": it is re-checked every run and
    replaced when the source changed.
    """
    argv = ["download", "camden", "--since", "2026-08", "--data-dir", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(argv) == cli.EXIT_OK
    assert "0 already on disk" in capsys.readouterr().err


def test_a_304_on_a_mutable_file_counts_as_skipped(
    monkeypatch, client_for, capsys, tmp_path
):
    state = {"served": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".json"):
            return httpx.Response(
                200, json=[{"m": "2026-08-01T00:00:00.000", "n": "1"}]
            )
        if state["served"]:
            return httpx.Response(304)
        state["served"] = True
        return httpx.Response(
            200, text="unique_identifier\nid1\n", headers={"ETag": 'W/"v1"'}
        )

    monkeypatch.setattr(cli, "make_client", lambda **_: client_for(handler))
    monkeypatch.setattr(camden, "current_month", lambda *_: "2026-09")
    argv = ["download", "camden", "--since", "2026-08", "--data-dir", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(argv) == cli.EXIT_OK
    assert "skipped=1" in capsys.readouterr().err


def test_force_refetches_everything(offline, capsys, tmp_path):
    argv = ["download", "camden", "--since", "2026-06", "--data-dir", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main([*argv, "--force"]) == cli.EXIT_OK
    assert "0 already on disk" in capsys.readouterr().err


def test_limit_takes_the_most_recent_files(offline, capsys, tmp_path):
    code = cli.main(
        [
            "download",
            "richmond",
            "--since",
            "2026-02",
            "--limit",
            "2",
            "--data-dir",
            str(tmp_path),
        ]
    )
    assert code == cli.EXIT_OK
    periods = sorted(p.name[:7] for p in (tmp_path / "raw/richmond").glob("*.csv"))
    assert periods == ["2026-06", "2026-07"]


def test_a_failure_gives_a_non_zero_exit_and_a_manifest_record(
    monkeypatch, client_for, capsys, tmp_path
):
    def broken(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".json"):
            return httpx.Response(200, json=CAMDEN_AGGREGATE)
        return httpx.Response(403)

    monkeypatch.setattr(cli, "make_client", lambda **_: client_for(broken))
    monkeypatch.setattr(camden, "current_month", lambda *_: "2026-09")
    code = cli.main(
        ["download", "camden", "--since", "2026-06", "--data-dir", str(tmp_path)]
    )
    assert code == cli.EXIT_FAILURES

    book = manifest.load(tmp_path, "camden")
    assert {e.status for e in book.entries.values()} == {"blocked"}
    assert not list(tmp_path.rglob("*.part"))


def test_ctrl_c_exits_130_and_prints_a_resume_command(
    monkeypatch, client_for, capsys, tmp_path
):
    def interrupt(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".json"):
            return httpx.Response(200, json=CAMDEN_AGGREGATE)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "make_client", lambda **_: client_for(interrupt))
    monkeypatch.setattr(camden, "current_month", lambda *_: "2026-09")
    code = cli.main(
        [
            "download",
            "camden",
            "--since",
            "2026-06",
            "--limit",
            "2",
            "--data-dir",
            str(tmp_path),
        ]
    )
    assert code == cli.EXIT_INTERRUPTED
    err = capsys.readouterr().err
    assert "spend download camden --since 2026-06" in err
    assert "--limit 2" in err
    assert not list(tmp_path.rglob("*.part"))


def test_the_manifest_survives_an_interrupt_after_the_first_file(
    monkeypatch, client_for, tmp_path
):
    """One file lands, the next is interrupted. The first must still be recorded."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".json"):
            return httpx.Response(200, json=CAMDEN_AGGREGATE)
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt
        return httpx.Response(200, text="unique_identifier\nid1\n")

    monkeypatch.setattr(cli, "make_client", lambda **_: client_for(handler))
    monkeypatch.setattr(camden, "current_month", lambda *_: "2026-09")
    code = cli.main(
        ["download", "camden", "--since", "2026-06", "--data-dir", str(tmp_path)]
    )
    assert code == cli.EXIT_INTERRUPTED

    book = manifest.load(tmp_path, "camden")
    done = [e for e in book.entries.values() if e.status == "ok"]
    assert len(done) == 1
    assert (tmp_path / done[0].path).is_file()
    assert not list(tmp_path.rglob("*.part"))
