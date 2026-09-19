"""The ``scrooge`` command: list boroughs, download their files, report on disk.

argparse with one subparser per verb, the same shape as the other CLIs in this
family. Tables go to stdout so they can be piped; progress and diagnostics go
to stderr so the pipe stays clean.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import __version__, manifest
from .boroughs import get_source, import_errors, iter_sources
from .boroughs.base import Source, filter_files
from .config import DEFAULT_DELAY, ENV_DATA_DIR, resolve_data_dir
from .http import FetchError, make_client
from .models import RemoteFile
from .progress import format_bytes, make_progress, stderr_console

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


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
    table = Table(title=f"Registered boroughs ({data_dir})", title_justify="left")
    for column in ("slug", "borough", "access", "threshold"):
        table.add_column(column)
    table.add_column("files", justify="right")
    table.add_column("latest")
    for source in iter_sources():
        summary = manifest.summarise(data_dir, source.slug)
        table.add_row(
            source.slug,
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
    table = Table(title=f"On disk ({data_dir})", title_justify="left")
    table.add_column("slug")
    for column in ("files", "bytes"):
        table.add_column(column, justify="right")
    table.add_column("earliest")
    table.add_column("latest")
    table.add_column("last run")
    table.add_column("failures", justify="right")
    totals = {"files": 0, "bytes": 0, "failures": 0}
    for source in iter_sources():
        summary = manifest.summarise(data_dir, source.slug)
        for key in totals:
            totals[key] += summary[key]
        table.add_row(
            source.slug,
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
    if args.all:
        return iter_sources()
    chosen = []
    for slug in args.slugs:
        source = get_source(slug)
        if source is None:
            known = ", ".join(s.slug for s in iter_sources()) or "none registered"
            err.print(f"[red]unknown borough {slug!r}[/]. Known: {known}")
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
        err.print("no boroughs registered")
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
    manifests = {s.slug: manifest.load(data_dir, s.slug) for s in sources}
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
        # markup=False: a borough list in square brackets would be eaten as
        # Rich markup, and soft_wrap keeps the summary on one line.
        err.print(
            f"scrooge download: {len(sources)} borough(s) ({slugs}) · "
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
        dest = manifest.dest_path(data_dir, remote)
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
    table.add_column("borough")
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
# argparse
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrooge",
        description=(
            "Download London borough council spending files (payments over "
            "£250/£500) and keep them raw on disk."
        ),
    )
    parser.add_argument("--version", action="version", version=f"scrooge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_list = sub.add_parser("list", help="registered boroughs and what is on disk")
    p_list.add_argument("--data-dir", help=f"data directory (${ENV_DATA_DIR})")

    p_download = sub.add_parser(
        "download",
        help="discover and download files for one or more boroughs",
        description=(
            "Discover what each borough publishes, then download what is not "
            "already on disk. Safe to re-run: finished files are skipped."
        ),
    )
    p_download.add_argument(
        "slugs", nargs="*", metavar="SLUG", help="boroughs to download"
    )
    p_download.add_argument(
        "--all", action="store_true", help="every registered borough"
    )
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

    p_status = sub.add_parser("status", help="per-borough counts from the manifests")
    p_status.add_argument("--data-dir", help=f"data directory (${ENV_DATA_DIR})")
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
                "nothing to download. Name one or more boroughs, or pass --all:\n"
                "  scrooge download camden richmond\n"
                "  scrooge download --all --since 2026-01\n"
                "  scrooge list   # to see the registered slugs",
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
    parser.error(f"unknown command {args.command}")
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
