"""Argparse shape, file selection and skip rules for the three database verbs.

Nothing here connects to anything: the usage paths exit before a connection is
opened, and the selection tests walk a data directory built in `tmp_path`.
"""

from __future__ import annotations

import pytest

from scrooge_indexer import cli
from scrooge_indexer.loader import db, runner
from scrooge_indexer.loader import files as spend_files


def make_tree(tmp_path, names: dict[str, list[str]]):
    for slug, filenames in names.items():
        directory = tmp_path / "raw" / slug
        directory.mkdir(parents=True)
        for name in filenames:
            (directory / name).write_text("Payment Date,Payee\n")
    return tmp_path


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #


def test_load_without_a_borough_is_a_usage_error(capsys):
    assert cli.main(["load"]) == cli.EXIT_USAGE
    assert "known boroughs" in capsys.readouterr().err


def test_load_rejects_a_borough_with_no_mapping(capsys, tmp_path):
    code = cli.main(["load", "bromley", "--data-dir", str(tmp_path)])
    assert code == cli.EXIT_USAGE
    assert "no column mapping" in capsys.readouterr().err


def test_load_validates_the_period_flags(capsys, tmp_path):
    code = cli.main(["load", "camden", "--since", "2019", "--data-dir", str(tmp_path)])
    assert code == cli.EXIT_USAGE
    assert "--since must be YYYY-MM" in capsys.readouterr().err


def test_db_needs_a_subcommand():
    with pytest.raises(SystemExit) as caught:
        cli.build_parser().parse_args(["db"])
    assert caught.value.code == cli.EXIT_USAGE


def test_load_status_takes_an_optional_problem_count():
    parser = cli.build_parser()
    assert parser.parse_args(["load-status"]).problems == 0
    assert parser.parse_args(["load-status", "--problems"]).problems == 50
    assert parser.parse_args(["load-status", "--problems", "5"]).problems == 5


def test_a_missing_database_url_is_reported_not_raised(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv(db.ENV_DATABASE_URL, raising=False)
    monkeypatch.setattr(db, "load_env", lambda *_: None)
    assert cli.main(["load-status"]) == cli.EXIT_FAILURES
    assert "pg url" in capsys.readouterr().err


def test_a_refused_write_is_reported_not_raised(capsys, monkeypatch):
    """The read-only `agent` login in `.env.local` is one forgotten export away."""
    psycopg = pytest.importorskip("psycopg")

    def refuse(*_):
        raise psycopg.errors.InsufficientPrivilege(
            "permission denied for table payments"
        )

    monkeypatch.setattr(db, "connect", refuse)
    assert cli.main(["load-status"]) == cli.EXIT_FAILURES
    err = capsys.readouterr().err
    assert "permission denied for table payments" in err
    assert "read-only" in err


def test_the_resume_command_repeats_the_window_and_drops_force():
    args = cli.build_parser().parse_args(
        ["load", "camden", "--since", "2019-09", "--until", "2019-10", "--force"]
    )
    resumed = cli._load_resume_command(args)
    assert resumed == "scrooge load camden --since 2019-09 --until 2019-10"


def test_the_resume_command_keeps_all_and_limit():
    args = cli.build_parser().parse_args(["load", "--all", "--limit", "3"])
    assert cli._load_resume_command(args) == "scrooge load --all --limit 3"


# --------------------------------------------------------------------------- #
# choosing files
# --------------------------------------------------------------------------- #


def test_the_period_comes_from_the_filename_prefix(tmp_path):
    make_tree(
        tmp_path,
        {
            "camden": [
                "2019-09__camden-payments.csv",
                "2019-10__camden-payments.csv",
                "manifest.json",
            ]
        },
    )
    found = spend_files.borough_files(tmp_path, "camden")
    assert [f.period for f in found] == ["2019-09", "2019-10"]
    assert found[0].relpath == "data/raw/camden/2019-09__camden-payments.csv"


def test_range_and_quarter_periods_survive_the_prefix(tmp_path):
    make_tree(
        tmp_path,
        {"bexley": ["2013-04_2013-09__April-to-September-2013.csv", "2018-Q2__q2.csv"]},
    )
    found = spend_files.borough_files(tmp_path, "bexley")
    assert {f.period for f in found} == {"2013-04_2013-09", "2018-Q2"}


def test_since_and_until_keep_a_range_that_straddles_the_window(tmp_path):
    make_tree(
        tmp_path,
        {
            "bexley": [
                "2013-04_2013-09__half-year.csv",
                "2019-10__Oct_2019.csv",
                "2024-06__june-2024.csv",
            ]
        },
    )
    chosen = spend_files.select(tmp_path, ["bexley"], since="2013-06", until="2013-07")
    assert [f.name for f in chosen] == ["2013-04_2013-09__half-year.csv"]


def test_limit_takes_the_most_recent(tmp_path):
    make_tree(
        tmp_path,
        {"camden": ["2019-09__a.csv", "2019-10__b.csv", "2019-11__c.csv"]},
    )
    chosen = spend_files.select(tmp_path, ["camden"], limit=2)
    assert [f.period for f in chosen] == ["2019-10", "2019-11"]


def test_the_manifest_period_wins_over_the_filename(tmp_path):
    make_tree(tmp_path, {"camden": ["2019-09__camden-payments.csv"]})
    (tmp_path / "raw" / "camden" / "manifest.json").write_text(
        '{"borough": "camden", "kind": "spend", "entries": {"k": {'
        '"url": "https://example.invalid/x.csv", "period": "2019-08", '
        '"path": "raw/camden/2019-09__camden-payments.csv", "bytes": 1, '
        '"fetched_at": "2026-09-19T00:00:00+00:00", "status": "ok"}}}'
    )
    (found,) = spend_files.borough_files(tmp_path, "camden")
    assert found.period == "2019-08"


def test_known_boroughs_needs_both_a_mapping_and_a_directory(tmp_path):
    make_tree(tmp_path, {"camden": ["2019-09__a.csv"], "lewisham": []})
    (tmp_path / "raw" / "bromley").mkdir()
    assert spend_files.known_boroughs(tmp_path) == ["camden", "lewisham"]


# --------------------------------------------------------------------------- #
# resume rules
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "plain", "forced"),
    [
        ("loaded", True, False),
        ("skipped", True, False),
        ("failed", False, False),
    ],
)
def test_should_skip_by_status(status, plain, forced):
    state = db.FileState(status=status, rows_loaded=0, reason=None)
    assert runner.should_skip(state, force=False) is plain
    assert runner.should_skip(state, force=True) is forced


def test_a_file_the_database_has_never_seen_is_loaded():
    assert runner.should_skip(None, force=False) is False
