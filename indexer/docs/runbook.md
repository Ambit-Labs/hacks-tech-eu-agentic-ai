# scrooge-indexer runbook

Operating the `scrooge` CLI: every command and flag, what a run leaves behind,
and how to recover from an interrupted one.

## Cold start

```sh
cd indexer
uv sync
uv run scrooge list --kind all
```

`uv sync` is the whole setup. There are no API keys, no secrets and no
binaries to install. `uv run scrooge list --kind all` should print 27
registered sources with zero files on disk.

Nothing in this tool authenticates anywhere. If a source ever needs a token
(Socrata offers app tokens to raise the anonymous rate limit), that will be a
new environment variable documented here, not a silent addition. GOV.UK's
content API, the DataPress portals and the Modern.Gov web service are all open,
unauthenticated and unmetered as of 2026-09-19.

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
