# Scrooge agent implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `agent/` from a no-tool chat stub into a Pydantic AI agent with seven database tools that answers questions about London borough spending, traced in Logfire.

**Architecture:** FastAPI serves `POST /chat` through Pydantic AI's Vercel AI adapter, as it does today. A `Database` wrapper around a psycopg async pool is passed to the agent as deps. Seven tools run fixed parameterised queries against the `payments` table and return typed Pydantic results. Logfire instruments FastAPI, Pydantic AI and psycopg.

**Tech Stack:** Python 3.12, uv, pydantic-ai-slim 2.46 (`google`, `ui` extras), FastAPI, psycopg 3 with psycopg_pool, logfire 5.1, modal (for the endpoint re-resolve), pytest with pytest-asyncio, Docker for the test Postgres.

**Spec:** `docs/superpowers/specs/2026-09-19-scrooge-agent-design.md` and `docs/payments-schema.md`

## Global constraints

- Never run `git commit` or `git push`. Leave every change in the working tree; the owner commits.
- Work inside `agent/` only, plus `agent/README.md`. Do not touch `web/`, `indexer/`, `infra/`, `data/` or `docs/` except where a task names a file there.
- Never print, log or copy the value of any key or password. `.env.local` files are read by `uv run --env-file`, never by code.
- Every command runs from `/home/ubuntu/projects/hacks/hacks-tech-eu-agentic-ai/agent` with `uv run`.
- Prose (README, docstrings, comments) follows the unslop rules: no em dashes, plain words, active voice, no filler. Tool docstrings are read by the model; keep them one to three sentences, specific.
- Python style: match `agent/main.py` as it is now. Module docstring, constants in caps, type hints everywhere, `from __future__ import annotations` at the top of every new module.
- Tests run with `uv run pytest -q`. They need Docker. `TEST_DATABASE_URL` skips the container and uses that database instead.

---

### Task 1: Dependencies, settings, test harness

**Files:**
- Modify: `agent/pyproject.toml`
- Create: `agent/config.py`
- Create: `agent/tests/__init__.py` (empty)
- Create: `agent/tests/conftest.py`
- Create: `agent/tests/seed.sql`
- Test: `agent/tests/test_config.py`

**Interfaces:**
- Produces: `config.Settings` with fields `model: str`, `google_api_key: str | None`, `database_url: str | None`, `environment: str`, and `Settings.from_env(env: Mapping[str, str] | None = None) -> Settings`. Constants `MODEL_ENV`, `DEFAULT_MODEL`, `GOOGLE_KEY_ENV`, `DATABASE_URL_ENV`, `ENV_ENV`.
- Produces: pytest fixture `database_url` (session scope, a URL to a Postgres with the schema and seed applied).

- [ ] **Step 1: Add dependencies**

Run:
```bash
uv add "psycopg[binary,pool]>=3.2" "logfire[fastapi,psycopg]>=5.1" "modal>=1.5.5,<2"
uv add --dev "pytest>=8" "pytest-asyncio>=0.24" "httpx>=0.28"
```

Then add to `agent/pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Replace the placeholder `description = "Add your description here"` with `description = "Chat agent over London borough spending data"`.

- [ ] **Step 2: Write the failing test for settings**

`agent/tests/test_config.py`:
```python
from config import DEFAULT_MODEL, Settings


def test_defaults_when_env_is_empty():
    settings = Settings.from_env({})
    assert settings.model == DEFAULT_MODEL
    assert settings.google_api_key is None
    assert settings.database_url is None
    assert settings.environment == "dev"


def test_reads_every_variable():
    settings = Settings.from_env(
        {
            "AGENT_MODEL": "test",
            "GOOGLE_AI_STUDIO_KEY": "k",
            "DATABASE_URL": "postgresql://a:b@h:1/d",
            "AGENT_ENV": "prod",
        }
    )
    assert settings.model == "test"
    assert settings.google_api_key == "k"
    assert settings.database_url == "postgresql://a:b@h:1/d"
    assert settings.environment == "prod"


def test_blank_values_count_as_missing():
    settings = Settings.from_env({"GOOGLE_AI_STUDIO_KEY": "", "DATABASE_URL": ""})
    assert settings.google_api_key is None
    assert settings.database_url is None
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 4: Write config.py**

`agent/config.py`:
```python
"""Settings read from the environment, once, at startup.

Every name the agent reads from the environment is a constant here, so the
README and the code cannot drift apart.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

MODEL_ENV = "AGENT_MODEL"
DEFAULT_MODEL = "google:gemini-3.8-flash"

# Kept in step with web/src/lib/model.ts: the two backends share one key.
GOOGLE_KEY_ENV = "GOOGLE_AI_STUDIO_KEY"

DATABASE_URL_ENV = "DATABASE_URL"

# The Logfire environment label. `dev` on a laptop, so weekend traces can be
# filtered out later.
ENV_ENV = "AGENT_ENV"
DEFAULT_ENV = "dev"


@dataclass(frozen=True)
class Settings:
    model: str
    google_api_key: str | None
    database_url: str | None
    environment: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        return cls(
            model=source.get(MODEL_ENV) or DEFAULT_MODEL,
            google_api_key=source.get(GOOGLE_KEY_ENV) or None,
            database_url=source.get(DATABASE_URL_ENV) or None,
            environment=source.get(ENV_ENV) or DEFAULT_ENV,
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_config.py -q`
Expected: 3 passed

- [ ] **Step 6: Write the seed**

`agent/tests/seed.sql`. Two boroughs, two months each, amounts chosen so totals are easy to assert. Populations are the ONS mid-2022 estimates rounded; they only need to be plausible.
```sql
INSERT INTO boroughs (slug, name, population) VALUES
  ('camden',    'London Borough of Camden',    210000),
  ('islington', 'London Borough of Islington', 220000);

INSERT INTO source_files (path, borough, period, status, rows_loaded) VALUES
  ('data/raw/camden/2019-09__camden-payments.csv',    'camden',    '2019-09', 'loaded', 6),
  ('data/raw/camden/2019-10__camden-payments.csv',    'camden',    '2019-10', 'loaded', 4),
  ('data/raw/islington/2019-09__islington.csv',       'islington', '2019-09', 'loaded', 5),
  ('data/raw/islington/2019-10__islington.csv',       'islington', '2019-10', 'loaded', 3);

INSERT INTO payments
  (borough, payment_date, financial_year, supplier, directorate, department, purpose, amount_gbp, vat_gbp, reference, source_file, source_row, raw)
VALUES
  -- camden, September 2019: total 10000.00 over 6 rows
  ('camden', '2019-09-02', '2019/20', 'NSL LIMITED',            'Corporate Services GF',    NULL, 'Third Party Payment Not Government', 5000.00, 0, 'sep-19-1', 'data/raw/camden/2019-09__camden-payments.csv', 1, '{}'),
  ('camden', '2019-09-05', '2019/20', 'CAPITA BUSINESS SERVICES', 'Corporate Services GF',  NULL, 'Consultants Fees',                  2000.00, 0, 'sep-19-2', 'data/raw/camden/2019-09__camden-payments.csv', 2, '{}'),
  ('camden', '2019-09-10', '2019/20', 'GREAT ORMOND STREET HOSPITAL', 'Supporting Communities GF', NULL, 'Professional Services General', 1500.00, 0, 'sep-19-3', 'data/raw/camden/2019-09__camden-payments.csv', 3, '{}'),
  ('camden', '2019-09-12', '2019/20', 'ACME TEMP ACCOMMODATION LTD', 'Supporting Communities GF', NULL, 'Temporary Accommodation',  800.00, 0, 'sep-19-4', 'data/raw/camden/2019-09__camden-payments.csv', 4, '{}'),
  ('camden', '2019-09-20', '2019/20', 'ACME TEMP ACCOMMODATION LTD', 'Supporting Communities GF', NULL, 'Temporary Accommodation',  600.00, 0, 'sep-19-5', 'data/raw/camden/2019-09__camden-payments.csv', 5, '{}'),
  ('camden', '2019-09-28', '2019/20', 'NSL LIMITED',            'Corporate Services GF',    NULL, 'Third Party Payment Not Government',  100.00, 0, 'sep-19-6', 'data/raw/camden/2019-09__camden-payments.csv', 6, '{}'),
  -- camden, October 2019: total 4000.00 over 4 rows, one negative
  ('camden', '2019-10-01', '2019/20', 'CAPITA BUSINESS SERVICES', 'Corporate Services GF',  NULL, 'Consultants Fees',                  3000.00, 0, 'oct-19-1', 'data/raw/camden/2019-10__camden-payments.csv', 1, '{}'),
  ('camden', '2019-10-08', '2019/20', 'NSL LIMITED',            'Corporate Services GF',    NULL, 'Third Party Payment Not Government',  700.00, 0, 'oct-19-2', 'data/raw/camden/2019-10__camden-payments.csv', 2, '{}'),
  ('camden', '2019-10-15', '2019/20', 'BIG BUILD CONSTRUCTION LTD', 'Supporting Communities GF', NULL, 'Works - Construction',         500.00, 0, 'oct-19-3', 'data/raw/camden/2019-10__camden-payments.csv', 3, '{}'),
  ('camden', '2019-10-22', '2019/20', 'NSL LIMITED',            'Corporate Services GF',    NULL, 'Third Party Payment Not Government', -200.00, 0, 'oct-19-4', 'data/raw/camden/2019-10__camden-payments.csv', 4, '{}'),
  -- islington, September 2019: total 6000.00 over 5 rows
  ('islington', '2019-09-03', '2019/20', 'Capita Business Services Ltd', 'Housing', 'Cap Prog Delivery', 'Consultants - Fees',     2500.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 1, '{}'),
  ('islington', '2019-09-09', '2019/20', 'Reed Agency Staff',            'Housing', 'Estates',           'Agency Staff',           1500.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 2, '{}'),
  ('islington', '2019-09-16', '2019/20', 'Reed Agency Staff',            'Children', 'Social Work',      'Agency Staff',           1000.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 3, '{}'),
  ('islington', '2019-09-23', '2019/20', '10 Ability Limited',           'Housing', 'Cap Prog Delivery', 'Consultants - Fees',      600.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 4, '{}'),
  ('islington', '2019-09-30', '2019/20', 'Big Build Construction Ltd',   'Housing', 'Estates',           'Works - Construction',    400.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 5, '{}'),
  -- islington, October 2019: total 2100.00 over 3 rows
  ('islington', '2019-10-04', '2019/20', 'Reed Agency Staff',            'Children', 'Social Work',      'Agency Staff',           1200.00, NULL, NULL, 'data/raw/islington/2019-10__islington.csv', 1, '{}'),
  ('islington', '2019-10-11', '2019/20', 'Capita Business Services Ltd', 'Housing', 'Cap Prog Delivery', 'Consultants - Fees',      500.00, NULL, NULL, 'data/raw/islington/2019-10__islington.csv', 2, '{}'),
  ('islington', '2019-10-25', '2019/20', '10 Ability Limited',           'Housing', 'Cap Prog Delivery', 'Consultants - Fees',      400.00, NULL, NULL, 'data/raw/islington/2019-10__islington.csv', 3, '{}');
```

Totals to assert later: camden 2019-09 = 10000.00 (6 rows); camden 2019-10 = 4000.00 (4 rows); camden Sep+Oct = 14000.00 (10 rows); islington 2019-09 = 6000.00 (5 rows); islington 2019-10 = 2100.00 (3 rows); all islington = 8100.00 (8 rows). NSL LIMITED camden total = 5600.00 over 4 rows (5000 + 100 + 700 - 200). Capita across both boroughs, any case, = 8000.00 over 5 rows. Temporary accommodation camden = 1400.00 over 2 rows. Agency staff islington = 3700.00 over 3 rows.

- [ ] **Step 7: Write conftest.py**

`agent/tests/conftest.py`:
```python
"""A throwaway Postgres 17 for the tests.

Starts a Docker container once per session, applies docs/payments-schema.sql
and tests/seed.sql, and removes the container at the end. Set
TEST_DATABASE_URL to use an existing database instead; the schema and seed
are then applied to that database, so point it at something disposable.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "docs" / "payments-schema.sql"
SEED_SQL = Path(__file__).with_name("seed.sql")

IMAGE = "postgres:17"
PASSWORD = "test"
READY_TIMEOUT_SECONDS = 60


def _apply(url: str, path: Path) -> None:
    # No parameters, so psycopg sends the whole file as one simple query and
    # Postgres runs every statement in it.
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(path.read_text())


def _wait_until_ready(url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while True:
        try:
            psycopg.connect(url, connect_timeout=2).close()
            return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def _host_port(container: str) -> str:
    out = subprocess.run(
        ["docker", "port", container, "5432/tcp"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    # One line per address family; the first is enough.
    return out.strip().splitlines()[0].rsplit(":", 1)[1]


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if url := os.environ.get("TEST_DATABASE_URL"):
        _apply(url, SCHEMA_SQL)
        _apply(url, SEED_SQL)
        yield url
        return

    container = f"scrooge-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", container,
            "-e", f"POSTGRES_PASSWORD={PASSWORD}",
            "-p", "127.0.0.1::5432",
            IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        url = f"postgresql://postgres:{PASSWORD}@127.0.0.1:{_host_port(container)}/postgres"
        _wait_until_ready(url)
        _apply(url, SCHEMA_SQL)
        _apply(url, SEED_SQL)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
```

- [ ] **Step 8: Prove the fixture works**

Append to `agent/tests/test_config.py`:
```python
import psycopg


def test_seed_is_loaded(database_url):
    with psycopg.connect(database_url) as conn:
        (count,) = conn.execute("SELECT count(*) FROM payments").fetchone()
    assert count == 18
```

Run: `uv run pytest tests/test_config.py -q`
Expected: 4 passed. The first run pulls `postgres:17` if it is not cached; allow a minute.

If Docker refuses with a permission error, stop and report; do not use `sudo`.

---

### Task 2: Database wrapper with the Modal re-resolve

**Files:**
- Create: `agent/db.py`
- Test: `agent/tests/test_db.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `db.Database(url: str, *, resolver: Callable[[str], str] = resolve_from_modal)` with `async open() -> None`, `async close() -> None`, `async fetch_all(sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]`. Pure helper `db.with_endpoint(url: str, host: str, port: int) -> str`. `db.resolve_from_modal(url: str) -> str`.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_db.py`:
```python
import psycopg
import pytest

from db import Database, with_endpoint


def test_with_endpoint_keeps_credentials_and_database():
    url = "postgresql://agent:p%40ss@old-host:1111/postgres"
    assert with_endpoint(url, "new-host", 2222) == "postgresql://agent:p%40ss@new-host:2222/postgres"


def test_with_endpoint_without_userinfo():
    assert with_endpoint("postgresql://old:1/db", "h", 5) == "postgresql://h:5/db"


async def test_fetch_all_returns_dict_rows(database_url):
    db = Database(database_url)
    await db.open()
    try:
        rows = await db.fetch_all(
            "SELECT borough, count(*) AS n FROM payments WHERE borough = %(b)s GROUP BY borough",
            {"b": "camden"},
        )
    finally:
        await db.close()
    assert rows == [{"borough": "camden", "n": 10}]


async def test_reresolves_once_on_connection_error(database_url):
    # Start with a port nothing listens on; the resolver hands back the real URL.
    broken = with_endpoint(database_url, "127.0.0.1", 1)
    calls: list[str] = []

    def resolver(url: str) -> str:
        calls.append(url)
        return database_url

    db = Database(broken, resolver=resolver)
    await db.open()
    try:
        rows = await db.fetch_all("SELECT 1 AS one")
    finally:
        await db.close()
    assert rows == [{"one": 1}]
    assert calls == [broken]


async def test_gives_up_after_one_reresolve(database_url):
    broken = with_endpoint(database_url, "127.0.0.1", 1)
    db = Database(broken, resolver=lambda url: url)
    await db.open()
    try:
        with pytest.raises(psycopg.OperationalError):
            await db.fetch_all("SELECT 1")
    finally:
        await db.close()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_db.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Write db.py**

`agent/db.py`:
```python
"""The connection pool, and finding the database again when it moves.

The Postgres server runs in a Modal container and gets a new host and port
every time that container restarts (see infra/README.md). The server
publishes its address into a Modal Dict; on a connection error this module
reads that Dict, keeps the user, password and database from the URL it was
given, swaps in the new host and port, reopens the pool and retries once.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

# Mirrored from infra/src/scrooge_infra/endpoint.py so this package does not
# import that one.
ENDPOINT_DICT_NAME = "scrooge-postgres-endpoint"
ENDPOINT_KEY = "current"

POOL_MIN = 1
POOL_MAX = 4
# Seconds to wait for a connection from the pool. The role's own
# statement_timeout bounds the query itself.
POOL_TIMEOUT = 10.0


def with_endpoint(url: str, host: str, port: int) -> str:
    """The same URL pointed at a new host and port."""
    parts = urllib.parse.urlsplit(url)
    userinfo, _, _ = parts.netloc.rpartition("@")
    netloc = f"{userinfo}@{host}:{port}" if userinfo else f"{host}:{port}"
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def resolve_from_modal(url: str) -> str:
    """Re-read host and port from the Dict the infra server publishes into."""
    import modal

    record = modal.Dict.from_name(ENDPOINT_DICT_NAME).get(ENDPOINT_KEY)
    if not isinstance(record, dict) or "host" not in record or "port" not in record:
        raise RuntimeError(
            "no Postgres endpoint is published in Modal. Run `uv run pg start` in infra/."
        )
    return with_endpoint(url, str(record["host"]), int(record["port"]))


class Database:
    """A pool that survives the server moving.

    `open()` does not connect: the pool connects lazily on first use, so a
    wrong address surfaces from `fetch_all`, where the re-resolve can handle
    it, and not from startup.
    """

    def __init__(self, url: str, *, resolver: Callable[[str], str] = resolve_from_modal) -> None:
        self._url = url
        self._resolver = resolver
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        self._pool = AsyncConnectionPool(
            self._url,
            min_size=POOL_MIN,
            max_size=POOL_MAX,
            timeout=POOL_TIMEOUT,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        await self._pool.open(wait=False)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def fetch_all(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run one statement and return every row as a dict."""
        try:
            return await self._run(sql, params)
        except psycopg.OperationalError:
            self._url = self._resolver(self._url)
            await self.close()
            await self.open()
            return await self._run(sql, params)

    async def _run(self, sql: str, params: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        if self._pool is None:
            raise RuntimeError("Database.open() was not called")
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params)
            return await cursor.fetchall()
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_db.py -q`
Expected: 5 passed

If `test_reresolves_once_on_connection_error` fails because the pool raises `psycopg_pool.PoolTimeout` instead of `psycopg.OperationalError`, catch both in `fetch_all`: `except (psycopg.OperationalError, PoolTimeout):` with `from psycopg_pool import PoolTimeout`, and change the `pytest.raises` in the last test to `pytest.raises((psycopg.OperationalError, PoolTimeout))`. Report which one fired.

---

### Task 3: Deps, result models, and the first three tools

**Files:**
- Create: `agent/tools.py`
- Test: `agent/tests/test_tools.py`

**Interfaces:**
- Consumes: `db.Database` from Task 2.
- Produces: `tools.Deps` dataclass with `db: Database`. Result models `Coverage`, `SpendTotal`, `SpendBy`, `GroupRow`, `Matched`. Async tool functions `coverage`, `spend_total`, `spend_by`, each taking `ctx: RunContext[Deps]` first. Module-level `ROW_LIMIT = 50` and helpers `_like`, `_norm`, `_filters` reused by Task 4.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_tools.py`:
```python
from datetime import date

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from db import Database
from tools import Deps, coverage, spend_by, spend_total


@pytest.fixture
async def ctx(database_url):
    db = Database(database_url)
    await db.open()
    yield RunContext(deps=Deps(db=db), model=TestModel(), usage=RunUsage())
    await db.close()


async def test_coverage_lists_every_borough_and_month(ctx):
    result = await coverage(ctx)
    got = {(r.borough, r.month.isoformat(), r.payments, r.total_gbp) for r in result.rows}
    assert got == {
        ("camden", "2019-09-01", 6, 10000.0),
        ("camden", "2019-10-01", 4, 4000.0),
        ("islington", "2019-09-01", 5, 6000.0),
        ("islington", "2019-10-01", 3, 2100.0),
    }


async def test_coverage_for_one_borough(ctx):
    result = await coverage(ctx, borough="Islington ")
    assert {r.borough for r in result.rows} == {"islington"}


async def test_spend_total_for_a_month(ctx):
    result = await spend_total(ctx, "camden", date(2019, 9, 1), date(2019, 9, 30))
    assert result.total_gbp == 10000.0
    assert result.payments == 6
    assert result.matched.departments == []


async def test_spend_total_with_purpose_filter_reports_matches(ctx):
    result = await spend_total(
        ctx, "camden", date(2019, 9, 1), date(2019, 10, 31), purpose_like="temporary accom"
    )
    assert result.total_gbp == 1400.0
    assert result.payments == 2
    assert result.matched.purposes == ["Temporary Accommodation"]


async def test_spend_total_with_department_filter(ctx):
    result = await spend_total(
        ctx, "islington", date(2019, 9, 1), date(2019, 10, 31), department_like="social work"
    )
    assert result.total_gbp == 2200.0
    assert result.matched.departments == ["Children / Social Work"]


async def test_spend_total_empty(ctx):
    result = await spend_total(ctx, "hackney", date(2019, 9, 1), date(2019, 9, 30))
    assert result.total_gbp == 0.0
    assert result.payments == 0


async def test_spend_total_escapes_like_wildcards(ctx):
    result = await spend_total(ctx, "camden", date(2019, 9, 1), date(2019, 10, 31), purpose_like="%")
    assert result.payments == 0


async def test_spend_by_supplier_orders_by_total(ctx):
    result = await spend_by(ctx, "camden", date(2019, 9, 1), date(2019, 10, 31), group_by="supplier")
    assert [(r.key, r.total_gbp, r.payments) for r in result.rows[:2]] == [
        ("NSL LIMITED", 5600.0, 4),
        ("CAPITA BUSINESS SERVICES", 5000.0, 2),
    ]


async def test_spend_by_month_orders_by_key(ctx):
    result = await spend_by(ctx, "islington", date(2019, 9, 1), date(2019, 10, 31), group_by="month")
    assert [(r.key, r.total_gbp) for r in result.rows] == [("2019-09", 6000.0), ("2019-10", 2100.0)]


async def test_spend_by_department_joins_both_levels(ctx):
    result = await spend_by(ctx, "islington", date(2019, 9, 1), date(2019, 9, 30), group_by="department")
    assert result.rows[0].key == "Housing / Cap Prog Delivery"
    assert result.rows[0].total_gbp == 3100.0


async def test_spend_by_limit_is_clamped(ctx):
    result = await spend_by(ctx, "camden", date(2019, 9, 1), date(2019, 10, 31), group_by="supplier", limit=0)
    assert len(result.rows) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_tools.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Write tools.py with Deps, models, helpers and the three tools**

`agent/tools.py`:
```python
"""The tools the agent can call. Each one is a fixed query over `payments`.

The model never writes SQL. Every tool takes typed arguments, runs one
parameterised statement as the read-only role, and returns a typed result
with the aggregate, the row count behind it, which distinct values a
substring filter matched, and at most ROW_LIMIT rows. Docstrings are what the
model reads when choosing a tool, so they say what the tool answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from db import Database

ROW_LIMIT = 50
MATCH_LIMIT = 20

# The same normalisation Postgres applies in the generated column
# payments.supplier_norm, so a supplier filter compares like with like.
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")

# The expression the department trigram index is built on, verbatim from
# docs/payments-schema.sql.
DEPARTMENT_EXPR = "upper(coalesce(directorate, '') || ' ' || coalesce(department, ''))"
DEPARTMENT_LABEL = "coalesce(directorate, '') || ' / ' || coalesce(department, '')"

GroupBy = Literal["department", "purpose", "supplier", "month", "financial_year"]

GROUP_EXPR: dict[str, str] = {
    "department": DEPARTMENT_LABEL,
    "purpose": "coalesce(purpose, '')",
    "supplier": "supplier",
    "month": "to_char(date_trunc('month', payment_date), 'YYYY-MM')",
    "financial_year": "financial_year",
}


@dataclass
class Deps:
    db: Database


class Matched(BaseModel):
    """Which distinct values a substring filter matched, so the answer can name them."""

    departments: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)


class CoverageRow(BaseModel):
    borough: str
    month: date
    payments: int
    total_gbp: float


class Coverage(BaseModel):
    rows: list[CoverageRow]


class SpendTotal(BaseModel):
    borough: str
    period_from: date
    period_to: date
    total_gbp: float
    payments: int
    matched: Matched


class GroupRow(BaseModel):
    key: str
    total_gbp: float
    payments: int


class SpendBy(BaseModel):
    borough: str
    period_from: date
    period_to: date
    group_by: str
    rows: list[GroupRow]
    matched: Matched


def _slug(borough: str) -> str:
    return borough.strip().lower()


def _like(value: str) -> str:
    """A LIKE pattern that matches `value` as a substring, wildcards escaped."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _norm(value: str) -> str:
    return _NON_ALNUM.sub(" ", value.upper()).strip()


def _clamp(limit: int, ceiling: int = ROW_LIMIT) -> int:
    return max(1, min(limit, ceiling))


def _filters(
    *,
    period_from: date,
    period_to: date,
    borough: str | None = None,
    boroughs: list[str] | None = None,
    department_like: str | None = None,
    purpose_like: str | None = None,
    supplier_like: str | None = None,
    min_amount: float | None = None,
    text: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """A WHERE clause body and its parameters. Only the filters given are added."""
    clauses = ["payment_date >= %(period_from)s", "payment_date <= %(period_to)s"]
    params: dict[str, Any] = {"period_from": period_from, "period_to": period_to}
    if borough:
        clauses.append("borough = %(borough)s")
        params["borough"] = _slug(borough)
    if boroughs:
        clauses.append("borough = ANY(%(boroughs)s)")
        params["boroughs"] = [_slug(b) for b in boroughs]
    if department_like:
        clauses.append(f"{DEPARTMENT_EXPR} LIKE upper(%(department_like)s)")
        params["department_like"] = _like(department_like)
    if purpose_like:
        clauses.append("upper(purpose) LIKE upper(%(purpose_like)s)")
        params["purpose_like"] = _like(purpose_like)
    if supplier_like:
        clauses.append("supplier_norm LIKE %(supplier_like)s")
        params["supplier_like"] = _like(_norm(supplier_like))
    if min_amount is not None:
        clauses.append("amount_gbp >= %(min_amount)s")
        params["min_amount"] = min_amount
    if text:
        clauses.append(
            "(supplier_norm LIKE %(text_norm)s OR upper(purpose) LIKE upper(%(text)s)"
            f" OR {DEPARTMENT_EXPR} LIKE upper(%(text)s))"
        )
        params["text_norm"] = _like(_norm(text))
        params["text"] = _like(text)
    return " AND ".join(clauses), params


async def _matched(
    db: Database, where: str, params: dict[str, Any], *, department: bool, purpose: bool
) -> Matched:
    """The distinct department and purpose values inside a filtered set."""
    result = Matched()
    if department:
        rows = await db.fetch_all(
            f"SELECT DISTINCT {DEPARTMENT_LABEL} AS label FROM payments WHERE {where}"
            f" ORDER BY label LIMIT {MATCH_LIMIT}",
            params,
        )
        result.departments = [r["label"] for r in rows]
    if purpose:
        rows = await db.fetch_all(
            f"SELECT DISTINCT coalesce(purpose, '') AS label FROM payments WHERE {where}"
            f" ORDER BY label LIMIT {MATCH_LIMIT}",
            params,
        )
        result.purposes = [r["label"] for r in rows]
    return result


async def coverage(ctx: RunContext[Deps], borough: str | None = None) -> Coverage:
    """Which boroughs have data and which months each covers, with payment counts and totals. Use it when unsure whether a borough or period is loaded."""
    where = "WHERE borough = %(borough)s" if borough else ""
    rows = await ctx.deps.db.fetch_all(
        f"SELECT borough, month, payments, total_gbp FROM coverage {where} ORDER BY borough, month",
        {"borough": _slug(borough)} if borough else None,
    )
    return Coverage(
        rows=[
            CoverageRow(
                borough=r["borough"],
                month=r["month"],
                payments=r["payments"],
                total_gbp=float(r["total_gbp"]),
            )
            for r in rows
        ]
    )


async def spend_total(
    ctx: RunContext[Deps],
    borough: str,
    period_from: date,
    period_to: date,
    department_like: str | None = None,
    purpose_like: str | None = None,
) -> SpendTotal:
    """Total spend of one borough between two dates, inclusive, with the number of payments behind it. Narrow it with a substring of the department or of the purpose, such as "temporary accommodation" or "agency"."""
    where, params = _filters(
        period_from=period_from,
        period_to=period_to,
        borough=borough,
        department_like=department_like,
        purpose_like=purpose_like,
    )
    rows = await ctx.deps.db.fetch_all(
        f"SELECT coalesce(sum(amount_gbp), 0) AS total, count(*) AS n FROM payments WHERE {where}",
        params,
    )
    matched = await _matched(
        ctx.deps.db, where, params, department=bool(department_like), purpose=bool(purpose_like)
    )
    return SpendTotal(
        borough=_slug(borough),
        period_from=period_from,
        period_to=period_to,
        total_gbp=float(rows[0]["total"]),
        payments=rows[0]["n"],
        matched=matched,
    )


async def spend_by(
    ctx: RunContext[Deps],
    borough: str,
    period_from: date,
    period_to: date,
    group_by: GroupBy,
    department_like: str | None = None,
    purpose_like: str | None = None,
    limit: int = 20,
) -> SpendBy:
    """Spend of one borough between two dates broken down by department, purpose, supplier, month or financial year. Biggest first, except month and financial_year which come in date order. Use it for top suppliers, which department spends most, and trends over time."""
    where, params = _filters(
        period_from=period_from,
        period_to=period_to,
        borough=borough,
        department_like=department_like,
        purpose_like=purpose_like,
    )
    expr = GROUP_EXPR[group_by]
    order = "key" if group_by in ("month", "financial_year") else "total DESC, key"
    rows = await ctx.deps.db.fetch_all(
        f"SELECT {expr} AS key, sum(amount_gbp) AS total, count(*) AS n FROM payments"
        f" WHERE {where} GROUP BY key ORDER BY {order} LIMIT {_clamp(limit)}",
        params,
    )
    matched = await _matched(
        ctx.deps.db, where, params, department=bool(department_like), purpose=bool(purpose_like)
    )
    return SpendBy(
        borough=_slug(borough),
        period_from=period_from,
        period_to=period_to,
        group_by=group_by,
        rows=[GroupRow(key=r["key"], total_gbp=float(r["total"]), payments=r["n"]) for r in rows],
        matched=matched,
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_tools.py -q`
Expected: 11 passed

If `RunContext(...)` in the fixture rejects the keyword arguments, check its dataclass fields with `uv run python -c "import dataclasses, pydantic_ai; print([f.name for f in dataclasses.fields(pydantic_ai.RunContext)])"` and pass the required ones (`deps`, `model`, `usage`, plus whatever else has no default). Report the field list.

---

### Task 4: The other four tools

**Files:**
- Modify: `agent/tools.py` (append)
- Test: `agent/tests/test_tools.py` (append)

**Interfaces:**
- Consumes: `Deps`, `_filters`, `_matched`, `_slug`, `_clamp`, `ROW_LIMIT` from Task 3.
- Produces: models `Payment`, `Payments`, `SupplierPayments`, `ComparisonRow`, `BoroughComparison`; tools `supplier_payments`, `largest_payments`, `search_payments`, `compare_boroughs`. Module constant `ALL_TOOLS: list` with all seven functions in this order: `coverage, spend_total, spend_by, supplier_payments, largest_payments, search_payments, compare_boroughs`.

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_tools.py`:
```python
from tools import ALL_TOOLS, compare_boroughs, largest_payments, search_payments, supplier_payments


async def test_supplier_payments_matches_across_case_and_suffix(ctx):
    result = await supplier_payments(ctx, "capita", date(2019, 9, 1), date(2019, 10, 31))
    assert result.total_gbp == 8000.0
    assert result.payments == 5
    assert result.boroughs == ["camden", "islington"]
    assert result.first_date == date(2019, 9, 3)
    assert result.last_date == date(2019, 10, 11)
    assert len(result.rows) == 5


async def test_supplier_payments_in_one_borough(ctx):
    result = await supplier_payments(ctx, "NSL", date(2019, 9, 1), date(2019, 10, 31), borough="camden")
    assert result.total_gbp == 5600.0
    assert result.payments == 4


async def test_supplier_payments_none(ctx):
    result = await supplier_payments(ctx, "nobody", date(2019, 9, 1), date(2019, 10, 31))
    assert result.payments == 0
    assert result.first_date is None
    assert result.rows == []


async def test_largest_payments_across_boroughs(ctx):
    result = await largest_payments(ctx, date(2019, 9, 1), date(2019, 10, 31), limit=3)
    assert [(r.borough, r.amount_gbp) for r in result.rows] == [
        ("camden", 5000.0),
        ("camden", 3000.0),
        ("islington", 2500.0),
    ]
    assert result.payments == 3


async def test_largest_payments_with_min_amount_and_borough(ctx):
    result = await largest_payments(
        ctx, date(2019, 9, 1), date(2019, 10, 31), borough="islington", min_amount=1000
    )
    assert [r.amount_gbp for r in result.rows] == [2500.0, 1500.0, 1200.0, 1000.0]


async def test_search_payments_matches_purpose_supplier_or_department(ctx):
    by_purpose = await search_payments(ctx, "construction", date(2019, 9, 1), date(2019, 10, 31))
    assert {r.supplier for r in by_purpose.rows} == {"BIG BUILD CONSTRUCTION LTD", "Big Build Construction Ltd"}

    by_department = await search_payments(ctx, "estates", date(2019, 9, 1), date(2019, 10, 31))
    assert by_department.payments == 2

    by_supplier = await search_payments(ctx, "reed", date(2019, 9, 1), date(2019, 10, 31), borough="islington")
    assert by_supplier.total_gbp == 3700.0


async def test_search_payments_limit(ctx):
    result = await search_payments(ctx, "a", date(2019, 9, 1), date(2019, 10, 31), limit=2)
    assert len(result.rows) == 2
    assert result.payments > 2


async def test_compare_boroughs_totals_and_per_resident(ctx):
    result = await compare_boroughs(ctx, ["camden", "islington"], date(2019, 9, 1), date(2019, 10, 31))
    rows = {r.borough: r for r in result.rows}
    assert rows["camden"].total_gbp == 14000.0
    assert rows["camden"].payments == 10
    assert rows["camden"].population == 210000
    assert rows["camden"].gbp_per_resident == pytest.approx(14000.0 / 210000, rel=1e-6)
    assert rows["islington"].total_gbp == 8100.0


async def test_compare_boroughs_with_purpose_filter(ctx):
    result = await compare_boroughs(
        ctx, ["camden", "islington"], date(2019, 9, 1), date(2019, 10, 31), purpose_like="agency"
    )
    rows = {r.borough: r for r in result.rows}
    assert rows["islington"].total_gbp == 3700.0
    assert rows["camden"].total_gbp == 0.0
    assert result.matched.purposes == ["Agency Staff"]


async def test_compare_boroughs_unknown_borough_has_no_population(ctx):
    result = await compare_boroughs(ctx, ["hackney"], date(2019, 9, 1), date(2019, 10, 31))
    assert result.rows[0].population is None
    assert result.rows[0].gbp_per_resident is None


def test_all_tools_lists_seven():
    assert [t.__name__ for t in ALL_TOOLS] == [
        "coverage", "spend_total", "spend_by", "supplier_payments",
        "largest_payments", "search_payments", "compare_boroughs",
    ]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_tools.py -q`
Expected: FAIL with `ImportError: cannot import name 'ALL_TOOLS'`

- [ ] **Step 3: Append the models and tools**

Append to `agent/tools.py`:
```python
PAYMENT_COLUMNS = (
    "borough, payment_date, supplier, directorate, department, purpose, amount_gbp, reference"
)


class Payment(BaseModel):
    borough: str
    payment_date: date
    supplier: str
    directorate: str | None
    department: str | None
    purpose: str | None
    amount_gbp: float
    reference: str | None


class Payments(BaseModel):
    """A filtered set of payments: the total and count over the whole set, and at most ROW_LIMIT rows."""

    total_gbp: float
    payments: int
    rows: list[Payment]


class SupplierPayments(BaseModel):
    supplier_like: str
    boroughs: list[str]
    total_gbp: float
    payments: int
    first_date: date | None
    last_date: date | None
    rows: list[Payment]


class ComparisonRow(BaseModel):
    borough: str
    total_gbp: float
    payments: int
    population: int | None
    gbp_per_resident: float | None


class BoroughComparison(BaseModel):
    period_from: date
    period_to: date
    rows: list[ComparisonRow]
    matched: Matched


def _payment(r: dict[str, Any]) -> Payment:
    return Payment(
        borough=r["borough"],
        payment_date=r["payment_date"],
        supplier=r["supplier"],
        directorate=r["directorate"],
        department=r["department"],
        purpose=r["purpose"],
        amount_gbp=float(r["amount_gbp"]),
        reference=r["reference"],
    )


async def _payment_set(db: Database, where: str, params: dict[str, Any], *, order: str, limit: int) -> Payments:
    totals = await db.fetch_all(
        f"SELECT coalesce(sum(amount_gbp), 0) AS total, count(*) AS n FROM payments WHERE {where}",
        params,
    )
    rows = await db.fetch_all(
        f"SELECT {PAYMENT_COLUMNS} FROM payments WHERE {where} ORDER BY {order} LIMIT {_clamp(limit)}",
        params,
    )
    return Payments(
        total_gbp=float(totals[0]["total"]),
        payments=totals[0]["n"],
        rows=[_payment(r) for r in rows],
    )


async def supplier_payments(
    ctx: RunContext[Deps],
    supplier_like: str,
    period_from: date,
    period_to: date,
    borough: str | None = None,
) -> SupplierPayments:
    """Everything paid to suppliers whose name contains the given text, ignoring case and punctuation, between two dates: total, count, first and last payment date, which boroughs paid them, and the payments. Leave borough empty to search every borough."""
    where, params = _filters(
        period_from=period_from, period_to=period_to, borough=borough, supplier_like=supplier_like
    )
    summary = await ctx.deps.db.fetch_all(
        "SELECT coalesce(sum(amount_gbp), 0) AS total, count(*) AS n,"
        " min(payment_date) AS first_date, max(payment_date) AS last_date,"
        " array_remove(array_agg(DISTINCT borough), NULL) AS boroughs"
        f" FROM payments WHERE {where}",
        params,
    )
    rows = await ctx.deps.db.fetch_all(
        f"SELECT {PAYMENT_COLUMNS} FROM payments WHERE {where}"
        f" ORDER BY payment_date DESC, amount_gbp DESC LIMIT {ROW_LIMIT}",
        params,
    )
    s = summary[0]
    return SupplierPayments(
        supplier_like=supplier_like,
        boroughs=sorted(s["boroughs"] or []),
        total_gbp=float(s["total"]),
        payments=s["n"],
        first_date=s["first_date"],
        last_date=s["last_date"],
        rows=[_payment(r) for r in rows],
    )


async def largest_payments(
    ctx: RunContext[Deps],
    period_from: date,
    period_to: date,
    borough: str | None = None,
    limit: int = 20,
    min_amount: float | None = None,
    department_like: str | None = None,
    purpose_like: str | None = None,
) -> Payments:
    """The biggest single payments between two dates, largest first, in one borough or across all of them. Narrow with a minimum amount or a substring of the department or purpose."""
    where, params = _filters(
        period_from=period_from,
        period_to=period_to,
        borough=borough,
        min_amount=min_amount,
        department_like=department_like,
        purpose_like=purpose_like,
    )
    return await _payment_set(
        ctx.deps.db, where, params, order="amount_gbp DESC, payment_date DESC", limit=limit
    )


async def search_payments(
    ctx: RunContext[Deps],
    text: str,
    period_from: date,
    period_to: date,
    borough: str | None = None,
    min_amount: float | None = None,
    limit: int = 50,
) -> Payments:
    """Payments whose supplier, purpose or department contains the given text, between two dates. Use it for "show me the payments for" questions about a topic such as parks, roads, libraries or consultants."""
    where, params = _filters(
        period_from=period_from, period_to=period_to, borough=borough, min_amount=min_amount, text=text
    )
    return await _payment_set(
        ctx.deps.db, where, params, order="payment_date DESC, amount_gbp DESC", limit=limit
    )


async def compare_boroughs(
    ctx: RunContext[Deps],
    boroughs: list[str],
    period_from: date,
    period_to: date,
    department_like: str | None = None,
    purpose_like: str | None = None,
) -> BoroughComparison:
    """Total spend of several boroughs over the same period side by side, with spend per resident where the population is known. Narrow with a substring of the department or purpose to compare one kind of spend."""
    where, params = _filters(
        period_from=period_from,
        period_to=period_to,
        boroughs=boroughs,
        department_like=department_like,
        purpose_like=purpose_like,
    )
    rows = await ctx.deps.db.fetch_all(
        "SELECT b.slug AS borough, b.population,"
        " coalesce(sum(p.amount_gbp), 0) AS total, count(p.id) AS n"
        " FROM unnest(%(boroughs)s::text[]) AS asked(slug)"
        " LEFT JOIN boroughs b ON b.slug = asked.slug"
        f" LEFT JOIN payments p ON p.borough = asked.slug AND {where}"
        " GROUP BY asked.slug, b.slug, b.population ORDER BY total DESC",
        params,
    )
    matched = await _matched(
        ctx.deps.db, where, params, department=bool(department_like), purpose=bool(purpose_like)
    )
    out: list[ComparisonRow] = []
    for r in rows:
        total = float(r["total"])
        population = r["population"]
        out.append(
            ComparisonRow(
                borough=r["borough"] or "",
                total_gbp=total,
                payments=r["n"],
                population=population,
                gbp_per_resident=(total / population) if population else None,
            )
        )
    return BoroughComparison(period_from=period_from, period_to=period_to, rows=out, matched=matched)


ALL_TOOLS = [
    coverage,
    spend_total,
    spend_by,
    supplier_payments,
    largest_payments,
    search_payments,
    compare_boroughs,
]
```

The `compare_boroughs` query needs `borough` in the row even for an unknown slug. Because `b.slug` is NULL for `hackney`, change `b.slug AS borough` to `asked.slug AS borough` and `GROUP BY asked.slug, b.population`. Do that before running.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_tools.py -q`
Expected: 22 passed

---

### Task 5: The agent, its instructions and the coverage instruction

**Files:**
- Create: `agent/agent.py`
- Test: `agent/tests/test_agent.py`

**Interfaces:**
- Consumes: `Settings`, `GOOGLE_KEY_ENV` from Task 1; `Deps`, `ALL_TOOLS` from Tasks 3 and 4; `Database` from Task 2.
- Produces: `agent.build_model(settings: Settings) -> Model`, `agent.build_agent(model: Model) -> Agent[Deps, str]`, `agent.INSTRUCTIONS: str`.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_agent.py`:
```python
import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from agent import build_agent, build_model
from config import Settings
from db import Database
from tools import Deps


@pytest.fixture
async def deps(database_url):
    db = Database(database_url)
    await db.open()
    yield Deps(db=db)
    await db.close()


def test_build_model_test_string():
    model = build_model(Settings(model="test", google_api_key=None, database_url=None, environment="dev"))
    assert isinstance(model, TestModel)


def test_build_model_google_needs_key():
    with pytest.raises(RuntimeError, match="GOOGLE_AI_STUDIO_KEY"):
        build_model(Settings(model="google:gemini-3.8-flash", google_api_key=None, database_url=None, environment="dev"))


def test_build_model_google_with_key():
    model = build_model(Settings(model="google:gemini-3.8-flash", google_api_key="k", database_url=None, environment="dev"))
    assert model.model_name == "gemini-3.8-flash"


async def test_instructions_carry_coverage(deps):
    agent = build_agent(TestModel(call_tools=[], custom_output_text="ok"))
    result = await agent.run("hi", deps=deps)
    first = result.all_messages()[0]
    assert isinstance(first, ModelRequest)
    assert "camden: 2019-09 to 2019-10, 10 payments" in (first.instructions or "")
    assert "islington: 2019-09 to 2019-10, 8 payments" in (first.instructions or "")


async def test_tool_call_reaches_the_database(deps):
    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        if any(isinstance(p, ToolReturnPart) for p in last.parts):
            return ModelResponse(parts=[TextPart("Camden spent £10,000 in September 2019 across 6 payments.")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "spend_total",
                    {"borough": "camden", "period_from": "2019-09-01", "period_to": "2019-09-30"},
                )
            ]
        )

    agent = build_agent(FunctionModel(model_fn))
    result = await agent.run("How much did Camden spend in September 2019?", deps=deps)
    assert result.output.startswith("Camden spent")
    returns = [
        p for m in result.all_messages() if isinstance(m, ModelRequest)
        for p in m.parts if isinstance(p, ToolReturnPart)
    ]
    assert len(returns) == 1
    assert returns[0].content.total_gbp == 10000.0
    assert returns[0].content.payments == 6


async def test_every_tool_is_registered(deps):
    agent = build_agent(TestModel(call_tools=[], custom_output_text="ok"))
    async with agent:
        names = {name for name in (await agent._get_toolset().get_tools(...))} if False else None
    # The public way: TestModel with call_tools='all' calls every tool once.
    calls = set()

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.update(t.name for t in info.function_tools)
        return ModelResponse(parts=[TextPart("done")])

    await build_agent(FunctionModel(model_fn)).run("hi", deps=deps)
    assert calls == {
        "coverage", "spend_total", "spend_by", "supplier_payments",
        "largest_payments", "search_payments", "compare_boroughs",
    }
```

Remove the three lines starting `async with agent:` through `names = ...` before running; they are a leftover and the `calls` approach below them is the test. The final test body is the `calls` set, the `model_fn`, the run and the assert.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_agent.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent'`

- [ ] **Step 3: Write agent.py**

`agent/agent.py`:
```python
"""The agent: model, instructions and tools.

Instructions come in two parts. The static text says what the agent is and
how to answer. The dynamic part runs once per request and lists which
boroughs and months are loaded, so the model can decline a question about
data it does not have instead of guessing.
"""

from __future__ import annotations

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from config import GOOGLE_KEY_ENV, Settings
from tools import ALL_TOOLS, Deps

GOOGLE_PREFIX = "google:"

INSTRUCTIONS = """\
You are Scrooge, an assistant that answers questions about what London
boroughs spend, from the payments each borough publishes under the
transparency code (every payment over £500, over £250 in some boroughs).

Answer only from the tools. Never estimate a number you did not get from a
tool. Every answer states the borough, the period and how many payments the
figure covers. When a department or purpose filter was used, name the values
it matched, because every borough labels these differently. When the data
does not cover the borough or period asked, say so and answer for the closest
period that is loaded.

Borough names are lower-case slugs such as camden or tower-hamlets. Financial
years run April to March. Amounts are pounds sterling, net of VAT where the
borough says so. Write short markdown: a sentence or two, and a table when
there are more than three numbers. Do not repeat the raw rows; the reader
sees them in the tool result.
"""


def build_model(settings: Settings) -> Model:
    """The model named by AGENT_MODEL.

    `google:<name>` is built by hand so the key can come from
    GOOGLE_AI_STUDIO_KEY rather than the env var the provider reads on its
    own. Every other string, including `test` and `gateway/...`, goes through
    Pydantic AI's own inference and its own env vars.
    """
    if settings.model.startswith(GOOGLE_PREFIX):
        if not settings.google_api_key:
            raise RuntimeError(f"{GOOGLE_KEY_ENV} is not set.")
        return GoogleModel(
            settings.model.removeprefix(GOOGLE_PREFIX),
            provider=GoogleProvider(api_key=settings.google_api_key),
        )
    return infer_model(settings.model)


def build_agent(model: Model) -> Agent[Deps, str]:
    agent: Agent[Deps, str] = Agent(
        model,
        deps_type=Deps,
        instructions=INSTRUCTIONS,
        tools=ALL_TOOLS,
        name="scrooge",
    )

    @agent.instructions
    async def loaded_data(ctx: RunContext[Deps]) -> str:
        rows = await ctx.deps.db.fetch_all(
            "SELECT borough, min(month) AS first, max(month) AS last, sum(payments) AS payments"
            " FROM coverage GROUP BY borough ORDER BY borough"
        )
        if not rows:
            return "No data is loaded yet. Say so; do not answer with numbers."
        lines = [
            f"{r['borough']}: {r['first']:%Y-%m} to {r['last']:%Y-%m}, {r['payments']:,} payments"
            for r in rows
        ]
        return "Data loaded, by borough:\n" + "\n".join(lines)

    return agent
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_agent.py -q`
Expected: 6 passed

If `ModelRequest.instructions` is `None` in `test_instructions_carry_coverage`, print `result.all_messages()[0]` and find where the instructions text landed (it may be a `SystemPromptPart` in `parts`); adjust the assertion to read from there and report what you found.

---

### Task 6: Wire main.py, Logfire, and the README

**Files:**
- Create: `agent/observability.py`
- Modify: `agent/main.py` (rewrite)
- Modify: `agent/README.md` (rewrite)
- Test: `agent/tests/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces: FastAPI `app` in `main.py` with `POST /chat`, `GET /health`; `app.state.db`, `app.state.agent`, `app.state.settings` set during lifespan.

- [ ] **Step 1: Write the failing test**

`agent/tests/test_main.py`:
```python
import json

import httpx
import pytest
from pydantic_ai.models.test import TestModel


@pytest.fixture
async def client(database_url, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    import importlib

    import main

    importlib.reload(main)
    async with main.lifespan(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, main


async def test_health_reports_model_and_database(client):
    c, _ = client
    r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "model": "test", "database": True}


async def test_chat_streams_a_reply(client):
    c, main = client
    with main.app.state.agent.override(model=TestModel(call_tools=[], custom_output_text="Hello from Scrooge")):
        body = {
            "id": "chat1",
            "trigger": "submit-message",
            "messageId": "m1",
            "messages": [{"id": "u1", "role": "user", "parts": [{"type": "text", "text": "hi"}]}],
        }
        r = await c.post("/chat", json=body)
    assert r.status_code == 200
    assert r.headers.get("x-vercel-ai-ui-message-stream") == "v1"
    text = r.text
    assert "Hello from Scrooge" in text
    assert "[DONE]" in text


async def test_chat_without_database_is_a_clear_500(database_url, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import importlib

    import main

    importlib.reload(main)
    async with main.lifespan(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/chat", json={"id": "x", "trigger": "submit-message", "messages": []})
    assert r.status_code == 500
    assert "DATABASE_URL" in r.json()["error"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_main.py -q`
Expected: FAIL with `AttributeError: module 'main' has no attribute 'lifespan'`

- [ ] **Step 3: Write observability.py**

`agent/observability.py`:
```python
"""Logfire setup. One call at startup, before the app serves anything.

With no LOGFIRE_TOKEN in the environment nothing is sent and nothing fails,
so tests and a fresh checkout run without an account. With a token, every
request is one trace: the FastAPI span, the agent run under it, each model
and tool call, and each SQL statement the tools run.
"""

from __future__ import annotations

import logfire
from fastapi import FastAPI

from config import Settings

SERVICE_NAME = "scrooge-agent"


def setup(settings: Settings, app: FastAPI) -> None:
    logfire.configure(
        service_name=SERVICE_NAME,
        environment=settings.environment,
        send_to_logfire="if-token-present",
        console=False,
    )
    # Full prompts, tool arguments and results: the data is public spending
    # records, and readable traces are the point.
    logfire.instrument_pydantic_ai(include_content=True)
    logfire.instrument_fastapi(app)
    logfire.instrument_psycopg()
```

- [ ] **Step 4: Rewrite main.py**

`agent/main.py`:
```python
"""The chat agent, served over HTTP.

`POST /chat` takes AI SDK messages and streams the answer back in the Vercel
data-stream protocol, which the web app's `useChat` reads. The agent's tools
query Postgres; the pool is opened in the lifespan and handed to each run as
deps.

`app` is a module-level FastAPI instance because Vercel's Python runtime
looks for that name in `main.py`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from starlette.requests import Request
from starlette.responses import Response

import observability
from agent import build_agent, build_model
from config import DATABASE_URL_ENV, Settings
from db import Database
from tools import Deps

# The web app runs AI SDK 7. The adapter's v7 wire is identical to v6's today,
# but passing the client's real major keeps both ends on the same value.
SDK_VERSION = 7


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    app.state.settings = settings
    app.state.agent = build_agent(build_model(settings))
    app.state.db = None
    if settings.database_url:
        app.state.db = Database(settings.database_url)
        await app.state.db.open()
    try:
        yield
    finally:
        if app.state.db is not None:
            await app.state.db.close()


app = FastAPI(lifespan=lifespan)
observability.setup(Settings.from_env(), app)


def _error(message: str, status: int = 500) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


@app.post("/chat")
async def chat(request: Request) -> Response:
    db: Database | None = request.app.state.db
    if db is None:
        return _error(
            f"The server is missing {DATABASE_URL_ENV}. Add it to .env.local and restart the agent."
        )
    return await VercelAIAdapter.dispatch_request(
        request,
        agent=request.app.state.agent,
        deps=Deps(db=db),
        sdk_version=SDK_VERSION,
    )


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "model": settings.model,
        "database": request.app.state.db is not None,
    }
```

The missing-key behaviour from the old `main.py` moves to `build_model`, which raises at startup with the variable's name. That is the right time: a server that cannot build its model should not start.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_main.py -q`
Expected: 3 passed

If `test_chat_streams_a_reply` gets a 400 from the adapter about the body shape, look at how the existing `web/src/app/api/chat/route.ts` client posts (the earlier build verified `id`, `messages` with `parts`, `trigger`, `messageId`) and match the field names the adapter validates; print the 400 body and fix the test body, not the app.

- [ ] **Step 6: Run the whole suite, then the manual smoke test**

Run: `uv run pytest -q`
Expected: all passed, one Docker container started and removed.

Then, with no database and no key, confirm the server refuses to start with a clear message:
```bash
env -u GOOGLE_AI_STUDIO_KEY uv run uvicorn main:app --port 8000
```
Expected: the lifespan raises `RuntimeError: GOOGLE_AI_STUDIO_KEY is not set.` and uvicorn exits. Stop it if it does not exit on its own.

Then with the key but no `DATABASE_URL`:
```bash
uv run --env-file ../.env.local uvicorn main:app --port 8000 &
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/chat -H 'content-type: application/json' \
  -d '{"id":"x","trigger":"submit-message","messages":[]}'
kill %1
```
Expected: health shows `"database": false`; chat answers 500 naming `DATABASE_URL`. Do not run against the Modal database; that is a later manual step for the owner.

- [ ] **Step 7: Rewrite the README**

`agent/README.md`:
```markdown
# Agent

The chat agent behind the web app. One Pydantic AI agent with seven tools
that query the `payments` table in Postgres and stream an answer back in the
Vercel data-stream protocol, which `web/`'s `useChat` reads. The model never
writes SQL; each tool is a fixed, parameterised query.

The data contract is [docs/payments-schema.md](../docs/payments-schema.md).
The design decisions are in
[docs/superpowers/specs/2026-09-19-scrooge-agent-design.md](../docs/superpowers/specs/2026-09-19-scrooge-agent-design.md).

## Run it

From this directory:

```bash
uv run --env-file ../.env.local uvicorn main:app --port 8000
```

`--env-file` is uv's own flag. The file needs `GOOGLE_AI_STUDIO_KEY` and
`DATABASE_URL`; see the table below. Without `DATABASE_URL` the server starts
and `/chat` answers 500 naming the variable. Without the model key it does
not start.

`DATABASE_URL` is built from the infra CLI: `cd ../infra && uv run pg url`
gives the superuser URL; replace the user and password with the `agent`
login the loader created. When the Modal container restarts and the address
changes, the agent re-reads it from Modal on the next query, so a restart of
this process is not needed.

## Endpoints

- `POST /chat` runs the agent and streams the reply. The body is what AI
  SDK's `DefaultChatTransport` posts: `id`, `messages`, `trigger`,
  `messageId`.
- `GET /health` returns `{"status": "ok", "model": "...", "database": true}`.

## Tools

| Tool | Answers |
| --- | --- |
| `coverage` | which boroughs and months are loaded |
| `spend_total` | total for one borough and period, with optional department or purpose substring |
| `spend_by` | breakdown by department, purpose, supplier, month or financial year |
| `supplier_payments` | everything paid to a supplier, across boroughs or in one |
| `largest_payments` | biggest single payments |
| `search_payments` | payments matching a word in supplier, purpose or department |
| `compare_boroughs` | several boroughs side by side, per resident when the population is filled |

Every result carries the row count behind it and, when a substring filter
was used, the distinct values it matched.

## Env vars

| Name | Meaning |
| --- | --- |
| `GOOGLE_AI_STUDIO_KEY` | Gemini API key. Required when `AGENT_MODEL` starts with `google:`. |
| `AGENT_MODEL` | Pydantic AI model string. Default `google:gemini-3.8-flash`. `test` gives a fake model for local checks. `gateway/google-cloud:<model>` routes through the Pydantic AI Gateway and then needs `PYDANTIC_AI_GATEWAY_API_KEY`. |
| `DATABASE_URL` | `postgresql://agent:<password>@<host>:<port>/postgres` |
| `LOGFIRE_TOKEN` | Logfire write token for the `hacks-eu-agentic` project. Without it nothing is sent. |
| `AGENT_ENV` | Logfire environment label, default `dev`. |
| `AGENT_URL` (web app) | Where the Next.js rewrite sends `/api/agent/*`. Default `http://127.0.0.1:8000`. |
| `NEXT_PUBLIC_CHAT_BACKEND` (web app) | `ai-sdk` to use the TypeScript route instead. |

## Observability

With `LOGFIRE_TOKEN` set, each request is one trace in Logfire: the HTTP
span, the agent run, every model and tool call with full content, and every
SQL statement. Environment is `AGENT_ENV`.

## Tests

```bash
uv run pytest -q
```

Needs Docker. The session starts one `postgres:17` container, applies
`docs/payments-schema.sql` and `tests/seed.sql`, and removes it at the end.
Set `TEST_DATABASE_URL` to use a database you already have instead; the
schema and seed are applied to it, so make it a disposable one. No test
calls a real model.
```

- [ ] **Step 8: Final check**

Run: `uv run pytest -q` once more, then `docker ps --filter name=scrooge-test` and confirm it prints no containers. Report the full test count.

---

## Self-review

Spec coverage: decisions 1 to 7 and 10 map to Tasks 1 to 6. Decision 8 (no evals) and 9 (no seeding or DDL) are constraints, honoured by omission. The gateway path (decision 5) is `AGENT_MODEL=gateway/google-cloud:...` through `infer_model` in Task 5, no extra code.

Type consistency: `Deps(db=Database)` in Tasks 3, 5, 6. `fetch_all(sql, params)` returns `list[dict]` everywhere. `ALL_TOOLS` order is fixed in Task 4 and asserted in Tasks 4 and 5. `build_agent(model) -> Agent[Deps, str]` in Tasks 5 and 6. Result models use `float` for money throughout.

Known soft spots, each with an instruction in its task: the `RunContext` constructor fields (Task 3), `PoolTimeout` versus `OperationalError` (Task 2), where instructions land on the first `ModelRequest` (Task 5), the adapter's body validation (Task 6).
