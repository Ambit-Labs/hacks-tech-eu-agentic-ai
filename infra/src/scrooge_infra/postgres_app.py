"""Postgres 17 as a Modal Function, reachable over a raw TCP tunnel.

Modal has no managed database, so the server is an ordinary subprocess in an
ordinary container and :func:`modal.forward` puts port 5432 on the public
internet. Two consequences run through everything below.

The address is not stable. ``modal.forward(5432, unencrypted=True)`` hands
back a random host and port, and a new one on every container start, so the
running server publishes where it landed into a ``modal.Dict`` and every
client reads the address from there instead of from a config file.

The data directory is not on the Volume. Modal Volumes are documented as
optimised for write-once, read-many workloads, which is the opposite of what
a Postgres heap does. PGDATA therefore stays on the container's local disk
and the Volume holds ``pg_dumpall`` archives: restore the newest at boot,
dump on a timer and again on the way out. The window of loss is one dump
interval, ten minutes by default. See docs/runbook.md for the reasoning and
the doc links.
"""

from __future__ import annotations

import gzip
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import modal

from .endpoint import (
    APP_NAME,
    ENDPOINT_DICT_NAME,
    ENDPOINT_KEY,
    PASSWORD_KEY,
    PG_DATABASE,
    PG_USER,
    SECRET_NAME,
    VOLUME_NAME,
    endpoint_payload,
    is_stale,
    parse_endpoint,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Postgres data directory, on the container's local disk. Lost on restart,
#: which is what the dumps are for.
PGDATA = Path("/pgdata")

#: Where the Volume is mounted. Only pg_dumpall output lives here.
DUMP_DIR = Path("/dumps")

#: Port inside the container. The public port is whatever the tunnel picks.
PG_PORT = 5432

#: Modal's ceiling for a Function timeout is 24 hours. A server started now
#: is killed 24 hours from now, and the supervisor starts a fresh one.
MAX_TIMEOUT = 24 * 60 * 60

#: Modal may take a preemptible container away at any moment to reclaim
#: capacity, and that is its default. For this server a preemption is a ten
#: minute outage, because the replacement restores the whole archive before it
#: opens a tunnel: one at 17:06 UTC on 2026-09-19 failed production requests
#: until 17:16. Opting out costs three times the list price for CPU and
#: memory, and leaves `pg stop` and the 24 hour ceiling as the only stops.
#: CPU only: Modal rejects the flag on a GPU Function.
NONPREEMPTIBLE = True

#: Seconds between dumps, overridable per run and by SCROOGE_PG_DUMP_INTERVAL.
DEFAULT_DUMP_INTERVAL = 600

#: How often the main loop wakes to check for a stop request or a dead
#: postmaster. Short, so `pg stop` feels immediate.
POLL_SECONDS = 5

#: The poll sleep is taken in slices this long. A SIGTERM arriving mid-sleep
#: would otherwise wait out the rest of it, and Modal's grace period before
#: it takes the container away is not generous.
SLEEP_SLICE = 1.0

#: Seconds between heartbeat refreshes into the Dict. Deliberately not tied
#: to the dump interval: a `--dump-interval 1800` would otherwise leave the
#: heartbeat looking stale to `pg status` between two healthy dumps.
HEARTBEAT_SECONDS = 60

#: Dump archives kept on the Volume, newest first.
KEEP_DUMPS = 8

#: Key in the Dict holding the desired state and any pending one-off
#: request, so the supervisor knows the difference between "crashed" and
#: "deliberately stopped".
CONTROL_KEY = "control"

#: Key the server writes the outcome of a one-off request into. `pg dump`
#: and `pg restore` poll it for their own request id.
RESULT_KEY = "last_request"

DUMP_PREFIX = "scrooge-postgres-"
DUMP_SUFFIX = ".sql.gz"

# --------------------------------------------------------------------------- #
# Modal objects
# --------------------------------------------------------------------------- #

# The official image already carries initdb, pg_dumpall, psql and pg_ctl at
# matching versions, which a debian_slim plus apt would have to pin by hand.
# It ships no Python, so add_python injects one for the Modal runtime, and
# the entrypoint is cleared because docker-entrypoint.sh wants to own process
# startup and this Function does that itself.
image = (
    modal.Image.from_registry("postgres:17", add_python="3.12")
    .entrypoint([])
    .pip_install("modal>=1.5.5,<2")
    .add_local_python_source("scrooge_infra")
)

app = modal.App(APP_NAME, image=image)

volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
endpoint_dict = modal.Dict.from_name(ENDPOINT_DICT_NAME, create_if_missing=True)
secret = modal.Secret.from_name(SECRET_NAME, required_keys=[PASSWORD_KEY])


def log(message: str) -> None:
    """One timestamped line to stdout, flushed, for `modal app logs`."""
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


# --------------------------------------------------------------------------- #
# Running postgres binaries as the postgres user
# --------------------------------------------------------------------------- #


def _pg_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PGDATA"] = str(PGDATA)
    env["PGPORT"] = str(PG_PORT)
    env.setdefault("LANG", "C.UTF-8")
    return env


def _run_as_postgres(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a postgres binary as the postgres user.

    The postmaster refuses to start as root, and Modal containers are root,
    so every binary that touches PGDATA goes through here. The official
    image already defines the postgres user, uid 999.
    """
    return subprocess.run(
        args,
        user="postgres",
        group="postgres",
        env=_pg_env(),
        check=kwargs.pop("check", True),
        **kwargs,
    )


def _popen_as_postgres(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(args, user="postgres", group="postgres", env=_pg_env())


# --------------------------------------------------------------------------- #
# Cluster setup
# --------------------------------------------------------------------------- #


def _write_conf() -> None:
    """Listen on every interface, and require scram from every client.

    The tunnel is a public TCP address. Anyone who finds it reaches the
    postmaster directly, so trust auth would be an open database and
    ``listen_addresses`` has to be wide enough for the tunnel to reach it.
    """
    conf = PGDATA / "postgresql.conf"
    conf.write_text(
        conf.read_text()
        + "\n# scrooge-infra overrides\n"
        + f"listen_addresses = '*'\nport = {PG_PORT}\n"
        + "password_encryption = 'scram-sha-256'\n"
        + "max_connections = 100\n"
        + "shared_buffers = '1GB'\n"
        + "work_mem = '32MB'\n"
        + "maintenance_work_mem = '256MB'\n"
    )
    (PGDATA / "pg_hba.conf").write_text(
        "# TYPE  DATABASE  USER  ADDRESS     METHOD\n"
        "local   all       all               trust\n"
        "host    all       all   127.0.0.1/32 trust\n"
        "host    all       all   ::1/128      trust\n"
        "host    all       all   0.0.0.0/0    scram-sha-256\n"
        "host    all       all   ::/0         scram-sha-256\n"
    )
    shutil.chown(conf, "postgres", "postgres")
    shutil.chown(PGDATA / "pg_hba.conf", "postgres", "postgres")


def _initdb(password: str) -> None:
    log(f"initdb into {PGDATA}")
    pwfile = Path("/tmp/pgpw")
    pwfile.write_text(password)
    os.chmod(pwfile, 0o600)
    shutil.chown(pwfile, "postgres", "postgres")
    try:
        _run_as_postgres(
            [
                "initdb",
                "--pgdata",
                str(PGDATA),
                f"--username={PG_USER}",
                f"--pwfile={pwfile}",
                "--auth-host=scram-sha-256",
                "--auth-local=trust",
                "--encoding=UTF8",
                "--locale=C.UTF-8",
            ]
        )
    finally:
        pwfile.unlink(missing_ok=True)


def _prepare_pgdata(password: str) -> bool:
    """Make sure PGDATA holds a cluster. Returns True when it is brand new."""
    PGDATA.mkdir(parents=True, exist_ok=True)
    shutil.chown(PGDATA, "postgres", "postgres")
    os.chmod(PGDATA, 0o700)
    fresh = not (PGDATA / "PG_VERSION").exists()
    if fresh:
        _initdb(password)
    _write_conf()
    return fresh


def _wait_until_ready(proc: subprocess.Popen, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"postgres exited during startup, rc={proc.returncode}")
        ready = subprocess.run(
            ["pg_isready", "-h", "127.0.0.1", "-p", str(PG_PORT), "-U", PG_USER],
            capture_output=True,
        )
        if ready.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"postgres was not accepting connections after {timeout:.0f}s")


def _psql(sql: str) -> None:
    _run_as_postgres(
        [
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            "127.0.0.1",
            "-U",
            PG_USER,
            "-d",
            PG_DATABASE,
            "-c",
            sql,
        ],
        capture_output=True,
    )


def _set_password(password: str) -> None:
    """Re-apply the Secret's password to the running cluster.

    A restored dump carries whatever password the cluster had when it was
    dumped. Applying the Secret on every boot means rotating the Secret and
    restarting is enough to change it.
    """
    escaped = password.replace("'", "''")
    _psql(f"ALTER ROLE {PG_USER} WITH PASSWORD '{escaped}'")


# --------------------------------------------------------------------------- #
# Dump and restore
# --------------------------------------------------------------------------- #


def list_dumps() -> list[Path]:
    """Dump archives on the Volume, newest first.

    Names carry a UTC timestamp, so lexicographic order is chronological
    order and no metadata file has to be kept in step.
    """
    if not DUMP_DIR.exists():
        return []
    found = [
        p
        for p in DUMP_DIR.iterdir()
        if p.name.startswith(DUMP_PREFIX) and p.name.endswith(DUMP_SUFFIX)
    ]
    return sorted(found, key=lambda p: p.name, reverse=True)


def dump_to_volume(keep: int = KEEP_DUMPS) -> Path | None:
    """pg_dumpall the cluster onto the Volume, then prune old archives.

    The dump is written to local disk first and only then copied into the
    mount. A crash halfway through a direct write would leave a truncated
    file that the automatic commit on container shutdown would publish as if
    it were good, and boot would restore from it.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    staging = Path(f"/tmp/{DUMP_PREFIX}{stamp}{DUMP_SUFFIX}")
    started = time.monotonic()
    proc = subprocess.Popen(
        [
            "pg_dumpall",
            "-h",
            "127.0.0.1",
            "-p",
            str(PG_PORT),
            "-U",
            PG_USER,
            "--clean",
            "--if-exists",
        ],
        stdout=subprocess.PIPE,
        user="postgres",
        group="postgres",
        env=_pg_env(),
    )
    try:
        with gzip.open(staging, "wb") as gz:
            shutil.copyfileobj(proc.stdout, gz)
    finally:
        proc.stdout.close()
    if proc.wait() != 0:
        log(f"dump failed, pg_dumpall rc={proc.returncode}")
        staging.unlink(missing_ok=True)
        return None

    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    target = DUMP_DIR / staging.name
    shutil.copyfile(staging, target)
    staging.unlink(missing_ok=True)

    for old in list_dumps()[keep:]:
        old.unlink(missing_ok=True)
    volume.commit()
    size_mb = target.stat().st_size / 1024 / 1024
    log(f"dumped {target.name} ({size_mb:.1f} MB) in {time.monotonic() - started:.1f}s")
    return target


def restore_archive(name: str | None = None) -> Path | None:
    """Load an archive into the running cluster, newest one by default.

    ON_ERROR_STOP stays off. pg_dumpall --clean emits DROP statements for
    objects a new cluster does not have yet, and those errors are expected
    on the boot path.
    """
    volume.reload()
    dumps = list_dumps()
    if not dumps:
        log("no dump on the volume, starting with an empty cluster")
        return None
    if name:
        match = [p for p in dumps if p.name == name]
        if not match:
            raise FileNotFoundError(f"no archive named {name} on the volume")
        newest = match[0]
    else:
        newest = dumps[0]
    started = time.monotonic()
    log(f"restoring {newest.name}")
    with gzip.open(newest, "rb") as gz:
        proc = subprocess.Popen(
            [
                "psql",
                "-h",
                "127.0.0.1",
                "-p",
                str(PG_PORT),
                "-U",
                PG_USER,
                # template1, not PG_DATABASE: pg_dumpall --clean opens with
                # DROP DATABASE, and a session cannot drop the database it is
                # connected to. Restoring from the side lets that succeed.
                "-d",
                "template1",
                "-q",
            ],
            stdin=subprocess.PIPE,
            user="postgres",
            group="postgres",
            env=_pg_env(),
        )
        shutil.copyfileobj(gz, proc.stdin)
        proc.stdin.close()
    rc = proc.wait()
    log(f"restore finished rc={rc} in {time.monotonic() - started:.1f}s")
    return newest


# --------------------------------------------------------------------------- #
# The server
# --------------------------------------------------------------------------- #


def _take_request() -> dict | None:
    """The pending one-off request, if this container has not run it yet.

    The request carries an id and the server records that id in RESULT_KEY
    when it is done, so a request is executed exactly once even though both
    keys are polled rather than queued.
    """
    control = endpoint_dict.get(CONTROL_KEY)
    if not isinstance(control, dict):
        return None
    request = control.get("request")
    if not isinstance(request, dict) or not request.get("id"):
        return None
    last = endpoint_dict.get(RESULT_KEY)
    if isinstance(last, dict) and last.get("id") == request["id"]:
        return None
    return request


def _finish_request(request: dict, status: str, detail: str) -> None:
    endpoint_dict[RESULT_KEY] = {
        "id": request["id"],
        "kind": request.get("kind"),
        "status": status,
        "detail": detail,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    log(f"request {request.get('kind')} {status}: {detail}")


def _handle_request(request: dict) -> None:
    """Run a `pg dump` or `pg restore` asked for from a laptop.

    Both have to happen in this container, because it is the only one with
    the running postmaster, so they arrive through the Dict rather than as
    their own Function call.
    """
    kind = request.get("kind")
    try:
        if kind == "dump":
            target = dump_to_volume()
            if target is None:
                _finish_request(request, "failed", "pg_dumpall returned non-zero")
            else:
                _finish_request(request, "ok", target.name)
        elif kind == "restore":
            restored = restore_archive(request.get("archive"))
            _set_password(os.environ[PASSWORD_KEY])
            _finish_request(
                request, "ok", restored.name if restored else "no archive on volume"
            )
        else:
            _finish_request(request, "failed", f"unknown request kind {kind!r}")
    except Exception as exc:
        _finish_request(request, "failed", f"{type(exc).__name__}: {exc}")


def _publish(host: str, port: int, started_at: datetime) -> None:
    endpoint_dict[ENDPOINT_KEY] = endpoint_payload(
        host=host,
        port=port,
        started_at=started_at,
        container_id=os.environ.get("MODAL_TASK_ID", "unknown"),
        heartbeat_at=datetime.now(UTC),
    )


def _stop_requested() -> bool:
    control = endpoint_dict.get(CONTROL_KEY)
    return isinstance(control, dict) and control.get("desired") == "stopped"


@app.function(
    volumes={str(DUMP_DIR): volume},
    secrets=[secret],
    timeout=MAX_TIMEOUT,
    nonpreemptible=NONPREEMPTIBLE,
    max_containers=1,
    cpu=2.0,
    memory=4096,
)
def server(dump_interval: int = DEFAULT_DUMP_INTERVAL, restore: bool = True) -> str:
    """Run Postgres until stopped, the timeout hits, or the postmaster dies.

    Returns a one-line reason so `modal app logs` and the Function call
    result both say why the server went away.
    """
    password = os.environ[PASSWORD_KEY]
    interval = max(60, int(dump_interval))
    started_at = datetime.now(UTC)

    stopping = {"reason": None}

    def on_term(signum, _frame):
        # Modal sends SIGTERM before it takes the container away, on a
        # timeout, a cancel, or a redeploy. Record it and let the loop run
        # its shutdown path, which dumps before it stops the postmaster.
        stopping["reason"] = f"signal {signal.Signals(signum).name}"

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    fresh = _prepare_pgdata(password)
    log(f"starting postgres, PGDATA {'initialised' if fresh else 'reused'}")
    proc = _popen_as_postgres(["postgres", "-D", str(PGDATA)])
    _wait_until_ready(proc)
    log("postgres is accepting connections on 127.0.0.1")

    if fresh and restore:
        restore_archive()
    # After the restore, never before it. A pg_dumpall archive carries the
    # role password the cluster had when it was dumped, so restoring an old
    # archive would otherwise quietly revert a rotated Secret.
    _set_password(password)

    with modal.forward(PG_PORT, unencrypted=True) as tunnel:
        host, port = tunnel.tcp_socket
        _publish(host, port, started_at)
        log(f"tunnel open at {host}:{port}, dumping every {interval}s")

        last_dump = last_beat = time.monotonic()
        while stopping["reason"] is None:
            waited = 0.0
            while waited < POLL_SECONDS and stopping["reason"] is None:
                time.sleep(SLEEP_SLICE)
                waited += SLEEP_SLICE
            if stopping["reason"] is not None:
                break
            if proc.poll() is not None:
                stopping["reason"] = f"postmaster exited rc={proc.returncode}"
                break
            if _stop_requested():
                stopping["reason"] = "stop requested"
                break
            request = _take_request()
            if request is not None:
                _handle_request(request)
                last_dump = last_beat = time.monotonic()
                _publish(host, port, started_at)
                continue
            if time.monotonic() - last_dump >= interval:
                last_dump = time.monotonic()
                dump_to_volume()
            if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                last_beat = time.monotonic()
                _publish(host, port, started_at)

    reason = stopping["reason"] or "loop exited"
    log(f"shutting down: {reason}")
    if proc.poll() is None:
        dump_to_volume()
        _run_as_postgres(
            ["pg_ctl", "stop", "-D", str(PGDATA), "-m", "fast", "-w", "-t", "60"],
            check=False,
        )
        proc.wait(timeout=90)
    endpoint_dict.pop(ENDPOINT_KEY, None)
    return reason


@app.function(volumes={str(DUMP_DIR): volume}, timeout=300)
def archives() -> list[dict]:
    """Name, size and mtime of every dump on the Volume, newest first.

    Runs in its own container with the Volume mounted, so it answers whether
    or not a server is up, which is exactly when someone asks.
    """
    volume.reload()
    return [
        {
            "name": p.name,
            "bytes": p.stat().st_size,
            "modified_at": datetime.fromtimestamp(
                p.stat().st_mtime, tz=UTC
            ).isoformat(),
        }
        for p in list_dumps()
    ]


@app.function(timeout=300, schedule=modal.Period(minutes=5))
def supervisor() -> str:
    """Start the server again when it should be running and is not.

    A Function cannot outlive 24 hours, so every server dies eventually.
    This runs on a schedule, compares the desired state written by `pg start`
    and `pg stop` against the heartbeat in the Dict, and spawns a replacement
    when they disagree. It never starts a server nobody asked for.
    """
    control = endpoint_dict.get(CONTROL_KEY)
    desired = control.get("desired") if isinstance(control, dict) else None
    if desired != "running":
        return f"desired={desired!r}, nothing to do"

    endpoint = parse_endpoint(endpoint_dict.get(ENDPOINT_KEY))
    if endpoint is not None and not is_stale(endpoint):
        return f"alive at {endpoint.address}"

    interval = int((control or {}).get("dump_interval") or DEFAULT_DUMP_INTERVAL)
    call = server.spawn(dump_interval=interval)
    return f"relaunched server, call {call.object_id}"


@app.local_entrypoint()
def main() -> None:
    """Print where the server is. `modal run -m scrooge_infra.postgres_app`.

    The same answer `pg status` gives, without needing this project
    installed as a console script.
    """
    endpoint = parse_endpoint(endpoint_dict.get(ENDPOINT_KEY))
    if endpoint is None:
        print("no endpoint published: the server is not running")
        raise SystemExit(1)
    stale = " (stale heartbeat)" if is_stale(endpoint) else ""
    print(f"host        {endpoint.host}")
    print(f"port        {endpoint.port}")
    print(f"started_at  {endpoint.started_at.isoformat()}{stale}")
    print(f"container   {endpoint.container_id}")
    print(
        f"url         postgresql://{PG_USER}:$SCROOGE_PG_PASSWORD@"
        f"{endpoint.address}/{PG_DATABASE}",
        file=sys.stdout,
    )
