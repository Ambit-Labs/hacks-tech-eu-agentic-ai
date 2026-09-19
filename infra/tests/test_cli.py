"""Argument parsing, password resolution and the plain progress fallback.

None of this touches Modal. The verbs that do reach the network get their
Modal access through one helper each, which these tests do not call.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from spend_infra.cli import (
    ENV_PASSWORD,
    CommandError,
    build_parser,
    resolve_password,
)
from spend_infra.endpoint import build_url
from spend_infra.progress import Waiter, out_console, waiting


@pytest.fixture
def parser():
    return build_parser()


# -- parsing ---------------------------------------------------------------- #


@pytest.mark.parametrize(
    "verb", ["start", "stop", "status", "url", "psql", "dump", "restore", "deploy"]
)
def test_every_verb_parses_bare(parser, verb):
    args = parser.parse_args([verb])
    assert args.command == verb
    assert callable(args.func)


def test_a_verb_is_required(parser):
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_an_unknown_verb_is_rejected(parser):
    with pytest.raises(SystemExit):
        parser.parse_args(["vacuum"])


def test_start_flags(parser):
    args = parser.parse_args(
        [
            "start",
            "--dump-interval",
            "120",
            "--timeout",
            "60",
            "--force",
            "--no-restore",
        ]
    )
    assert (args.dump_interval, args.timeout) == (120, 60)
    assert args.force and args.no_restore


def test_start_leaves_the_interval_unset_so_the_env_can_win(parser):
    assert parser.parse_args(["start"]).dump_interval is None


def test_url_defaults_to_the_postgres_database(parser):
    args = parser.parse_args(["url"])
    assert args.database == "postgres"
    assert not args.no_password


def test_psql_passes_the_tail_through(parser):
    args = parser.parse_args(["psql", "--", "-c", "select 1"])
    assert args.psql_args == ["--", "-c", "select 1"]


def test_restore_has_a_confirmation_gate(parser):
    assert parser.parse_args(["restore"]).yes is False
    assert parser.parse_args(["restore", "--yes"]).yes is True


def test_restore_can_just_list(parser):
    args = parser.parse_args(["restore", "--list"])
    assert args.list and args.archive is None


# -- password --------------------------------------------------------------- #


def test_password_prefers_the_flag(monkeypatch):
    monkeypatch.setenv(ENV_PASSWORD, "from-env")
    assert resolve_password("from-flag") == "from-flag"


def test_password_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_PASSWORD, "from-env")
    assert resolve_password(None) == "from-env"


def test_password_missing_names_the_secret(monkeypatch):
    monkeypatch.delenv(ENV_PASSWORD, raising=False)
    with pytest.raises(CommandError) as caught:
        resolve_password(None)
    message = str(caught.value)
    assert ENV_PASSWORD in message and "spend-postgres" in message


# -- progress --------------------------------------------------------------- #


def piped_console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, force_terminal=False, width=100), buffer


def test_a_piped_wait_still_says_something():
    # Rich's Live renders nothing through a pipe, so `pg start` under cron
    # would otherwise be silent for the whole cold start.
    console, buffer = piped_console()
    with waiting(console, "waiting") as waiter:
        waiter.note("tunnel at h:1")
    text = buffer.getvalue()
    assert "waiting: starting" in text
    assert "tunnel at h:1" in text
    assert "waiting: done" in text


def test_a_piped_wait_reports_an_exception_as_stopped():
    console, buffer = piped_console()
    with pytest.raises(KeyboardInterrupt), waiting(console, "waiting"):
        raise KeyboardInterrupt
    assert "waiting: stopped" in buffer.getvalue()


def test_plain_updates_are_rate_limited():
    console, buffer = piped_console()
    waiter = Waiter(console, "waiting", interval=3600)
    waiter._start()
    for _ in range(50):
        waiter.update("still going")
    assert buffer.getvalue().count("still going") == 0


def test_plain_updates_do_print_once_the_interval_passes():
    console, buffer = piped_console()
    waiter = Waiter(console, "waiting", interval=0)
    waiter._start()
    waiter.update("still going")
    assert "still going" in buffer.getvalue()


# -- stdout ----------------------------------------------------------------- #


def test_stdout_never_wraps_a_long_url(monkeypatch):
    # The first live run of `$(pg url)` produced a URL with a newline inside
    # the database name: rich folded the 100 character line at the 80
    # column default width of a pipe, and psycopg then asked the server for
    # a database called "pos\ntgres".
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)
    console = out_console()
    console.file = buffer
    console.width = 40
    url = build_url("r437.modal.host", 35619, "x" * 64)
    console.print(url)
    assert buffer.getvalue() == url + "\n"


def test_stdout_does_not_parse_markup_in_a_password():
    buffer = io.StringIO()
    console = out_console()
    console.file = buffer
    url = build_url("h", 1, "pw[bold]with[/bold]brackets")
    console.print(url)
    assert buffer.getvalue() == url + "\n"
