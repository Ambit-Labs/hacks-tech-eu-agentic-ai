# spend-indexer

Downloads the spending files London boroughs publish under the transparency
code (every payment over £500, and over £250 in some boroughs) and saves them
byte for byte on disk. No parsing, no column renaming, no re-encoding. The BOM
Richmond puts on its CSVs is still there after the download, because a later
stage that has to reconcile 33 different schemas needs the original bytes to
argue with.

One borough is one file in `src/spend_indexer/boroughs/`. Adding the 34th
borough means writing that file and nothing else.

## Install

```sh
cd indexer
uv sync
```

Python 3.12 or newer. Everything else comes from `uv.lock`.

## Commands

```sh
uv run spend list                     # registered boroughs, and what is on disk
uv run spend download camden          # one borough, full history
uv run spend download --all --since 2026-01
uv run spend status                   # counts, byte totals, failures
```

`spend download` discovers what a borough publishes, then fetches whatever is
not already on disk. Re-running is safe and cheap: a file recorded as complete
in the manifest and still present on disk is skipped without a request.

Flags, defaults, recovery and the cron line are in
[docs/runbook.md](docs/runbook.md).

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
```

The data directory is the repo root `data/` unless `--data-dir` or
`$SPEND_DATA_DIR` says otherwise, and it is gitignored.

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
setting, and `spend list` and `spend status` do not, because a manifest records
periods and not the borough that chose the convention. Nothing on disk is
affected today.

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

## Adding a borough

Write one file in `src/spend_indexer/boroughs/`. The registry imports every
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

`uv run spend list` will show Bexley on the next run.

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
  (Barnet and Brent), which speak the CKAN action API.

Rules the registry enforces:

- The class needs `slug`, `name`, `threshold`, `access`, `landing_page` and a
  `discover()`. A class without a `slug` is treated as a shared base and not
  registered, which is how Richmond and Wandsworth share `_umbraco.py` without
  it becoming a third borough.
- A module name starting with `_` is skipped.
- A module that fails to import is reported as a warning and the other
  boroughs still run.

Set `mutable=True` on a `RemoteFile` the publisher overwrites in place, such as
a cumulative year-to-date export or the month still being added to. Mutable
files are re-checked on every run, with a conditional request when the server
supports one, and replaced when the bytes changed. They are never appended to.

## Not covered

Five boroughs block automated requests and are deliberately left out: Barking
and Dagenham, Enfield, Kensington and Chelsea, Hammersmith and Fulham, and
Greenwich. See the politeness section of the runbook.

## Tests

```sh
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

Every test runs against `httpx.MockTransport`. Nothing in the suite touches the
network, so a broken council website cannot turn the suite red.
