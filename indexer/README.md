# scrooge-indexer

Downloads what London boroughs publish about their money, saves it byte for
byte on disk, and reads the payment files into Postgres. Two kinds of thing
come down:

- **spend**: the transaction-level files published under the transparency code,
  every payment over £500 and over £250 in some boroughs.
- **budget**: planned spend, from each council's own budget book and from the
  MHCLG returns that carry all 33 boroughs in one national file.

The download does no parsing, no column renaming and no re-encoding. The BOM
Richmond puts on its CSVs is still there afterwards, because the stage that
has to reconcile 33 different schemas needs the original bytes to argue with.

That stage is `scrooge load`, and it is where the 33 schemas become one table.
Which published column becomes which typed column is settled in
[docs/payments-schema.md](../docs/payments-schema.md) rather than here; the
loader is that table written as code.

One source is one file in `src/scrooge_indexer/boroughs/`. Adding the 34th
borough, or the next budget publisher, means writing that file and nothing
else.

## Install

```sh
cd indexer
uv sync
```

Python 3.12 or newer. Everything else comes from `uv.lock`.

## Commands

```sh
uv run scrooge list                     # registered sources, and what is on disk
uv run scrooge download camden          # one source, full history
uv run scrooge download --all --since 2026-01
uv run scrooge status                   # counts, byte totals, failures

uv run scrooge list --kind all          # spend and budget together
uv run scrooge download --all --kind budget
uv run scrooge download mhclg           # a slug works whatever --kind says
```

`scrooge download` discovers what a source publishes, then fetches whatever is
not already on disk. Re-running is safe and cheap: a file recorded as complete
in the manifest and still present on disk is skipped without a request.

Three more verbs read those files into Postgres:

```sh
export DATABASE_URL="$(cd ../infra && uv run pg url)"
uv run scrooge db init                  # schema once, then the 33 boroughs
uv run scrooge load camden --since 2019-09 --until 2019-09
uv run scrooge load --all               # every borough on disk
uv run scrooge load-status --problems   # per borough, and what did not load
```

`DATABASE_URL` comes from the environment, or from `.env` and `.env.local` in
the repo root when the shell has none. The Modal tunnel gets a new host and
port on every restart, so there is no host, port or password anywhere in this
repo, and the startup line prints the password as `***`.

One file is one transaction: its old rows are deleted, its `source_files` row
is written, the new rows go in with `COPY`, and the outcome is recorded. A run
killed halfway leaves the file in flight absent rather than half present, so
rerunning the same command is the whole of the recovery procedure.

Flags, defaults, cold start, the bulk-load procedure, recovery and the cron
lines are in [docs/runbook.md](docs/runbook.md).

## Kinds

`list`, `download` and `status` all take `--kind spend` (the default),
`--kind budget` or `--kind all`. The default is spend so that every command and
cron line written before budgets existed keeps doing exactly what it did. A
slug named outright is downloaded whatever `--kind` says, because typing
`mhclg` is already a choice of kind.

The kind decides which tree a source writes to, and nothing else about the
tool changes between them: same period grammar, same `manifest.json`, same
resume rules, same politeness.

## Output layout

```
data/
  raw/
    camden/
      manifest.json
      2026-06__camden-payments.csv
      2026-07__camden-payments.csv
    richmond/
      manifest.json
      2026-07__council_expenditure_july_2026.csv
  budgets/
    mhclg/
      manifest.json
      2026-04_2027-03__RA_2026-27_data_Part_1.ods
      2026-04_2027-03__counciltax-Table_10_2026-27.ods
      2026-04_2029-03__CSP_information_table_2026-27_to_2028-29_fLGFS.xlsx
    richmond-budget/
      manifest.json
      2026-04_2027-03__budget_book_2026_27.pdf
```

The data directory is the repo root `data/` unless `--data-dir` or
`$SCROOGE_DATA_DIR` says otherwise, and it is gitignored.

A filename is the period, two underscores, then the publisher's own filename
with path separators and odd characters stripped. Periods are normalised across
boroughs:

- `2026-07` for a monthly file.
- `2026-07_2026-11` for a file covering several months: first month, one
  underscore, last month, both inclusive. Half years, whole financial years and
  the off-cycle quarters Brent published until 2024 all land here, and so does a
  cumulative export, which is the range it has reached so far. Build one with
  `range_period()`, which writes a one-month span as a month. The separator
  before the publisher's filename is two underscores, so the single one inside a
  period is unambiguous.
- `2026-Q1` for a quarterly file. The quarter number is the publisher's own, so
  Westminster's "Q1 2026-27" is `2026-Q1` and covers April to June 2026. Use
  `fy_quarter_period()` or `calendar_quarter_period()` to build one, and set
  `Source.quarters` so the filters know which convention this borough uses.

There is no bare `2026`: a year said nothing about which twelve months it held,
and a council's year starts in April. A period only ever claims months the file
really covers, which is what lets `--since` and `--until` keep any file that
overlaps the window rather than only the ones that sit inside it.

`YYYY-Qn` is the financial-year quarter for every borough registered today: all
five quarterly publishers set `quarters = "financial"`, so Q1 is April to June
and `2026-Q4` covers January to March 2027. A borough that numbers its quarters
by the calendar year sets `quarters = "calendar"` and gets the same spelling
with January to March as Q1; `period_bounds()` and `in_range()` take that
setting, and `scrooge list` and `scrooge status` do not, because a manifest
records periods and not the borough that chose the convention. Nothing on disk
is affected today.

A budget uses the same grammar and nothing new. A budget for 2026-27 is
`2026-04_2027-03`, Merton's rolling four-year book is `2026-04_2030-03`, and a
multi-year statistical series is the range of its span. There is still no bare
`2026`, which for a financial year would be the wrong twelve months.

`manifest.json` records every fetch: URL, period, relative path, bytes, sha256,
content type, ETag, Last-Modified, timestamp and status. It is rewritten
atomically after every file, so an interrupted run leaves it consistent with
what is actually on disk.

## Boroughs covered

Fifteen, each verified against the live site on 2026-09-19. "History start" is
the earliest period the borough still publishes, not the earliest it ever did.

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

Barnet, Bexley, Brent, Hounslow and Lambeth each publish some files covering
several months at once, and those land as ranges: Bexley's half years,
Hounslow's four whole financial years, Barnet's 2013/14, Brent's off-cycle
quarters and Lambeth's April to December 2017.

## Budget sources

Twelve, each verified against the live site on 2026-09-19. "Files" is what a
full `--kind budget` run discovers today. `mhclg` covers all 33 boroughs at
once and `london-datastore-counciltax` all 33 council tax bands; the other ten
are one borough each.

| slug | what | format | years | mutable |
| --- | --- | --- | --- | --- |
| mhclg | national returns per authority: RA revenue budget, SG grants, Revenue Outturn time series, QRU quarterly update and its RA crosswalk, CER capital estimates, COR capital outturn, capital time series, council tax levels, Core Spending Power, Section 251 education | ods, xlsx, xls, csv | 2007-08 to 2028-29, 233 files | 7: both time series, QRU, Core Spending Power, Section 251 |
| london-datastore-counciltax | council tax charge for all eight bands, per borough | xlsx | 1999-00 to 2026-27 in one workbook | yes |
| richmond-budget | budget book: revenue strategy, tables by committee, capital programme, MTFS | pdf | 2007-08 to 2026-27, 20 files | no |
| wandsworth-budget | council budget: general fund, capital, HRA, schools, MTFS, pension fund | pdf | 2008-09 to 2026-27, 19 files | no |
| camden-budget | budget book and budget code book | pdf | 2015-16 to 2026-27, 17 files | no |
| croydon-budget | budget book, cost-centre level | pdf | 2009-10 to 2026-27, 18 files | no |
| merton-budget | rolling four-year budget book, business plan before 2023 | pdf | 2013-17 to 2026-30, 13 files | no |
| lewisham-budget | corporate budget book, directorate by service | pdf | 2012-13 to 2026-27, 17 files | no |
| hounslow-budget | Budget Setting Meeting pack: report plus appendices A to I | pdf | 2013-14 to 2026-27, 83 files | no |
| lambeth-budget | Budget Council pack: report, directorate budgets, capital programme, MTFS, alternative budgets | pdf | 2011-12 to 2026-27, 143 files | no |
| brent-budget | Budget and Council Tax Setting pack, 27 documents a year | pdf | 2020-21 to 2026-27, 184 files | no |
| haringey-budget | Full Council budget pack with per-directorate appendices | pdf | 2020-21 to 2026-27, 104 files | no |

A few things worth knowing before using any of it.

- MHCLG's RA asset IDs are the middle token of the Revenue Outturn column
  names, so budget joins to outturn per borough per service line with no fuzzy
  matching. `qru-QRU_2026-27_Mapping_Document.ods` is the citable authority for
  where the RA form is coarser than the RO form.
- The `E09` row in the MHCLG files is the London aggregate, not a borough. It
  double counts if you keep it.
- Section 251 keys authorities by DfE LA number, not ONS code, and names them
  DfE style. It needs a lookup table before it joins to anything else here.
- The four Modern.Gov sources find the budget meeting by the label the council
  puts on it. Years the council did not label are not reachable that way, which
  is why Lambeth has 2011 and then a gap to 2019. Guessing which February
  meeting was the budget one would mean fetching every agenda to find out.
- Nothing here is parsed. The budget books are PDFs with real text layers, but
  turning them into numbers is a later stage's problem.

## Adding a borough

Write one file in `src/scrooge_indexer/boroughs/`. The registry imports every
module in that package and picks up `Source` subclasses, so there is no list to
edit and no merge conflict with whoever is adding the borough next door.

```python
"""Bexley: one CSV per month, linked from the transparency page."""

from __future__ import annotations

import httpx

from ..models import RemoteFile
from .base import Source, extract_links, parse_period


class Bexley(Source):
    slug = "bexley"
    name = "Bexley"
    threshold = "£500"
    access = "scrape"
    landing_page = (
        "https://www.bexley.gov.uk/services/council-and-democracy/payments-over-500"
    )

    def discover(self, client, since, until):
        page = client.get(self.landing_page)
        page.raise_for_status()
        files = []
        for url, text in extract_links(page.text, self.landing_page, pattern=r"\.csv$"):
            period = parse_period(url) or parse_period(text)
            if not period:
                continue
            files.append(
                RemoteFile(
                    borough=self.slug,
                    period=period,
                    url=url,
                    filename=url.rsplit("/", 1)[-1],
                    format="csv",
                )
            )
        return files
```

`uv run scrooge list` will show Bexley on the next run.

What the base class gives you:

- `Source.fetch()` already streams to a `.part` file and renames atomically.
  Override it only when the file has to be assembled, as Camden's does from a
  paged API. An override must keep the promise that a file which exists is a
  file which is complete.
- `parse_month_name`, `month_name`, `parse_period`, `month_period`,
  `current_month`, `shift_month`, `months_between` for months as councils
  spell them ("Sept 2019", "SEPTEMBER 2019", "sep_2019" all parse).
- `month_span(text)` for a file that covers several: the first and last month
  named, through "Dec 2024 - Mar 2025", "April to December 2017", "september
  2010 to march 2011" and two-digit years. Pass it to `range_period()` to get
  the period. `short_years=False` refuses two-digit years, which is what Brent
  needs to keep the 24 in "Transparency 24 June - 24 August" out of it.
- `fy_quarter_from_label(text)` for the other half of that problem: the
  financial-year quarter a label or a slug names, from "Q1 2026/27",
  "quarter 1, financial year 2025/26", "2026-27Q1", "q1_23-24" and
  "April - June 2026". It wants both halves of the financial year, so a bare
  "q1-2025" is None and the borough that knows which year that means says so
  itself.
- `fy_label`, `fy_of_month`, `fy_months`, `fy_quarter_of_month`,
  `fy_quarter_months`, `fy_quarter_bounds`, `fy_quarter_of_span`,
  `fy_quarter_period`, `calendar_quarter_period` for the UK financial year,
  which runs April to March with Q1 in April.
- `period_bounds`, `in_range`, `filter_files` for `--since` and `--until`.
- `extract_links(html, base_url, pattern=...)` returns
  `[(absolute_url, link_text)]`. The label is often the only place a period
  appears. `dedupe=False` keeps both anchors when a page points two links at
  one URL and only their labels tell them apart.
- `datapress_resources(client, base_url, package_id)` for the DataPress portals
  (Barnet, Brent and the London Datastore), which speak the CKAN action API.
- `fy_period(start[, end])` and `parse_fy_span(text)` for financial years.
  `parse_fy_span` reads every spelling on a budget page in one go: `2026/27`,
  `2026-2027`, `2026 to 2027`, `2026_27`, the en dash Lewisham uses, and the
  multi-year `2026-2030` Merton publishes. It returns None for a bare `2026`,
  which does not say which financial year it means.

Rules the registry enforces:

- The class needs `slug`, `name`, `threshold`, `access`, `landing_page` and a
  `discover()`. A class without a `slug` is treated as a shared base and not
  registered, which is how Richmond and Wandsworth share `_umbraco.py` without
  it becoming a third borough.
- A module name starting with `_` is skipped.
- A module that fails to import is reported as a warning and the other
  boroughs still run.

## Adding a budget source

Same file, same registry, one extra line: `kind = "budget"`. That is all that
moves it to `data/budgets/` and puts it behind `--kind budget`. Set
`threshold = "n/a"`, since a budget has no publication threshold, and reuse
whichever shared base fits:

- `_budgetbook.BudgetBookSource` for a council page listing one PDF per year.
  Set `link_pattern` (matched against the URL) and `label_pattern` (matched
  against the link text, which is where the year actually is). Six boroughs
  use it.
- `_budgetbook.UmbracoBudgetBookSource` adds a generated-URL fallback for the
  Richmond and Wandsworth media host, used only when the page stops listing
  anything.
- `_moderngov.ModernGovBudgetSource` for a Modern.Gov committee system. Set
  `host` and `committee_id` (from `GET /mgWebService.asmx/GetCommittees`) and
  it finds the budget meeting by its status label, then takes the whole pack.
- `_govuk` for anything on GOV.UK: `collection_documents()` to enumerate years
  and `release()` to resolve a release's files, so no asset hash is ever
  hard-coded.

Set `mutable=True` on a `RemoteFile` the publisher overwrites in place, such as
a cumulative year-to-date export or the month still being added to. Mutable
files are re-checked on every run, with a conditional request when the server
supports one, and replaced when the bytes changed. They are never appended to.

## The loader

`src/scrooge_indexer/loader/` is six modules in the order a file passes
through them.

`mappings.py` is the table from `docs/payments-schema.md` written as tuples,
one entry per borough and layout. The doc's own column name is first in every
tuple; the spellings after it are ones real files use and each carries a
comment naming the borough and the months it came from. A borough with two
layouts gets two entries and the header decides which one fits.

`readers.py` answers the three questions no file states: which encoding, which
delimiter, which line is the header. Encoding is decided by decoding the whole
file as UTF-8 and falling back to cp1252, because a 20 MB file that is clean
for its first megabyte and cp1252 near the end would otherwise fail halfway
through a `COPY`. The header is the first row carrying one of the borough's
date column names, which covers the Bexley and Brent title rows, Lewisham's
row 3 header and the two Hounslow files that open with a leaked SQL query.

`values.py` holds the date, amount and financial-year rules, strictly. A cell
that matches none of the listed forms fails its row rather than being coerced
into something plausible, and day always comes before month.

`rows.py` builds the tuples and counts what it drops. `db.py` writes them.
`runner.py` decides skip, load or fail for one file, and `files.py` walks
`data/raw/`.

Adding a borough to the loader is one entry in `LAYOUTS` plus its row in the
schema doc. Adding a date form means adding it to `values.py` with a comment
saying which file needed it, and saying so in the doc too.

## Not covered

Five boroughs block automated requests and are deliberately left out of the
spend side: Barking and Dagenham, Enfield, Kensington and Chelsea, Hammersmith
and Fulham, and Greenwich. Twenty-three boroughs' Modern.Gov committee systems
and both of Lewisham's and Merton's are behind the same kind of shield, which
is why only four boroughs have a committee budget source. See the politeness
section of the runbook.

## Tests

```sh
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

Every download test runs against `httpx.MockTransport`, and the loader tests
build their fixtures from inline strings in `tmp_path`. Nothing in the default
suite touches the network, opens a real spend file or needs a database, so a
broken council website cannot turn the suite red.

The database tests need a Postgres 17 to create and drop a database on:

```sh
docker run -d --name scrooge-loader-test -e POSTGRES_PASSWORD="$PGPASS" \
    -p 127.0.0.1:55432:5432 postgres:17
export SCROOGE_TEST_DATABASE_URL="postgresql://postgres:$PGPASS@127.0.0.1:55432/postgres"
uv run pytest -q
```

They work in their own `scrooge_loader_tests` database, so they cannot touch a
real load on the same server, and they skip with a message when the variable
is unset or the server is unreachable.
