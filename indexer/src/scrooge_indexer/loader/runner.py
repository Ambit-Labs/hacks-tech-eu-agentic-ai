"""One file, start to finish: open it, map it, write it, say what happened.

The skip rules from docs/payments-schema.md live here rather than in the
reader, because "this is a supplier total, not a list of payments" is a fact
about the file's meaning and not about its bytes. Each rule is named in the
reason it writes, so `source_files` reads as an explanation rather than a
status code.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from . import db
from .files import SpendFile
from .mappings import header_markers, normalise, resolve
from .readers import NoHeader, ReadError, open_table
from .rows import (
    DAY_FIRST,
    MIXED,
    MONTH_FIRST,
    AmbiguousDateOrder,
    RowStats,
    detect_date_order,
    payment_rows,
)

#: Lambeth published fourteen months as one total per supplier and two more as
#: a bare pivot table. Both are aggregates, neither is a payment list.
_AGGREGATE_HEADERS = frozenset({"sum of invoice nett amount", "total"})


@dataclass
class LoadResult:
    """What happened to one file."""

    path: str
    borough: str
    period: str
    status: str
    reason: str | None
    rows_loaded: int = 0
    rows_dropped: int = 0
    layout: str = ""


def _aggregate_reason(header: list[str]) -> str | None:
    """Is this a supplier-total or pivot file rather than a payment list?"""
    names = {normalise(cell) for cell in header if str(cell or "").strip()}
    if names & _AGGREGATE_HEADERS:
        return "supplier totals, not payments"
    return None


def load_file(
    conn: psycopg.Connection,
    spend_file: SpendFile,
) -> LoadResult:
    """Read, map and write one file. Never raises for a file-shaped problem.

    A database problem is a different matter and is allowed out, because the
    run cannot carry on without a connection and pretending each remaining file
    failed on its own would bury the one thing the operator needs to read.

    Files are loaded day first on the first attempt. The one that is not,
    Lambeth 2020-Q2, raises on its first transposed date, its column is scanned
    to settle the order, and it is loaded again. Two reads for that file and
    one for the other 1,370.
    """
    expected = header_markers(spend_file.borough)
    date_order = DAY_FIRST
    stats = RowStats()
    try:
        for attempt in (1, 2):
            stats = RowStats()
            try:
                with open_table(spend_file.path, expected) as table:
                    reason = _aggregate_reason(table.header)
                    if reason is not None:
                        return _record(conn, spend_file, "skipped", reason)
                    mapping = resolve(spend_file.borough, table.header)
                    if mapping is None:
                        missing = "no date, supplier or amount column"
                        return _record(
                            conn, spend_file, "skipped", f"unmapped header: {missing}"
                        )

                    def finish(written: int, order: str = date_order) -> tuple:
                        return ("loaded", _loaded_reason(stats, order))

                    written = db.copy_payments(
                        conn,
                        path=spend_file.relpath,
                        borough=spend_file.borough,
                        period=spend_file.period,
                        rows=payment_rows(
                            table,
                            mapping,
                            borough=spend_file.borough,
                            source_file=spend_file.relpath,
                            stats=stats,
                            date_order=date_order,
                        ),
                        finish=finish,
                    )
                break
            except AmbiguousDateOrder as exc:
                # The COPY was inside the transaction that just rolled back, so
                # the rows written so far are gone and nothing is half loaded.
                if attempt == 2:
                    return _record(conn, spend_file, "failed", str(exc))
                date_order = _scan_date_order(spend_file, expected)
                if date_order == MIXED:
                    return _record(
                        conn,
                        spend_file,
                        "failed",
                        "date column has both orders, no reading fits the file",
                    )
    except NoHeader as exc:
        # Lambeth's supplier totals have no date column and so reach here
        # rather than the header check above. The rows they do have say which
        # of the two they are.
        reason = next(
            (r for row in exc.rows if (r := _aggregate_reason(row))),
            "no header row found",
        )
        return _record(conn, spend_file, "skipped", reason)
    except ReadError as exc:
        status = "skipped" if _is_skip(str(exc)) else "failed"
        return _record(conn, spend_file, status, str(exc))
    except db.DatabaseUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - one file, not the whole run
        return _record(conn, spend_file, "failed", f"{type(exc).__name__}: {exc}")
    return LoadResult(
        path=spend_file.relpath,
        borough=spend_file.borough,
        period=spend_file.period,
        status="loaded",
        reason=_loaded_reason(stats, date_order),
        rows_loaded=written,
        rows_dropped=stats.dropped_total,
        layout=mapping.layout,
    )


def _loaded_reason(stats: RowStats, date_order: str) -> str | None:
    """What `source_files.reason` says about a file that loaded.

    The dropped-row count, and for the one file read the other way round, the
    fact that it was. Anyone looking at a Lambeth date in 2020-21 Q2 can see
    from the database that it was transposed on the way in.
    """
    parts = [part for part in (stats.reason(),) if part]
    if date_order == MONTH_FIRST:
        parts.append("dates read month-first")
    return "; ".join(parts) or None


def _scan_date_order(spend_file: SpendFile, expected: tuple[str, ...]) -> str:
    """One extra read of the date column, to settle which order the file is in."""
    with open_table(spend_file.path, expected) as table:
        mapping = resolve(spend_file.borough, table.header)
        if mapping is None:
            return DAY_FIRST
        return detect_date_order(table, mapping)


#: Read failures that are a property of the file rather than a fault: there is
#: no reader for the format, or the file holds no table at all.
_SKIP_PREFIXES = ("no ODS reader", "no reader for", "no header row found", "Excel 97")


def _is_skip(reason: str) -> bool:
    return reason.startswith(_SKIP_PREFIXES)


def _record(
    conn: psycopg.Connection,
    spend_file: SpendFile,
    status: str,
    reason: str | None,
) -> LoadResult:
    db.record_outcome(
        conn,
        path=spend_file.relpath,
        borough=spend_file.borough,
        period=spend_file.period,
        status=status,
        reason=reason,
    )
    return LoadResult(
        path=spend_file.relpath,
        borough=spend_file.borough,
        period=spend_file.period,
        status=status,
        reason=reason,
    )


def should_skip(state: db.FileState | None, *, force: bool) -> bool:
    """Is this file already done?

    `loaded` is done and is skipped on a rerun. `skipped` is a decision about
    the file's content that rerunning cannot change, so it stays skipped too.
    `failed` is retried: a failure here is usually a dropped connection or a
    parser that ran out of memory, and the natural response to a failed run is
    to run it again, not to add a flag that would also reload everything that
    worked. `--force` reloads all three.
    """
    if force or state is None:
        return False
    return state.status in ("loaded", "skipped")
