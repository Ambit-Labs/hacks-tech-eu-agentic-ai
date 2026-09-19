"""The pure helpers, exercised without Modal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scrooge_infra.endpoint import (
    PG_DATABASE,
    PG_USER,
    Endpoint,
    build_url,
    endpoint_payload,
    format_uptime,
    is_stale,
    parse_endpoint,
    uptime_seconds,
)

T0 = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


def make_endpoint(**overrides) -> Endpoint:
    fields = {
        "host": "r1.modal.host",
        "port": 41234,
        "started_at": T0,
        "container_id": "ta-abc123",
        "heartbeat_at": T0,
    }
    return Endpoint(**{**fields, **overrides})


# -- payload round trip ----------------------------------------------------- #


def test_payload_round_trips_through_parse():
    payload = endpoint_payload("r1.modal.host", 41234, T0, "ta-abc123")
    endpoint = parse_endpoint(payload)
    assert endpoint == make_endpoint()


def test_payload_is_plain_json_types():
    payload = endpoint_payload("r1.modal.host", 41234, T0, "ta-abc123")
    assert set(payload) == {
        "host",
        "port",
        "started_at",
        "container_id",
        "heartbeat_at",
    }
    assert all(isinstance(v, str | int) for v in payload.values())


def test_payload_defaults_heartbeat_to_start():
    payload = endpoint_payload("h", 1, T0, "c")
    assert payload["heartbeat_at"] == payload["started_at"]


def test_payload_accepts_a_naive_datetime_as_utc():
    payload = endpoint_payload("h", 1, T0.replace(tzinfo=None), "c")
    assert parse_endpoint(payload).started_at == T0


def test_payload_accepts_a_posix_timestamp():
    payload = endpoint_payload("h", 1, T0.timestamp(), "c")
    assert parse_endpoint(payload).started_at == T0


def test_parse_accepts_a_trailing_z():
    endpoint = parse_endpoint(
        {"host": "h", "port": 1, "started_at": "2026-09-19T12:00:00Z"}
    )
    assert endpoint.started_at == T0


def test_parse_coerces_a_string_port():
    assert parse_endpoint({"host": "h", "port": "5432", "started_at": T0}).port == 5432


def test_parse_fills_in_a_missing_container_id():
    assert parse_endpoint({"host": "h", "port": 1, "started_at": T0}).container_id == (
        "unknown"
    )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not a dict",
        {},
        {"host": "h", "port": 1},
        {"host": "h", "started_at": T0},
        {"port": 1, "started_at": T0},
        {"host": "h", "port": "not a port", "started_at": T0},
        {"host": "h", "port": 1, "started_at": "never"},
        {"host": "", "port": 1, "started_at": T0},
    ],
    ids=[
        "none",
        "string",
        "empty",
        "no-start",
        "no-port",
        "no-host",
        "bad-port",
        "bad-date",
        "blank-host",
    ],
)
def test_parse_returns_none_for_anything_unusable(payload):
    # The Dict outlives every container, so a half-written or old-format
    # record is a normal thing for `pg status` to meet.
    assert parse_endpoint(payload) is None


def test_address_joins_host_and_port():
    assert make_endpoint().address == "r1.modal.host:41234"


# -- URL building ----------------------------------------------------------- #


def test_build_url_has_the_libpq_shape():
    assert build_url("r1.modal.host", 41234, "hunter2") == (
        f"postgresql://{PG_USER}:hunter2@r1.modal.host:41234/{PG_DATABASE}"
    )


def test_build_url_percent_encodes_the_password():
    # An unencoded @ would reparse as a different host and fail as a DNS
    # error three layers away from the cause.
    url = build_url("h", 5432, "p@ss/w:rd?")
    assert "p%40ss%2Fw%3Ard%3F" in url
    assert url.count("@") == 1


def test_build_url_takes_a_named_database():
    assert build_url("h", 1, "p", database="spend").endswith("/spend")


def test_build_url_encodes_the_user_too():
    assert "spend%20user" in build_url("h", 1, "p", user="spend user")


# -- uptime ----------------------------------------------------------------- #


def test_uptime_counts_from_started_at():
    endpoint = make_endpoint()
    assert uptime_seconds(endpoint, T0 + timedelta(hours=2)) == 7200


def test_uptime_never_goes_negative_on_a_skewed_clock():
    assert uptime_seconds(make_endpoint(), T0 - timedelta(hours=1)) == 0.0


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (41, "41s"),
        (63, "1m 03s"),
        (3600, "1h 0m"),
        (3600 * 4 + 60 * 12, "4h 12m"),
        (86400 * 3 + 3600 * 4 + 60 * 12, "3d 4h 12m"),
        (-5, "0s"),
    ],
)
def test_format_uptime(seconds, expected):
    assert format_uptime(seconds) == expected


# -- staleness -------------------------------------------------------------- #


def test_a_fresh_heartbeat_is_not_stale():
    endpoint = make_endpoint(heartbeat_at=T0)
    assert not is_stale(endpoint, T0 + timedelta(minutes=5))


def test_an_old_heartbeat_is_stale():
    # A container killed at the 24 hour timeout cannot clear its own entry,
    # so heartbeat age is the only signal without opening a connection.
    endpoint = make_endpoint(heartbeat_at=T0)
    assert is_stale(endpoint, T0 + timedelta(hours=2))


def test_staleness_uses_started_at_when_there_is_no_heartbeat():
    endpoint = make_endpoint(heartbeat_at=None)
    assert is_stale(endpoint, T0 + timedelta(hours=2))
    assert not is_stale(endpoint, T0 + timedelta(minutes=1))


def test_staleness_window_is_overridable():
    endpoint = make_endpoint(heartbeat_at=T0)
    now = T0 + timedelta(minutes=2)
    assert is_stale(endpoint, now, max_age=timedelta(minutes=1))
    assert not is_stale(endpoint, now, max_age=timedelta(minutes=10))
