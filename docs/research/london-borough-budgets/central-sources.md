# Central and aggregated sources for London borough budget data

Verification date: 2026-09-19. Every URL below was fetched from this machine on that date unless the
row says otherwise. "Verified live" means I got a 2xx and parsed the payload, not just a ping.

Scope: cross-borough and national sources for **planned** spending (revenue budget, capital
estimates, council tax requirement, medium-term financial plans) and for joining budget to outturn.
The 33 borough websites are covered by other agents. Transaction-level £500 spend is covered by
`../london-borough-spending/central-sources.md`; I do not repeat those sources here.

## Headline

Budget data is in much better shape than transaction data. MHCLG publishes a complete, current,
per-authority Revenue Account Budget (RA) return for every English authority including all 33 London
boroughs, and the asset ID codes in the RA file line up with the Revenue Outturn time series column
names. I verified the join numerically: 195 of the 204 RA 2026-27 measure columns reuse an asset ID
that also appears as the middle token of a Revenue Outturn column name. That gives you a real
budget-vs-outturn table per borough per service line, with no fuzzy matching.

What is missing centrally is medium-term financial plans. MHCLG collects one budget year at a time.
MTFS documents live only in each borough's February or March Budget Council report, and the only
cross-borough route to those is the Modern.Gov `mgWebService.asmx` SOAP/GET service, which works but
is bot-shielded on most borough hosts.

Ranked short list for a developer is in section 11.

---

## 1. How to resolve GOV.UK statistics file URLs

Asset hashes change on every release, so hardcoding `assets.publishing.service.gov.uk/media/{hash}/`
breaks. Resolve it instead:

```bash
# every release in a collection, newest first
curl -s "https://www.gov.uk/api/content/government/collections/local-authority-revenue-expenditure-and-financing" \
  | jq -r '.links.documents[] | "\(.public_updated_at[0:10]) \(.base_path)"'

# the file URLs for one release
curl -s "https://www.gov.uk/api/content/government/statistics/local-authority-revenue-expenditure-and-financing-england-2026-to-2027-budget-individual-local-authority-data" \
  | jq -r '.details.attachments[] | "\(.title)\t\(.url)"'
```

No auth, no key, no rate limit I hit. The content API mirrors the HTML page, so `details.attachments[].url`
is the authoritative current file location. Collection slugs that matter:

| Collection | Slug |
|---|---|
| Revenue expenditure and financing (RA, RO, RS, RSX, SG) | `local-authority-revenue-expenditure-and-financing` |
| Capital expenditure, receipts and financing (CER, COR) | `local-authority-capital-expenditure-receipts-and-financing` |
| Council Tax statistics (CTR, collection rates) | `council-tax-statistics` |
| Final settlement 2026-27 to 2028-29 | `final-local-government-finance-settlement-england-2026-2027-to-2028-2029` |
| Section 251 (education budget and outturn) | `section-251-materials` |

License on all MHCLG statistics: OGL v3.

---

## 2. MHCLG Revenue Account Budget (RA) per authority

This is the core budget source. **Verified live, downloaded, parsed.**

- Latest release: https://www.gov.uk/government/statistics/local-authority-revenue-expenditure-and-financing-england-2026-to-2027-budget-individual-local-authority-data (published 11 June 2026)
- Files (2026-27):
  - `RA_2026-27_data_Part_1.ods` (509 KB) https://assets.publishing.service.gov.uk/media/6a2962166d178a6fb7e32089/RA_2026-27_data_Part_1.ods
  - `RA_2026-27_data_Part_2.ods` (233 KB) https://assets.publishing.service.gov.uk/media/6a281185e371d9d2c0052b0a/RA_2026-27_data_Part_2.ods
  - `SG_2026-27.ods` (118 KB, specific and special revenue grants) https://assets.publishing.service.gov.uk/media/6a28119b6d178a6fb7e31f7f/SG_2026-27.ods
- England summary tables sit in a separate release, `...-2026-to-2027-budget`, as `RA_2026-27_Table_1.ods` through `Table_4.ods`. You do not need those if you have the per-LA files.

### Structure of the per-LA workbook

Sheet `RA_LA_Data_2026-27`. Four metadata rows above the header make this awkward for a naive
reader, and they are the useful part:

| Row | Content |
|---|---|
| 7 (0-indexed 6) | **Asset ID code** per column: `eduerl`, `eduprm`, `servicetot`, `ctrtot` … |
| 8 | Section heading, merged across the group: `Education Services`, `Adult Social Care` … |
| 9 | **Line number** on the RA collection form: `110`, `120`, `799`, `990` … |
| 10 | Human-readable column title |
| 11+ | One row per authority |

Identity columns are `E-code`, `ONS Code`, `Local authority`, `Class`, `Subclass`, `Notes`.

Boroughs are `Class = LB`, `Subclass = London`, ONS codes `E09000001` to `E09000033`. All 33 are
present, including City of London (`E5010` / `E09000001`). A 34th `LB` row carries ONS code `E09`
and the name `London Boroughs`, which is the London aggregate, so filter it out or you double count.
The GLA is a separate row, `E5100` / `E12000007`, appearing under both `Class = O` and `Class = GLA`.
The three statutory waste authorities (East, North and West London Waste) appear as `E50000001`,
`E50000002`, `E50000003`.

MHCLG's own `E-code` (`E5011` for Camden) is a stable LGF identifier and is more reliable than name
matching. Keep both it and the ONS code.

### Service lines in Part 1 (210 columns)

Section groups, in form order: Education Services, Highways and Transport, Children's Social Care,
Adult Social Care, Public Health, Housing Services (general fund only), Cultural and Related
Services, Environmental and Regulatory Services, Planning and Development Services, Police, Fire,
Central Services, Other, Total Service Expenditure (line 799, `servicetot`), Housing benefits,
Precepts and Levies, Trading Accounts and Adjustments, Net Current Expenditure (line 849,
`netcurrtot`), Non-current Expenditure and Receipts, Revenue Expenditure (line 900, `revenuetot`),
Revenue Expenditure Financing ending at **line 990 `ctrtot`, COUNCIL TAX REQUIREMENT**.

Per-section totals: `edutot`, `transtot`, `csctot`, `asctot`, `phtot`, `housgfcftot`, `cultot`,
`envtot`, `plantot`, `poltot`, `frstot`, `centot`, `othtot`.

Financing detail includes `grantrsg` (Revenue Support Grant, line 951), `retainnndr` (retained
business rates, line 970), `colfunct` (collection fund surplus/deficit, line 980) and the
appropriations to and from reserves (lines 911 to 916).

### Part 2 (95 columns)

Reserves at 1 April and 31 March, sub-categories of earmarked reserves, capital items, Local Council
Tax Support, the whole **Housing Revenue Account** income and expenditure block, HRA reserves, and
investment properties broken down by whether they sit inside or outside the authority boundary.
The HRA block matters for London: most boroughs still hold stock.

### Format history and file naming

| Years | Format | File pattern |
|---|---|---|
| 2010-11 to 2015-16 | `.xls` | `RA_<yy-yy>_data_by_LA...xls` |
| ~2016-17 to 2020-21 | `.xlsx` | `RA_<yy-yy>_data_by_LA.xlsx` |
| 2021-22, 2022-23 | `.ods`, single file | `RA_2021-22_data_by_LA.ods`, `RA_2022-23_data.ods` |
| 2023-24 onwards | `.ods`, split | `RA_<yy-yy>_data_Part_1.ods` and `_Part_2.ods` |

There is **no CSV** and, unlike outturn, **no multi-year budget time series**. I checked all 85
documents in the revenue collection: the only multi-year file is the Revenue Outturn one. To build a
budget time series you download one release per year and stack them. The RA release exists for every
year back to 2010-11, so nine to sixteen files depending how far back you go.

Parsing ODS with no dependencies is straightforward: unzip, read `content.xml`, walk
`table:table-row` and `table:table-cell`, respect `table:number-columns-repeated` and
`office:value`. Watch for repeat counts in the thousands used for trailing empty cells.

---

## 3. Budget vs outturn: the RA to RO join

This is the part worth the most to a developer, and it is better than I expected.

The Revenue Outturn multi-year CSV (already documented in the spending survey) has 2,475 columns
named `<FORM>_<assetid>_<measure>`, for example `RO1_eduerl_net_cur_exp`, `RS_ctrtot_net_exp`,
`RSX_edu_tot_exp`. The RA budget columns use **the same asset IDs**.

- File: https://assets.publishing.service.gov.uk/media/6aaa9380f1f8d2a39605f8bb/Revenue_Outturn_time_series_data_v4.csv (24,290,759 bytes, updated 17 Sept 2026)
- Years present: `201803` through `202603`, that is outturn 2017-18 to 2025-26, nine years.
- 34 distinct `E09*` values, being the 33 boroughs plus the `E09` London aggregate row.

**Measured overlap:** of the 204 measure columns in `RA_2026-27_data_Part_1.ods`, 195 reuse an asset
ID that appears as the middle token of a Revenue Outturn column. The nine that do not are recent RA
splits with no outturn equivalent yet: `ascact`, `ascdlv`, `phsmdrgalctrt`, `phsmprdrgalc`,
`culhrtxarc`, `culsprlscom`, `culpksopn`, `othtot`, `netoffexpcap`.

Join rules I verified:

- **Detail service lines**: RA asset ID maps directly. `eduerl` → `RO1_eduerl_net_cur_exp`.
- **Service totals**: strip the `tot` suffix, with three exceptions. `edutot` → `RS_edu_net_exp`,
  `asctot` → `RS_asc_net_exp`, `csctot` → `RS_csc_net_exp`, but `phtot` → `RS_phs_net_exp`,
  `housgfcftot` → `RS_hous_net_exp`, and `servicetot` → `RS_totsx_net_exp`.
- **Financing lines**: direct. `ctrtot` → `RS_ctrtot_net_exp`, `revenuetot` → `RS_revenuetot_net_exp`,
  `netcurrtot` → `RS_netcurrtot_net_exp`, `grantrsg` → `RS_grantrsg_net_exp`.

Worked example, Camden (E09000007), 2024-25, £ thousand:

| Measure | RA budget | RO outturn | Column used |
|---|---|---|---|
| Council tax requirement | 141,132 | 141,131 | `ctrtot` / `RS_ctrtot_net_exp` |
| Total service expenditure | 641,564 | 688,466 | `servicetot` / `RS_totsx_net_exp` |
| Education, total | 241,074 | 278,748 | `edutot` / `RS_edu_net_exp` |
| Adult social care, total | 136,450 | 128,204 | `asctot` / `RS_asc_net_exp` |
| Children's social care, total | 80,997 | 92,206 | `csctot` / `RS_csc_net_exp` |
| Early years education | 19,718 | 27,491 | `eduerl` / `RO1_eduerl_net_cur_exp` |
| Net current expenditure | 760,081 | 831,129 | `netcurrtot` / `RS_netcurrtot_net_exp` |
| Revenue expenditure | 601,588 | 663,527 | `revenuetot` / `RS_revenuetot_net_exp` |

The council tax requirement matching to within £1k is the sanity check that the join is real: CTR is
fixed at budget setting, so budget and outturn should agree. Everything else is genuine variance.

Trap: `RS_servicetot_nonias_net_exp` exists but is **only populated to 2019-20**. Use `RS_totsx_net_exp`
for 2020-21 onwards. I confirmed this against Camden's whole 2017-18 to 2025-26 series.

RA gives one number per line, the budgeted net figure. RO gives eight measures per line (`empl`,
`run_exp`, `tot_exp`, `sfc`, `oth_inc`, `tot_inc`, `net_cur_exp`, `mss`). Compare RA against
`net_cur_exp` and ignore the rest, or you are comparing a net budget to a gross outturn.

### The official crosswalk document

MHCLG publishes a line-level mapping between the RA form, the RO forms and the quarterly return.
**This is the citable authority for the form structure.** Verified live.

- Publication: https://www.gov.uk/government/publications/quarterly-revenue-outturn (updated 1 July 2026)
- Mapping file: https://assets.publishing.service.gov.uk/media/6a44f8936c5c6d8122b815df/QRU_2026-27_Mapping_Document.ods (17 KB)

Sheet `Summary`, 78 mapping rows, columns `QRULine`, `Classification`, `ROForm`, `ROLine`, `RALine`,
`RA service Category`, `Comments`. Sample rows:

| QRULine | Classification | ROForm | ROLine | RALine | RA service Category | Comments |
|---|---|---|---|---|---|---|
| 1 | General Public Services | RO5 | 111 | 500 | Archives | Same |
| 2 | General Public Services | RO6 | 421 | 628 | Local tax collection: other | RA Line 628 contains RO6 Lines 421, 422, 426 & 428 |
| 2 | General Public Services | RO6 | 430 | 675 | Central services to the public: other | RA Line 675 contains RO6 Lines 430, 441, 442, 460, 465, 470 & 489 |

The `Comments` column tells you exactly where the RA form is coarser than the RO form. That is the
detail you need to avoid a wrong join on central services and local tax collection.

### Form guidance notes

- RA form and guidance: https://www.gov.uk/government/publications/general-fund-revenue-account-budget (updated 13 Feb 2026). Includes `GF_Revenue_Account_Budget_2026-27_data_preparation_template.xlsx`, "Changes and key points to note", specific guidance notes, general guidance notes.
- RO forms and guidance: https://www.gov.uk/government/publications/general-fund-revenue-account-outturn (updated 24 Apr 2026). Includes `RO_2025-26_v1.3.xlsx`, the blank RO suite, plus the supplementary guidance on recharging and management and support services, which is the document that explains why service lines move between years.

---

## 4. Quarterly Revenue Update: in-year budget vs actual

Newer than the RO annual cycle and the strongest source for tracking a borough's budget during the
year. **Verified live, downloaded, parsed.** Easy to miss because it is filed as a "live table", not
as a statistics release.

- Hub page: https://www.gov.uk/government/statistical-data-sets/live-tables-on-local-government-finance (updated 3 Sept 2026)
- File: https://assets.publishing.service.gov.uk/media/6a97ede03b22fb169dc1905c/QRU1_2026_27.ods (5.8 MB)

Sheets that matter:

| Sheet | Content |
|---|---|
| `QRU1_LA_Data_2026-27_forecast` | Full-year forecast per authority, per QRU category, 36 E09 rows |
| `QRU_LA_Data_Q1_2026-27` | Q1 actuals per authority on the same categories |
| `Timeseries` | Every authority, every quarter, **back to 2017-18 Q1**, with `yyyy_yy` and `Qq` columns |
| `Categories_mapping` | The same QRULine / ROForm / ROLine / RALine crosswalk as section 3, plus an `Identifier` column (`genpub1`, `genpub2` …) |

The QRU categories are COFOG-style (General Public Services, Defence, Public Order and Safety,
Economic Affairs, and so on), not SeRCOP service lines, which is why the mapping sheet exists.
Identity columns are `LA_LGF_Code`, `LACode` (ONS), `LA_Name`, `LA_Region`, `LA_Class`.

MHCLG also publishes the RA budget pre-divided into QRU categories, one quarter's worth per cell,
so the comparison is like for like:
https://assets.publishing.service.gov.uk/media/6a44f958732d8e7ce5f53a46/QRU_2026-27_RA_aggregated_to_QRU.ods
(sheet `RA_Data_for_QRU_2026-27`). The header rows name the contributing RA lines, for example
QRU Line 2 is "RA Line(s) 610, 623, 625, 628, 675".

If you want a quarterly budget-vs-actual chart per borough, this file alone gets you there.

---

## 5. Capital: estimates (CER) and outturn (COR)

### 5a. Capital estimates return, forward looking

- Release: https://www.gov.uk/government/statistics/local-authority-capital-expenditure-and-financing-in-england-2026-to-2027-individual-local-authority-data-forecast (18 June 2026)
- Files, all `.ods`:
  - `CER_2026-27_A1.ods` (1.2 MB), capital expenditure and receipts by service and category: https://assets.publishing.service.gov.uk/media/6a32911f0bea238415c9a170/CER_2026-27_A1.ods
  - `CER_2026-27_A2.ods`, memorandum items and other transactions
  - `CER_2026-27_B.ods`, financing
  - `CER_2026-27_C.ods`, prudential system information

**Verified live and parsed.** A1 is an interactive workbook, which trips people up. The sheets
`la_breakdown` and `service_breakdown` are drop-down views that render only the selected authority
or service, so scraping those gives you one row. The machine-readable sheets are:

| Sheet | Shape |
|---|---|
| `fixed_assets` | One row per LA, columns are `<Service>: <Category>` pairs, 36 E09 rows |
| `receipts` | One row per LA, same shape, disposals and repayments |
| `service_breakdown` | One row per LA for the currently selected service (defaults to All Services Total) |
| `la_list` | The service code vocabulary: `eduerlprm`, `eduscn`, `eduspc`, `edupstoth`, `edutot`, `transrds`, `transprk`, `transpblbus`, `transpblrail` … |

Identity columns are `LGF Code`, `ONS Code`, `LA Name`, `Class`, `Subclass`. Categories are
acquisition of land and existing buildings, new construction/conversion/renovation, vehicles, plant
and furniture and equipment, intangible fixed assets, total expenditure on fixed assets, grants.
Source note on the file says 414 of 415 eligible authorities returned a valid CER for 2026-27.

The service codes in `la_list` use the same naming family as the RA asset IDs but are **coarser**
(`eduerlprm` merges early years and primary, which RA splits into `eduerl` and `eduprm`). Capital and
revenue do not join at the detail line. They join at the service group.

### 5b. Capital outturn return

- 2024-25 individual LA data: https://www.gov.uk/government/statistics/local-authority-capital-expenditure-and-receipts-in-england-2024-to-2025-individual-local-authority-data (5 June 2026)
- Ten `.ods` files: `COR_A1` (total capital expenditure), `COR_A2` (social housing detail), `COR_A3`
  (acquisitions, disposals, impairment), `COR_B1` (financing), `COR_B2` (central government grants),
  `COR_C` (prudential), `COR_D` (accumulated receipts and major repairs reserve), `COR_E` (trading
  companies and subsidiaries), `COR_F` (asset values), `COR_HRA` (HRA supplementary).

### 5c. Capital time series, the CSV you actually want

**The only capital file in CSV.** Verified live.

- Release: https://www.gov.uk/government/statistics/local-authority-capital-expenditure-and-receipts-in-england-final-outturn-time-series (25 March 2026)
- File: https://assets.publishing.service.gov.uk/media/69c2a55b13f1436476e4436c/Capital_time_series_data_wide_24_03_26.csv
- Metadata: https://assets.publishing.service.gov.uk/media/695e72a78ab0677c14afdfda/Metadata_COR_time_series.ods
- Coverage: 2018-19 to 2024-25 final outturn, wide format, one row per authority per year.

Capital forecast is only published one to two years ahead and only in ODS, so there is no capital
equivalent of a multi-year budget series. Stack the CER releases if you need one.

### 5d. Capital Payments and Receipts, quarterly

- File: https://assets.publishing.service.gov.uk/media/6a85a77db0504df9f2c897df/CPR1_2026-27.ods (1.9 MB), from the live tables hub.
- **Verified live and parsed.** Sheet `2026-27_Q1_CPR1`, 36 E09 rows, identity columns `Data source`,
  `LGF code`, `ONS code`, `Local authority name`, `Class code`, `Subclass code`, then
  `Expenditure: <category>` and receipts columns.
- The same workbook carries back-series sheets: `2025-26_Q1-Q4_CPR4`, `2024-25_Q1-Q4_COR`,
  `2023-24_Q1-Q4_COR`, `2022-23_Q1-Q4_COR` and all the intermediate quarters, plus
  `Capital_Financing_Requirement`. One download covers 2022-23 to date.
- Form and guidance: https://www.gov.uk/government/publications/capital-payments-and-receipts-return

---

## 6. Council tax: requirement, band D, and the bands table

### 6a. MHCLG Council Tax levels set by local authorities

**The authoritative per-borough council tax requirement source.** Verified live, downloaded, parsed.

- Release: https://www.gov.uk/government/statistics/council-tax-levels-set-by-local-authorities-in-england-2026-to-2027 (25 March 2026)
- Per-authority file: https://assets.publishing.service.gov.uk/media/6a02eeeccd2e0e8b5b20b449/Table_10_2026-27.ods (279 KB)
- Summary tables 1 to 9: https://assets.publishing.service.gov.uk/media/69de1fa63e81003ae0422508/Tables_1-9_2026-27.ods (99 KB)
- Annual series exists back to 2011-12 under the same slug pattern, ending `-<yyyy>-to-<yyyy>`.

`Table_10` sheets:

| Sheet | Content |
|---|---|
| `Data_Billing` | CTR1 return, one row per billing authority, **101 columns**, current year and previous year side by side. Exactly **33 E09 rows**, all boroughs, no aggregate mixed in the E09 range |
| `Data_Precepting` | CTR2/CTR3 returns. The GLA is here as `E12000007`, band D £490.38 for 2025-26 and £510.51 for 2026-27, split into `E5101` "Whole of GLA's area" (£176.38) and `E5102` "London Boroughs area" (£334.13) |
| `Billing_Authorities`, `Precepting_Authorities`, `GLA`, `CA_with_Police` | Blank CTR form layouts, useful for reading the line numbers |

Column set on `Data_Billing`, paired current/previous for each: council tax requirement including
special expenses and the adult social care precept (line 1), aggregate special expenses (1a), parish
precepts (2), CTR excluding local precepts (3), levies and special levies (3a), tax base after the
council tax reduction scheme (4), estimated collection rate (5), tax base adjustment for Class O
exemptions (6), council tax base for tax-setting purposes (7), and onward.

Aggregate class rows `ILB` (Inner London Boroughs) and `OLB` (Outer London Boroughs) are in the same
sheet with non-ONS codes, so filtering on `ONS Code LIKE 'E09%'` cleanly excludes them.

`Tables_1-9`, sheet `Table_8a`, is the quick answer if all you want is the headline: average band D
for London boroughs plus metropolitan districts and unitaries, with the year-on-year percent change.
Every London borough shows 4.99 percent for 2026-27, which is the referendum threshold.

### 6b. CTR form structure, for citation

- https://www.gov.uk/government/publications/council-tax-requirement-return (updated 13 Feb 2026).
  Carries `CTR1_Form_2026-27_v1.1.xlsx`, `CTR2_Form_2026-27_v1.1.xlsx`, validation checks, bulk
  upload guidance, and separate guidance notes for CTR1, CTR2, CTR3 and CTR4.
- Tax base: https://www.gov.uk/government/publications/council-tax-base-calculation (CTB form).

### 6c. London Datastore, council tax by band and borough

A genuinely useful London-specific file, and the only place I found all eight bands per borough in
one download. **Verified live, downloaded, parsed.**

- Dataset id `expnl`, "Council Tax Charges - Bands, Borough":
  https://data.london.gov.uk/dataset/council-tax-charges-bands-borough
- File: https://data.london.gov.uk/download/expnl/59cc7c37-da8f-4158-bc47-491c3d167b05/council-tax-bands-borough.xlsx (141 KB)
- One sheet per financial year, `1999-00` through **`2026-27`**, plus a `Metadata` sheet. Each sheet
  is `Code` (E09 ONS), `Local authority`, `Band A` … `Band H`. 33 boroughs plus totals.
- Resource timestamp 2026-04-13, so it is current. License OGL v2. No auth.

Related on the same portal, both stale but worth knowing: `em8zm` "Average Band D Council Tax,
Region" (last file 2023-03-23) and `e64wz` "Dwellings Numbers on Valuation List, Borough" (2018).

---

## 7. Local Government Finance Settlement, core spending power

**Verified live, downloaded, parsed.** Both are `.xlsx` with clean per-LA rows.

- Core spending power table, final settlement 2026-27 to 2028-29:
  https://www.gov.uk/government/publications/core-spending-power-table-final-local-government-finance-settlement-2026-27-to-2028-29 (9 Feb 2026)
  File: https://assets.publishing.service.gov.uk/media/6a2a8b741f6fa5c3377e5d7f/CSP_information_table_2026-27_to_2028-29_fLGFS.xlsx (1.1 MB)
  Sheets: `Core Spending Power` (drop-down view, avoid), then flat per-LA sheets `2024-25`, `2025-26`,
  `2026-27`, `2027-28`, `2028-29`, plus `input_data`. **This settlement is multi-year**, which the
  RA return is not, so it is your only central forward view beyond the budget year.
  Header row has machine names `ecode`, `ons_code`, `authority`, `region`, `class`, `ruc_21`,
  `csp_2024`, `pop_2024`. 35 E09 rows. Boroughs carry `class = LB`.
- Key information table for local authorities, final settlement 2026-27:
  https://www.gov.uk/government/publications/key-information-table-for-local-authorities-final-local-government-finance-settlement-2026-to-2027
  File: https://assets.publishing.service.gov.uk/media/69bd1799bbf7c14d0b834dda/260317_final_hc_KI_table_LGFS_2627.xlsx (103 KB)
  Sheet `KI 2026-27`: `ecode`, `ons_code`, `class` (here `ILB`/`OLB`), `enhanced`, `authority`,
  `tier_split_enhanced`, `ffa_enhanced_2026` (Fair Funding Allocation), `rsg_enhanced_2026` (Revenue
  Support Grant), `bfl_enhanced_2026` (Baseline Funding Level). 35 E09 rows.
- Explanatory notes accompany both, and the provisional settlement for the same period is at
  `.../provisional-local-government-finance-settlement-2026-2027-to-2028-29`. Comparing provisional
  to final per borough is a two-file diff.

---

## 8. Section 251: education and children's services budget per authority

Overlooked and directly relevant, since education is the largest single service line in most borough
budgets. **Verified live, downloaded, parsed.**

- Collection: https://www.gov.uk/government/collections/section-251-materials
- 2025-26: https://www.gov.uk/government/publications/section-251-2025-to-2026 (23 June 2026)
- 2026-27: https://www.gov.uk/government/publications/section-251-2026-to-2027 (26 March 2026)

The file to take is the multi-year one, 12.7 MB, long format rather than wide:

https://assets.publishing.service.gov.uk/media/68d5564c275fc9339a248d02/Local_authority_planned_expenditure_on_education_and_children_s_services_2015_to_2016_financial_year_to_2025_to_2026_financial_year.ods

Sheet `Planned_expenditure`, columns `Financial year` (`1516`, `1617` …), `Table name`
(`SchoolsBudget` and others), `Local authority number`, `Local authority name`, `Order line`,
`Description`, `Section 251 line` (`1.0.1` …), then the phase columns `Early years`, `Primaries`,
`Secondaries` and so on.

**Join caveat, and it is real.** Section 251 uses **DfE LA numbers**, not ONS codes. City of London
is 201, Camden 202, Greenwich 203, Hackney 204. You need a DfE-to-ONS lookup to join this to
anything else. The names are also DfE style, "Camden London Borough Council", not "Camden".

Companion files in the same release: `Local_authority_planned_expenditure_on_early_years_budgets_2025_to_2026.ods`,
`Section251_budget_per_capita_net_2025_to_2026.xls`, `Section251_budget_per_capita_gross_2025_to_2026.xls`,
`Section251_local_authority_benchmarking_tables_between_2024_to_2025_and_2025_to_2026.xls`, and
`High_needs_places_and_funding_by_maintained_school_2025_to_2026.ods`.

The DfE Explore Education Statistics API (`https://api.education.gov.uk/statistics/v1/publications`)
is live and open, no key, but **it exposes 25 publications and none of them is finance**. Section 251
is files on GOV.UK only.

---

## 9. LG Inform and LG Inform Plus

Two different things behind one brand, and the distinction decides whether you can use it.

### LG Inform, the LGA's free public site

- https://lginform.local.gov.uk/, **verified live**. The bare root 302s to
  `/home/check?returnUrl=...`, which is a cookie handshake, not a login wall. With a cookie jar you
  get a 200 and a 497 KB page anonymously.
- Report pages render real data with no account. Verified:
  `https://lginform.local.gov.uk/reports/lgastandard?mod-metric=4746&mod-area=E09000007&mod-group=AllLaInCountry_England&mod-type=namedComparisonGroup`
  returned a Camden page with the metric title and values. Areas are addressed by ONS code, so
  `mod-area=E09000007` works directly.
- **No anonymous export.** I searched the rendered HTML for csv/xlsx/json/download links and found
  none. The metric search page is JavaScript-driven with no discoverable JSON endpoint.

### The ESD web services API underneath

- Root: https://webservices.esd.org.uk/, **verified live**, reports "Version: 1.84, Build-Time
  2026-07-14, Environment: live". Actively maintained.
- Endpoint index: https://webservices.esd.org.uk/explain, 127 endpoints, including `/data`,
  `/data/regression`, `/metricTypes`, `/metricTypes/search`, `/metricTypes/{identifier}`,
  `/datasets`, `/areas/{identifier}`, `/periods/{identifier}`, `/valueTypes`.
- **Every data endpoint returns 401 without a key.** I confirmed on `/metricTypes`,
  `/metricTypes/search?query=council tax requirement` and `/data`. Body is
  `{"errors":[{"message":"Not authorized...","errorCode":10}]}`.
- Request shape, from ESD's own developer tools:
  `https://webservices.esd.org.uk/data?metricType=1&area=E92000001&period=latest&headerCellType=label&ApplicationKey=<key>&Signature=<sig>`
  Minimum parameters are `area`, `metricType`, `period`. `valueType` accepts `raw`, `rank`, `band`.
- **Is the key free?** Not cleanly. https://help.esd.org.uk/api/access-and-use/reasons-why-api-access-may-be-denied
  (verified) describes a monthly data allowance per subscribed organisation plus a "one-off allowance
  for trials before subscription", and a daily cap, with the error "User has exceeded allowed usage
  limits". So: trial allowance free, sustained use paid. **I could not verify what budget or council
  tax metrics exist, because metric search is behind the same 401.** Marked uncertain.
- Developer tools: https://developertools.esd.org.uk/methods and `/data`, both live.
- Sign-up: https://home.esd.org.uk/developers (the old `api.esd.org.uk` redirects here).

**My view:** for budget data specifically, LG Inform is a convenience layer over MHCLG files you can
already download for free in bulk. Registering for a key is worth it only if you want LGA's derived
per-head and per-dwelling metrics without computing them yourself. Do not build a pipeline on it.

---

## 10. Modern.Gov: reaching Budget Council reports across boroughs

Yes, there is a common API, and it returns exactly what you want. The catch is bot shielding.

### The service

Modern.Gov installs expose `/mgWebService.asmx`, an ASP.NET web service that also answers plain
HTTP GET. 21 operations, the useful ones being `GetCommittees`, `GetMeetings`, `GetMeeting`,
`GetAllMeetingsByDate`, `GetAttachment`, `GetAttachmentByPath`.

### Worked example, Lambeth Budget Council, verified end to end today

```bash
# 1. list committees (99 at Lambeth); "Council" is committee 142
curl -s "https://moderngov.lambeth.gov.uk/mgWebService.asmx/GetCommittees?lDays=0"

# 2. list that committee's meetings (133 of them, 2006 to 2026)
curl -s "https://moderngov.lambeth.gov.uk/mgWebService.asmx/GetMeetings?lCommitteeId=142&sFromDate=2026-01-01&sToDate=2026-04-30"

# 3. pull the 4 March 2026 Budget Council with all agenda items and attachments
curl -s "https://moderngov.lambeth.gov.uk/mgWebService.asmx/GetMeeting?lMeetingId=17355"
```

Step 3 returned 338 KB of XML, 11 agenda items. The budget item:

```
Revenue and Capital Budget 2026/27  (21 linked documents)
  Budget Report 2026-27 - COUNCIL                             -> mgConvert2PDF.aspx?ID=174193
  Addendum to Budget Report 2026-27                           -> mgConvert2PDF.aspx?ID=174194
  Appendix 01 - MTFS 2026-30                                  -> mgConvert2PDF.aspx?ID=174195
  Appendix 02 - Simplified Council Tax Model and Statutory Calculations -> mgConvert2PDF.aspx?ID=174196
```

Plus separate items for the Green Group and Liberal Democrat alternative budgets, each with the
section 151 officer's statement. That "Appendix 01 - MTFS 2026-30" is the medium-term financial plan
that exists nowhere central.

Relevant XML elements: `agendaitem`, `agendaitemtitle`, `linkeddocuments`, `linkeddoc`, `title`,
`url`, `attachmentid`, `isrestricted`, `agendapublished`, `minutepublished`.

Known quirks: `GetMeetings` accepts `sFromDate` and `sToDate` but **ignores them**, returning the
committee's full history. Filter client-side on `<meetingdate>`, which is `dd/mm/yyyy`. Document
URLs come back as `http://`, not https.

### Coverage across the 33 boroughs

I probed 33 borough Modern.Gov hostnames plus the GLA, twice, with realistic browser headers:

| Result | Count | Boroughs |
|---|---|---|
| **200, service works** | 4 | Lambeth (`moderngov.lambeth.gov.uk`), Brent (`democracy.brent.gov.uk`), City of London (`democracy.cityoflondon.gov.uk`), Haringey (`www.minutes.haringey.gov.uk`) |
| 403, WAF block | 23 | Barnet, Bexley, Camden, Croydon, Ealing, Enfield, Greenwich, Hackney, Hammersmith & Fulham, Harrow, Islington, Kensington & Chelsea, Kingston, Lewisham, Merton, Sutton, Tower Hamlets, Waltham Forest, Westminster, and the GLA |
| 404, different path or not Modern.Gov | 4 | Havering, Hillingdon, Hounslow, Southwark, Wandsworth (hostnames guessed) |
| DNS or connection failure | 5 | Barking & Dagenham, Bromley, Newham, Redbridge, Richmond (hostnames guessed) |

The 403s are **bot shields, not missing services**. Camden returns a Cloudflare "Just a moment..."
interstitial; Croydon and Harrow return a different WAF page. On those hosts the ordinary
`mgListCommittees.aspx` page is blocked too, so it is the client that is being rejected, not the
endpoint that is absent. A real browser session, or a residential-looking client, would very likely
get through. I could not confirm that here because Chromium could not launch in this sandbox.

Hostnames in the 404 and failure rows were my guesses, so those boroughs may well run Modern.Gov at
a different address. The sibling agents covering borough sites should nail those down; feed them the
`/mgWebService.asmx` probe.

---

## 11. Ranked recommendation

For a developer who wants per-borough, per-service budget figures across several years, joinable to
MHCLG outturn and to the transaction-level spend files:

1. **MHCLG Revenue Account Budget per-LA ODS**, one file per year from
   `.../england-<yyyy>-to-<yyyy>-budget-individual-local-authority-data`. All 33 boroughs, ~300
   service and financing lines, E09 and MHCLG E-codes, OGL v3, no auth. Stack ten years and you have
   the budget side of the whole problem. Section 2.
2. **Revenue Outturn multi-year CSV** for the actuals, joined on the RA asset IDs. One 24 MB GET,
   2017-18 to 2025-26, verified 195-of-204 column overlap with RA. Section 3. Cite
   `QRU_2026-27_Mapping_Document.ods` for the line-level RA/RO crosswalk, including the places where
   RA is coarser.
3. **Council tax Table 10 (`Data_Billing`)** for the council tax requirement, tax base and collection
   rate per borough, and **London Datastore `expnl`** for all eight bands per borough back to
   1999-00. Section 6.
4. **Quarterly Revenue Update live table** if you want in-year budget vs actual rather than annual.
   Forecast, Q1 actuals and a 2017-18 quarterly time series in one 5.8 MB file. Section 4.
5. **Core Spending Power table** for the only central multi-year forward view, 2024-25 to 2028-29.
   Section 7.
6. **Capital time series CSV** for capital outturn 2018-19 to 2024-25, plus `CER_2026-27_A1.ods`
   sheets `fixed_assets` and `receipts` for forward capital. Skip the drop-down sheets. Section 5.
7. **Section 251 multi-year ODS** if education detail matters, accepting that you must map DfE LA
   numbers to ONS codes. Section 8.
8. **Modern.Gov `mgWebService.asmx`** for the MTFS and the narrative budget report, borough by
   borough, once you solve the WAF problem. Section 10.
9. **LG Inform / ESD API** only if you want LGA's derived metrics and are willing to register and
   possibly subscribe. Not a substitute for the MHCLG files. Section 9.

Joining to the £500 transaction files: the bridge is the ONS code plus the service classification.
Borough spend files carry a free-text `organisational_unit` or directorate, not a SeRCOP line, so
the join to RA service lines is approximate at best and needs a per-borough mapping table. The clean
joins are at authority level (ONS `E09*`) and financial year.

---

## 12. Dead, blocked, paywalled or absent

| Thing | Status on 2026-09-19 |
|---|---|
| RA multi-year time series | **Does not exist.** Checked all 85 documents in the revenue collection. Only outturn has one. Stack yearly releases |
| Capital multi-year forecast series | Does not exist. Only the final outturn time series CSV, 2018-19 to 2024-25 |
| `local-authority-data.service.gov.uk` (Oflog Data Explorer) | **Dead**, DNS does not resolve |
| `oflog.gov.uk` | Redirects to the GOV.UK org page, which the content API marks `"status": "no_longer_exists"`. Oflog abolished 16 Dec 2024. **No successor data service** |
| `www.london.gov.uk` (Mayor's budget, GLA consolidated budget) | **403 to every HTTP client**, Cloudflare interstitial, including direct `/sites/default/files/*.pdf` downloads. Browser-only. The current page is `/about-us/greater-london-authority-gla/spending-money-wisely/mayors-budget`, confirmed via a Wayback snapshot dated 2026-09-06; it links PDFs, no structured data. **Use the MHCLG CTR precepting data instead** for the GLA precept (section 6a) and the GLA's own row in the RA and RO files for its budget |
| `apps.london.gov.uk` | 403, same shield |
| `ifs.org.uk` | **403 to WebFetch and curl.** Could not confirm whether IFS publishes a per-authority local government finance dataset. **Unverified** |
| `cipfa.org` | **403 to WebFetch and curl.** The Financial Resilience Index is widely described as members-only. Could not confirm today. **Unverified, assume paywalled** |
| `centreforlondon.org/data/` | 404. The site search responds but I found no borough finance dataset. Their output is reports, not data |
| London Councils | Site live. Sitemap has 578 URLs; the finance content is press releases and committee PDFs. Their budget survey (run with the Society of London Treasurers, the source of the "£1.5bn gap in 2026-27" figure) is **not published as data**, only as narrative. `who-we-are/governance-and-spending/financial-reporting/spending-over-ps500` is London Councils' own spend, not the boroughs' |
| London Datastore borough budget datasets | Only council tax ones are current (`expnl`, 2026-04-13). `208n1` "2010-2013 GLA budget detail" is 16 years old. No borough revenue or capital budget datasets |
| DfE Explore Education Statistics API | Live and open, no key, but exposes 25 publications, **none financial**. Section 251 is files only |
| `webservices.esd.org.uk/*` data endpoints | 401 without a key. Metric catalogue not inspectable anonymously |
| GitHub, normalised RA/RO data | Nothing credible. Best near-misses: `wulfsagedev/civaccount` (active, pushed 2026-09-12, 317 English councils, `NOASSERTION` license, worth reading its `DATA-CONSTITUTION.md` for its sourcing rules), `docsucram/england-local-authority-dashboard` (2026-08-28, no license, claims all 317 LAs and 33 boroughs), `dorcas-aina-analytics/fabric-local-gov-starter` (MIT, a Fabric/PySpark template over DLUHC Revenue Outturn). **No repo publishes a cleaned RA/RO dataset** |
| Modern.Gov on 23 borough hosts | 403 WAF, not absent. Section 10 |
| Chromium / Playwright in this environment | Cannot launch, no usable sandbox. Every browser-only source above stayed unverified |
