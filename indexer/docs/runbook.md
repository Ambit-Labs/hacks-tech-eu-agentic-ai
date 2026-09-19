# scrooge-indexer runbook

Operating the `scrooge` CLI: every command and flag, what a run leaves behind,
and how to recover from an interrupted one.

## Cold start

```sh
cd indexer
uv sync
uv run scrooge list
```

`uv sync` is the whole setup. There are no API keys, no secrets and no
binaries to install. `uv run scrooge list` should print the registered boroughs
with zero files on disk.

Nothing in this tool authenticates anywhere. If a borough ever needs a token
(Socrata offers app tokens to raise the anonymous rate limit), that will be a
new environment variable documented here, not a silent addition.

## Environment

| Variable | Default | What it does |
| --- | --- | --- |
| `SCROOGE_DATA_DIR` | the repo root `data/` | Where files and manifests are written. |

The data directory resolves in this order: `--data-dir PATH`, then
`$SCROOGE_DATA_DIR`, then the repo root `data/` found by walking up from the
package until a `.git` directory appears, then `./data` if there is no
checkout. `.env` and `.env.local` in the repo root are loaded if present, and
never override a variable already set in the shell or the cron line.

## Commands

### scrooge list

```
scrooge list [--data-dir PATH]
```

One row per registered borough: slug, council name, access method
(`socrata-api`, `datapress-api`, `url-pattern`, `scrape`), publication
threshold, files already on disk, and the latest period held. The table goes to
stdout, warnings go to stderr.

### scrooge download

```
scrooge download [SLUG ...] [--all] [--since YYYY-MM] [--until YYYY-MM]
                 [--limit N] [--force] [--data-dir PATH] [--delay SECONDS]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `SLUG ...` | none | Boroughs to download, by slug. `scrooge list` prints them. |
| `--all` | off | Every registered borough. |
| `--since YYYY-MM` | the borough's earliest period | Skip anything ending before this month. |
| `--until YYYY-MM` | the current month | Skip anything starting after this month. |
| `--limit N` | no limit | At most N files per borough, the most recent N. |
| `--force` | off | Re-download files already recorded as complete. |
| `--data-dir PATH` | see Environment | Where to write. |
| `--delay SECONDS` | `0.5` | Minimum pause between two requests to the same host. |

A file that straddles a bound is kept. `--since 2026-06` keeps the quarter
that contains June rather than dropping it, and keeps a half year that runs
through June. Both flags are months; there is no range form for them.

Naming no borough and not passing `--all` prints a usage hint and exits 2.

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
scrooge status [--data-dir PATH]
```

Per-borough counts read from the manifests: files, bytes, earliest and latest
period, last run, and failures. The last row is the total. Earliest and latest
are read through the period grammar rather than off the string, so a file
covering September 2010 to March 2011 counts as reaching March 2011 and a
quarter counts as reaching the last month in it.

## Periods

A saved file is named for the period it covers, two underscores, then the
publisher's own filename. Three spellings, and no others:

| Period | Means | Who writes one |
| --- | --- | --- |
| `2026-07` | one calendar month | every monthly borough |
| `2026-07_2026-11` | July to November inclusive | Barnet, Bexley, Brent, Hounslow, Lambeth |
| `2026-Q1` | one quarter | Brent, Haringey, Islington, Lambeth, Westminster |

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

`--force` refetches everything discovered, even files recorded as complete, and
replaces them in place. Use it after a council silently republishes a
corrected month. It is not needed for ordinary catch-up, and the resume hint
printed on Ctrl-C deliberately leaves it out.

Mutable files behave differently by design. Camden's current month, and any
cumulative year-to-date export a borough republishes, carry `mutable=True` and
are re-checked on every run. The check is a conditional request first
(`If-None-Match` and `If-Modified-Since` from the manifest). A 304 costs
nothing and counts as skipped. Socrata ignores conditional requests, so the
file comes back in full and the sha256 decides: identical bytes count as
skipped, changed bytes replace the file. Mutable files are replaced, never
appended to, so a month that gains late postings ends up correct rather than
doubled.

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

Five boroughs are excluded for exactly that reason and have no module here:

| Borough | Block |
| --- | --- |
| Barking and Dagenham | Flat nginx 403 on the whole domain, including direct file URLs. |
| Enfield | Cloudflare managed challenge on every request. |
| Kensington and Chelsea | Cloudflare bot protection, JS challenge. |
| Hammersmith and Fulham | AWS WAF challenge on the whole domain. |
| Greenwich | WAF, 403 on the landing page. |

Their data is public and obtainable by hand from a browser. Getting it that way
is a decision for a person, not something this tool should do quietly.

## Not implemented yet

Thirteen boroughs have no module here and are not blocked: Bromley, City of
London, Croydon, Ealing, Hackney, Harrow, Hillingdon, Kingston, Merton,
Southwark, Sutton, Tower Hamlets and Waltham Forest. Nobody has written them
yet, which is one file each in `src/scrooge_indexer/boroughs/`. They are absent
from `scrooge list` and from every total, so a count of fifteen is the tool's
coverage and not London's.
