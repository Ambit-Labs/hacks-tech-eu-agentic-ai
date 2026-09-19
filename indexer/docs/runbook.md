# scrooge-indexer runbook

Operating the `scrooge` CLI: every command and flag, what a run leaves behind,
and how to recover from an interrupted one.

The tool does two jobs. `list`, `download` and `status` fetch what councils
publish and keep it byte for byte on disk. `db init`, `load` and `load-status`
read those files into Postgres. The download half needs nothing but the
network; the load half needs `$DATABASE_URL`.

## Cold start

```sh
cd indexer
uv sync
uv run scrooge list --kind all
```

`uv sync` is the whole setup for downloading. There are no API keys, no
secrets and no binaries to install. `uv run scrooge list --kind all` should
print 27 registered sources with zero files on disk.

Nothing on the download side authenticates anywhere. If a source ever needs a
token (Socrata offers app tokens to raise the anonymous rate limit), that will
be a new environment variable documented here, not a silent addition. GOV.UK's
content API, the DataPress portals and the Modern.Gov web service are all open,
unauthenticated and unmetered as of 2026-09-19.

### Cold start for the loader

The loader needs a Postgres it can write to. On Modal that is the `infra/`
project; anywhere else it is a connection string you already have.

```sh
cd ../infra && uv run pg start --dump-interval 3600
export DATABASE_URL="$(cd ../infra && uv run pg url)"
cd ../indexer
uv run scrooge db init
```

`pg url` builds the string from the live tunnel address and the password in
`infra/.env`. Nothing writes it to disk here, and the Modal tunnel gets a new
host and port on every restart, so treat the export as good for one session
and re-export it whenever a command says the connection dropped.

`db init` applies `docs/payments-schema.sql` when there is no `payments` table
yet, then upserts all 33 London authorities into `boroughs` with their ONS
mid-2025 population. It is safe to run twice: the second run reports that
`payments` exists, refreshes the 33 rows and re-grants `SELECT` to
`scrooge_reader`.

The agent's login role is created by hand, once, and its password never
reaches the repo:

```sh
read -rs AGENT_PASSWORD           # nothing echoed, nothing in shell history
cd ../infra && uv run pg psql -c \
  "CREATE ROLE agent LOGIN PASSWORD '$AGENT_PASSWORD' IN ROLE scrooge_reader"
uv run pg psql -c "ALTER ROLE agent SET statement_timeout = '10s'"
unset AGENT_PASSWORD
```

`scrooge_reader` comes from the schema file and can only read `boroughs`,
`source_files`, `payments` and `coverage`. The agent session gets
`postgresql://agent:<password>@<host>:<port>/postgres` and can do nothing else
with it.

## Kinds

Every verb takes `--kind`:

| Value | Selects | Writes to |
| --- | --- | --- |
| `spend` (default) | the 15 boroughs publishing transaction-level payments | `data/raw/<slug>/` |
| `budget` | the 12 budget sources: planned spend | `data/budgets/<slug>/` |
| `all` | both | both |

The default is `spend` so that a cron line written before budgets existed does
exactly what it did before. `--all` respects `--kind`; a slug named outright is
downloaded whatever `--kind` says, because typing `mhclg` is already a choice
of kind. The two trees are otherwise identical: same `<period>__<filename>`
naming, same per-source `manifest.json`, same resume rules.

`--kind` belongs to the download half. `load` reads `data/raw/` and has no
`--kind`, because a budget book is a PDF and the loader reads payment tables.

## Environment

| Variable | Default | What it does |
| --- | --- | --- |
| `SCROOGE_DATA_DIR` | the repo root `data/` | Where files and manifests are written, and where `load` reads them from. |
| `DATABASE_URL` | none | Where `db init`, `load` and `load-status` write. No default: the Modal address changes on every restart. Must be the owner login; see the note on `.env.local` below. |
| `SCROOGE_TEST_DATABASE_URL` | none | A Postgres the test suite may create and drop a database on. Unset means the database tests skip. |

The data directory resolves in this order: `--data-dir PATH`, then
`$SCROOGE_DATA_DIR`, then the repo root `data/` found by walking up from the
package until a `.git` directory appears, then `./data` if there is no
checkout. `.env` and `.env.local` in the repo root are loaded if present, and
never override a variable already set in the shell or the cron line.

No host, port or password for the database is stored anywhere in this repo.
`DATABASE_URL` is read from the environment, and the one line the loader
prints at startup replaces the password with `***` so a log or a screenshot
cannot leak it.

The `.env.local` rule applies to `DATABASE_URL` too, and that file is where
the agent session keeps its read-only `agent` login. A `scrooge load` in a
shell with no export picks that one up and stops at its first write with
`the database refused: permission denied for table payments`. The startup
line names the login it is using, so `postgresql://agent:***@...` there means
the export is missing.

## Commands

### scrooge list

```
scrooge list [--kind {spend,budget,all}] [--data-dir PATH]
```

One row per registered source: slug, kind, publisher name, access method
(`socrata-api`, `datapress-api`, `govuk-content-api`, `moderngov-api`,
`url-pattern`, `scrape`), publication threshold, files already on disk, and the
latest period held. The table goes to stdout, warnings go to stderr. It is wide
with `--kind all`; a terminal under about 130 columns folds the slug.

### scrooge download

```
scrooge download [SLUG ...] [--all] [--kind {spend,budget,all}]
                 [--since YYYY-MM] [--until YYYY-MM]
                 [--limit N] [--force] [--data-dir PATH] [--delay SECONDS]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `SLUG ...` | none | Sources to download, by slug. `scrooge list --kind all` prints them. |
| `--all` | off | Every registered source of `--kind`. |
| `--kind` | `spend` | Which sources `--all` selects, and which tree they write to. Ignored for a named slug. |
| `--since YYYY-MM` | the source's earliest period | Skip anything ending before this month. |
| `--until YYYY-MM` | the current month | Skip anything starting after this month. |
| `--limit N` | no limit | At most N files per source, the most recent N. |
| `--force` | off | Re-download files already recorded as complete. |
| `--data-dir PATH` | see Environment | Where to write. |
| `--delay SECONDS` | `0.5` | Minimum pause between two requests to the same host. |

A file that straddles a bound is kept. `--since 2026-06` keeps the quarter
that contains June rather than dropping it, and keeps a half year that runs
through June. Both flags are months; there is no range form for them. For
budgets that means `--since 2026-04` is the 2026-27 financial year and
everything still open at that point, including the multi-year time series.

`--since` and `--until` also cut discovery cost, not just what is fetched. The
per-year budget families check the year against the window before they spend a
request on that year's release page, so a narrow window on `mhclg` is tens of
requests rather than about seventy.

Naming no source and not passing `--all` prints a usage hint and exits 2.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Everything discovered was fetched or already on disk. |
| 1 | At least one file failed (5xx after retries, timeout, 403, bot challenge). |
| 2 | Usage error: no borough named, unknown slug, malformed `--since`/`--until`. |
| 130 | Ctrl-C. |

A 404 is not a failure. An unpublished month is recorded with status `missing`
and the run still exits 0.

### scrooge status

```
scrooge status [--kind {spend,budget,all}] [--data-dir PATH]
```

Per-source counts read from the manifests: files, bytes, earliest and latest
period, last run, and failures. The last row is the total, of whatever `--kind`
selected, so a spend total and a budget total are two separate runs of this
command. Earliest and latest are read through the period grammar rather than
off the string, so a file covering September 2010 to March 2011 counts as
reaching March 2011 and a quarter counts as reaching the last month in it.

### scrooge db init

```
scrooge db init
```

Applies `docs/payments-schema.sql` when `payments` does not exist, then
upserts the 33 `boroughs` rows and re-grants `SELECT` to `scrooge_reader`. The
schema file is resolved relative to the git checkout the package was run from,
so it is never duplicated and never drifts from the copy the agent session
reads as its contract. Outside a checkout the command fails and says so rather
than applying some other schema.

Populations are the ONS mid-2025 estimates, fetched from NOMIS dataset
`NM_2002_1` on 2026-09-19 and checked against table MYE2 of the ONS
"Estimates of the population for England and Wales" release. The URLs, the
table name and the year are in the header comment of
`src/scrooge_indexer/loader/boroughs_data.py`. To move to a later year, change
that file and run `db init` again; the upsert replaces name and population in
place and touches nothing else.

`CREATE ROLE scrooge_reader` in the schema file sits inside a `DO` block that
swallows `duplicate_object`. Roles live in the cluster rather than in one
database, so without that guard a second `db init` against a different
database on the same server, or against a server restored from a dump that
carried the role, would abort the file on its last two statements.

### scrooge load

```
scrooge load [SLUG ...] [--all] [--since YYYY-MM] [--until YYYY-MM]
             [--limit N] [--force] [--data-dir PATH]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `SLUG ...` | none | Boroughs to load. Only the 15 with a column mapping are accepted. |
| `--all` | off | Every borough with a mapping and a directory under `data/raw/`. |
| `--since YYYY-MM` | the earliest file held | Skip anything ending before this month. |
| `--until YYYY-MM` | the latest file held | Skip anything starting after this month. |
| `--limit N` | no limit | At most N files per borough, the most recent N. |
| `--force` | off | Reload files already recorded as `loaded` or `skipped`. |
| `--data-dir PATH` | see Environment | Where to read from. |

The period comes from the borough's `manifest.json` where there is an entry
for the file and from the `<period>__` filename prefix where there is not, so
`--since` and `--until` use the same period grammar and the same overlap rule
as `scrooge download`.

One file is one transaction. It deletes that file's rows from `payments`,
writes its `source_files` row, COPYs the new rows in, and only then records
the outcome. A run killed mid-file leaves that file absent rather than half
present, which is what makes rerunning the same command the whole of the
recovery procedure.

Every file ends as one of three things in `source_files`:

| Status | Means | Retried on a plain rerun |
| --- | --- | --- |
| `loaded` | Its rows are in `payments`. `reason` carries the count of dropped rows if there were any. | no |
| `skipped` | The file is not a payment list, or there is no reader for it. | no |
| `failed` | Something went wrong that another run might survive. | yes |

Retrying `failed` by default is a deliberate choice. A failure here is almost
always a dropped connection or a parser that gave up partway, and the natural
response to a failed run is to run it again. Making that need `--force` would
also reload the thousand files that worked. A `skipped` file is a decision
about what the file contains, and rerunning cannot change it, so skips need
`--force` like loaded files do.

A row that breaks a value rule is dropped, counted, and the file still loads.
The count and the reasons go into `source_files.reason`, for example
`12 rows dropped: 9 bad date, 3 empty supplier`. `source_row` counts every
data row after the header, so a gap in the numbering is the record that
something was thrown away. Fully blank rows, section markers such as Bexley's
`APRIL`, and footer totals are not failures and are not counted as drops.

Exit codes are the download's: 0 clean, 1 at least one file failed or the
database was unreachable, 2 usage, 130 Ctrl-C.

### scrooge load-status

```
scrooge load-status [--problems [N]]
```

Loaded, skipped and failed file counts per borough, row totals and the period
range, read from `source_files` rather than from disk. `--problems` also lists
up to N files that did not load with their reason, 50 by default.

The verb is `load-status` rather than `load status` because `load` takes a
list of borough slugs as positionals, and a subcommand sitting in that
position would be ambiguous in argparse and worse in `--help`. Issue #8
sketched it as `scrooge load status`; this is the same thing with a hyphen.

### What does not load, and why

Measured against every file on disk on 2026-09-19: 1,371 files, 1,348 loaded,
23 skipped, 0 failed, 15,017,306 rows. The 23 skips are stable, so a run that
reports these numbers is a clean run rather than one to investigate.

| Files | Status | Reason |
| --- | --- | --- |
| 18 Lambeth months, 2010-12 to 2012-07 | `skipped` | `supplier totals, not payments`. One row per supplier with a month's total, which the schema doc says to skip. |
| 2 Lambeth quarters, 2018-Q2 and 2018-Q3 | `skipped` | `no ODS reader`. Adding one means a new dependency for two files. |
| Newham 2019-02 | `skipped` | An Excel 97 workbook published with a `.csv` extension. openpyxl reads xlsx, not xls. |
| Bexley 2015-07 to 2015-09, Havering 2013-05 | `skipped` | No header row at all. The doc allows applying the borough's dominant header by position; this does not, because a mapping inferred from nothing is the one kind of error nobody would catch. |

One file is read the other way round. Lambeth
`2020-Q2__ec-over-500-report-q2-2020-21.csv` publishes its dates month first,
which the loader settles by scanning that file's date column and records as
`dates read month-first` in `source_files.reason`. The rule is in the Dates
paragraph of `docs/payments-schema.md`: at least one slash date with a second
number above 12 and none with a first number above 12. A file carrying both
kinds fails with `date column has both orders`, and no file on disk does.

The largest remaining drop is Bexley's October 2014 to March 2015 half year,
which publishes a month rather than a day, `Oct-14` for every row. Those 9,928
rows are dropped as `bad date`. There is no day to recover and inventing the
first of the month would be worse than the gap.

## Where files land

```
data/
  raw/<slug>/         spend, unchanged since before budgets existed
  budgets/<slug>/     budget
```

Both trees hold `manifest.json` plus `<period>__<publisher filename>` and
nothing else. Budget files add `.pdf` to the formats already on disk, and the
MHCLG source prefixes each file with its family (`ra-`, `ro-`, `qru-`, `cer-`,
`cor-`, `capital-`, `counciltax-`, `csp-`, `s251-`) unless the publisher's own
name already starts that way, so `ls data/budgets/mhclg` groups by return
rather than by MHCLG's internal form numbering. `COR_A1.ods` carries no year at
all, which is the period prefix doing real work.

## Periods

A saved file is named for the period it covers, two underscores, then the
publisher's own filename. Three spellings, and no others:

| Period | Means | Who writes one |
| --- | --- | --- |
| `2026-07` | one calendar month | every monthly borough |
| `2026-07_2026-11` | July to November inclusive | Barnet, Bexley, Brent, Hounslow, Lambeth |
| `2026-Q1` | one quarter | Brent, Haringey, Islington, Lambeth, Westminster |

Budgets add no fourth spelling. A financial year is the range it covers, so
2026-27 is `2026-04_2027-03`; a budget book covering four years at once is
`2026-04_2030-03` and a window inside that span still reaches it; a multi-year
statistical series is the range of its span, `1999-04_2027-03` for the London
Datastore council tax workbook.

The range form is a start month, one underscore and an end month. The
separator before the filename is two underscores, so a range is still readable
at a glance: `2010-09_2011-03__council-spending-over-500-september-2010-to-march-2011.csv`.
It holds a half year, a whole financial year, and a quarter that does not line
up with anyone's quarters, which is how Bexley's 23 pre-2019 files and
Hounslow's four whole-year files are fetched at all.

`YYYY-Qn` is the financial-year quarter: Q1 is April to June, and `2026-Q4`
covers January to March 2027. Every quarterly borough registered today sets
`quarters = "financial"`, so that reading holds for everything on disk. A
borough that numbered its quarters by the calendar year would set
`quarters = "calendar"` and write the same string for January to March;
`--since` and `--until` honour that setting, while `scrooge list` and
`scrooge status` assume the financial one, because a manifest records a period
and not the convention behind it.

A bare year is not a period. Nothing publishes a calendar year, and a
financial year is a range that says so.

## Borough coverage

What a full run is asking for, borough by borough. Verified against the live
sites on 2026-09-19.

| slug | borough | access | threshold | frequency | history start | quirks |
| --- | --- | --- | --- | --- | --- | --- |
| barnet | Barnet | datapress-api | none | monthly | 2013-04 (one whole-FY file, then monthly from 2014-04) | cp1252; skips the cumulative roll-up |
| bexley | Bexley | scrape | £500 | monthly | 2010 (half-year and annual files before 2019-01) | purchase-card files excluded by page section, plus one mislinked under a year heading |
| brent | Brent | datapress-api | £500 | quarterly | 2020-03 | off-cycle quarters until 2024, true FY quarters from 2025-Q1 |
| camden | Camden | socrata-api | £500 | monthly (API export) | 2019-09 | last two months mutable |
| haringey | Haringey | scrape | not stated | quarterly (FY) | 2023-Q1, only three FYs kept online | pre-aggregated, negative rows, publishes up to two quarters late |
| havering | Havering | scrape | £500 | monthly | 2010-12 | URLs carry no extension |
| hounslow | Hounslow | scrape (Next.js data route) | £500 | monthly, CSV or XLSX | 2010-09 | buildId re-read each run |
| islington | Islington | scrape | £500 nominal, not filtered | quarterly (FY) | 2019-Q3 | filed by closing month, quarters ran Mar-May until 2023 |
| lambeth | Lambeth | scrape | £500 | quarterly since 2015, monthly before | 2010-12 | cp1252; XLSX and ODS before 2023 |
| lewisham | Lewisham | scrape + url-pattern fallback | £250 | monthly | 2023-02 | two preamble rows; XLSX months in 2023-24 |
| newham | Newham | scrape | £250 | monthly | 2018-04 | slugs lie, month from link text |
| redbridge | Redbridge | scrape (DataShare) | £500 | monthly, CSV or XML | 2010-04 | two 2026-27 slugs mislabelled 2027 |
| richmond | Richmond upon Thames | url-pattern | £500 | monthly | 2019-01 | media hash ignored by server; UTF-8 BOM |
| wandsworth | Wandsworth | url-pattern | £500 | monthly | 2019-01 | same system as Richmond |
| westminster | Westminster | scrape | £500 | quarterly (FY) | 2021-Q1 | CSV served without extension |

## Budget coverage

Twelve sources, verified against the live sites on 2026-09-19. "Files" is what
a full run discovers today; a first backfill of all twelve is roughly 850 files
and a few gigabytes, most of it MHCLG's capital returns.

| slug | access | frequency | history start | files | quirks |
| --- | --- | --- | --- | --- | --- |
| mhclg | govuk-content-api | yearly, plus quarterly live tables | 2007-04 (capital outturn), RA budget from 2010-11 | 233 | ~70 discovery requests with no window; 7 mutable files |
| london-datastore-counciltax | datapress-api | yearly, in place | 1999-00 | 1 | one workbook, one sheet per year, mutable |
| richmond-budget | url-pattern | yearly | 2007-08 | 20 | generated-URL fallback if the page is rebuilt |
| wandsworth-budget | url-pattern | yearly | 2008-09 | 19 | same CMS as Richmond |
| camden-budget | scrape | yearly | 2015-16 | 17 | modern URLs carry no file extension |
| croydon-budget | scrape | yearly | 2009-10 | 18 | five filename conventions across 18 years |
| merton-budget | scrape | every year, four-year book | 2013-17 | 13 | periods are four-year ranges |
| lewisham-budget | scrape | yearly | 2012-13 | 17 | three path prefixes; en dashes in labels |
| hounslow-budget | moderngov-api | yearly | 2013-14 | 83 | report plus appendices A to I; 10 years labelled of 14 |
| lambeth-budget | moderngov-api | yearly | 2011-12 | 143 | 8 years labelled; gaps 2012-13 to 2018-19 and 2022-23 |
| brent-budget | moderngov-api | yearly | 2020-21 | 184 | 27 documents per year |
| haringey-budget | moderngov-api | yearly | 2020-21 | 104 | 5 years labelled; gaps 2021-22 and 2024-25 |

The Modern.Gov sources find the budget meeting by the status label the council
puts on it ("Confirmed; Budget Council", "Confirmed; Budget Setting Meeting").
A year the council left unlabelled is not reachable that way and simply does
not appear. That is a gap in coverage, not a fault: finding it any other way
would mean fetching every February agenda on the chance it was the budget one.
A budget source that shows nothing new for eleven months is also normal; these
publish once a year, in February or March.

Two known log lines that are not faults:

- `mhclg: no ra files matched in ...2007-to-2008-individual-local-authority-data`
  every run. That release holds outturn RS and RSX files under a slug and a
  title that do not say so. The filter is right to skip it, and it says so
  rather than skipping silently, which is what a genuinely renamed file would
  look like.
- `mhclg: no section 251 planned expenditure file in ...` if DfE has published
  the current year's guidance before its data.

## What a run looks like

stderr gets one line before discovery starts, one summary line once the file
list is known, then progress:

```
scrooge download: camden, richmond, wandsworth · discovering...
scrooge download: 3 borough(s) (camden, richmond, wandsworth) · 7 file(s) discovered · 0 already on disk · /repo/data
```

On a terminal, progress is a Rich bar with done/total, elapsed, ETA and live
counters for ok, skipped, failed and bytes. Piped or under cron, stderr is not
a tty and the same counters come out as plain lines instead, every step for a
run of 40 files or fewer and every 15 seconds for a larger one:

```
download: 3/7 · ok=3 bytes=4.1MB in 0:00:01
download: done 7/7 · ok=7 bytes=5.5MB in 0:00:02
```

The per-borough summary table goes to stdout at the end, so `scrooge download
--all > summary.txt` keeps the table and leaves the progress on the terminal.

Two things load as published and are wrong at the source. The loader has no
rule for either, so queries over these months need to know.

- Two files are byte-for-byte copies of another month and both load. Havering
  `2011-12__december-2011.csv` is December 2010 again (5,209 rows, £45.3m),
  and Newham `2018-06__paymentstosuppliersjuly2018.csv` is the July file
  (10,303 rows, £65.2m). Havering December 2010 and Newham July 2018 are
  double in `coverage`, and December 2011 and June 2018 are missing.
- Some councils transposed day and month in part of a file before publishing
  it. Hounslow `2021-01` carries ISO dates such as `2021-05-01` for 5 January,
  1,115 of its 3,250 rows. Redbridge March 2016 has 699 rows written
  `03/MM/2016` with a month after March. The per-file month-first rule cannot
  see these, because the rest of each file is day first. 3,053 rows across
  Hounslow, Lambeth and Redbridge are dated more than a month after their
  file's period ends.

A load prints the same shapes with its own counters:

```
scrooge load: 15 borough(s) (barnet, bexley, ...) · 1371 file(s) on disk · 0 already done · postgresql://postgres:***@host:5432/postgres
load: 829/1,371 · loaded=806 skipped=23 rows=8,398,016 in 0:05:07
```

The bar counts files, not rows, because files are what resume works on. Rows
is the live counter next to it, and it is the number worth watching: a bar
that advances with the row count stuck means the loader is reading files it
has decided to skip.

A skipped or failed file prints one line naming the file and the reason, so a
run under cron leaves an explanation in the log without anyone querying
`source_files`.

## Bulk loading into the Modal Postgres

The whole corpus is about 2.9 GB of CSV and 16 million rows, and it all goes
through the Modal tunnel. The server keeps PGDATA on the container's local
disk and only the periodic `pg_dumpall` archives land on the Volume, so a
restart in the middle of a load costs everything written since the last dump.

Start the server with a long dump interval, load, then dump once by hand:

```sh
cd ../infra
uv run pg start --dump-interval 3600
export DATABASE_URL="$(uv run pg url)"
cd ../indexer
uv run scrooge db init
uv run scrooge load --all
cd ../infra && uv run pg dump
```

The default interval is 600 seconds, and a `pg_dumpall` of a 17 GB database
blocks the server's own loop while it runs. Six dumps an hour of a database
that is still being written to is wasted work: raise the interval for the
load, take one dump at the end, and put the interval back for normal running.

What a restart costs during a load. A replacement container restores the last
archive and gets a new tunnel address, so the loader's connection drops and it
stops with the message that says to re-export `DATABASE_URL`. Files committed
after that last dump are gone from `payments` and from `source_files`
together, because they were written in the same transaction, so the rerun
reloads exactly those files and nothing else. With `--dump-interval 3600` the
worst case is an hour of loading to redo, which at the speed measured on a
local Postgres 17 is roughly 90 million rows of headroom and in practice the
whole corpus.

Two things end a container: a deliberate `pg stop`, and the 24 hour function
timeout. `infra/docs/runbook.md` has the detail. If the load will run near a
container's 24 hour mark, start a fresh one first.

### The faster route: load locally, restore on Modal

Loading through the tunnel is the slow way to fill an empty server. The
server's own archive format is a gzipped `pg_dumpall --clean --if-exists` on
the Volume `scrooge-postgres-data`, and it restores the newest one at boot. So
load into a local Postgres 17, dump it in that format, and hand the archive
to the Volume. This is how the first full load was done on 2026-09-19.

```sh
docker run -d --name scrooge-loader-test --restart unless-stopped \
  -e POSTGRES_PASSWORD="$PGPASS" -p 127.0.0.1:55432:5432 postgres:17
export DATABASE_URL="postgresql://postgres:$PGPASS@127.0.0.1:55432/postgres"
uv run scrooge db init && uv run scrooge load --all

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
docker exec scrooge-loader-test pg_dumpall -U postgres --clean --if-exists \
  | pigz > /tmp/scrooge-postgres-$STAMP.sql.gz

cd ../infra
uv run pg stop                                # only if a server is up
uv run modal volume put scrooge-postgres-data \
  /tmp/scrooge-postgres-$STAMP.sql.gz /scrooge-postgres-$STAMP.sql.gz
uv run pg restore --list                      # the new archive must be newest
uv run pg start --dump-interval 21600 --timeout 5400
```

Measured on 2026-09-19 for 15,017,306 rows: local load 9 minutes, dump 25
seconds, archive 491 MB, upload under 2 minutes, boot with restore 11 minutes
on the 2 CPU container. The database is 19 GB locally and 14 GB after the
restore, because a restore writes no dead rows.

The name matters. The server picks the newest archive by the timestamp in the
file name, so the stamp has to be later than every archive already on the
Volume. The archive carries the local `postgres` password, which the server
overwrites with the Modal secret after the restore and before the tunnel
opens. It also carries every login role in the local cluster, so dump before
creating any local-only login, or that login and its weak password go to a
server on the public internet.

Those 11 minutes are paid again on every container start, including the daily
replacement after the 24 hour function timeout, and `pg start` has to be given
a `--timeout` that covers them. The default of 900 seconds leaves little room.

Check the copy before trusting it. Run the same per-borough query on both
sides and compare:

```sql
SELECT borough, count(*), sum(amount_gbp), min(payment_date), max(payment_date)
FROM payments GROUP BY 1 ORDER BY 1;
```

## Resume and recovery

Re-running the same command is the recovery procedure. A file is skipped when
the manifest records it as `ok` for that exact period and URL and the file is
still on disk. Deleting a file is enough to make the next run fetch it again.

Ctrl-C exits 130 and prints the exact command to resume. It leaves behind:

- Every file that had finished, and a manifest that lists them. The manifest is
  rewritten atomically after every single file, so it never describes a file
  that is not there.
- No `.part` file. The in-flight transfer is deleted on the way out, because a
  partial CSV that survived would be indistinguishable from a complete one.
- Nothing else. There is no lock file and no scratch directory to clean up.

If a run dies in a way that does leave a `.part` behind (`kill -9`, a full
disk), delete it. `find data/raw -name '*.part' -delete`. The matching file was
never renamed into place, so the next run refetches it.

If a manifest is corrupted, it is read as empty rather than crashing the run,
and the next download rebuilds it. That costs one refetch of that borough.

### Resume and recovery for a load

Rerunning the same command is again the whole procedure. Files recorded as
`loaded` or `skipped` are passed over without opening them, files recorded as
`failed` are retried, and files with no row at all are loaded.

Ctrl-C exits 130 and prints the resume command. The file in flight is rolled
back, so `payments` never holds part of a file and `source_files` never claims
a file that is not there. There is no lock file and nothing to clean up.

If the connection drops mid-run, the loader stops with one message:

```
The database connection dropped. The Modal tunnel gets a new address on every
restart, so re-export the URL and run the same command again; files already
loaded are skipped.
  export DATABASE_URL="$(cd ../infra && uv run pg url)"
```

That is the whole recovery. It stops rather than retrying because a new tunnel
address is the usual cause and no amount of reconnecting to the old one will
find it.

Other things that go wrong, and what to do:

- **`the database refused: permission denied`.** `DATABASE_URL` is a login
  that cannot write, nearly always the `agent` one from `.env.local`. Export
  the owner URL from `pg url` and rerun. Nothing was written.
- **The loader was killed, or the machine went down.** Every file commits on
  its own, so everything the progress line had counted as loaded is in the
  database and the file in flight is absent. Rerun the same command.
- **A borough loads zero rows.** `scrooge load-status --problems` names the
  files and the reason. `unmapped header` means the council changed its column
  names, which is a change to the table in `docs/payments-schema.md` and then
  to `LAYOUTS` in `loader/mappings.py`.
- **A file reports a large number of dropped rows.** The reason field says
  which rule they broke. A whole file dropping on `bad date` usually means the
  borough published a month rather than a day, as Bexley did for October 2014
  to March 2015. Dropping the rows is right; inventing a day for them is not.
- **`db init` says the schema file is missing.** The package was installed
  outside a checkout. `docs/payments-schema.sql` is resolved from the git root
  above the package, and there is deliberately no second copy to fall back to.
- **The row counts look right but the agent sees nothing.** Re-run
  `scrooge db init`. It re-grants `SELECT` to `scrooge_reader`, which a restore
  from an archive taken before the role existed can leave behind.
- **A file needs reloading after a fix.** `scrooge load <borough> --since
  <month> --until <month> --force`. `--force` is the only thing that reloads a
  file recorded as `loaded` or `skipped`.

`--force` refetches everything discovered, even files recorded as complete, and
replaces them in place. Use it after a council silently republishes a
corrected month. It is not needed for ordinary catch-up, and the resume hint
printed on Ctrl-C deliberately leaves it out.

Mutable files behave differently by design. Camden's current month, any
cumulative year-to-date export a borough republishes, and the seven MHCLG and
London Datastore files that are extended in place carry `mutable=True` and are
re-checked on every run. The check is a conditional request first
(`If-None-Match` and `If-Modified-Since` from the manifest). A 304 costs
nothing and counts as skipped. Socrata ignores conditional requests, so the
file comes back in full and the sha256 decides: identical bytes count as
skipped, changed bytes replace the file. Mutable files are replaced, never
appended to, so a month that gains late postings ends up correct rather than
doubled.

### Recovery specific to budgets

- **A budget source discovers nothing.** For a scraped budget book the page has
  been rebuilt. Richmond and Wandsworth fall back to generated media URLs and
  keep the modern years; the other four go to zero and need their
  `link_pattern` or `label_pattern` looked at. Open the `landing_page` from
  `scrooge list --kind budget` and compare.
- **MHCLG logs "no ... files matched".** A release has been renamed. The
  warning names the page path and how many attachments it has; open it and fix
  the family's pattern in `mhclg.py`. The other nine families are unaffected,
  which is the point of the per-family wrapping.
- **MHCLG logs "... failed, skipping that family".** A collection or release
  path has moved. `SETTLEMENT_COLLECTION` is the one that is expected to move,
  once per settlement round.
- **A time series period is short by a year.** `REVENUE_SERIES_SPAN` in
  `mhclg.py` and `SPAN` in `london_datastore_counciltax.py` are declared,
  because neither publisher states the span anywhere machine-readable. The file
  itself is still correct and still re-downloaded; only the period on disk
  understates it. Bump the constant, then `--force` that source to rename.
- **A Modern.Gov committee is renumbered.** `GET
  <host>/mgWebService.asmx/GetCommittees?lDays=0` lists the current ids.

## Monthly cron

Ten of the fifteen boroughs publish monthly, mostly in the second or third
week. A run in the early hours of the 20th picks up the previous month for
those.

Westminster, Brent, Haringey, Islington and Lambeth publish quarterly, and
Haringey and Westminster run up to two quarters behind, which is four months
of silence before a file appears. A monthly cron is still the right schedule
for all five: it costs one discovery request a month and catches the quarter
the week it goes up. What it does mean is that a borough showing no new file
for months is the normal state of a quarterly publisher, not an outage. Check
`scrooge status` against the table above before going looking for a fault.

```cron
# 03:17 on the 20th of each month. Two months of overlap so a late
# publication is not missed, and resume makes the overlap nearly free.
17 3 20 * * cd /srv/hacks-tech-eu-agentic-ai/indexer && /usr/local/bin/uv run scrooge download --all --since $(date -d '2 months ago' +\%Y-\%m) >> /var/log/scrooge-indexer.log 2>&1
```

stderr is not a tty under cron, so the log gets plain progress lines rather
than escape codes. A non-zero exit means at least one file failed, which is
worth an alert. A borough that starts returning 403 will fail every month until
someone looks at it.

For the first full backfill, run it by hand and expect it to take a while:
about 90 monthly files per borough at 0.5 s apart, plus transfer time.
Redbridge alone is roughly 10 MB per month.

## Budget cron

Budgets are not monthly. A borough sets its budget once, in February or March,
and MHCLG publishes the year's returns between March and July. Two lines, for
the two rhythms:

```cron
# Yearly, after the June and July MHCLG releases have landed. The RA budget
# release is mid-June and the Section 251 data is late June, so an August run
# catches both with a month to spare. --since is the financial year that has
# just started, which keeps discovery to a few requests per family instead of
# re-walking sixteen years of releases.
23 2 5 8 * cd /srv/hacks-tech-eu-agentic-ai/indexer && /usr/local/bin/uv run scrooge download --all --kind budget --since $(date -d '-4 months' +\%Y-\%m) >> /var/log/scrooge-budgets.log 2>&1

# Monthly, for the files that are rewritten in place: the two time series,
# the quarterly revenue update, Core Spending Power, Section 251, and the
# London Datastore council tax workbook. Cheap: a conditional request each,
# and nothing moves unless the publisher changed something.
41 2 21 * * cd /srv/hacks-tech-eu-agentic-ai/indexer && /usr/local/bin/uv run scrooge download mhclg london-datastore-counciltax >> /var/log/scrooge-budgets.log 2>&1
```

The yearly line is the one that matters. The monthly line exists because the
Quarterly Revenue Update lands four times a year and the outturn time series
gains a year each September, and neither announces itself.

A borough budget source is worth a single yearly run in April, once every
council has set its budget:

```cron
# 04:09 on 5 April. Every council has set its budget by 11 March.
9 4 5 4 * cd /srv/hacks-tech-eu-agentic-ai/indexer && /usr/local/bin/uv run scrooge download --all --kind budget >> /var/log/scrooge-budgets.log 2>&1
```

Run that one without `--since` the first time: it is the full backfill, about
850 files. After that the resume rules make it nearly free, and the yearly
August line with `--since` keeps it that way.

Do not add `--kind all` to the existing monthly spend cron. It would put the
seventy-odd MHCLG discovery requests on a monthly schedule for data that
changes once a year.

## Politeness

This tool identifies itself honestly and does not work around anything.

- The User-Agent is `scrooge-indexer/0.1 (+research; contact via repo)` on every
  request. No browser string, no rotation.
- One request per host per 0.5 s by default. Raise it with `--delay` if a
  council asks.
- Retries are limited to 4 attempts with exponential backoff, and only on 429
  and 5xx and transport faults. A 429 with a numeric `Retry-After` is honoured
  up to 120 seconds.
- A 403 or a bot challenge page is recorded with status `blocked` and the run
  moves on. There is no proxy support, no challenge solving and no fingerprint
  spoofing anywhere in the codebase, and none should be added. A council that
  does not want this traffic has to be able to say no.

Five boroughs are excluded from the spend side for exactly that reason and have
no module here:

| Borough | Block |
| --- | --- |
| Barking and Dagenham | Flat nginx 403 on the whole domain, including direct file URLs. |
| Enfield | Cloudflare managed challenge on every request. |
| Kensington and Chelsea | Cloudflare bot protection, JS challenge. |
| Hammersmith and Fulham | AWS WAF challenge on the whole domain. |
| Greenwich | WAF, 403 on the landing page. |

The same applies to the budget side, and it is the reason there are four
Modern.Gov sources and not thirty-three. Twenty-three boroughs' committee
systems return a WAF page to any client that is not a browser, including
Camden's, Croydon's, Lewisham's and Merton's. Where the council's own CMS
carries the budget book those four are covered through it instead, which is
strictly better anyway: one file per year rather than an agenda to crawl. What
is lost is the committee-only material on those hosts, the formal council tax
resolution, the report appendices and the in-year monitoring reports.

Two other budget sources were looked at and left out:

| Source | Block |
| --- | --- |
| GLA, `www.london.gov.uk` and `apps.london.gov.uk` | Cloudflare 403 to every HTTP client, direct PDF URLs included. The GLA's own numbers are in the MHCLG files instead: its row in RA and RO, and the precepting sheet of council tax Table 10. |
| ESD web services behind LG Inform | 401 without a key, and sustained use is a paid subscription. It is a convenience layer over the MHCLG files this tool already downloads in bulk. |

Their data is public and obtainable by hand from a browser. Getting it that way
is a decision for a person, not something this tool should do quietly.

## Not implemented yet

Thirteen boroughs have no spend module here and are not blocked: Bromley, City
of London, Croydon, Ealing, Hackney, Harrow, Hillingdon, Kingston, Merton,
Southwark, Sutton, Tower Hamlets and Waltham Forest. Nobody has written them
yet, which is one file each in `src/scrooge_indexer/boroughs/`. They are absent
from `scrooge list` and from every total, so a count of fifteen is the tool's
coverage and not London's.

On the budget side the national picture is complete, because MHCLG carries all
33 boroughs. What is missing per borough is the budget book and the
medium-term financial strategy for the 23 boroughs without one here. Ten have
a module; the rest are either behind a WAF on the committee side, or simply
not written yet. The medium-term strategy in particular exists nowhere
central: MHCLG collects one budget year at a time, so a borough's four-year
plan is only ever in its own papers.
