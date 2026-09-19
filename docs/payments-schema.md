# Payments schema and loader mapping

The contract between the loader (reads `data/raw/`, writes Postgres) and the
agent (reads Postgres through fixed tools). DDL is in
[payments-schema.sql](payments-schema.sql). This page says which published
column lands in which typed column for each borough, and the rules for the
values. Based on a survey of all 1,340 files on disk on 2026-09-19; the full
survey output is not in the repo.

## The typed columns

Every borough publishes some version of these nine facts. The agent's tools
query only these. Anything else the borough published stays in `raw`, keyed
by the header text exactly as it appeared in the file.

| Column | Meaning | Missing in |
| --- | --- | --- |
| `borough` | Directory name under `data/raw/` | never |
| `payment_date` | The date the borough attached to the payment | never, but see date rules |
| `financial_year` | `2019/20` style, April to March, derived from `payment_date` | never |
| `supplier` | Beneficiary as published | never |
| `directorate` | Top organisational level | Brent |
| `department` | Second level: service, division, cost centre | Barnet (old), Brent, Camden, Haringey, Newham, Richmond, Wandsworth, Westminster |
| `purpose` | Expense type, subjective, activity or free text | never |
| `amount_gbp` | Net amount; negatives kept as negatives | never |
| `vat_gbp` | Irrecoverable VAT | everyone except Bexley, Brent, Camden, Havering (new), Hounslow, Newham |
| `reference` | Transaction, invoice or payment number | Brent, Haringey, Islington, Lewisham, Newham, Richmond, Wandsworth, Westminster |

## Column mapping per borough

Header names are matched after trimming whitespace and ignoring case. Where a
borough changed layout over the years, both layouts are listed. "Two levels"
means the borough gives both `directorate` and `department`.

| Borough | Layouts | date | supplier | directorate | department | purpose | amount | vat | reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| barnet | old (to 2023) | Payment Date | Vendor Name | Directorate | Department | Expenditure Type | Expenditure Amount (exc VAT) | | Ref.Doc.1 |
| barnet | new (2024+) | Payment Date | Supplier Name | Cost Centre Hierarchy - Directorate | the department-level hierarchy column | Expenditure Type | Distribution Amount | | Payment Reference Number |
| bexley | | Payment Date | Supplier | Directorate | Service area | Expense Type | Amount | Non Recoverable VAT | Transaction Number |
| brent | | Payment Date | Vendor Name 2 | | Cost Centre Description | Subjective desctiption (sic) | Amount | Non Recoverable VAT | |
| camden | | payment_date | beneficiary_name | organisational_unit | | purpose | amount_gbp | irrecoverable_vat_amount_gbp | unique_identifier |
| haringey | | Payment date | Supplier Name | Department | | Purpose | Amount | | |
| havering | new | Transaction Date | Beneficiary | Local Authority Department | | Purpose of Expenditure | Amount (excluding VAT) | Non Recoverable VAT | |
| havering | old | Posted Fiscal Date | Supplier Name | Directorate | Service | Subjective Name | Amount | | Transaction Number |
| hounslow | | PaymentDate | BeneficiaryName | OrganisationalUnit | ServiceCategoryLabel | Purpose | Amount | IrrecoverableVATAmount | TransactionNumber |
| islington | | Entry Date | Supplier Name | Department | Service | Spend Type | Net Amount | | |
| lambeth | transactions (old) | Invoice Creation Date | Supplier Name | Department | | Subj Description | Invoice Nett Amount | | |
| lambeth | transparency report | PAYMENT_DATE | Supplier Name ******* | Directorate | Division | Subjective Description | Amount | | Over £500 Report Ref |
| lewisham | | PAYMENT DATE | SUPPLIER | DEPARTMENT | SERVICE | DESCRIPTION | £ SPEND (EXCLUDING VAT) | | |
| newham | | Transaction Date | BENEFICIARY | Local Authority Department | | Purpose | Amount | Non Recoverable | |
| redbridge | | Transaction Date | Supplier description | Directorate | Service | Account description | Amount | | Transaction No |
| richmond | | PAYMENT DATE | PAYEE | DIRECTORATE | | ACTIVITY | PAYMENT AMOUNT | | |
| wandsworth | | PAYMENT DATE | PAYEE | DIRECTORATE | | ACTIVITY | PAYMENT AMOUNT | | |
| westminster | | Posting date | FINAL Supplier name, else Supplier name | Department | | Expense type | Amount | | |

Choices made where a borough offers two candidates:

- Lambeth's transparency report has `PAYMENT_DATE`, `Invoice Creation Date`
  and `Accounting Date`. `PAYMENT_DATE` wins; the others stay in `raw`.
- Redbridge has four description columns. `Account description` is the
  purpose; `Bvsub`, `Bvsum` and `Classification` stay in `raw`.
- Newham's `Merchant Category` and Hounslow's `CategoryInternalName` are coded
  categories, kept in `raw`, not used as `purpose`.
- Westminster added `FINAL Supplier name` in 2024 files. Use it when present.
- Islington's date column changed name three times (`Entry Date`,
  `Transaction Date`, `Input Date`). All map to `payment_date`.
- Barnet's new layout has both `Payment Reference Number` and `Payment
  Number`. The first is `reference`.

## Value rules

Dates. Parse these forms, in this order, and fail the row on anything else:
`DD/MM/YYYY`, `DD/MM/YYYY HH:MM:SS`, `DD-MM-YYYY`, `DD-Mon-YY`, `DD-Mon-YYYY`,
`D Mon YYYY`, `DD Month YYYY`, ISO `YYYY-MM-DDTHH:MM:SS.sss`, and Excel
datetime cells. Day comes before month everywhere. A literal `N/A` (Havering)
fails the row.

Amounts. Strip everything before the first digit or minus sign, including
`£`, spaces and the `œ` mojibake that stands for `£` in a few old Bexley and
Havering files. Remove thousands commas. `-1,040.22` and `-£177,790.95` are
negatives; no borough uses parentheses. Store two decimals.

Financial year. April to March. A payment on 2019-09-30 is `2019/20`; one on
2020-03-31 is also `2019/20`.

Supplier. Trim. Do not upper-case or de-duplicate; `supplier_norm` is a
generated column that does that for matching.

Raw. Every cell of the row, keyed by the header text as it appeared in the
file, including columns the mapping ignores and blank trailing columns.
Header typos (`Transcation Number`, `Supplier Numbe`) are kept as published.

## Files to skip or handle

- Lambeth files with only `Supplier Name, Total` (14 of them) are supplier
  totals, not payments. Skip with `status = 'skipped'`.
- Lambeth `Sum of Invoice Nett Amount` files are aggregates. Skip.
- Hounslow `2021-03__invoices-over-500-march-2021.csv` and
  `2022-09__invoices-over-500-sep-2022.csv` start with a leaked SQL query;
  the header is on line 5 and there is an extra leading column.
- Bexley and Brent put a title row before the header in most files. Find the
  header by looking for the first row containing the expected date column.
- Havering `2013-05__may-2013.csv` and Bexley
  `2015-07_2015-09__...-V2.csv` have no header row. Skip, or apply the
  borough's dominant header by position.
- Broken quoting (newline inside an unquoted field): Hounslow 2021-08,
  Havering 2015-08 and 2015-09, Lambeth 2011-11, Newham 2019-02. Load what
  parses, record `status = 'failed'` with the reason if the parser gives up.
- Newham 2019-02 is tab delimited. Sniff the delimiter per file.
- Encodings: utf-8, utf-8 with BOM, and cp1252 all occur. Try utf-8-sig
  first, then cp1252.
- Lewisham xlsx files have a title row and a blank row; the header is row 3.
- Lambeth has 2 `.ods` files. Skip them unless a reader is already at hand.

## Who owns what

The loader session owns the database. It applies `payments-schema.sql` to
the Modal Postgres once, fills `boroughs`, writes `source_files` and
`payments`, and creates the login role for the agent:

```sql
CREATE ROLE agent LOGIN PASSWORD '...' IN ROLE scrooge_reader;
```

The agent session owns `agent/` only. It never runs DDL, never writes rows,
and connects with the `agent` login through `DATABASE_URL`, which is
`postgresql://agent:<password>@<host>:<port>/postgres` built from `pg url`.

If the schema has to change, change `payments-schema.sql` first, in the same
commit as the loader change, then tell the agent session. The agent's tools
depend on these names exactly: `payments` with every column above,
`coverage`, and `boroughs.population`.

## What the agent needs from this

The agent's tools query `payments`, `coverage` and `boroughs` only, as the
`scrooge_reader` role. `coverage` is how the agent learns which boroughs and
months exist before it answers. `boroughs.population` is what makes
per-resident comparisons possible; until it is filled, that option is off.

The agent can be built against an empty database: every tool answers "no
rows" cleanly. The first real test needs one loaded file, and Camden's
`2019-09` file is the cleanest one to start with.
