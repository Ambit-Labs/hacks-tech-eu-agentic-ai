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
