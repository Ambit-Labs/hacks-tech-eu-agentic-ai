"""The ``pg`` command: start the Modal Postgres, find it, connect to it.

argparse with one subparser per verb, the same shape as ``spend`` in
``indexer/``. Results go to stdout so ``$(pg url)`` works and a table can be
piped; progress and diagnostics go to stderr so the pipe stays clean.

``modal`` is imported inside the verbs rather than at module scope. It pulls
in grpc and takes about a second, and ``pg --help`` should not pay for that.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from . import __version__
from .endpoint import (
    APP_NAME,
    ENDPOINT_DICT_NAME,
    ENDPOINT_KEY,
    PASSWORD_KEY,
    PASSWORD_PLACEHOLDER,
    PG_DATABASE,
    PG_USER,
    SECRET_NAME,
    Endpoint,
    build_url,
    format_uptime,
    is_stale,
    parse_endpoint,
    uptime_seconds,
)
from .progress import out_console, stderr_console, waiting

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

#: Env var holding the postgres superuser password on a client machine.
ENV_PASSWORD = "SPEND_PG_PASSWORD"

#: Env var overriding the dump interval `pg start` asks the server for.
ENV_DUMP_INTERVAL = "SPEND_PG_DUMP_INTERVAL"

#: Keys inside the endpoint Dict, mirrored from postgres_app so the CLI does
#: not import the app module and therefore does not need the Modal image.
CONTROL_KEY = "control"
RESULT_KEY = "last_request"

DEFAULT_DUMP_INTERVAL = 600
START_TIMEOUT = 900
STOP_TIMEOUT = 300
REQUEST_TIMEOUT = 900

MODULE = "spend_infra.postgres_app"


class CommandError(Exception):
    """A failure with a message already fit to print."""


# --------------------------------------------------------------------------- #
# Modal access
# --------------------------------------------------------------------------- #


def _dict():
    """The endpoint Dict, resolved against whatever profile the env selects.

    Every call that touches Modal goes through here, so an unauthenticated
    machine gets one clear message instead of a grpc traceback per verb.
    `from_name` only builds a handle, so this hydrates it too, otherwise the
    auth failure would surface from the caller's first `get` instead.
    """
    import modal

    try:
        store = modal.Dict.from_name(ENDPOINT_DICT_NAME, create_if_missing=True)
        store.hydrate()
        return store
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the user
        raise CommandError(
            f"cannot reach Modal ({type(exc).__name__}: "
            f"{str(exc).strip().splitlines()[0]}). "
            "Run `uv run modal token new`, or set MODAL_TOKEN_ID and "
            "MODAL_TOKEN_SECRET. See docs/runbook.md."
        ) from exc


def _lookup_function(name: str):
    """A function from the deployed app, resolved now rather than on call."""
    import modal

    try:
        function = modal.Function.from_name(APP_NAME, name)
        function.hydrate()
        return function
    except Exception as exc:  # noqa: BLE001
        raise CommandError(
            f"cannot use {APP_NAME}/{name} ({type(exc).__name__}: "
            f"{str(exc).strip().splitlines()[0]}). Run `pg deploy` first."
        ) from exc


def _read_endpoint(store) -> Endpoint | None:
    return parse_endpoint(store.get(ENDPOINT_KEY))


def _set_control(store, **fields) -> dict:
    control = store.get(CONTROL_KEY)
    control = dict(control) if isinstance(control, dict) else {}
    control.update(fields)
    control["updated_at"] = datetime.now(UTC).isoformat()
    store[CONTROL_KEY] = control
    return control


# --------------------------------------------------------------------------- #
# Password
# --------------------------------------------------------------------------- #


def resolve_password(explicit: str | None) -> str:
    password = explicit or os.environ.get(ENV_PASSWORD)
    if not password:
        raise CommandError(
            f"no password. Set {ENV_PASSWORD} in the environment or pass "
            "--password. It must match the "
            f"{PASSWORD_KEY} key of the Modal secret {SECRET_NAME}."
        )
    return password


# --------------------------------------------------------------------------- #
# pg start
# --------------------------------------------------------------------------- #


def cmd_start(args: argparse.Namespace, out: Console, err: Console) -> int:
    interval = args.dump_interval or int(
        os.environ.get(ENV_DUMP_INTERVAL) or DEFAULT_DUMP_INTERVAL
    )
    store = _dict()
    existing = _read_endpoint(store)
    if existing is not None and not is_stale(existing) and not args.force:
        err.print(
            f"already running at {existing.address}, up "
            f"{format_uptime(uptime_seconds(existing))}. --force starts another."
        )
        out.print(existing.address)
        return EXIT_OK

    err.print(
        f"start: spawning {APP_NAME}/server on Modal, dumping every {interval}s, "
        f"waiting up to {args.timeout}s for a tunnel address"
    )
    previous_container = existing.container_id if existing else None
    _set_control(store, desired="running", dump_interval=interval)
    function = _lookup_function("server")
    call = function.spawn(dump_interval=interval, restore=not args.no_restore)
    err.print(f"start: function call {call.object_id}")

    deadline = time.monotonic() + args.timeout
    with waiting(err, "waiting for the tunnel") as waiter:
        while time.monotonic() < deadline:
            endpoint = _read_endpoint(store)
            if (
                endpoint is not None
                and not is_stale(endpoint)
                and endpoint.container_id != previous_container
            ):
                waiter.note(f"tunnel at {endpoint.address}")
                out.print(endpoint.address)
                return EXIT_OK
            waiter.update("cold start: image, initdb, restore")
            time.sleep(3)

    raise CommandError(
        f"no endpoint after {args.timeout}s. The container may still be building "
        f"the image. Check `modal app logs {APP_NAME}`, then `pg status`."
    )


# --------------------------------------------------------------------------- #
# pg stop
# --------------------------------------------------------------------------- #


def cmd_stop(args: argparse.Namespace, out: Console, err: Console) -> int:
    store = _dict()
    endpoint = _read_endpoint(store)
    err.print(
        "stop: asking the server to dump and shut down"
        + (f", currently at {endpoint.address}" if endpoint else ", none published")
    )
    _set_control(store, desired="stopped")
    if endpoint is None:
        err.print("stop: nothing published, the supervisor will leave it alone")
        return EXIT_OK

    deadline = time.monotonic() + args.timeout
    with waiting(err, "waiting for a final dump and a clean shutdown") as waiter:
        while time.monotonic() < deadline:
            current = _read_endpoint(store)
            if current is None or current.container_id != endpoint.container_id:
                waiter.note("server stopped")
                return EXIT_OK
            waiter.update("final pg_dumpall, then pg_ctl stop -m fast")
            time.sleep(3)

    raise CommandError(
        f"still published after {args.timeout}s. The container may be dumping a "
        f"large database. To kill it anyway: `modal app stop {APP_NAME}`."
    )


# --------------------------------------------------------------------------- #
# pg status
# --------------------------------------------------------------------------- #


def _reachable(url: str, timeout: float) -> tuple[bool, str]:
    try:
        import psycopg
    except ImportError:  # pragma: no cover - psycopg is a hard dependency
        return False, "psycopg not installed"
    try:
        with psycopg.connect(url, connect_timeout=int(timeout)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
        return True, version.split(" on ")[0]
    except Exception as exc:  # noqa: BLE001 - any failure is unreachable
        return False, f"{type(exc).__name__}: {str(exc).strip().splitlines()[0]}"


def cmd_status(args: argparse.Namespace, out: Console, err: Console) -> int:
    store = _dict()
    endpoint = _read_endpoint(store)
    control = store.get(CONTROL_KEY)
    desired = control.get("desired") if isinstance(control, dict) else "unset"

    if endpoint is None:
        out.print(f"state       stopped (desired: {desired})")
        err.print(f"status: nothing published in the {ENDPOINT_DICT_NAME} dict")
        return EXIT_FAILURES

    stale = is_stale(endpoint)
    beat = endpoint.heartbeat_at or endpoint.started_at
    beat_age = (datetime.now(UTC) - beat).total_seconds()

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("state", "stale heartbeat" if stale else "running")
    table.add_row("desired", str(desired))
    table.add_row("address", endpoint.address)
    table.add_row("uptime", format_uptime(uptime_seconds(endpoint)))
    table.add_row("started", endpoint.started_at.isoformat())
    table.add_row("heartbeat", f"{format_uptime(beat_age)} ago")
    table.add_row("container", endpoint.container_id)

    password = args.password or os.environ.get(ENV_PASSWORD)
    if args.no_check:
        table.add_row("postgres", "not checked (--no-check)")
    elif not password:
        table.add_row("postgres", f"not checked (no {ENV_PASSWORD})")
    else:
        url = build_url(endpoint.host, endpoint.port, password)
        with waiting(err, "connecting"):
            ok, detail = _reachable(url, args.connect_timeout)
        table.add_row("postgres", ("SELECT 1 ok, " + detail) if ok else detail)
        if not ok:
            out.print(table)
            return EXIT_FAILURES

    out.print(table)
    return EXIT_FAILURES if stale else EXIT_OK


# --------------------------------------------------------------------------- #
# pg url, pg psql
# --------------------------------------------------------------------------- #


def _require_endpoint(store) -> Endpoint:
    endpoint = _read_endpoint(store)
    if endpoint is None:
        raise CommandError("no endpoint published. Start the server with `pg start`.")
    if is_stale(endpoint):
        raise CommandError(
            f"the endpoint at {endpoint.address} has a stale heartbeat, so the "
            "container is probably gone. Run `pg start` for a fresh one."
        )
    return endpoint


def cmd_url(args: argparse.Namespace, out: Console, err: Console) -> int:
    endpoint = _require_endpoint(_dict())
    if args.no_password:
        out.print(
            f"postgresql://{PG_USER}:{PASSWORD_PLACEHOLDER}@"
            f"{endpoint.address}/{args.database}"
        )
        return EXIT_OK
    password = resolve_password(args.password)
    out.print(build_url(endpoint.host, endpoint.port, password, database=args.database))
    return EXIT_OK


def cmd_psql(args: argparse.Namespace, out: Console, err: Console) -> int:
    endpoint = _require_endpoint(_dict())
    password = resolve_password(args.password)
    binary = shutil.which("psql")
    if binary is None:
        err.print("psql is not on PATH. Install postgresql-client, then run:")
        out.print(
            f"PGPASSWORD=$SPEND_PG_PASSWORD psql -h {endpoint.host} "
            f"-p {endpoint.port} -U {PG_USER} -d {args.database}"
        )
        return EXIT_FAILURES
    err.print(f"psql: connecting to {endpoint.address}")
    # The password never reaches argv, where `ps` would show it.
    env = dict(os.environ, PGPASSWORD=password)
    argv = [
        binary,
        "-h",
        endpoint.host,
        "-p",
        str(endpoint.port),
        "-U",
        PG_USER,
        "-d",
        args.database,
        *args.psql_args,
    ]
    os.execve(binary, argv, env)
    return EXIT_OK  # pragma: no cover - execve does not return


# --------------------------------------------------------------------------- #
# pg dump, pg restore
# --------------------------------------------------------------------------- #


def _submit_request(store, kind: str, err: Console, *, timeout: int, **extra) -> dict:
    """Ask the running container to do something, and wait for the answer.

    A dump has to run where the postmaster is, so it travels as a record in
    the Dict rather than as its own Function call. The id makes the handshake
    idempotent: the server stamps it into the result key when it is done.
    """
    _require_endpoint(store)
    request = {"id": uuid.uuid4().hex, "kind": kind, **extra}
    _set_control(store, request=request)
    deadline = time.monotonic() + timeout
    with waiting(err, f"waiting for the server to {kind}") as waiter:
        while time.monotonic() < deadline:
            result = store.get(RESULT_KEY)
            if isinstance(result, dict) and result.get("id") == request["id"]:
                waiter.note(f"{kind}: {result.get('status')} {result.get('detail')}")
                return result
            waiter.update("the server picks this up on its next poll")
            time.sleep(3)
    raise CommandError(
        f"no answer to the {kind} request after {timeout}s. Check "
        f"`modal app logs {APP_NAME}`."
    )


def cmd_dump(args: argparse.Namespace, out: Console, err: Console) -> int:
    store = _dict()
    err.print("dump: asking the running server for a pg_dumpall onto the volume")
    result = _submit_request(store, "dump", err, timeout=args.timeout)
    if result.get("status") != "ok":
        raise CommandError(f"dump failed: {result.get('detail')}")
    out.print(str(result.get("detail")))
    return EXIT_OK


def _format_bytes(n: float) -> str:
    if n < 1024:
        return f"{int(n)}B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f}{unit}"
    return f"{n:.1f}PB"


def cmd_restore(args: argparse.Namespace, out: Console, err: Console) -> int:
    if args.list:
        err.print("restore: listing archives on the volume")
        with waiting(err, "reading the volume"):
            listing = _lookup_function("archives").remote()
        if not listing:
            err.print("restore: the volume holds no archives yet")
            return EXIT_FAILURES
        table = Table(box=None, pad_edge=False)
        table.add_column("archive")
        table.add_column("size", justify="right")
        table.add_column("modified")
        for row in listing:
            table.add_row(row["name"], _format_bytes(row["bytes"]), row["modified_at"])
        out.print(table)
        return EXIT_OK

    target = args.archive or "the newest archive"
    if not args.yes:
        raise CommandError(
            f"restoring {target} drops and recreates every object in the cluster. "
            "Re-run with --yes to confirm."
        )
    store = _dict()
    err.print(f"restore: loading {target} into the running server")
    result = _submit_request(
        store, "restore", err, timeout=args.timeout, archive=args.archive
    )
    if result.get("status") != "ok":
        raise CommandError(f"restore failed: {result.get('detail')}")
    out.print(str(result.get("detail")))
    return EXIT_OK


# --------------------------------------------------------------------------- #
# pg deploy
# --------------------------------------------------------------------------- #


def cmd_deploy(args: argparse.Namespace, out: Console, err: Console) -> int:
    argv = [sys.executable, "-m", "modal", "deploy", "-m", MODULE]
    if args.env:
        argv += ["--env", args.env]
    err.print(
        "deploy: building the image and registering the server, supervisor and "
        "archives functions. First build pulls postgres:17 and takes a few minutes."
    )
    with waiting(err, "modal deploy"):
        completed = subprocess.run(argv)
    if completed.returncode != 0:
        raise CommandError(f"modal deploy exited {completed.returncode}")
    err.print("deploy: done. `pg start` can now spawn the server.")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pg",
        description="Run and reach the self-hosted Postgres on Modal.",
    )
    parser.add_argument("--version", action="version", version=f"pg {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="start the server on Modal, detached")
    start.add_argument(
        "--dump-interval",
        type=int,
        default=None,
        help=f"seconds between dumps (default {DEFAULT_DUMP_INTERVAL}, "
        f"or ${ENV_DUMP_INTERVAL})",
    )
    start.add_argument(
        "--timeout",
        type=int,
        default=START_TIMEOUT,
        help=f"seconds to wait for a tunnel address (default {START_TIMEOUT})",
    )
    start.add_argument(
        "--no-restore",
        action="store_true",
        help="start empty instead of restoring the newest archive",
    )
    start.add_argument(
        "--force",
        action="store_true",
        help="spawn even though an endpoint is already published",
    )
    start.set_defaults(func=cmd_start)

    stop = subparsers.add_parser("stop", help="dump and shut the server down")
    stop.add_argument("--timeout", type=int, default=STOP_TIMEOUT)
    stop.set_defaults(func=cmd_stop)

    status = subparsers.add_parser("status", help="endpoint, uptime, reachability")
    status.add_argument("--password", default=None, help=f"overrides ${ENV_PASSWORD}")
    status.add_argument(
        "--no-check", action="store_true", help="skip the SELECT 1 round trip"
    )
    status.add_argument("--connect-timeout", type=float, default=10.0)
    status.set_defaults(func=cmd_status)

    url = subparsers.add_parser("url", help="print the connection URL")
    url.add_argument("--password", default=None, help=f"overrides ${ENV_PASSWORD}")
    url.add_argument(
        "--no-password",
        action="store_true",
        help=f"print {PASSWORD_PLACEHOLDER} in place of the password",
    )
    url.add_argument("--database", default=PG_DATABASE)
    url.set_defaults(func=cmd_url)

    psql = subparsers.add_parser("psql", help="open psql against the endpoint")
    psql.add_argument("--password", default=None, help=f"overrides ${ENV_PASSWORD}")
    psql.add_argument("--database", default=PG_DATABASE)
    psql.add_argument(
        "psql_args",
        nargs=argparse.REMAINDER,
        help="everything after -- is handed to psql",
    )
    psql.set_defaults(func=cmd_psql)

    dump = subparsers.add_parser("dump", help="dump now, onto the volume")
    dump.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT)
    dump.set_defaults(func=cmd_dump)

    restore = subparsers.add_parser("restore", help="load an archive back in")
    restore.add_argument(
        "--archive", default=None, help="archive name (default: the newest)"
    )
    restore.add_argument(
        "--list", action="store_true", help="list archives on the volume and exit"
    )
    restore.add_argument(
        "--yes", action="store_true", help="confirm that this overwrites the cluster"
    )
    restore.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT)
    restore.set_defaults(func=cmd_restore)

    deploy = subparsers.add_parser("deploy", help="modal deploy the app")
    deploy.add_argument("--env", default=None, help="Modal environment to deploy into")
    deploy.set_defaults(func=cmd_deploy)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    load_dotenv(".env.local", override=False)
    parser = build_parser()
    args = parser.parse_args(argv)
    out, err = out_console(), stderr_console()
    try:
        return args.func(args, out, err)
    except CommandError as exc:
        err.print(f"[red]error[/red] {exc}")
        return EXIT_FAILURES
    except KeyboardInterrupt:
        err.print("interrupted. The server on Modal is unaffected, `pg status` to see.")
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
