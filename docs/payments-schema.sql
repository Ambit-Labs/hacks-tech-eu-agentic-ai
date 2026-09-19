-- Scrooge payments schema. Postgres 17.
-- One row per published payment, every borough in one table. The columns the
-- agent's tools query are typed; everything the borough published is kept in
-- `raw` under its original header, so nothing is lost when the mapping is wrong.
-- Companion: docs/payments-schema.md (column mapping per borough, loader rules).

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Which boroughs exist, and their population for per-resident comparisons.
-- Filled by hand from ONS mid-year estimates; 33 rows when complete.
CREATE TABLE boroughs (
    slug        text PRIMARY KEY,             -- directory name under data/raw: camden
    name        text NOT NULL,                -- London Borough of Camden
    population  integer                       -- latest mid-year estimate, NULL until filled
);

-- One row per source file the loader has seen, whether it loaded it or not.
-- Lets `coverage` and the loader's resume logic agree on what is in the table.
CREATE TABLE source_files (
    path         text PRIMARY KEY,            -- data/raw/<borough>/<file>
    borough      text NOT NULL REFERENCES boroughs(slug),
    period       text NOT NULL,               -- manifest period: 2026-07, 2026-Q1, 2025-04_2026-03
    status       text NOT NULL CHECK (status IN ('loaded', 'skipped', 'failed')),
    reason       text,                        -- why skipped or failed
    rows_loaded  integer NOT NULL DEFAULT 0,
    loaded_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE payments (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    borough         text NOT NULL REFERENCES boroughs(slug),
    payment_date    date NOT NULL,
    financial_year  text NOT NULL,            -- '2019/20'; April to March; derived from payment_date
    supplier        text NOT NULL,            -- as published, whitespace trimmed
    supplier_norm   text GENERATED ALWAYS AS (
                        regexp_replace(upper(supplier), '[^A-Z0-9]+', ' ', 'g')
                    ) STORED,                 -- for matching one supplier across boroughs
    directorate     text,                     -- top organisational level the borough gives
    department      text,                     -- second level: service, division, cost centre
    purpose         text,                     -- expense type, subjective, activity, description
    amount_gbp      numeric(14, 2) NOT NULL,  -- net of VAT where the borough says so; negatives kept
    vat_gbp         numeric(14, 2),           -- irrecoverable VAT, only 6 boroughs publish it
    reference       text,                     -- transaction, invoice or payment number as published
    source_file     text NOT NULL REFERENCES source_files(path),
    source_row      integer NOT NULL,         -- 1-based data row within the file, header excluded
    raw             jsonb NOT NULL,           -- every original column, header text as published
    UNIQUE (source_file, source_row)          -- reloading a file is idempotent
);

CREATE INDEX payments_borough_date_idx   ON payments (borough, payment_date);
CREATE INDEX payments_supplier_norm_idx  ON payments (supplier_norm);
CREATE INDEX payments_supplier_trgm_idx  ON payments USING gin (supplier_norm gin_trgm_ops);
CREATE INDEX payments_purpose_trgm_idx   ON payments USING gin (upper(purpose) gin_trgm_ops);
CREATE INDEX payments_department_trgm_idx ON payments USING gin (upper(coalesce(directorate, '') || ' ' || coalesce(department, '')) gin_trgm_ops);
CREATE INDEX payments_amount_idx         ON payments (amount_gbp DESC);

-- What the agent's `coverage` tool reads.
CREATE VIEW coverage AS
SELECT borough,
       date_trunc('month', payment_date)::date AS month,
       count(*)                                AS payments,
       sum(amount_gbp)                         AS total_gbp
FROM payments
GROUP BY borough, month;

-- The agent connects as this role. It can read, and nothing else.
CREATE ROLE scrooge_reader NOLOGIN;
GRANT USAGE ON SCHEMA public TO scrooge_reader;
GRANT SELECT ON boroughs, source_files, payments, coverage TO scrooge_reader;
ALTER ROLE scrooge_reader SET statement_timeout = '10s';
-- CREATE ROLE agent LOGIN PASSWORD '...' IN ROLE scrooge_reader;   -- done by hand, password never in the repo
