"""Everything that talks to Postgres: the schema, `boroughs`, and one file at a time.

The connection string comes from `$DATABASE_URL` and nowhere else. The Modal
tunnel gets a new host and port on every restart, so a checked-in host would be
wrong within the day, and the password has no business in a repo at all.

A file is one transaction: delete this file's payments, write its `source_files`
row, COPY the new payments, then set the outcome. Nothing else can see the
in-between state, and a run that dies mid-file leaves that file absent rather
than half present, which is what makes rerunning the whole command the recovery
procedure.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql

from ..config import load_env, repo_root
from .boroughs_data import LONDON_BOROUGHS

ENV_DATABASE_URL = "DATABASE_URL"

#: Where the DDL lives. Shipped once, in docs/, because the agent session reads
#: the same file as the contract and a second copy would drift from it.
SCHEMA_SQL = "docs/payments-schema.sql"

#: Column order for the COPY, matching :func:`payment_row`.
PAYMENT_COLUMNS = (
    "borough",
    "payment_date",
    "financial_year",
    "supplier",
    "directorate",
    "department",
    "purpose",
    "amount_gbp",
    "vat_gbp",
    "reference",
    "source_file",
    "source_row",
    "raw",
)

_COPY_TYPES = (
    "text",
    "date",
    "text",
    "text",
    "text",
    "text",
    "text",
    "numeric",
    "numeric",
    "text",
    "text",
    "integer",
    "jsonb",
)

PaymentRow = tuple[
    str,
    date,
    str,
    str,
    str | None,
    str | None,
    str | None,
    Decimal,
    Decimal | None,
    str | None,
    str,
    int,
    object,
]


class DatabaseUnavailable(Exception):
    """The database is not reachable, or was reachable and stopped being.

    Carries the message the operator needs rather than the driver's, because
    the fix is nearly always the same one: the tunnel moved, re-export
    `DATABASE_URL` and run the command again.
    """


RECONNECT_HINT = (
    "The database connection dropped. The Modal tunnel gets a new address on "
    "every restart, so re-export the URL and run the same command again; files "
    "already loaded are skipped.\n"
    '  export DATABASE_URL="$(cd ../infra && uv run pg url)"'
)


def database_url() -> str:
    """`$DATABASE_URL`, or a clear refusal to guess one."""
    load_env()
    url = os.environ.get(ENV_DATABASE_URL)
    if not url:
        raise DatabaseUnavailable(
            f"${ENV_DATABASE_URL} is not set. Get one from the infra CLI:\n"
            '  export DATABASE_URL="$(cd ../infra && uv run pg url)"'
        )
    return url


def redact(url: str) -> str:
    """The connection string with the password replaced, safe to print."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit(
        (parts.scheme, f"{parts.username}:***@{host}", parts.path, "", "")
    )


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a connection, turning a refused one into an operator message.

    Autocommit, so that each `conn.transaction()` below is a real transaction
    that commits when its block ends. Without it the first SELECT of a run
    opens a transaction that never closes, every block after it is a savepoint
    inside that one, and a run killed after 900 files has loaded none.
    """
    target = url or database_url()
    try:
        return psycopg.connect(target, connect_timeout=15, autocommit=True)
    except psycopg.OperationalError as exc:
        raise DatabaseUnavailable(f"cannot connect: {exc}\n\n{RECONNECT_HINT}") from exc
    except psycopg.ProgrammingError:
        # The driver quotes the string it could not parse, password included,
        # so its message is dropped rather than passed on.
        raise DatabaseUnavailable(
            f"${ENV_DATABASE_URL} is not a connection string the driver can "
            "parse. It should look like postgresql://user:password@host:port/postgres:\n"
            '  export DATABASE_URL="$(cd ../infra && uv run pg url)"'
        ) from None


def schema_sql_path() -> Path:
    """`docs/payments-schema.sql` in the checkout this package was run from."""
    root = repo_root()
    if root is None:
        raise DatabaseUnavailable(
            f"cannot find {SCHEMA_SQL}: no git checkout above "
            f"{Path(__file__).resolve().parent}. Run `scrooge db init` from a "
            "clone of the repo."
        )
    path = root / SCHEMA_SQL
    if not path.is_file():
        raise DatabaseUnavailable(f"schema file missing: {path}")
    return path


def schema_present(conn: psycopg.Connection) -> bool:
    """Is `payments` already there? The one question `db init` asks."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.payments') IS NOT NULL")
        row = cur.fetchone()
    return bool(row and row[0])


def apply_schema(conn: psycopg.Connection) -> Path:
    """Run `payments-schema.sql` as one statement block, in one transaction."""
    path = schema_sql_path()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(path.read_text("utf-8"))
    return path


def upsert_boroughs(conn: psycopg.Connection) -> int:
    """Write all 33 authorities, replacing name and population in place."""
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO boroughs (slug, name, population) VALUES (%s, %s, %s) "
            "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, "
            "population = EXCLUDED.population",
            [(slug, name, population) for slug, name, _, population in LONDON_BOROUGHS],
        )
    return len(LONDON_BOROUGHS)


def grant_reader(conn: psycopg.Connection) -> None:
    """Re-grant SELECT to `scrooge_reader` on everything the agent reads.

    Idempotent, and separate from the schema so it can be re-run after a
    restore from a dump taken before the role existed.
    """
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            sql.SQL("GRANT SELECT ON {} TO scrooge_reader").format(
                sql.SQL(", ").join(
                    sql.Identifier(name)
                    for name in ("boroughs", "source_files", "payments", "coverage")
                )
            )
        )


# --------------------------------------------------------------------------- #
# source_files
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FileState:
    """What the database already knows about one file."""

    status: str
    rows_loaded: int
    reason: str | None


def file_states(conn: psycopg.Connection) -> dict[str, FileState]:
    """Every `source_files` row, keyed by path. One query, then all decisions."""
    with conn.cursor() as cur:
        cur.execute("SELECT path, status, rows_loaded, reason FROM source_files")
        return {
            path: FileState(status, rows_loaded, reason)
            for path, status, rows_loaded, reason in cur.fetchall()
        }


def record_outcome(
    conn: psycopg.Connection,
    *,
    path: str,
    borough: str,
    period: str,
    status: str,
    reason: str | None,
    rows_loaded: int = 0,
) -> None:
    """Write a `source_files` row on its own, for a file that loaded no rows."""
    with conn.transaction(), conn.cursor() as cur:
        if status != "loaded":
            cur.execute("DELETE FROM payments WHERE source_file = %s", (path,))
        _upsert_source_file(cur, path, borough, period, status, reason, rows_loaded)


def copy_payments(
    conn: psycopg.Connection,
    *,
    path: str,
    borough: str,
    period: str,
    rows: Iterable[PaymentRow],
    finish,
) -> int:
    """Replace one file's payments, in one transaction.

    `finish` is called after the last row has been written and before the
    transaction closes; it returns the `(status, reason)` to store, which is how
    a count of dropped rows that is only known at the end of the file still
    lands in the same commit as the rows themselves.
    """
    written = 0
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("DELETE FROM payments WHERE source_file = %s", (path,))
            _upsert_source_file(
                cur, path, borough, period, "failed", "load interrupted", 0
            )
            columns = ", ".join(PAYMENT_COLUMNS)
            statement = f"COPY payments ({columns}) FROM STDIN (FORMAT BINARY)"
            with cur.copy(statement) as copy:
                copy.set_types(_COPY_TYPES)
                for row in rows:
                    copy.write_row(row)
                    written += 1
            status, reason = finish(written)
            cur.execute(
                "UPDATE source_files SET status = %s, reason = %s, "
                "rows_loaded = %s, loaded_at = now() WHERE path = %s",
                (status, reason, written, path),
            )
    except psycopg.OperationalError as exc:
        raise DatabaseUnavailable(f"{exc}\n\n{RECONNECT_HINT}") from exc
    return written


def _upsert_source_file(
    cur: psycopg.Cursor,
    path: str,
    borough: str,
    period: str,
    status: str,
    reason: str | None,
    rows_loaded: int,
) -> None:
    cur.execute(
        "INSERT INTO source_files (path, borough, period, status, reason, rows_loaded) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (path) DO UPDATE SET borough = EXCLUDED.borough, "
        "period = EXCLUDED.period, status = EXCLUDED.status, "
        "reason = EXCLUDED.reason, rows_loaded = EXCLUDED.rows_loaded, "
        "loaded_at = now()",
        (path, borough, period, status, reason, rows_loaded),
    )


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def status_rows(conn: psycopg.Connection) -> list[tuple]:
    """Per-borough counts for `scrooge load-status`, straight from the database."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.slug,
                   count(*) FILTER (WHERE f.status = 'loaded')  AS loaded,
                   count(*) FILTER (WHERE f.status = 'skipped') AS skipped,
                   count(*) FILTER (WHERE f.status = 'failed')  AS failed,
                   coalesce(sum(f.rows_loaded), 0)              AS rows_loaded,
                   min(f.period)                                AS earliest,
                   max(f.period)                                AS latest
            FROM boroughs b
            LEFT JOIN source_files f ON f.borough = b.slug
            GROUP BY b.slug
            HAVING count(f.path) > 0
            ORDER BY b.slug
            """
        )
        return cur.fetchall()


def failed_files(conn: psycopg.Connection, limit: int = 50) -> list[tuple]:
    """The files that failed or were skipped, newest reason first."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT path, status, reason FROM source_files "
            "WHERE status <> 'loaded' ORDER BY status, path LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def iter_boroughs(conn: psycopg.Connection) -> Iterator[tuple[str, str, int | None]]:
    with conn.cursor() as cur:
        cur.execute("SELECT slug, name, population FROM boroughs ORDER BY slug")
        yield from cur.fetchall()
