"""The ``scrooge`` command: list sources, download their files, report on disk.

argparse with one subparser per verb, the same shape as the other CLIs in this
family. Tables go to stdout so they can be piped; progress and diagnostics go
to stderr so the pipe stays clean.

``--kind`` defaults to ``spend`` on every verb. Budgets were added after the
cron lines were written, and a flag that quietly doubled what a nightly run
fetches would be a rude way to ship them, so budgets are opt-in: ``--kind
budget`` for those alone, ``--kind all`` for both. Naming a slug outright works
whatever ``--kind`` says, because somebody who typed ``mhclg`` has already said
which kind they mean.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__, manifest
from .boroughs import get_source, import_errors, iter_sources
from .boroughs.base import Source, filter_files
from .config import DEFAULT_DELAY, ENV_DATA_DIR, resolve_data_dir
from .http import FetchError, make_client
from .loader import db, runner
from .loader import files as spend_files
from .loader.mappings import SPEND_BOROUGHS
from .models import RemoteFile
from .progress import format_bytes, make_progress, stderr_console

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

KINDS = ("spend", "budget", "all")
DEFAULT_KIND = "spend"

#: Live counters on the load bar. Rows rather than bytes: the interesting
#: question during a 16 million row load is how many rows have landed, and a
#: byte count of what was read says nothing about that.
LOAD_COUNTERS = ("loaded", "skipped", "failed", "rows")


def _of_kind(kind: str) -> list[Source]:
    """Registered sources of one kind, or every source when ``kind`` is ``all``."""
    return [s for s in iter_sources() if kind == "all" or s.kind == kind]


@dataclass
class BoroughOutcome:
    """Running totals for one borough during a download."""

    slug: str
    discovered: int = 0
    ok: int = 0
    skipped: int = 0
    missing: int = 0
    failed: int = 0
    bytes: int = 0
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# scrooge list
# --------------------------------------------------------------------------- #


def cmd_list(args: argparse.Namespace, out: Console, err: Console) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    table = Table(
        title=f"Registered sources, kind={args.kind} ({data_dir})",
        title_justify="left",
    )
    for column in ("slug", "kind", "source", "access", "threshold"):
        table.add_column(column)
    table.add_column("files", justify="right")
    table.add_column("latest")
    for source in _of_kind(args.kind):
        summary = manifest.summarise(data_dir, source.slug, source.kind)
        table.add_row(
            source.slug,
            source.kind,
            source.name,
            source.access,
            source.threshold,
            str(summary["files"]),
            summary["latest"] or "-",
        )
    out.print(table)
    _warn_import_errors(err)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# scrooge status
# --------------------------------------------------------------------------- #


def cmd_status(args: argparse.Namespace, out: Console, err: Console) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    table = Table(title=f"On disk, kind={args.kind} ({data_dir})", title_justify="left")
    table.add_column("slug")
    table.add_column("kind")
    for column in ("files", "bytes"):
        table.add_column(column, justify="right")
    table.add_column("earliest")
    table.add_column("latest")
    table.add_column("last run")
    table.add_column("failures", justify="right")
    totals = {"files": 0, "bytes": 0, "failures": 0}
    for source in _of_kind(args.kind):
        summary = manifest.summarise(data_dir, source.slug, source.kind)
        for key in totals:
            totals[key] += summary[key]
        table.add_row(
            source.slug,
            source.kind,
            str(summary["files"]),
            format_bytes(summary["bytes"]),
            summary["earliest"] or "-",
            summary["latest"] or "-",
            (summary["last_run"] or "-")[:19],
            str(summary["failures"]),
        )
    table.add_section()
    table.add_row(
        "total",
        "",
        str(totals["files"]),
        format_bytes(totals["bytes"]),
        "",
        "",
        "",
        str(totals["failures"]),
    )
    out.print(table)
    _warn_import_errors(err)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# scrooge download
# --------------------------------------------------------------------------- #


def _select_sources(args: argparse.Namespace, err: Console) -> list[Source] | None:
    """``--all`` respects ``--kind``; a named slug ignores it.

    Somebody who typed ``scrooge download mhclg`` has already chosen a kind,
    and making them add ``--kind budget`` to be told what they asked for would
    be a flag getting in the way of the thing it selects.
    """
    if args.all:
        return _of_kind(args.kind)
    chosen = []
    for slug in args.slugs:
        source = get_source(slug)
        if source is None:
            known = ", ".join(s.slug for s in iter_sources()) or "none registered"
            err.print(f"[red]unknown source {slug!r}[/]. Known: {known}")
            return None
        chosen.append(source)
    return chosen


def _discover(
    source: Source, client, args: argparse.Namespace, err: Console
) -> tuple[list[RemoteFile], str | None]:
    """Discovery for one borough, with the failure turned into a message.

    A council that has moved its page should cost that borough's files, not
    the whole run, so the exception is caught here and reported next to the
    borough it belongs to.
    """
    try:
        found = source.discover(client, args.since, args.until)
    except Exception as exc:  # noqa: BLE001 - one borough, not the whole run
        return [], f"{type(exc).__name__}: {exc}"
    found = filter_files(found, args.since, args.until, quarters=source.quarters)
    found.sort(key=lambda f: (f.period, f.filename))
    if args.limit:
        # The most recent N, because a capped run is nearly always a smoke test
        # or a catch-up, and both want the newest data first.
        found = found[-args.limit :]
    return found, None


def cmd_download(args: argparse.Namespace, out: Console, err: Console) -> int:
    sources = _select_sources(args, err)
    if sources is None:
        return EXIT_USAGE
    if not sources:
        err.print(f"no sources registered for --kind {args.kind}")
        return EXIT_USAGE

    data_dir = resolve_data_dir(args.data_dir)
    slugs = ", ".join(s.slug for s in sources)
    err.print(
        f"scrooge download: {slugs} · discovering...",
        highlight=False,
        markup=False,
        soft_wrap=True,
    )

    plan: list[tuple[Source, list[RemoteFile]]] = []
    outcomes: dict[str, BoroughOutcome] = {}
    manifests = {s.slug: manifest.load(data_dir, s.slug, s.kind) for s in sources}
    already = 0
    client = make_client(delay=args.delay)
    try:
        for source in sources:
            found, error = _discover(source, client, args, err)
            outcomes[source.slug] = BoroughOutcome(source.slug, discovered=len(found))
            if error:
                outcomes[source.slug].failed += 1
                outcomes[source.slug].errors.append(f"discover: {error}")
                err.print(f"[red]{source.slug}: discovery failed[/] {error}")
            already += sum(
                1
                for remote in found
                if manifest.should_skip(
                    manifests[source.slug], remote, data_dir, force=args.force
                )
            )
            plan.append((source, found))

        total = sum(len(found) for _, found in plan)
        # markup=False: a source list in square brackets would be eaten as
        # Rich markup, and soft_wrap keeps the summary on one line.
        err.print(
            f"scrooge download: {len(sources)} source(s) ({slugs}) · "
            f"{total} file(s) discovered · {already} already on disk · "
            f"{data_dir}",
            highlight=False,
            markup=False,
            soft_wrap=True,
        )
        if total == 0:
            _summary_table(out, outcomes, data_dir)
            return EXIT_FAILURES if _any_failure(outcomes) else EXIT_OK

        interrupted = False
        with make_progress(err) as progress:
            task = progress.add_task(
                "download", total=total, ok=0, skipped=0, failed=0, bytes=0
            )
            counters = {"ok": 0, "skipped": 0, "failed": 0, "bytes": 0}
            try:
                for source, found in plan:
                    _download_borough(
                        source,
                        found,
                        client,
                        data_dir,
                        manifests[source.slug],
                        outcomes[source.slug],
                        args,
                        progress,
                        task,
                        counters,
                        err,
                    )
            except KeyboardInterrupt:
                interrupted = True
    finally:
        client.close()

    _summary_table(out, outcomes, data_dir)
    if interrupted:
        err.print(
            "\n[yellow]interrupted.[/] Manifests are consistent and partial "
            "files were removed. Resume with:\n  " + _resume_command(args),
            highlight=False,
        )
        return EXIT_INTERRUPTED
    _warn_import_errors(err)
    return EXIT_FAILURES if _any_failure(outcomes) else EXIT_OK


def _download_borough(
    source: Source,
    found: list[RemoteFile],
    client,
    data_dir: Path,
    borough_manifest,
    outcome: BoroughOutcome,
    args: argparse.Namespace,
    progress,
    task: int,
    counters: dict[str, int],
    err: Console,
) -> None:
    for remote in found:
        dest = manifest.dest_path(data_dir, remote, source.kind)
        if manifest.should_skip(borough_manifest, remote, data_dir, force=args.force):
            outcome.skipped += 1
            counters["skipped"] += 1
            _advance(progress, task, counters)
            continue
        previous = borough_manifest.entries.get(remote.key)
        conditional = (
            manifest.conditional_headers(borough_manifest, remote, data_dir)
            if remote.mutable and not args.force
            else {}
        )

        def on_bytes(n: int) -> None:
            counters["bytes"] += n

        try:
            result = source.fetch(
                client,
                remote,
                dest,
                on_bytes=on_bytes,
                conditional=conditional or None,
            )
        except FetchError as exc:
            status = exc.kind
            manifest.record(borough_manifest, remote, status=status, error=str(exc))
            manifest.save(data_dir, borough_manifest)
            if status == "missing":
                outcome.missing += 1
            else:
                outcome.failed += 1
                counters["failed"] += 1
                outcome.errors.append(f"{remote.period}: {exc}")
                err.print(f"[red]{source.slug} {remote.period}[/] {exc}")
            _advance(progress, task, counters)
            continue
        # A mutable file whose bytes came back identical counts as skipped, not
        # as a download. Socrata ignores conditional requests, so the sha256 is
        # the only thing that can tell "Camden added rows to August" from
        # "Camden sent August again".
        unchanged = result.status == "unchanged" or (
            remote.mutable
            and not args.force
            and previous is not None
            and previous.sha256 is not None
            and previous.sha256 == result.sha256
        )
        if unchanged:
            outcome.skipped += 1
            counters["skipped"] += 1
        else:
            outcome.ok += 1
            outcome.bytes += result.bytes
            counters["ok"] += 1
        if result.status != "unchanged":
            manifest.record(
                borough_manifest,
                remote,
                status="ok",
                bytes_=result.bytes,
                sha256=result.sha256,
                content_type=result.content_type,
                etag=result.etag,
                last_modified=result.last_modified,
            )
        borough_manifest.last_run = manifest.utc_now()
        # Saved after every file: a Ctrl-C in the next second must not lose the
        # record of the file that just landed.
        manifest.save(data_dir, borough_manifest)
        _advance(progress, task, counters)


def _advance(progress, task: int, counters: dict[str, int]) -> None:
    progress.update(task, advance=1, **counters)


def _any_failure(outcomes: dict[str, BoroughOutcome]) -> bool:
    return any(o.failed for o in outcomes.values())


def _summary_table(
    out: Console, outcomes: dict[str, BoroughOutcome], data_dir: Path
) -> None:
    table = Table(title=f"Download summary ({data_dir})", title_justify="left")
    table.add_column("source")
    for column in ("found", "downloaded", "skipped", "not published", "failed"):
        table.add_column(column, justify="right")
    table.add_column("bytes", justify="right")
    for outcome in outcomes.values():
        table.add_row(
            outcome.slug,
            str(outcome.discovered),
            str(outcome.ok),
            str(outcome.skipped),
            str(outcome.missing),
            str(outcome.failed),
            format_bytes(outcome.bytes),
        )
    out.print(table)


def _resume_command(args: argparse.Namespace) -> str:
    """The exact command that picks up where an interrupted run stopped.

    ``--force`` is deliberately dropped: files already fetched under it are on
    disk, and repeating it would refetch them.
    """
    parts = ["scrooge download"]
    parts.append("--all" if args.all else " ".join(args.slugs))
    if args.all and args.kind != DEFAULT_KIND:
        parts.append(f"--kind {args.kind}")
    for flag, value in (
        ("--since", args.since),
        ("--until", args.until),
        ("--data-dir", args.data_dir),
    ):
        if value:
            parts.append(f"{flag} {value}")
    if args.limit:
        parts.append(f"--limit {args.limit}")
    if args.delay != DEFAULT_DELAY:
        parts.append(f"--delay {args.delay}")
    return " ".join(parts)


def _warn_import_errors(err: Console) -> None:
    for name, exc in import_errors():
        err.print(f"[yellow]borough module {name} failed to import:[/] {exc}")


# --------------------------------------------------------------------------- #
# scrooge db init
# --------------------------------------------------------------------------- #


def cmd_db_init(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Apply the schema once, then fill `boroughs`. Safe to run twice."""
    with db.connect() as conn:
        if db.schema_present(conn):
            err.print("payments already exists, leaving the schema alone")
        else:
            path = db.apply_schema(conn)
            err.print(f"applied {path}")
        count = db.upsert_boroughs(conn)
        db.grant_reader(conn)
        table = Table(title="boroughs", title_justify="left")
        table.add_column("slug")
        table.add_column("name")
        table.add_column("population", justify="right")
        for slug, name, population in db.iter_boroughs(conn):
            table.add_row(slug, name, f"{population:,}" if population else "-")
        out.print(table)
        err.print(f"{count} borough(s) upserted")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# scrooge load
# --------------------------------------------------------------------------- #


@dataclass
class LoadOutcome:
    """Running totals for one borough during a load."""

    slug: str
    files: int = 0
    loaded: int = 0
    skipped: int = 0
    failed: int = 0
    already: int = 0
    rows: int = 0
    dropped: int = 0


def _load_slugs(
    args: argparse.Namespace, data_dir: Path, err: Console
) -> list[str] | None:
    if args.all:
        return spend_files.known_boroughs(data_dir)
    chosen = []
    for slug in args.slugs:
        if slug not in SPEND_BOROUGHS:
            known = ", ".join(SPEND_BOROUGHS)
            err.print(f"[red]no column mapping for {slug!r}[/]. Known: {known}")
            return None
        chosen.append(slug)
    return chosen


def cmd_load(args: argparse.Namespace, out: Console, err: Console) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    slugs = _load_slugs(args, data_dir, err)
    if slugs is None:
        return EXIT_USAGE
    if not slugs:
        err.print(
            f"no spend files on disk under {data_dir}. Run scrooge download first."
        )
        return EXIT_USAGE

    plan = spend_files.select(
        data_dir, slugs, since=args.since, until=args.until, limit=args.limit
    )
    outcomes = {slug: LoadOutcome(slug) for slug in slugs}
    for spend_file in plan:
        outcomes[spend_file.borough].files += 1

    url = db.database_url()
    with db.connect(url) as conn:
        if not db.schema_present(conn):
            err.print("[red]no payments table.[/] Run scrooge db init first.")
            return EXIT_FAILURES
        states = db.file_states(conn)
        already = sum(
            1
            for spend_file in plan
            if runner.should_skip(states.get(spend_file.relpath), force=args.force)
        )
        # markup=False keeps a bracketed slug list out of Rich's hands, and
        # soft_wrap keeps the summary on one line however narrow the terminal.
        err.print(
            f"scrooge load: {len(slugs)} borough(s) ({', '.join(slugs)}) · "
            f"{len(plan)} file(s) on disk · {already} already done · "
            f"{db.redact(url)}",
            highlight=False,
            markup=False,
            soft_wrap=True,
        )
        if not plan:
            _load_summary(out, outcomes)
            return EXIT_OK

        interrupted = False
        counters = {"loaded": 0, "skipped": 0, "failed": 0, "rows": 0}
        with make_progress(err, counters=LOAD_COUNTERS) as progress:
            task = progress.add_task("load", total=len(plan), **counters)
            try:
                for spend_file in plan:
                    outcome = outcomes[spend_file.borough]
                    state = states.get(spend_file.relpath)
                    if runner.should_skip(state, force=args.force):
                        outcome.already += 1
                        counters["skipped"] += 1
                        progress.update(task, advance=1, **counters)
                        continue
                    result = runner.load_file(conn, spend_file)
                    _tally(outcome, counters, result, err)
                    progress.update(task, advance=1, **counters)
            except KeyboardInterrupt:
                interrupted = True

    _load_summary(out, outcomes)
    if interrupted:
        err.print(
            "\n[yellow]interrupted.[/] The file in flight was rolled back, so "
            "nothing is half loaded. Resume with:\n  " + _load_resume_command(args),
            highlight=False,
        )
        return EXIT_INTERRUPTED
    return EXIT_FAILURES if any(o.failed for o in outcomes.values()) else EXIT_OK


def _tally(
    outcome: LoadOutcome,
    counters: dict[str, int],
    result: runner.LoadResult,
    err: Console,
) -> None:
    if result.status == "loaded":
        outcome.loaded += 1
        outcome.rows += result.rows_loaded
        outcome.dropped += result.rows_dropped
        counters["loaded"] += 1
        counters["rows"] += result.rows_loaded
        return
    if result.status == "skipped":
        outcome.skipped += 1
        counters["skipped"] += 1
        err.print(
            f"[yellow]skipped[/] {escape(f'{result.path}: {result.reason}')}",
            highlight=False,
            soft_wrap=True,
        )
        return
    outcome.failed += 1
    counters["failed"] += 1
    err.print(
        f"[red]failed[/] {escape(f'{result.path}: {result.reason}')}",
        highlight=False,
        soft_wrap=True,
    )


def _load_summary(out: Console, outcomes: dict[str, LoadOutcome]) -> None:
    table = Table(title="Load summary", title_justify="left")
    table.add_column("borough")
    for column in (
        "files",
        "loaded",
        "skipped",
        "failed",
        "already",
        "rows",
        "dropped",
    ):
        table.add_column(column, justify="right")
    totals = LoadOutcome("total")
    for outcome in outcomes.values():
        table.add_row(
            outcome.slug,
            str(outcome.files),
            str(outcome.loaded),
            str(outcome.skipped),
            str(outcome.failed),
            str(outcome.already),
            f"{outcome.rows:,}",
            str(outcome.dropped),
        )
        for name in (
            "files",
            "loaded",
            "skipped",
            "failed",
            "already",
            "rows",
            "dropped",
        ):
            setattr(totals, name, getattr(totals, name) + getattr(outcome, name))
    table.add_section()
    table.add_row(
        "total",
        str(totals.files),
        str(totals.loaded),
        str(totals.skipped),
        str(totals.failed),
        str(totals.already),
        f"{totals.rows:,}",
        str(totals.dropped),
    )
    out.print(table)


def _load_resume_command(args: argparse.Namespace) -> str:
    """The exact command that picks up where an interrupted load stopped.

    ``--force`` is dropped for the same reason the download hint drops it: the
    files it already reloaded are recorded as loaded, and repeating it would
    do all of them again.
    """
    parts = ["scrooge load"]
    parts.append("--all" if args.all else " ".join(args.slugs))
    for flag, value in (
        ("--since", args.since),
        ("--until", args.until),
        ("--data-dir", args.data_dir),
    ):
        if value:
            parts.append(f"{flag} {value}")
    if args.limit:
        parts.append(f"--limit {args.limit}")
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# scrooge load-status
# --------------------------------------------------------------------------- #


def cmd_load_status(args: argparse.Namespace, out: Console, err: Console) -> int:
    with db.connect() as conn:
        if not db.schema_present(conn):
            err.print("[red]no payments table.[/] Run scrooge db init first.")
            return EXIT_FAILURES
        table = Table(title="In the database", title_justify="left")
        table.add_column("borough")
        for column in ("loaded", "skipped", "failed", "rows"):
            table.add_column(column, justify="right")
        table.add_column("earliest")
        table.add_column("latest")
        for slug, loaded, skipped, failed, rows, earliest, latest in db.status_rows(
            conn
        ):
            table.add_row(
                slug,
                str(loaded),
                str(skipped),
                str(failed),
                f"{rows:,}",
                earliest or "-",
                latest or "-",
            )
        out.print(table)
        if args.problems:
            problems = Table(title="Not loaded", title_justify="left")
            for column in ("path", "status", "reason"):
                problems.add_column(column)
            for path, status, reason in db.failed_files(conn, limit=args.problems):
                problems.add_row(path, status, reason or "-")
            out.print(problems)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #


def _add_kind(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--kind",
        choices=KINDS,
        default=DEFAULT_KIND,
        help=(
            f"which sources to act on (default {DEFAULT_KIND}): spend is what "
            "councils paid, budget is what they planned to spend"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrooge",
        description=(
            "Download London borough council spending files (payments over "
            "£250/£500) and budget files (planned spend), and keep them raw "
            "on disk."
        ),
    )
    parser.add_argument("--version", action="version", version=f"scrooge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_list = sub.add_parser("list", help="registered sources and what is on disk")
    p_list.add_argument("--data-dir", help=f"data directory (${ENV_DATA_DIR})")
    _add_kind(p_list)

    p_download = sub.add_parser(
        "download",
        help="discover and download files for one or more sources",
        description=(
            "Discover what each source publishes, then download what is not "
            "already on disk. Safe to re-run: finished files are skipped."
        ),
    )
    p_download.add_argument(
        "slugs", nargs="*", metavar="SLUG", help="sources to download"
    )
    p_download.add_argument(
        "--all", action="store_true", help="every registered source of --kind"
    )
    _add_kind(p_download)
    p_download.add_argument("--since", metavar="YYYY-MM", help="earliest period")
    p_download.add_argument("--until", metavar="YYYY-MM", help="latest period")
    p_download.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="at most N files per borough, most recent first",
    )
    p_download.add_argument(
        "--force",
        action="store_true",
        help="re-download files already recorded as complete",
    )
    p_download.add_argument("--data-dir", help=f"data directory (${ENV_DATA_DIR})")
    p_download.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        metavar="SECONDS",
        help=f"pause between requests to the same host (default {DEFAULT_DELAY})",
    )

    p_status = sub.add_parser("status", help="per-source counts from the manifests")
    p_status.add_argument("--data-dir", help=f"data directory (${ENV_DATA_DIR})")
    _add_kind(p_status)

    p_db = sub.add_parser("db", help="set the database up")
    db_sub = p_db.add_subparsers(dest="db_command", required=True, metavar="COMMAND")
    db_sub.add_parser(
        "init",
        help="apply the schema and fill boroughs",
        description=(
            "Apply docs/payments-schema.sql when there is no payments table "
            "yet, then upsert all 33 London authorities with their ONS "
            "mid-year population. Safe to run twice."
        ),
    )

    p_load = sub.add_parser(
        "load",
        help="read the spend files on disk into Postgres",
        description=(
            "Read data/raw/<borough>/ into payments, one transaction per "
            "file. Safe to re-run: files already loaded are skipped, and a "
            "file that fails is retried on the next run."
        ),
    )
    p_load.add_argument("slugs", nargs="*", metavar="SLUG", help="boroughs to load")
    p_load.add_argument(
        "--all", action="store_true", help="every borough with files on disk"
    )
    p_load.add_argument("--since", metavar="YYYY-MM", help="earliest period")
    p_load.add_argument("--until", metavar="YYYY-MM", help="latest period")
    p_load.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="at most N files per borough, most recent first",
    )
    p_load.add_argument(
        "--force",
        action="store_true",
        help="reload files already recorded as loaded or skipped",
    )
    p_load.add_argument("--data-dir", help=f"data directory (${ENV_DATA_DIR})")

    p_load_status = sub.add_parser(
        "load-status",
        help="loaded, skipped and failed files per borough, from the database",
    )
    p_load_status.add_argument(
        "--problems",
        type=int,
        nargs="?",
        const=50,
        default=0,
        metavar="N",
        help="also list up to N files that did not load (default 50)",
    )
    return parser


_MONTH_FLAG = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_period(value: str | None, flag: str, err: Console) -> bool:
    if value is None or _MONTH_FLAG.match(value):
        return True
    err.print(f"[red]{flag} must be YYYY-MM, got {value!r}[/]")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = Console()
    err = stderr_console()

    if args.command == "list":
        return cmd_list(args, out, err)
    if args.command == "status":
        return cmd_status(args, out, err)
    if args.command == "download":
        if not args.slugs and not args.all:
            err.print(
                "nothing to download. Name one or more sources, or pass --all:\n"
                "  scrooge download camden richmond\n"
                "  scrooge download --all --since 2026-01\n"
                "  scrooge download --all --kind budget\n"
                "  scrooge list --kind all   # to see the registered slugs",
                highlight=False,
            )
            return EXIT_USAGE
        if not _validate_period(args.since, "--since", err) or not _validate_period(
            args.until, "--until", err
        ):
            return EXIT_USAGE
        try:
            return cmd_download(args, out, err)
        except KeyboardInterrupt:
            err.print("\ninterrupted before any file was fetched.")
            return EXIT_INTERRUPTED
    if args.command in ("db", "load", "load-status"):
        return _run_database_command(args, parser, out, err)
    parser.error(f"unknown command {args.command}")
    return EXIT_USAGE


def _run_database_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    out: Console,
    err: Console,
) -> int:
    """The three verbs that need a connection, with one place to report losing it.

    Every one of them ends the same way when the Modal tunnel moves, so the
    message that says how to get a fresh URL is written once here rather than
    at each call site.
    """
    if args.command == "load":
        if not args.slugs and not args.all:
            err.print(
                "nothing to load. Name one or more boroughs, or pass --all:\n"
                "  scrooge load camden --since 2019-09 --until 2019-09\n"
                "  scrooge load --all\n"
                f"  known boroughs: {', '.join(SPEND_BOROUGHS)}",
                highlight=False,
            )
            return EXIT_USAGE
        if not _validate_period(args.since, "--since", err) or not _validate_period(
            args.until, "--until", err
        ):
            return EXIT_USAGE
    try:
        if args.command == "db":
            if args.db_command == "init":
                return cmd_db_init(args, out, err)
            parser.error(f"unknown db command {args.db_command}")
            return EXIT_USAGE
        if args.command == "load":
            return cmd_load(args, out, err)
        return cmd_load_status(args, out, err)
    except db.DatabaseUnavailable as exc:
        err.print(f"[red]{exc}[/]", highlight=False)
        return EXIT_FAILURES
    except psycopg.OperationalError as exc:
        # Lost between files rather than inside a COPY, so db.py never saw it.
        err.print(f"{exc}\n\n{db.RECONNECT_HINT}", highlight=False, markup=False)
        return EXIT_FAILURES
    except psycopg.Error as exc:
        err.print(
            f"the database refused: {exc}\n"
            f"Files already loaded stay loaded. Check that ${db.ENV_DATABASE_URL} "
            "is the owner login from `pg url` and not the read-only agent one.",
            highlight=False,
            markup=False,
        )
        return EXIT_FAILURES
    except KeyboardInterrupt:
        err.print("\ninterrupted before any file was written.")
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
