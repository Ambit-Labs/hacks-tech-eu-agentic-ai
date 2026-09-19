"""Names, the endpoint record, and the pure functions that read it.

Nothing here imports ``modal``. The server writes a dict into a
``modal.Dict`` and the CLI reads it back; both ends go through
:func:`endpoint_payload` and :func:`parse_endpoint` so the shape of that
record is defined once and can be tested without a Modal account.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: Modal App name. Also the first argument to ``modal.Function.from_name``.
APP_NAME = "scrooge-postgres"

#: Volume holding the pg_dump archives. Not the Postgres data directory, see
#: the persistence section of docs/runbook.md.
VOLUME_NAME = "scrooge-postgres-data"

#: Secret carrying POSTGRES_PASSWORD.
SECRET_NAME = "scrooge-postgres"

#: Key the secret must define.
PASSWORD_KEY = "POSTGRES_PASSWORD"

#: Dict the running server publishes its address into.
ENDPOINT_DICT_NAME = "scrooge-postgres-endpoint"

#: The single key inside that Dict.
ENDPOINT_KEY = "current"

#: Superuser and database the server creates.
PG_USER = "postgres"
PG_DATABASE = "postgres"

#: Printed in place of a password by ``pg url --no-password``.
PASSWORD_PLACEHOLDER = "PASSWORD"

#: An endpoint whose heartbeat is older than this is treated as dead. The
#: server refreshes on every dump, so this has to clear the dump interval
#: with room for a slow dump of a large database.
STALE_AFTER = timedelta(minutes=25)


@dataclass(frozen=True)
class Endpoint:
    """Where the Postgres server is right now, as last published.

    ``host`` and ``port`` change every time the container restarts, which is
    why nothing downstream may hardcode them.
    """

    host: str
    port: int
    started_at: datetime
    container_id: str
    heartbeat_at: datetime | None = None

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


def _to_aware(value: str | float | datetime) -> datetime:
    """Accept an ISO string, a POSIX timestamp or a datetime, return UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def endpoint_payload(
    host: str,
    port: int,
    started_at: datetime,
    container_id: str,
    heartbeat_at: datetime | None = None,
) -> dict:
    """The record the server puts in the Dict.

    Plain JSON types only. The Dict will happily cloudpickle a dataclass, but
    then every reader needs this package importable at the same version.
    """
    return {
        "host": host,
        "port": int(port),
        "started_at": _to_aware(started_at).isoformat(),
        "container_id": container_id,
        "heartbeat_at": _to_aware(heartbeat_at or started_at).isoformat(),
    }


def parse_endpoint(payload: object) -> Endpoint | None:
    """Turn a Dict value back into an :class:`Endpoint`.

    Returns ``None`` for a missing or malformed record rather than raising:
    the Dict outlives any one container, so a half-written or stale-format
    entry is a normal thing for ``pg status`` to meet, not an error.
    """
    if not isinstance(payload, dict):
        return None
    host = payload.get("host")
    port = payload.get("port")
    started_at = payload.get("started_at")
    if not host or port is None or started_at is None:
        return None
    try:
        parsed_port = int(port)
        started = _to_aware(started_at)
        beat_raw = payload.get("heartbeat_at")
        beat = _to_aware(beat_raw) if beat_raw else started
    except (TypeError, ValueError):
        return None
    return Endpoint(
        host=str(host),
        port=parsed_port,
        started_at=started,
        container_id=str(payload.get("container_id") or "unknown"),
        heartbeat_at=beat,
    )


def build_url(
    host: str,
    port: int,
    password: str,
    *,
    user: str = PG_USER,
    database: str = PG_DATABASE,
) -> str:
    """A libpq URL for ``host:port``.

    The password is percent-encoded. A generated password containing ``@`` or
    ``/`` otherwise produces a URL that parses as a different host, and the
    failure surfaces three layers away as a DNS error.
    """
    quoted_user = urllib.parse.quote(user, safe="")
    quoted_password = urllib.parse.quote(password, safe="")
    return f"postgresql://{quoted_user}:{quoted_password}@{host}:{port}/{database}"


def uptime_seconds(endpoint: Endpoint, now: datetime | None = None) -> float:
    """Seconds since the server started. Never negative."""
    current = now.astimezone(UTC) if now else datetime.now(UTC)
    return max(0.0, (current - endpoint.started_at).total_seconds())


def format_uptime(seconds: float) -> str:
    """``3d 4h 12m`` / ``4h 12m`` / ``12m 03s`` / ``41s``."""
    total = int(max(0.0, seconds))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def is_stale(
    endpoint: Endpoint,
    now: datetime | None = None,
    max_age: timedelta = STALE_AFTER,
) -> bool:
    """True when the heartbeat stopped, so the container is presumed gone.

    A container killed by the 24 hour timeout has no chance to clear its own
    entry, so the Dict keeps pointing at an address that answers nothing. Age
    of the heartbeat is the only signal available without a connection.
    """
    current = now.astimezone(UTC) if now else datetime.now(UTC)
    beat = endpoint.heartbeat_at or endpoint.started_at
    return (current - beat) > max_age
