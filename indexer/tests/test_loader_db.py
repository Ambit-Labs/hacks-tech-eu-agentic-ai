"""Database tests against a throwaway Postgres 17.

They run only when `$SCROOGE_TEST_DATABASE_URL` points at a server this suite
may create and drop a database on, and are skipped otherwise, so a plain
`uv run pytest -q` stays green with no database anywhere near it.

    docker run -d --name scrooge-loader-test -e POSTGRES_PASSWORD=test \\
        -p 127.0.0.1:55432:5432 postgres:17
    export SCROOGE_TEST_DATABASE_URL=postgresql://postgres:$PGPASS@127.0.0.1:55432/postgres

Each run works in its own database, `scrooge_loader_tests`, created fresh and
dropped at the end, so it can never touch a real load.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import pytest

psycopg = pytest.importorskip("psycopg")

from scrooge_indexer.loader import db, runner  # noqa: E402
from scrooge_indexer.loader.files import SpendFile  # noqa: E402

ENV = "SCROOGE_TEST_DATABASE_URL"
TEST_DATABASE = "scrooge_loader_tests"

CAMDEN_HEADER = (
    "payment_date,beneficiary_name,organisational_unit,purpose,amount_gbp,"
    "irrecoverable_vat_amount_gbp,unique_identifier\n"
)
CAMDEN_ROWS = (
    "2019-09-30T00:00:00.000,VEOLIA ES LTD,Supporting Communities,Waste,"
    "1500.00,0.00,ABC1\n"
    "2019-09-02T00:00:00.000,A LTD,Corporate Services,Legal,-250.50,,ABC2\n"
    "N/A,B LTD,Corporate Services,Legal,700.00,,ABC3\n"
    ",,,,,,\n"
)


def _admin_url() -> str:
    url = os.environ.get(ENV)
    if not url:
        pytest.skip(f"${ENV} is not set")
    return url


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, ""))


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """A freshly created database on the server `$SCROOGE_TEST_DATABASE_URL` names."""
    admin = _admin_url()
    try:
        connection = psycopg.connect(admin, connect_timeout=5, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"{ENV} is set but unreachable: {exc}")
    with connection:
        with connection.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    yield _with_database(admin, TEST_DATABASE)
    with psycopg.connect(admin, connect_timeout=5, autocommit=True) as connection:
        with connection.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')


@pytest.fixture
def conn(test_database_url):
    with db.connect(test_database_url) as connection:
        with connection.transaction(), connection.cursor() as cur:
            cur.execute(
                "DROP TABLE IF EXISTS payments, source_files, boroughs CASCADE; "
                "DROP VIEW IF EXISTS coverage CASCADE"
            )
        db.apply_schema(connection)
        db.upsert_boroughs(connection)
        yield connection


@pytest.fixture
def camden_file(tmp_path) -> SpendFile:
    path = tmp_path / "2019-09__camden-payments.csv"
    path.write_text(CAMDEN_HEADER + CAMDEN_ROWS, encoding="utf-8")
    return SpendFile(
        borough="camden",
        path=path,
        relpath="data/raw/camden/2019-09__camden-payments.csv",
        period="2019-09",
    )


# --------------------------------------------------------------------------- #
# db init
# --------------------------------------------------------------------------- #


def test_schema_file_is_where_the_loader_looks():
    path = db.schema_sql_path()
    assert path.name == "payments-schema.sql"
    assert "CREATE TABLE payments" in path.read_text("utf-8")


def test_apply_schema_is_safe_to_run_twice(test_database_url):
    """The second `db init` finds `payments` and leaves the schema alone.

    The role guard is what makes this possible at all: `scrooge_reader` lives
    in the cluster, so it survives dropping every table in the database.
    """
    with db.connect(test_database_url) as connection:
        with connection.transaction(), connection.cursor() as cur:
            cur.execute(
                "DROP TABLE IF EXISTS payments, source_files, boroughs CASCADE; "
                "DROP VIEW IF EXISTS coverage CASCADE"
            )
        assert db.schema_present(connection) is False
        db.apply_schema(connection)
        assert db.schema_present(connection) is True
        # The role exists in the cluster now, which is the case a bare
        # CREATE ROLE would abort on.
        with connection.transaction(), connection.cursor() as cur:
            cur.execute(
                "DROP TABLE payments, source_files, boroughs CASCADE; "
                "DROP VIEW IF EXISTS coverage CASCADE"
            )
        db.apply_schema(connection)
        assert db.schema_present(connection) is True


def test_boroughs_has_all_33_with_populations(conn):
    rows = list(db.iter_boroughs(conn))
    assert len(rows) == 33
    assert all(population and population > 10_000 for _, _, population in rows)
    slugs = {slug for slug, _, _ in rows}
    assert {"camden", "richmond", "city-of-london"} <= slugs


def test_upsert_boroughs_twice_changes_nothing(conn):
    before = list(db.iter_boroughs(conn))
    db.upsert_boroughs(conn)
    assert list(db.iter_boroughs(conn)) == before


# --------------------------------------------------------------------------- #
# load
# --------------------------------------------------------------------------- #


def count(conn, sql: str, *args) -> tuple:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_load_writes_payments_and_a_source_files_row(conn, camden_file):
    result = runner.load_file(conn, camden_file)
    assert result.status == "loaded"
    assert result.rows_loaded == 2
    assert result.rows_dropped == 1
    assert result.reason == "1 rows dropped: 1 bad date"

    assert count(conn, "SELECT count(*), sum(amount_gbp) FROM payments") == (
        2,
        Decimal("1249.50"),
    )
    status, rows_loaded, reason = count(
        conn,
        "SELECT status, rows_loaded, reason FROM source_files WHERE path = %s",
        camden_file.relpath,
    )
    assert (status, rows_loaded) == ("loaded", 2)
    assert "1 rows dropped" in reason


def test_source_row_leaves_a_gap_where_a_row_was_dropped(conn, camden_file):
    runner.load_file(conn, camden_file)
    with conn.cursor() as cur:
        cur.execute("SELECT source_row FROM payments ORDER BY source_row")
        assert [row[0] for row in cur.fetchall()] == [1, 2]


def test_raw_keeps_every_published_column(conn, camden_file):
    runner.load_file(conn, camden_file)
    (raw,) = count(conn, "SELECT raw FROM payments WHERE reference = %s", "ABC1")
    assert raw["beneficiary_name"] == "VEOLIA ES LTD"
    assert raw["irrecoverable_vat_amount_gbp"] == "0.00"


def test_financial_year_and_generated_supplier_norm(conn, camden_file):
    runner.load_file(conn, camden_file)
    year, norm = count(
        conn,
        "SELECT financial_year, supplier_norm FROM payments WHERE reference = %s",
        "ABC1",
    )
    assert year == "2019/20"
    assert norm == "VEOLIA ES LTD"


def test_reloading_the_same_file_leaves_the_same_row_count(conn, camden_file):
    runner.load_file(conn, camden_file)
    first = count(conn, "SELECT count(*) FROM payments")
    runner.load_file(conn, camden_file)
    assert count(conn, "SELECT count(*) FROM payments") == first
    assert count(conn, "SELECT count(*) FROM source_files") == (1,)


def test_a_loaded_file_is_committed_before_the_next_one_starts(
    conn, camden_file, test_database_url
):
    """A second session sees the file as soon as `load_file` returns.

    `scrooge load` reads `source_files` before it writes anything. On a
    connection without autocommit that read opens a transaction, every
    `conn.transaction()` after it is only a savepoint, and the whole run
    commits at exit, so a killed run or a dropped tunnel loses every file.
    """
    db.file_states(conn)
    runner.load_file(conn, camden_file)
    with psycopg.connect(test_database_url, autocommit=True) as other:
        seen = other.execute("SELECT count(*) FROM payments").fetchone()
    assert seen == (2,)


def test_a_rerun_skips_a_loaded_file_and_force_reloads_it(conn, camden_file):
    runner.load_file(conn, camden_file)
    states = db.file_states(conn)
    assert runner.should_skip(states[camden_file.relpath], force=False) is True
    assert runner.should_skip(states[camden_file.relpath], force=True) is False


def test_an_aggregate_file_is_skipped_with_a_reason(conn, tmp_path):
    path = tmp_path / "2011-01__LambethPaymentsOver500January2011.csv"
    path.write_text("Supplier Name,Sum of Invoice Nett Amount\nSicor,500.6\n")
    spend = SpendFile(
        borough="lambeth",
        path=path,
        relpath="data/raw/lambeth/2011-01__LambethPaymentsOver500January2011.csv",
        period="2011-01",
    )
    result = runner.load_file(conn, spend)
    assert result.status == "skipped"
    assert result.reason == "supplier totals, not payments"
    assert count(conn, "SELECT count(*) FROM payments") == (0,)
    states = db.file_states(conn)
    assert states[spend.relpath].status == "skipped"
    assert runner.should_skip(states[spend.relpath], force=False) is True


def test_an_ods_file_is_skipped(conn, tmp_path):
    path = tmp_path / "2018-Q2__report.ods"
    path.write_bytes(b"PK\x03\x04 not really")
    spend = SpendFile(
        borough="lambeth",
        path=path,
        relpath="data/raw/lambeth/2018-Q2__report.ods",
        period="2018-Q2",
    )
    assert runner.load_file(conn, spend).status == "skipped"
    assert db.file_states(conn)[spend.relpath].reason == "no ODS reader"


LAMBETH_HEADER = (
    "Over £500 Report Ref,PAYMENT_DATE,Supplier Name *******,Amount,"
    "Directorate,Division,Subjective Description\n"
)


def lambeth_file(tmp_path, rows: str, name="2020-Q2__ec-over-500-report.csv"):
    path = tmp_path / name
    path.write_text(LAMBETH_HEADER + rows, encoding="utf-8")
    return SpendFile(
        borough="lambeth",
        path=path,
        relpath=f"data/raw/lambeth/{name}",
        period="2020-Q2",
    )


def test_a_month_first_file_loads_and_says_so_in_the_database(conn, tmp_path):
    """Lambeth 2020-Q2 in miniature: detected on the retry, then loaded."""
    spend = lambeth_file(
        tmp_path,
        "R1,09/18/2020,A LTD,500,ADULTS,ASC,CARE\n"
        "R2,07/03/2020,B LTD,250,ADULTS,ASC,CARE\n",
    )
    result = runner.load_file(conn, spend)
    assert result.status == "loaded"
    assert result.rows_loaded == 2
    assert result.reason == "dates read month-first"
    with conn.cursor() as cur:
        cur.execute("SELECT payment_date FROM payments ORDER BY source_row")
        assert [row[0] for row in cur.fetchall()] == [
            date(2020, 9, 18),
            date(2020, 7, 3),
        ]
    assert db.file_states(conn)[spend.relpath].reason == "dates read month-first"


def test_a_month_first_file_keeps_its_dropped_row_count_too(conn, tmp_path):
    spend = lambeth_file(
        tmp_path,
        "R1,09/18/2020,A LTD,500,ADULTS,ASC,CARE\nR2,N/A,B LTD,250,ADULTS,ASC,CARE\n",
    )
    result = runner.load_file(conn, spend)
    assert result.reason == "1 rows dropped: 1 bad date; dates read month-first"


def test_a_file_with_both_date_orders_fails(conn, tmp_path):
    spend = lambeth_file(
        tmp_path,
        "R1,09/18/2020,A LTD,500,ADULTS,ASC,CARE\n"
        "R2,18/09/2020,B LTD,250,ADULTS,ASC,CARE\n",
        name="2020-Q3__mixed.csv",
    )
    result = runner.load_file(conn, spend)
    assert result.status == "failed"
    assert "both orders" in result.reason
    assert count(conn, "SELECT count(*) FROM payments") == (0,)


def test_an_ambiguous_file_stays_day_first(conn, tmp_path):
    spend = lambeth_file(
        tmp_path,
        "R1,07/03/2020,A LTD,500,ADULTS,ASC,CARE\n"
        "R2,01/02/2020,B LTD,250,ADULTS,ASC,CARE\n",
        name="2020-Q4__ambiguous.csv",
    )
    result = runner.load_file(conn, spend)
    assert result.status == "loaded"
    assert result.reason is None
    with conn.cursor() as cur:
        cur.execute("SELECT payment_date FROM payments ORDER BY source_row")
        assert [row[0] for row in cur.fetchall()] == [
            date(2020, 3, 7),
            date(2020, 2, 1),
        ]


def test_a_parenthesised_amount_loads_as_a_negative(conn, tmp_path):
    spend = lambeth_file(
        tmp_path,
        'R1,02/07/2015,A LTD,"(1,040.22)",ADULTS,ASC,CARE\n'
        'R2,03/07/2015,B LTD,"(£559.33)",ADULTS,ASC,CARE\n',
        name="2015-Q2__parens.csv",
    )
    assert runner.load_file(conn, spend).rows_loaded == 2
    assert count(conn, "SELECT sum(amount_gbp) FROM payments") == (Decimal("-1599.55"),)


def test_a_failed_file_is_retried_without_force(conn, camden_file):
    """Deliberate: a failure is usually transient and a rerun is the recovery."""
    db.record_outcome(
        conn,
        path=camden_file.relpath,
        borough="camden",
        period="2019-09",
        status="failed",
        reason="connection dropped",
    )
    states = db.file_states(conn)
    assert runner.should_skip(states[camden_file.relpath], force=False) is False
    assert runner.load_file(conn, camden_file).status == "loaded"


def test_reloading_replaces_rather_than_appends(conn, camden_file):
    runner.load_file(conn, camden_file)
    camden_file.path.write_text(
        CAMDEN_HEADER + "2019-09-30T00:00:00.000,ONE LTD,Unit,Waste,10.00,0.00,X1\n",
        encoding="utf-8",
    )
    runner.load_file(conn, camden_file)
    assert count(conn, "SELECT count(*) FROM payments") == (1,)
    assert count(conn, "SELECT supplier FROM payments") == ("ONE LTD",)


# --------------------------------------------------------------------------- #
# what the agent sees
# --------------------------------------------------------------------------- #


def test_coverage_has_a_row_per_borough_and_month(conn, camden_file):
    runner.load_file(conn, camden_file)
    with conn.cursor() as cur:
        cur.execute("SELECT borough, month, payments, total_gbp FROM coverage")
        rows = cur.fetchall()
    assert len(rows) == 1
    borough, month, payments, total = rows[0]
    assert (borough, str(month), payments) == ("camden", "2019-09-01", 2)
    assert total == Decimal("1249.50")


def test_scrooge_reader_can_select_and_cannot_write(conn, camden_file):
    runner.load_file(conn, camden_file)
    db.grant_reader(conn)
    with conn.cursor() as cur:
        cur.execute("SET ROLE scrooge_reader")
        for table in ("boroughs", "source_files", "payments", "coverage"):
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] >= 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "INSERT INTO payments (borough, payment_date, financial_year, "
                "supplier, amount_gbp, source_file, source_row, raw) VALUES "
                "('camden', '2019-09-01', '2019/20', 'X', 1, %s, 99, '{}')",
                (camden_file.relpath,),
            )
    conn.rollback()


def test_status_rows_report_per_borough(conn, camden_file):
    runner.load_file(conn, camden_file)
    rows = db.status_rows(conn)
    assert len(rows) == 1
    slug, loaded, skipped, failed, rows_loaded, earliest, latest = rows[0]
    assert (slug, loaded, skipped, failed, rows_loaded) == ("camden", 1, 0, 0, 2)
    assert earliest == latest == "2019-09"


def test_redact_keeps_the_password_out_of_the_summary_line():
    assert db.redact("postgresql://agent:hunter2@1.2.3.4:5432/postgres") == (
        "postgresql://agent:***@1.2.3.4:5432/postgres"
    )


def test_missing_database_url_says_where_to_get_one(monkeypatch):
    # A checkout with a DATABASE_URL in .env.local would put it straight back.
    monkeypatch.setattr(db, "load_env", lambda *_: None)
    monkeypatch.delenv(db.ENV_DATABASE_URL, raising=False)
    with pytest.raises(db.DatabaseUnavailable, match="pg url"):
        db.database_url()


def test_a_refused_connection_says_how_to_re_export(monkeypatch):
    monkeypatch.setenv(db.ENV_DATABASE_URL, "postgresql://x@127.0.0.1:1/postgres")
    with pytest.raises(db.DatabaseUnavailable, match="re-export"):
        db.connect()


def test_an_unparseable_url_is_reported_without_echoing_it(monkeypatch):
    """The driver quotes the string it could not parse, password and all."""
    monkeypatch.setenv(db.ENV_DATABASE_URL, "postgresql//agent:hunter2@host/postgres")
    with pytest.raises(db.DatabaseUnavailable) as caught:
        db.connect()
    assert "hunter2" not in str(caught.value)
    assert "DATABASE_URL" in str(caught.value)
