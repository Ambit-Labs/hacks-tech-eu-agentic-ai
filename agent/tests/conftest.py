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
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container,
            "-e",
            f"POSTGRES_PASSWORD={PASSWORD}",
            "-p",
            "127.0.0.1::5432",
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
