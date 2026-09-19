# scrooge-infra runbook

Operating the `pg` CLI and the `scrooge-postgres` Modal app: cold start, every
command and flag, what a run leaves behind, and how to get the data back when
something has gone.

## Cold start

Five steps, in order. Steps 2 and 3 need the Modal web console once.

```sh
cd infra
uv sync
```

`uv sync` installs the `modal` CLI into `.venv`, so every `modal` command
below is `uv run modal ...`. Nothing is installed globally.

**1. Check the CLI is there.**

```sh
uv run modal --help
uv run pg --help
```

**2. Authenticate.** On a machine with a browser:

```sh
uv run modal token new
```

That opens the console, creates a token and writes it to `~/.modal.toml`. On
a machine without a browser, create the token at
<https://modal.com/settings/tokens> and paste it in:

```sh
uv run modal token set --token-id ak-... --token-secret as-... --verify
```

`--profile NAME` writes it under a named section instead of `[default]`, and
`--activate` makes that section the active one. In CI, skip the file and set
`MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in the environment. Environment
variables take precedence over the file.

**3. Create the secret.** The password is a real credential. Generate it,
put it in Modal, put the same value in your own environment, and never write
it into a file in this repo.

```sh
export SCROOGE_PG_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run modal secret create scrooge-postgres POSTGRES_PASSWORD="$SCROOGE_PG_PASSWORD"
```

Add `SCROOGE_PG_PASSWORD` to your shell profile or to `infra/.env`, which is
gitignored. `.env.example` lists the names and no values.

**4. Deploy.**

```sh
uv run pg deploy
```

This builds the image, which pulls `postgres:17` and took 26 seconds the
first time and a few seconds afterwards, then registers three functions: `server`,
`supervisor` and `archives`. Deploying also arms the supervisor schedule.

**5. Start it and check it.**

```sh
uv run pg start
uv run pg status
```

A first `pg start` has no archive to restore, so it comes up empty. `pg
status` should print `running`, an address, and `SELECT 1 ok`.

## Environment

| Variable | Default | What it does |
| --- | --- | --- |
| `SCROOGE_PG_PASSWORD` | unset | Postgres superuser password on the client side. Must equal the `POSTGRES_PASSWORD` key of the Modal secret `scrooge-postgres`. Used by `pg url`, `pg psql` and the `pg status` reachability check. |
| `SCROOGE_PG_DUMP_INTERVAL` | `600` | Seconds between dumps, the interval `pg start` asks the server for. `--dump-interval` wins over it. Floored at 60 by the server. |
| `MODAL_TOKEN_ID` | unset | Modal token id. Only needed where there is no `~/.modal.toml`, such as CI. |
| `MODAL_TOKEN_SECRET` | unset | Modal token secret. Both must be set together. |
| `MODAL_PROFILE` | `default` | Which section of `~/.modal.toml` to use. |
| `MODAL_CONFIG_PATH` | `~/.modal.toml` | Where that file lives. |

`.env` and `.env.local` in `infra/` are loaded at CLI startup and never
override a variable already set in the shell or the cron line.

## Commands

Results go to stdout, progress and diagnostics to stderr, so `$(pg url)`
captures a URL and nothing else. Every wait longer than a few seconds shows a
spinner with elapsed time on a terminal, and one plain stderr line every 15
seconds when stderr is a pipe.

### pg deploy

```
pg deploy [--env NAME]
```

Wraps `modal deploy -m scrooge_infra.postgres_app`. Run it after any change to
`postgres_app.py`. A redeploy does not restart a running server, but it does
change what the next start runs, and it re-arms the supervisor schedule.

### pg start

```
pg start [--dump-interval SECONDS] [--timeout SECONDS] [--no-restore] [--force]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--dump-interval` | `600`, or `$SCROOGE_PG_DUMP_INTERVAL` | Seconds between dumps to the volume. |
| `--timeout` | `900` | How long to wait for an address before giving up. The wait is the image pull, initdb and restore. |
| `--no-restore` | off | Start on an empty cluster instead of restoring the newest archive. |
| `--force` | off | Spawn even though a live endpoint is already published. |

Sets the desired state to `running`, spawns the deployed `server` function
detached, then polls the Dict until an endpoint appears whose container id
differs from the one that was there before. Prints `host:port` on stdout.
Already running and not forced, it says so and prints the existing address.

Ctrl-C during the wait does not stop the server. It is already running on
Modal. Run `pg status` to pick it up again.

### pg stop

```
pg stop [--timeout SECONDS]
```

Sets the desired state to `stopped`. The server notices within 5 seconds,
runs a final `pg_dumpall` to the volume, stops the postmaster with `pg_ctl
stop -m fast`, and clears its endpoint from the Dict. `pg stop` waits for
that to happen, up to `--timeout` (default 300 seconds; a large database
takes a while to dump). The `stopped` state is what keeps the supervisor from
starting it again five minutes later.

If it hangs past the timeout, kill it the blunt way with `modal app stop
scrooge-postgres`, and accept losing anything written since the last dump.

### pg status

```
pg status [--password PASSWORD] [--no-check] [--connect-timeout SECONDS]
```

Prints state, desired state, address, uptime, start time, heartbeat age and
container id. With a password available it also opens a real connection and
runs `SELECT 1`, and prints the server version. Exit code 0 when running and
reachable, 1 when stopped, stale, or unreachable, which makes it usable in a
shell guard.

`--no-check` skips the connection, for when you only want the address.

### pg url

```
pg url [--password PASSWORD] [--no-password] [--database NAME]
```

Prints `postgresql://postgres:<password>@host:port/postgres` on stdout. The
password comes from `--password`, else `$SCROOGE_PG_PASSWORD`. It is
percent-encoded, so a generated password containing `@` or `/` still yields a
URL that parses. `--no-password` prints the literal `PASSWORD` in its place,
for pasting into a doc or a ticket.

Refuses to print anything when the endpoint is missing or its heartbeat is
stale, rather than handing out an address that answers nothing.

### pg psql

```
pg psql [--password PASSWORD] [--database NAME] [-- PSQL ARGS...]
```

Execs `psql` against the current endpoint, passing the password through
`PGPASSWORD` so it never appears in `ps` output. Everything after `--` goes
to psql. Without psql on `PATH` it prints the command to run and exits 1.

### pg dump

```
pg dump [--timeout SECONDS]
```

Asks the running server for an immediate `pg_dumpall`, waits for it, and
prints the archive name. The dump has to run in the container that holds the
postmaster, so the request travels as a record in the Dict with a uuid the
server stamps back when it is done. The server picks it up on its next poll,
within 5 seconds.

Run this before anything destructive, and before a deliberate `pg stop` if
you want a named archive to point at later.

### pg restore

```
pg restore [--archive NAME] [--list] [--yes] [--timeout SECONDS]
```

`--list` prints the archives on the volume with sizes and timestamps, newest
first, and touches nothing. It works whether or not a server is running,
because it runs in its own container with the volume mounted.

Without `--list`, it loads an archive into the running cluster. The dumps
carry `--clean --if-exists`, so this drops and recreates every object:
`--yes` is required, and there is no undo beyond the other archives. Default
archive is the newest.

## Persistence

**PGDATA is on the container's local disk at `/pgdata`, not on the Volume.**
The Volume `scrooge-postgres-data` is mounted at `/dumps` and holds gzipped
`pg_dumpall` archives, the newest 8.

The reason is in Modal's own Volume guide: "Volumes are optimized for
write-once, read-many I/O workloads, like creating machine learning model
weights and distributing them for inference"
(<https://modal.com/docs/guide/volumes>, checked 2026-09-19). A Postgres heap
is the opposite: small random writes, rewritten in place, with fsync ordering
that the storage layer has to honour for the WAL to mean anything. The same
page says changes need an explicit `commit()` to become visible outside the
container and that "Last write wins in case of concurrent modification of the
same file", neither of which is a durability model a database can be built
on. So the heap stays on local disk and the Volume gets whole-file archives,
which is exactly the write-once read-many shape it is built for.

The cost of that choice is a bounded window of loss. The timeline:

- Boot: initdb, start postgres, restore the newest archive if the data
  directory was empty, then open the tunnel. Clients only ever see a restored
  cluster, never an empty one that is about to be overwritten.
- Every `--dump-interval` seconds: `pg_dumpall | gzip` to `/tmp`, copy into
  `/dumps`, prune to 8 archives, `volume.commit()`. Dumping to `/tmp` first
  matters: a direct write interrupted halfway would be published by the
  automatic commit on container shutdown, and the next boot would restore
  from a truncated file.
- SIGTERM, from a stop, a timeout, a redeploy or a cancel: one more dump,
  then `pg_ctl stop -m fast`.

So a clean shutdown loses nothing and a hard crash loses at most one dump
interval. If that is too much for what you are loading, drop
`--dump-interval`, or run `pg dump` after a big batch load.

Revisit this if Modal's Volume docs stop saying write-once read-many. Putting
PGDATA straight on the Volume would remove the restore step and the window
entirely.

## Restart and re-launch behaviour

A Modal Function timeout can be at most 24 hours, so `server` is declared
with `timeout=86400` and is killed when it gets there. Nothing can hold a
single container open longer.

What fills the gap is `supervisor`, an `@app.function` on
`modal.Period(minutes=5)`. Every five minutes it compares two things in the
Dict: the desired state that `pg start` and `pg stop` write, and the
heartbeat the server refreshes every 60 seconds. It spawns a replacement only
when the desired state is `running` and the heartbeat is either missing or
more than 25 minutes old. A deliberately stopped server stays stopped, and a
healthy one is left alone.

The heartbeat is on its own timer rather than riding the dump, so raising
`--dump-interval` does not make a healthy server look dead. The 25 minute
window is wide enough that a slow dump of a large database, which blocks the
loop while it runs, does not trip it.

A replacement is a new container, so it restores the last archive and gets a
new tunnel address. Anything holding a connection sees it drop, and anything
holding a cached URL has to re-read `pg url`.

`min_containers=1` on a `modal.Cls` was the alternative. It keeps a container
warm but does not extend the 24 hour ceiling, and it would start a server
whenever the app was deployed, whether or not anyone wanted one running. The
schedule plus an explicit desired state gives the same recovery and leaves
starting and stopping under the operator's control.

`server` is declared `max_containers=1`, so a stray second `pg start --force`
queues rather than running two postmasters against the same archives.

## Recovery

### The server is gone and nothing is published

```sh
uv run pg status          # exits 1, prints the desired state
uv run modal app logs scrooge-postgres
uv run pg start
```

`pg status` prints the desired state it read. If that says `stopped`, the
supervisor is doing what it was told and `pg start` is the fix. If it says
`running` and there is still no endpoint, the logs will say why the last
container died. A fresh `pg start` restores the newest archive.

### The endpoint is published but nothing answers

The heartbeat is the tell. `pg status` marks an endpoint stale once the
heartbeat is over 25 minutes old, which is what a container killed at the
timeout leaves behind: it has no chance to clear its own entry. `pg start`
replaces it and overwrites the record.

If the heartbeat is fresh and the connection still fails, the password is the
next suspect. See below.

### Restoring an older archive

```sh
uv run pg restore --list
uv run pg restore --archive scrooge-postgres-20260919T101500Z.sql.gz --yes
```

Only the newest 8 archives are kept, so at the default 10 minute interval
that is about 80 minutes of history. Copy one off the volume before it ages
out if you need it longer:

```sh
uv run modal volume get scrooge-postgres-data scrooge-postgres-20260919T101500Z.sql.gz .
```

`modal volume ls scrooge-postgres-data` lists the same files from outside.

### Starting over from a specific archive

Stop, start with `--no-restore`, then restore the one you want:

```sh
uv run pg stop
uv run pg start --no-restore
uv run pg restore --archive NAME --yes
```

### Lost or rotated password

The password is stored in two places that have to agree: the Modal secret,
and the role in the running cluster. Rotate both:

```sh
export SCROOGE_PG_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run modal secret create scrooge-postgres POSTGRES_PASSWORD="$SCROOGE_PG_PASSWORD" --force
uv run pg stop
uv run pg start
```

The server re-applies the secret's password with `ALTER ROLE` on every boot,
after any restore, so a restart is what makes a rotation take effect. There
is no recovery path that keeps the old password: it is only ever stored
hashed in the cluster and encrypted in Modal.

If you have lost the password but still have a running server, `modal shell`
into the container and `psql` in over the local socket, which `pg_hba.conf`
trusts, then `ALTER ROLE postgres WITH PASSWORD '...'` and update the secret
to match.

### The volume has no archives at all

Then there is nothing to restore and the next start comes up empty. Reload
from `indexer/` output. This is the case the dump interval exists to make
rare, and the reason `pg dump` exists to be run by hand after a large load.

## Verified live on 2026-09-19

Run from the devsicap box against workspace `ambit-labs`, Postgres 17.11.

| Step | Result |
| --- | --- |
| `pg deploy`, first build | 26 s. The `postgres:17` pull plus `add_python` is not the minutes the first draft of this page guessed. |
| `pg start`, no warm container | 18 s from spawn to a tunnel address. |
| `pg status` | `SELECT 1 ok` over the tunnel with scram auth. |
| `pg dump` | 6 s round trip, 1.2 KB archive on an empty cluster. |
| `pg restore --list` | 8 s, lists the archive from a separate container. |
| `pg stop` | 6 to 12 s, including the final dump. |
| `pg start` 2.5 minutes after `pg stop` | 9 s. New container, `initdb`, `restoring scrooge-postgres-...` in the log, restore finished in 0.6 s, and the row written before the stop was back. This is the path the archives exist for. |
| `pg start` within a minute of `pg stop` | 3 s. The log says `PGDATA reused`: Modal handed back the same warm container, the data directory was intact, and no restore ran. The row written before the stop was still there. |

A warm restart therefore proves nothing about the archives. To exercise the
restore path, wait a few minutes after `pg stop` so the container is
reclaimed, then `pg start` and look for `restoring scrooge-postgres-...` in
`modal app logs scrooge-postgres`.

One bug came out of the live run. `pg url` through a pipe folded the URL at
80 columns, so `$(pg url)` produced a database name with a newline in it.
The stdout console now has `soft_wrap=True` and a regression test.

## Modal facts checked on 2026-09-19

Checked against the docs on this date. Modal's API moves, so re-check before
trusting any of it in a rewrite.

### 1. Tunnels and `modal.forward`

<https://modal.com/docs/guide/tunnels> and
<https://modal.com/docs/sdk/py/latest/forward>

Signature, confirmed against the installed `modal` 1.5.5:

```
modal.forward(port, *, unencrypted=False, h2_enabled=False, client=None)
```

It is a context manager, used from inside a running container, and it is
documented as an experimental API. The default puts TLS in front of the port
and yields a `tunnel.url`, which is HTTPS and no use to libpq. Raw TCP needs
`unencrypted=True`: "For protocols that do not use TLS, Modal supports
unencrypted TCP tunnels. These tunnels are exposed via a direct TCP socket
with a randomly assigned port number, rather than a secure URL." The yielded
object then carries `tunnel.tcp_socket`, a `(host, port)` tuple. The docs'
own SSH example unpacks it exactly as this app does:

```python
with modal.forward(port=22, unencrypted=True) as tunnel:
    hostname, port = tunnel.tcp_socket
```

The port is assigned at random per container, which is the whole reason for
the Dict.

### 2. Volumes as a Postgres data directory

<https://modal.com/docs/guide/volumes>

Still write-once read-many: "Volumes are optimized for write-once, read-many
I/O workloads, like creating machine learning model weights and distributing
them for inference." Also on that page: changes "need to be committed for
those the changes to become visible outside the current container", with an
automatic snapshot and commit on container shutdown; and "Concurrent
modification from multiple containers is supported, but concurrent
modifications of the same files should be avoided. Last write wins in case of
concurrent modification of the same file." Volumes v2 lifts the concurrency
ceiling for distinct files and adds `sync` on the mountpoint, but the
write-once read-many framing is unchanged.

**Decision: PGDATA stays off the Volume.** Dump-based persistence, as
described under Persistence above.

There is also a size ceiling worth knowing: Volumes "perform optimally with
fewer than 50,000 files and directories", with "a hard limit of 500,000
inodes". One archive per dump and 8 kept is nowhere near it, but a PGDATA
directory of a busy cluster would have made that a live concern too.

### 3. Function lifetime and how the server gets started

<https://modal.com/docs/guide/timeouts>, <https://modal.com/docs/guide/functions>,
<https://modal.com/docs/guide/trigger-deployed-functions>

The default execution timeout is "300 seconds (5 minutes)" and you "may
specify timeout durations between 1 second and 24 hours". 24 hours is a hard
ceiling; there is no documented way to keep one Function call alive past it.
Exceeding it raises `modal.exception.FunctionTimeoutError` after retries are
exhausted.

Three patterns exist for getting a long-lived service running, and this app
uses the second and third together:

- `modal run --detach` runs an ephemeral app that survives the terminal
  closing. Fine for a one-off, but the app is not deployed, so nothing can
  look its functions up by name later.
- A deployed app, invoked by name. "Modal Functions in deployed applications
  can be invoked from outside the application source using a function
  lookup", scoped by app name and function name, and this "is exclusively
  supported for deployed applications and will fail if the application is
  ephemeral". That is what `pg start` does: `modal.Function.from_name(
  "scrooge-postgres", "server").spawn(...)`.
- A `modal.Period` schedule, for re-launching. `supervisor` runs every five
  minutes and spawns a replacement when the desired state says running and
  the heartbeat has stopped.

`modal.Cls` with `min_containers=1` keeps a container warm but does not
change the 24 hour ceiling, so it solves a cold-start problem this app does
not have and not the lifetime problem it does.

### 4. `modal.Dict` and `modal.Secret`

<https://modal.com/docs/sdk/py/latest/Dict> and
<https://modal.com/docs/sdk/py/latest/Secret>

```
modal.Dict.from_name(name, *, environment_name=None, create_if_missing=False, client=None)
modal.Secret.from_name(name, *, environment_name=None, required_keys=[], client=None)
```

A Dict works from local code as well as inside a container, hydrating lazily
on first use, which is what lets `pg status` read the endpoint from a laptop.
It supports `put`, `get`, `contains`, `pop`, `update`, `clear`, `keys`,
`items` and `__getitem__`/`__setitem__`. Contents "can be essentially any
object so long as they can be serialized by cloudpickle", but this app writes
plain JSON types only, so a reader never needs this package importable at a
matching version.

`Secret.from_name(..., required_keys=["POSTGRES_PASSWORD"])` makes the server
assert the key exists rather than fail later on a `KeyError` inside the
container. Secrets are injected as environment variables into functions
listed in `secrets=[...]`. Create one from the CLI with `modal secret create
NAME KEY=VALUE`, which also takes `--env`, a `.env` or JSON file, and a force
flag to overwrite.

### 5. Authenticating from a machine that is not logged into the console

<https://modal.com/docs/reference/modal.config> and
<https://modal.com/docs/cli/latest/token>

`modal token new` opens the console and writes a fresh token. `modal token
set --token-id ak-... --token-secret as-... [--profile NAME] [--activate]
[--verify]` writes one you already have; passing `-` for either value reads
it from stdin instead of leaving it in shell history. Both write
`~/.modal.toml`:

```toml
[default]
token_id = "ak-12345..."
token_secret = "as-12345..."
```

`MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` do the same job without a file and
take precedence over it, which is the CI path. `MODAL_PROFILE` picks a
section of the toml and "defaults to 'default'". `MODAL_CONFIG_PATH`
relocates the file. Token auth and Modal's OAuth variables cannot be mixed.

### Notes on the image

`modal.Image.from_registry("postgres:17", add_python="3.12")`. The official
image has every binary at a matching version (`initdb`, `postgres`,
`pg_ctl`, `pg_dumpall`, `psql`, `pg_isready`), which a `debian_slim` plus apt
would have to pin by hand. It carries no Python, hence `add_python`, which
the docs cover under "Install Python on existing images". `.entrypoint([])`
clears `docker-entrypoint.sh`, which otherwise wants to own process startup
and fights the Function for it.

Postgres refuses to run as root and Modal containers are root, so every
binary that touches PGDATA runs through `subprocess` with `user="postgres"`,
the uid the official image already defines.
