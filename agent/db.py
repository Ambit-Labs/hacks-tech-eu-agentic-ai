"""The connection pool, and finding the database again when it moves.

The Postgres server runs in a Modal container and gets a new host and port
every time that container restarts (see infra/README.md). The server
publishes its address into a Modal Dict; on a connection error this module
reads that Dict, keeps the user, password and database from the URL it was
given, swaps in the new host and port, reopens the pool and retries once.
"""

from __future__ import annotations

import asyncio
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
    return urllib.parse.urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )


def resolve_from_modal(url: str) -> str:
    """Re-read host and port from the Dict the infra server publishes into."""
    import modal

    try:
        record = modal.Dict.from_name(ENDPOINT_DICT_NAME).get(ENDPOINT_KEY)
    except Exception as exc:
        # Modal reports a missing or wrong token from deep inside its client,
        # and this is the first place that shows up on a server with no Modal
        # credentials, such as a fresh Vercel function.
        raise RuntimeError(
            "could not read the Postgres endpoint from Modal. Set MODAL_TOKEN_ID "
            "and MODAL_TOKEN_SECRET for the workspace that runs the database."
        ) from exc
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

    def __init__(
        self, url: str, *, resolver: Callable[[str], str] = resolve_from_modal
    ) -> None:
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

    async def fetch_all(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run one statement and return every row as a dict."""
        try:
            return await self._run(sql, params)
        except psycopg.errors.QueryCanceled:
            # The role's statement_timeout, not a moved server: re-resolving
            # would cost a Modal call and run the slow query a second time.
            raise
        except psycopg.OperationalError:
            # The resolver is a blocking Modal round trip. On the event loop it
            # would stall every other request in flight, not only this one.
            self._url = await asyncio.to_thread(self._resolver, self._url)
            await self.close()
            await self.open()
            return await self._run(sql, params)

    async def _run(
        self, sql: str, params: Mapping[str, Any] | None
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            raise RuntimeError("Database.open() was not called")
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params)
            return await cursor.fetchall()
