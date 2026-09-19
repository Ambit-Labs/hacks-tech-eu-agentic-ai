import sys
import types

import psycopg
import pytest

from db import Database, resolve_from_modal, with_endpoint


def test_resolve_from_modal_names_the_token_vars(monkeypatch):
    # Modal raises from inside its own client when the token is missing, which
    # is what a Vercel function without MODAL_TOKEN_ID looks like.
    stub = types.ModuleType("modal")

    class Dict:
        @staticmethod
        def from_name(name):
            raise RuntimeError("token missing")

    stub.Dict = Dict
    monkeypatch.setitem(sys.modules, "modal", stub)

    with pytest.raises(RuntimeError) as caught:
        resolve_from_modal("postgresql://agent:p@old-host:1111/postgres")
    assert "MODAL_TOKEN_ID" in str(caught.value)
    assert "MODAL_TOKEN_SECRET" in str(caught.value)


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


async def test_statement_timeout_does_not_reresolve(database_url):
    # SET LOCAL and the slow query go as one multi-statement string: the
    # timeout is armed when each statement starts, so set_config inside the
    # SELECT itself would come too late to cancel it.
    calls: list[str] = []

    def resolver(url: str) -> str:
        calls.append(url)
        return url

    db = Database(database_url, resolver=resolver)
    await db.open()
    try:
        with pytest.raises(psycopg.errors.QueryCanceled):
            await db.fetch_all("SET LOCAL statement_timeout = '100ms'; SELECT pg_sleep(1)")
    finally:
        await db.close()
    assert calls == []


async def test_gives_up_after_one_reresolve(database_url):
    broken = with_endpoint(database_url, "127.0.0.1", 1)
    db = Database(broken, resolver=lambda url: url)
    await db.open()
    try:
        with pytest.raises(psycopg.OperationalError):
            await db.fetch_all("SELECT 1")
    finally:
        await db.close()
