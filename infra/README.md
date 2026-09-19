# scrooge-infra

Postgres 17 running on Modal, for the parsed spending rows that `indexer/`
downloads and that `agent/` and `web/` query. Modal sells no managed
database, so this is the real server process in a Modal container with port
5432 pushed onto the public internet through a Modal TCP tunnel.

The address changes every time the container starts. The running server
publishes its `host:port` into a `modal.Dict`, and `pg url` reads it back, so
nothing downstream may hold a hostname in a config file.

## Install

```sh
cd infra
uv sync
```

Python 3.12 or newer. Everything else comes from `uv.lock`. You also need a
Modal account and a token on this machine, and a Modal secret holding the
Postgres password. Both are in [docs/runbook.md](docs/runbook.md#cold-start).

## The four commands

```sh
uv run pg deploy                 # once, and after any change to postgres_app.py
uv run pg start                  # boot a server, wait for its address
uv run pg status                 # where it is, how long it has been up, SELECT 1
uv run pg url                    # postgresql://... for psycopg, alembic, psql
```

`pg stop` dumps and shuts down. `pg psql` opens a shell against the current
address. `pg dump` and `pg restore` drive the archives by hand.

Point anything at it with a substitution, never a literal:

```sh
export DATABASE_URL="$(uv run pg url)"
```

## Persistence

`PGDATA` lives on the container's local disk, not on the Volume. Modal
documents Volumes as optimised for write-once, read-many workloads, which is
not what a Postgres heap does to a file. The Volume `scrooge-postgres-data`
instead holds gzipped `pg_dumpall` archives: the server restores the newest
one at boot, dumps every 10 minutes, and dumps once more on SIGTERM before
`pg_ctl stop -m fast`.

So a crash costs at most one dump interval of writes. A clean stop, a
redeploy or the 24 hour timeout costs nothing, because each of those arrives
as a SIGTERM that the server dumps on. Full reasoning, with the doc links
that decided it, in [docs/runbook.md](docs/runbook.md#persistence).

## Caveats

The address is not stable. Every restart yields a new `host:port` from
`modal.forward`. Read it from `pg url` at process start, and reconnect
through `pg url` after a restart rather than retrying a cached address.

A Modal Function cannot run longer than 24 hours, so the server is killed
and replaced roughly daily. A `supervisor` function on a five minute schedule
notices the missing heartbeat and starts a replacement, which restores the
last dump. Expect a gap of a few minutes and a new address. `pg stop` records
that you meant it, so the supervisor leaves a deliberately stopped server
stopped.

It bills for wall clock time. Two CPUs and 4 GB, charged the whole time the
container is up, not per query. Run `pg stop` when you are done for the day.

The tunnel is a public TCP address with no IP allowlist. The only thing
between the internet and the database is the password, so `pg_hba.conf`
requires `scram-sha-256` from every non-local address. Treat the password as
a production credential and keep it out of the repo.

## Layout

```
src/scrooge_infra/
  postgres_app.py   the Modal app: image, volume, server, supervisor, archives
  cli.py            the pg command
  endpoint.py       URL building, Dict payload parsing, uptime, staleness
  progress.py       rich spinner on a tty, plain stderr lines on a pipe
tests/              the pure helpers, the parser, and the app object
docs/runbook.md     cold start, every flag, recovery, the Modal facts
```
