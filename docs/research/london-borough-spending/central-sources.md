# Central and aggregated sources for London borough spending data

Verification date: 2026-09-19. Every endpoint below was hit live from this machine unless the row
says otherwise. "Verified live" means I got a 2xx and inspected the payload, not just a ping.

Scope: cross-borough and national sources only. The 33 individual borough websites are covered by
other agents.

## Headline

There is no single central source that gives you transaction-level spend for all 33 London
boroughs, current to this month. The closest things are:

- **data.gov.uk CKAN** for discovery (which borough publishes what, where), but its stored resource
  URLs for London boroughs are mostly dead 2011-2015 links.
- **AppGov** for a normalised 33-borough transaction archive, but it stops around 2024-05 and the
  spend pages need a login.
- **MHCLG revenue outturn** for complete, clean, current borough-level totals, but aggregate only,
  never transaction level.
- **Contracts Finder / Find a Tender OCDS** for contract awards (not payments), full coverage,
  current, free, no auth.

Anyone who wants transaction rows for all 33 boroughs has to crawl the borough portals. The central
sources give you the index and the reconciliation totals.

---

## 1. data.gov.uk (CKAN) — discovery index, mostly stale payloads

- **URL**: https://www.data.gov.uk/ (now branded "National Data Library"; roadmap at
  https://www.data.gov.uk/roadmap/)
- **API**: CKAN 3 Action API. `https://data.gov.uk/api/action/...` 301-redirects to
  `https://ckan.publishing.service.gov.uk/api/action/...`. Use the canonical host directly:
  `https://ckan.publishing.service.gov.uk/api/3/action/`
- **Auth / limits**: none documented, none hit. No API key.
- **Verified live**: yes.

Working example requests:

```bash
# all 1043 publisher orgs
curl -sL "https://ckan.publishing.service.gov.uk/api/3/action/organization_list"

# every dataset from one borough
curl -sL "https://ckan.publishing.service.gov.uk/api/3/action/package_search?fq=organization:london-borough-of-camden&rows=100"

# free-text across several boroughs
curl -sL "https://ckan.publishing.service.gov.uk/api/3/action/package_search?q=%22over+500%22&fq=organization:(london-borough-of-hounslow+OR+london-borough-of-camden)&rows=50"

# one dataset with resource URLs
curl -sL "https://ckan.publishing.service.gov.uk/api/3/action/package_show?id=council-spending-over-f5001"
```

Gotcha: the JSON result list key is `result.results`, not `result.result`.

### London borough publisher slugs on data.gov.uk (verified from `organization_list`)

`london-borough-of-barnet`, `-brent`, `-bromley`, `-camden`, `-ealing`, `-hackney`,
`-hammersmith-and-fulham`, `-harrow`, `-havering`, `-hounslow`, `-islington`, `-lambeth`,
`-lewisham`, `-merton`, `-redbridge`, `-richmond-upon-thames`, `-sutton`, `-tower-hamlets`,
`-waltham-forest`, `-wandsworth`, plus `royal-borough-of-greenwich`,
`royal-borough-of-kensington-and-chelsea`, `royal-borough-of-kingston-upon-thames`,
`southwark-london-borough-council`, `westminster-city-council`, `city-of-london`,
`greater-london-authority`, `transport-for-london`.

Not present as publishers at all: Barking & Dagenham, Bexley, Croydon, Enfield, Haringey,
Hillingdon, Newham. So data.gov.uk covers at most 26 of 33 boroughs, and several of those have a
single stub dataset.

### What the spend datasets actually contain (all checked individually)

| Borough | Dataset | Resources | Format | Latest | State |
|---|---|---|---|---|---|
| Hounslow | `council-spending-over-f5001` | 139 | CSV, XLSX | May 2026 | Live, current. Resource URLs point at `data.hounslow.gov.uk` landing pages, real files live on `blob.datopian.com` |
| Barnet | `expenditure-reporting-2026-27` and one per year back to 2014-15 | 12/yr (4 so far for 26-27) | CSV | Jul 2026 | Dataset metadata current (modified 2026-09-18) but **resource `url` fields are empty strings** in the CKAN record. Harvest is broken; go to `open.barnet.gov.uk` instead |
| Camden | `camden-council-spend-over-500-gbp` | 3 | link to Socrata | Aug 2026 | Live. Resource points at `https://opendata.camden.gov.uk/api/v3/views/3ixw-qvb8/...` |
| Greenwich | `royal-borough-of-greenwich-spending-over-500` | 45 | CSV, HTML | 2018 | Stale |
| Harrow | 3 datasets, 21 resources total | CSV | 2011 | Dead. URLs are `webarchive.nationalarchives.gov.uk` redirects |
| Islington | `local-authority-spending-over-500-islington` | 7 | XLS | 2011 | Dead (national archives) |
| Kingston | `local-authority-spending-over-500-kingston-upon-thames` | 5 | XLS | 2011 | Stale |
| K&C | `council-spend-above-500`, `council-spend-above-250` | 2 | CSV, ASHX | 2013-14 | Stale |
| Richmond | `local-authority-spend-over-500-richmond-upon-thames` | 1 | CSV | ~2011 | Dead (`http://www.richmond.gov.uk/june_expenses.csv`) |
| TfL | `tfl-spend-over-500` | 42 | CSV | 2022-11 | Stale |
| Bromley, Merton, Redbridge, Sutton, Westminster, GLA | `local-authority-spend(ing)-over-500-*` | **0 resources** | — | — | Empty stubs from the 2010 transparency push |
| Brent, Ealing, Hackney, H&F, Havering, Lambeth, Lewisham, Southwark, Tower Hamlets, Waltham Forest, Wandsworth, City of London | — | — | — | — | No usable spend dataset |

- **Granularity**: transaction level where files exist.
- **License**: `uk-ogl` (OGL) on nearly all the £500 datasets. Camden's is unlabelled in CKAN but
  OGL v3 at source.
- **Verdict**: use as an index and a source of borough portal URLs. Do not rely on the stored
  resource links.

### Bulk dump

No public CKAN dump. `current_package_list_with_resources` returns 403 on the publishing host,
`/data/dumps` and `/dump/` both 404. Paginate `package_search` instead.

---

## 2. London Datastore (data.london.gov.uk) — GLA only, no borough spend

- **URL**: https://data.london.gov.uk/
- **Platform**: DataPress 4.1.0 (https://datapress.com/docs/api)
- **Verified live**: yes.

### Export API (the good one)

```bash
curl -sL "https://data.london.gov.uk/api/v3/datasets/export.json"        # 11.1 MB, 1302 datasets
curl -sL "https://data.london.gov.uk/api/v3/datasets/export.datasets.csv"
curl -sL "https://data.london.gov.uk/api/v3/datasets/export.resources.csv"
curl -sL "https://data.london.gov.uk/api/v3/datasets/export.xlsx"        # sheets: datasets, resources, links
```

No auth needed for the public catalogue; an optional API key (UUID in the `Authorization` header,
`Bearer` prefix accepted) adds your private datasets. Each record carries `id`, `title`,
`description`, `topics`, `tags`, `licence` (url + title), `contact`, `custom` (incl.
`update_frequency`), and a `resources` array with `url`, `filename`, `size`, `hash`, `timestamp`.
Direct file URLs look like
`https://data.london.gov.uk/download/{datasetId}/{resourceId}/{filename}`.

### CKAN compatibility layer (broken search)

`https://data.london.gov.uk/api/action/package_search` responds 200 but **ignores `q`**: every
query returns the same 1302 records sorted by `metadata_modified`. DataPress marks these endpoints
deprecated. Do not use them for search; pull `export.json` and filter locally.

### Coverage reality check

Filtering `export.json` for spend/payment/expenditure keywords gives 88 hits, and 186 datasets sit
under the `transparency` topic. Almost none is borough transaction data:

- The borough entries (`Brent Open Data`, `Hillingdon Open Data`, `Wandsworth Open Data`,
  `Camden Data`, `Waltham Forest - Council Transparency`) have **0 resources**. They are pointers to
  borough portals, last touched 2014-2019.
- `GLA Expenditure over £250` (`vq8w7`), `LLDC Expenditure over £250` (`e6wqp`), `OPDC Expenditure
  over £250` (`vdjdm`): all **0 resources**, last updated 2013.
- Real transaction data present: `LFB electronic Purchasing Card Solution (ePCS) transactions`
  (`2l8yg`, 21 resources, CSV/XLSX, OGL v2) — explicitly marked "*** Legacy data ***", stops 2022.
  `LFB Contracts Register` (`29zqj`, 33 resources).
- `2010-2013 GLA budget detail` (`208n1`): aggregate, ancient.

- **License**: per dataset; OGL v2/v3 typical, but the `licence` field is frequently null.
- **Verdict**: excellent catalogue API, almost no borough spend content. Useful for GLA-family
  bodies (LFB, LLDC, OPDC) and for locating borough portals, nothing else.

### DataPress pattern is reusable

Several borough portals run the same platform, so the same export endpoint works:

```bash
curl -sL "https://open.barnet.gov.uk/api/v3/datasets/export.json"   # 200, 2.5 MB, verified
```

Tested and **not** DataPress: `data.hounslow.gov.uk` (Datopian portal.js, files on
`blob.datopian.com`, 404 on both DataPress and CKAN endpoints), `opendata.camden.gov.uk` (Socrata),
`data.redbridge.gov.uk` (400). Worth having the sibling agents probe
`/api/v3/datasets/export.json` on every borough portal; it is a one-request full catalogue when it
hits.

---

## 3. MHCLG local authority finance statistics — complete, current, aggregate only

Publisher: Ministry of Housing, Communities and Local Government (pages still carry DLUHC/MHCLG
naming). License: OGL v3. No auth, no rate limits. All verified live.

Trick for automation: every GOV.UK statistics page exposes JSON with the attachment URLs at
`https://www.gov.uk/api/content/government/statistics/{slug}` — read
`details.attachments[].url`. Files sit on `https://assets.publishing.service.gov.uk/media/{hash}/{name}`,
so the hash changes each release and you must resolve it from the content API rather than hardcode.

### 3a. Revenue outturn multi-year data set — the single best borough finance file

- Landing page: https://www.gov.uk/government/statistics/local-authority-revenue-expenditure-and-financing-england-revenue-outturn-multi-year-data-set
- File: https://assets.publishing.service.gov.uk/media/6aaa9380f1f8d2a39605f8bb/Revenue_Outturn_time_series_data_v4.csv
- Metadata: https://assets.publishing.service.gov.uk/media/6aaa93a044ec1aa417346b5b/Revenue_Outturn_metadata.ods
- **Verified by download**: 24,290,759 bytes, 3,931 rows, 2,587 columns.
- Columns start `year_ending, ONS_code, LA_LGF_code, LA_name, status, LA_class, LA_subclass`, then
  ~2,580 measure columns (`RG_grantin*`, `RO1..RO6`, `RS`, `RSX`, `TSR` line items).
- **Coverage**: years 201803, 201903, 202003, 202103, 202203, 202303, 202403, 202503, 202603
  (that is 2017-18 through 2025-26 outturn). 34 distinct `E09*` codes present: E09000001 (City of
  London) through E09000033, plus an `E09` London aggregate row. All 33 boroughs, all 9 years.
- **Granularity**: aggregate, one row per authority per year, service-line detail.
- Updated 2026-09-17.

### 3b. Revenue outturn — individual local authority data (per-return workbooks)

- Latest with borough detail: https://www.gov.uk/government/statistics/local-authority-revenue-expenditure-and-financing-england-2024-to-2025-individual-local-authority-data-outturn (updated 2026-06-11)
- Files are `.ods`, one per return form:
  `RS_LA_Data_2024-25_data_by_LA.ods`, `RSX_...`, `RG_...`, `RG_Other_...`,
  `RO1_...` (education) through `RO6_...` (central/protective/other), `TSR_...` (trading accounts).
  Example: https://assets.publishing.service.gov.uk/media/6a2aca48a3674dfd3eb50749/RS_LA_Data_2024-25_data_by_LA.ods
- Boroughs identified by ONS code (E09xxxxxx) and by MHCLG's own `LA_LGF_code`.

### 3c. Revenue account budget (RA) — forward-looking

- Collection: https://www.gov.uk/government/collections/local-authority-revenue-expenditure-and-financing
- Latest: https://www.gov.uk/government/statistics/local-authority-revenue-expenditure-and-financing-england-2026-to-2027-budget (25 June 2026)
- Files: `RA_2026-27_Table_1.ods` … `Table_4.ods` on assets.publishing.service.gov.uk. England-level
  summary tables; per-LA budget data is in the matching "individual local authority data" release.

### 3d. Latest outturn release

- https://www.gov.uk/government/statistics/local-authority-revenue-expenditure-and-financing-england-2025-to-2026-first-release (17 Sept 2026)
- `RO_2025-26_Table_1a_1b.ods` … `Table_6.ods`. England-level summaries, ODS.

### 3e. Capital outturn (COR) and capital estimates (CER)

- Collection: https://www.gov.uk/government/collections/local-authority-capital-expenditure-receipts-and-financing
- 2024-25 final outturn: https://www.gov.uk/government/statistics/local-authority-capital-expenditure-and-receipts-in-england-2024-to-2025-final-outturn (12 Aug 2026), `TAB1.ods` … `TAB6.ods`
- 2024-25 individual LA data: https://www.gov.uk/government/statistics/local-authority-capital-expenditure-and-receipts-in-england-2024-to-2025-individual-local-authority-data
- Forecast/estimates series runs to 2026-27: `CER_2024-25_A1.ods`, `_A2`, `_B`, `_C`.
- **Format caution**: MHCLG moved to `.ods` (OpenDocument). No CSV except the multi-year RO file.

---

## 4. Procurement and contracts

These give contract awards and tender notices, not payment transactions. Useful for supplier-side
joins.

### 4a. Contracts Finder OCDS API — verified live, free, no auth

- Endpoint: `https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search`
- Docs: https://www.contractsfinder.service.gov.uk/apidocumentation/Notices/1/GET-Published-Notice-OCDS-Search
- Example (returned 585 KB, 100 releases, incl. `London Borough of Southwark`):

```bash
curl -s -H "Accept: application/json" \
  "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?publishedFrom=2026-08-01&publishedTo=2026-09-01&size=2"
```

- Parameters: `publishedFrom`, `publishedTo` (ISO 8601), `stages` (planning, tender, award,
  implementation, comma-separated), `limit` (1-100, default 100), `cursor`.
- **No buyer filter.** You must page the whole date window and filter client-side on
  `releases[].buyer.name` or `releases[].parties[].id`. Buyer ids look like `GB-CFS-49530`
  (Southwark), with `parties[].roles: ["buyer"]`.
- Pagination: `links.next` carries a base64 cursor.
- Publisher: Cabinet Office (`GB-GOR`, uid `D2`). OCDS v1.1.
- License: OGL v3 (`license` field in the package).
- Rate limit: exceeding it returns 403; the docs say wait 5 minutes.
- Note: the `size` parameter I passed was ignored in favour of `limit=100`.

### 4b. Find a Tender (FTS) OCDS API — verified live, free, no auth

- Endpoint: `https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages`
- Docs landing: https://www.find-tender.service.gov.uk/Developer/Documentation

```bash
curl -s "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?updatedFrom=2026-09-01T00:00:00&updatedTo=2026-09-02T00:00:00&limit=5"
```

- Verified behaviour: `updatedFrom` is **required** (omitting it returns 400). `updatedTo`, `limit`,
  `stages` all accepted (`stages=award` returned 200). `buyer=...` returns **400** — no buyer
  filter. `ocdsRecordPackages` with the same params returned 400; the record-package endpoint likely
  needs different arguments, unresolved.
- Pagination: `links.next` with a base64 cursor.
- OCDS 1.1 with the EU profile plus amendment-rationale and budget-breakdown extensions.
- Publisher: Cabinet Office. License: OGL v3.
- Buyers appear as free text (`"Sutton, Achieving for Children and Kingston"`), so borough matching
  needs fuzzy logic.

### 4c. London Tenders Portal / ProContract

- `https://www.londontenders.org/` — **dead**, DNS does not resolve (curl exit 6).
- `https://procontract.due-north.com/` — live, redirects to `/Login`. Login-gated, no open API found.
- `https://www.capitalesourcing.com/` — returns 200 but the body is empty to a plain curl
  (JS-rendered). Treat as browser-only. **Uncertain**: I did not confirm what it now hosts.
- Practical effect: borough tender portals are not a machine-readable route. Contracts Finder and
  FTS are the ones to use, since notices above threshold must land there anyway.

### 4d. Contract registers

Transparency Code 2015 requires quarterly publication of contracts over £5,000. These live on
borough sites individually. The only central copy is whatever each borough also pushed to
data.gov.uk, which is patchy. `LFB Contracts Register` (London Datastore `29zqj`, 33 resources) is
the one GLA-family register I confirmed centrally.

---

## 5. Third-party aggregators

### 5a. AppGov (appgov.org) — best normalised cross-borough archive, but stale and login-gated

- **URL**: https://www.appgov.org/ — verified live, footer says "© 2026 AppGov".
- London borough index: https://www.appgov.org/apg/la/lalist3/London%20Borough — **33 records
  found**, all 33 boroughs including City of London.
- What it does (from https://www.appgov.org/apg/default/noteslasp): downloads each council's £500
  spend files, converts them "to a standardised format on a central database" and republishes.
  Loading starts January 2011.
- **Coverage verified per borough**, with date ranges scraped live today:

| Borough | Range | Freq | Borough | Range | Freq |
|---|---|---|---|---|---|
| Barking & Dagenham | 2011/01-2024/05 | Monthly | Kingston upon Thames | 2011/01-2024/05 | Monthly |
| Barnet | 2011/01-2024/03 | Monthly | Lambeth | 2011/01-2024/03 | Quarterly |
| Bexley | 2011/01-2024/04 | Monthly | Lewisham | 2011/01-2024/04 | Monthly |
| Brent | 2011/01-2024/05 | Quarterly | Merton | 2011/01-2024/04 | Monthly |
| Bromley | 2011/01-2024/03 | Monthly | Newham | 2011/01-2024/05 | Monthly |
| Camden | 2011/01-2024/04 | Monthly | Redbridge | 2011/01-2024/03 | Monthly |
| City of London | 2011/01-2023/10 | Monthly | Richmond upon Thames | 2011/01-2024/05 | Monthly |
| Croydon | 2011/01-2024/03 | Monthly | Southwark | 2014/11-2024/05 | Monthly |
| Ealing | 2011/01-2024/05 | Monthly | Sutton | 2011/01-2024/05 | Monthly |
| Enfield | 2014/04-2024/04 | Monthly | Tower Hamlets | 2015/04-2024/03 | Monthly |
| Greenwich | 2011/01-2023/12 | Quarterly | Waltham Forest | 2011/01-2024/03 | Monthly |
| Hackney | 2011/01-2024/04 | Monthly | Wandsworth | 2011/01-2024/04 | Monthly |
| Hammersmith & Fulham | 2011/01-2023/12 | Quarterly | Westminster | 2011/01-2024/03 | Quarterly |
| Haringey | 2011/01-2024/03 | Quarterly | Harrow | 2011/01-2024/03 | Quarterly |
| Havering | 2011/01-2024/03 | Monthly | Hillingdon | 2011/01-2024/04 | Monthly |
| Hounslow | 2011/01-2024/05 | Monthly | Islington | 2011/01-2024/03 | Quarterly |
| Kensington & Chelsea | 2011/01-2024/03 | Quarterly | | | |

- **Staleness**: the site's own "Mths behind" column reads 27-34 for every borough, consistent with
  ingestion stopping around May 2024. Its front page still claims "London Boroughs ... are generally
  up to date", which is no longer true. Roughly 2 years and 4 months behind today.
- **Access**: LA detail pages (e.g. https://www.appgov.org/apg/la/ladetail/19 for Barking &
  Dagenham) are open and carry ONS/GSS codes. The spend views (`/apg/la/laspend/{id}`,
  `/apg/la/laspavg/{id}`, `/apg/la/laspsums/{id}`, `/apg/la/laspsumu/{id}`, `/apg/la/lasumtot/{id}`,
  `/apg/la/launval/{id}`) return 200 but **render the LA-selection page instead of data**, i.e. they
  bounce anonymous users. A login exists at `/apg/default/user/login`.
- **No API, no bulk export found.** The data-sources page names no export mechanism and points at
  info@appgov.org.
- **License**: not stated. Underlying data is OGL but AppGov's own terms are unclear. **Uncertain.**
- **Verdict**: highest-value normalised archive I found for all 33 boroughs, but you need an account
  and it ends mid-2024. Worth an email if historical depth matters.

### 5b. LG Inform Plus / ESD open data aggregator — the most promising untested route

- Schema for council spend: https://schemas.opendata.esd.org.uk/spend — "Expenditure exceeding £500
  (LGA)", the standard councils are told to follow alongside the Transparency Code 2015 and LGA
  guidance. Verified 200.
- **Aggregator**: https://aggregator.opendata.esd.org.uk/details?schemaURI=http%3a%2f%2fschemas.opendata.esd.org.uk%2fSpend — verified 200.
  Its own description: "if multiple local authorities have published data using the same schema
  their data can be returned in the same file(s). The data can be downloaded from this page, or
  programmatically fetched via an API. Generate API links." Output is CSV, paginated at 10,000 rows
  per file/page.
- Schema picker confirms "Expenditure exceeding £500 (LGA)" **has data** (unlike Inventory, Pay
  multiples, Senior employees and Service directory, which are labelled "(no data)").
- **Blocked on auth**: the page shows "Please sign in / Not signed in". I probed
  `/data`, `/csv`, `/links`, `/api/data` with the schemaURI param — all 404. The real API link
  pattern is only emitted by the signed-in "Generate API links" UI, so I could not verify the
  endpoint or the per-borough coverage.
- Dataset registry: https://datasets.opendata.esd.org.uk/ — live, lists datasets logged by councils.
  Its publisher dropdown includes Barnet, Brent, Ealing, Harrow, Hillingdon, Hounslow, Redbridge and
  more London boroughs. Search posts to `/Search/SearchResults` with fields `SchemaIdOrURI`,
  `PublisherURI`, `TextFilter`, `Formats`, `Function`, `Service` plus an anti-forgery token.
- **Keys**: https://home.esd.org.uk/developers → https://developertools.esd.org.uk/ with
  `/data`, `/methods` (80+ web methods) and `/key`. "Anyone signed up can get a key" but "usage is
  capped to a small amount unless you subscribe" (https://lginformplus.org/subscription).
- `https://webservices.esd.org.uk/` verified live: "Inform web services, Version 1.84, Build-Time
  2026-07-14, Environment: live". So the backend is actively maintained.
- `https://lginform.local.gov.uk/` 302-redirects to `signin.esd.org.uk`. Sign-in required.
- **Verdict**: this is the one source that might deliver a single cross-council CSV of £500 spend
  rows on the LGA schema. It needs a free account to even see the API URL pattern, and possibly a
  paid subscription for real volume. **Recommend someone register and confirm.** I could not verify
  the coverage or the recency of its spend holdings.

### 5c. Tussell — commercial, paid

- https://www.tussell.com/ live. Plans at https://www.tussell.com/plans, API at
  https://www.tussell.com/gov/integrations.
- API is a premium add-on: authenticated access to a curated AWS S3 bucket refreshed daily with
  opportunities, awards, frameworks, call-offs, **spend**, buyer and supplier data.
- Three tiers (Starter, Plus, Pro); API bundled only at higher tiers. No public pricing.
- **Paywalled.** Not verified beyond the marketing pages.

### 5d. Spend Network / OpenOpps — commercial, procurement-focused

- https://www.spendnetwork.com/ and https://www.spendnetwork.com/data — live (200).
- https://openopps.com/ — live (200).
- API referenced as `https://api.spendnetwork.cloud/api/v3/notices/records_openopps`; the bare host
  returns 404, so no anonymous probing. Covers ~40 national procurement portals in OCDS shape.
- Spend Network began by compiling council spending spreadsheets, but the current product is tender
  and award data, not £500 payment lines.
- **Paywalled / account required.**

### 5e. OpenSpending (OKFN) — alive but useless here

- https://www.openspending.org/ — 200, but only **85 datasets across 32 countries**. The UK entry is
  `os-gb-gov-cra` (Country and Regional Analyses), fiscal period **2004-2010**.
- No London borough £500 data. Effectively abandoned for this purpose.

### 5f. OpenCouncilData — repurposed, gone

- http://opencouncildata.co.uk/ returns 200 but the site is now "Open Council Data UK - Councillors
  Archive & Communications". It is councillor data, not spend. The old spend work is not there.

### 5g. Oflog data explorer — dead

- `https://local-authority-data.service.gov.uk/` — **DNS does not resolve** (curl exit 6).
- Oflog was abolished by the government on 16 December 2024. Treat as gone. Its metrics were
  aggregate performance indicators anyway, not spend transactions.

### 5h. 360Giving — grants only, partial borough coverage

- GrantNav: https://grantnav.threesixtygiving.org/ (live). Datasets page:
  https://grantnav.threesixtygiving.org/datasets/ (live, lists licence and retrieval date per
  publisher).
- Registry: https://registry.threesixtygiving.org/ (live, 200).
- `https://data.threesixtygiving.org/` now **redirects to https://www.360giving.org/registry-moved/**.
  The Data Quality Dashboard replaced it as the publisher list.
- API: requires sign-up at
  https://www.threesixtygiving.org/data/360giving-datastore/api-sign-up-form/. Datastore rebuilt
  nightly from registry files.
- `https://grantnav.threesixtygiving.org/search?query=London+Borough` returned **503** on my probe.
  Transient or rate-limited; **uncertain**, retry.
- **Scope**: grants made by funders, so it catches borough grant-giving only where a borough
  publishes to the 360Giving standard. Not a substitute for payment data.
- License: per publisher, mostly OGL/CC-BY. Augmented with OGL-licensed ONS/OS/Royal Mail data.

---

## 6. GitHub repos and existing scrapes

| Repo | Last push | Content | Verdict |
|---|---|---|---|
| https://github.com/odileeds/council-spending-data | 2023-05-02 | Cleaned spend files, one dir per body: bradford, calderdale, darlington, gateshead, harrogate, kirklees, leeds, liverpool, **london**, manchester, networkrail, newcastle, northtyneside, salford, sheffield, tfl, wakefield, cabinetoffice. Each dir has `index.json` (column-mapping + file manifest) plus `clean/` and `processed/`. `tidy.pl` does the normalisation | **The `london` dir is GLA only** (`"dir": "gla"`, files pulled from london.gov.uk, starting 2013-P01). No boroughs. Stale by 3 years. The `index.json` column-map is still the best published crosswalk for the messy column names (`Amount` ← `Net amount`/`NetAmount`/`Net Amount £`, `Beneficiary Name` ← `Supplier name`/`SupplierName`/`Benificiary Name`, `Payment Date` ← `Date`/`Date paid`/`DatePaid`, etc.). Steal that. No license file |
| https://github.com/wulfsagedev/civaccount | **2026-09-12** | "Free, independent transparency tool for UK council budgets ... across all 317 English councils - tax bands, spending breakdowns, CEO salaries, suppliers". Next.js + Supabase, has `DATA-CONSTITUTION.md`, `COUNCIL-ROLLOUT-PLAYBOOK.md`, `ROTATION-RUNBOOK.md`, `scripts/`, `DATA-LICENSE` | Actively maintained, 0 stars, license `NOASSERTION`. Worth reading `scripts/` and `COUNCIL-ROLLOUT-PLAYBOOK.md` for its ingestion approach. **Uncertain** whether its spend data is transaction level or budget aggregates; I did not read the source |
| https://github.com/hdurand/uk-public-spending | 2015-05-16 | Scrapes data.gov.uk for £25k central and £500 local spend. GPL-2.0 | Abandoned 11 years. Historical interest only |
| https://github.com/okfn/data-quality-uk-25k-spend | (not fetched in detail) | "Database of all UK Government spending data files (25k and Local Gov)" | Old OKFN project. Repo responds 200 |
| https://github.com/Devon-County-Council/spending | — | Single council | Not London |

No academic dataset, Zenodo deposit, Kaggle set or HuggingFace dataset of normalised UK council
£500 spend turned up. Searched; nothing credible. **If one exists it is not discoverable by obvious
queries.**

---

## 7. Local Government Transparency Code 2015 — what boroughs must publish

- Code: https://www.gov.uk/government/publications/local-government-transparency-code-2015/local-government-transparency-code-2015
- Regulations: https://www.legislation.gov.uk/uksi/2015/480/made
- LGA guidance (updated 2025): https://www.local.gov.uk/sites/default/files/documents/Updated%20guidance%202025%20-%20publishing%20spending%20and%20procurement%20information%20-%20final%20for%20publishing.pdf
- LGA hub: https://www.local.gov.uk/our-support/research-and-data/data-standards-and-transparency/local-government-transparency-code

Obligations relevant here:

- **Every individual item of expenditure over £500**, published **at least quarterly**.
- **All** government procurement card / purchasing card transactions, including those under £500.
- **Every invitation to tender over £5,000**, quarterly.
- **Every contract, commissioned activity, purchase order, framework agreement or other legally
  enforceable agreement over £5,000**, quarterly, published no later than one month after the
  quarter it covers.
- Also: grants to VCSE organisations, land and building assets, social housing assets, organisation
  chart, trade union facility time, parking account income and expenditure, senior officer salaries,
  pay policy statement, counter-fraud data.

Practical consequences for a scraper:

- Quarterly is the legal floor. Most London boroughs publish monthly (see the AppGov frequency
  column above; the quarterly publishers are Brent, Greenwich, Hammersmith & Fulham, Haringey,
  Harrow, Islington, K&C, Lambeth, Westminster).
- The standard column set is the LGA/esd `Spend` schema at https://schemas.opendata.esd.org.uk/spend.
  Camden's Socrata feed follows it almost exactly: `organisation_label`, `organisation_uri`,
  `payment_date`, `payment_month`, `payment_year`, `financial_year`, `beneficiary_name`, `purpose`,
  `organisational_unit`, `amount_gbp`, `irrecoverable_vat_amount_gbp`, `unique_identifier`.
- There is **no enforcement mechanism and no central deposit requirement**, which is exactly why
  data.gov.uk is full of 2011 stubs.

---

## 8. Things I checked that are dead, stale or paywalled

| Thing | Status |
|---|---|
| `https://local-authority-data.service.gov.uk/` (Oflog Data Explorer) | **Dead**, DNS fails. Oflog abolished 16 Dec 2024 |
| `https://www.londontenders.org/` | **Dead**, DNS fails |
| `https://data.threesixtygiving.org/` | Redirects to a "registry moved" notice |
| `http://opencouncildata.co.uk/` | Repurposed to councillor data, no spend |
| `https://www.openspending.org/` | Live but 85 datasets, UK content ends 2010 |
| `data.london.gov.uk/api/action/package_search` | Responds but **ignores the query**; DataPress marks CKAN endpoints deprecated |
| `ckan.publishing.service.gov.uk/api/3/action/current_package_list_with_resources` | 403 |
| `data.gov.uk/data/dumps`, `ckan.publishing.service.gov.uk/dump/` | 404 |
| Barnet's data.gov.uk resources | Metadata current, **`url` fields empty**. Broken harvest |
| `https://www.london.gov.uk/.../our-spending` | **403 to bots** (Cloudflare "Just a moment..."). Needs a real browser. Could not verify GLA's current £250 files |
| `https://www.tussell.com/solutions/data` | 404 (use `/plans` and `/gov/integrations`) |
| `https://api.spendnetwork.cloud/` | 404 at root, account needed |
| `https://procontract.due-north.com/` | Login wall |
| `https://www.capitalesourcing.com/` | 200 but empty to curl, JS-only. Unverified |
| `https://grantnav.threesixtygiving.org/search?...` | 503 on my probe. Retry |
| `aggregator.opendata.esd.org.uk` data endpoints | Sign-in required; my 4 guessed URL patterns all 404 |
| `lginform.local.gov.uk` | 302 to sign-in |
| AppGov `/apg/la/laspend/{id}` etc. | 200 but bounces anonymous users to the selection page |
| Find a Tender `ocdsRecordPackages` | 400 with the same params that work on `ocdsReleasePackages`. Unresolved |

---

## 9. Ranked recommendation for a developer

1. **data.gov.uk CKAN API** — free, no auth, verified. Use for discovery: which of the 26
   London-borough publishers exist, what they call their spend datasets, and where their real
   portal lives. Do not trust the stored resource URLs.
2. **MHCLG Revenue Outturn multi-year CSV** — one 24 MB HTTP GET, all 33 boroughs, 2017-18 to
   2025-26, OGL v3, clean ONS `E09*` codes. Aggregate only, but it is the reconciliation baseline
   any transaction pipeline needs.
3. **AppGov** — the only place all 33 boroughs' transactions already sit in one schema. Costs you a
   login and stops at 2024-05.
4. **LG Inform Plus aggregator** — the best unverified lead. Register, generate API links for
   `schemas.opendata.esd.org.uk/Spend`, confirm coverage. Could collapse the whole problem into one
   paginated CSV feed, or could turn out to hold three councils. **Unknown.**
5. **Contracts Finder + Find a Tender OCDS** — free, current, no auth, but awards not payments. Page
   by date and filter buyers client-side.
6. **DataPress `/api/v3/datasets/export.json`** — a one-request full catalogue wherever a borough
   runs DataPress. Confirmed on `open.barnet.gov.uk` and `data.london.gov.uk`.
7. **Commercial (Tussell, Spend Network)** — if budget exists and you need it maintained.
