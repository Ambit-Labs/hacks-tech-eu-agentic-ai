INSERT INTO boroughs (slug, name, population) VALUES
  ('camden',    'London Borough of Camden',    210000),
  ('islington', 'London Borough of Islington', 220000);

INSERT INTO source_files (path, borough, period, status, rows_loaded) VALUES
  ('data/raw/camden/2019-09__camden-payments.csv',    'camden',    '2019-09', 'loaded', 6),
  ('data/raw/camden/2019-10__camden-payments.csv',    'camden',    '2019-10', 'loaded', 4),
  ('data/raw/islington/2019-09__islington.csv',       'islington', '2019-09', 'loaded', 5),
  ('data/raw/islington/2019-10__islington.csv',       'islington', '2019-10', 'loaded', 3);

INSERT INTO payments
  (borough, payment_date, financial_year, supplier, directorate, department, purpose, amount_gbp, vat_gbp, reference, source_file, source_row, raw)
VALUES
  -- camden, September 2019: total 10000.00 over 6 rows
  ('camden', '2019-09-02', '2019/20', 'NSL LIMITED',            'Corporate Services GF',    NULL, 'Third Party Payment Not Government', 5000.00, 0, 'sep-19-1', 'data/raw/camden/2019-09__camden-payments.csv', 1, '{}'),
  ('camden', '2019-09-05', '2019/20', 'CAPITA BUSINESS SERVICES', 'Corporate Services GF',  NULL, 'Consultants Fees',                  2000.00, 0, 'sep-19-2', 'data/raw/camden/2019-09__camden-payments.csv', 2, '{}'),
  ('camden', '2019-09-10', '2019/20', 'GREAT ORMOND STREET HOSPITAL', 'Supporting Communities GF', NULL, 'Professional Services General', 1500.00, 0, 'sep-19-3', 'data/raw/camden/2019-09__camden-payments.csv', 3, '{}'),
  ('camden', '2019-09-12', '2019/20', 'ACME TEMP ACCOMMODATION LTD', 'Supporting Communities GF', NULL, 'Temporary Accommodation',  800.00, 0, 'sep-19-4', 'data/raw/camden/2019-09__camden-payments.csv', 4, '{}'),
  ('camden', '2019-09-20', '2019/20', 'ACME TEMP ACCOMMODATION LTD', 'Supporting Communities GF', NULL, 'Temporary Accommodation',  600.00, 0, 'sep-19-5', 'data/raw/camden/2019-09__camden-payments.csv', 5, '{}'),
  ('camden', '2019-09-28', '2019/20', 'NSL LIMITED',            'Corporate Services GF',    NULL, 'Third Party Payment Not Government',  100.00, 0, 'sep-19-6', 'data/raw/camden/2019-09__camden-payments.csv', 6, '{}'),
  -- camden, October 2019: total 4000.00 over 4 rows, one negative
  ('camden', '2019-10-01', '2019/20', 'CAPITA BUSINESS SERVICES', 'Corporate Services GF',  NULL, 'Consultants Fees',                  3000.00, 0, 'oct-19-1', 'data/raw/camden/2019-10__camden-payments.csv', 1, '{}'),
  ('camden', '2019-10-08', '2019/20', 'NSL LIMITED',            'Corporate Services GF',    NULL, 'Third Party Payment Not Government',  700.00, 0, 'oct-19-2', 'data/raw/camden/2019-10__camden-payments.csv', 2, '{}'),
  ('camden', '2019-10-15', '2019/20', 'BIG BUILD CONSTRUCTION LTD', 'Supporting Communities GF', NULL, 'Works - Construction',         500.00, 0, 'oct-19-3', 'data/raw/camden/2019-10__camden-payments.csv', 3, '{}'),
  ('camden', '2019-10-22', '2019/20', 'NSL LIMITED',            'Corporate Services GF',    NULL, 'Third Party Payment Not Government', -200.00, 0, 'oct-19-4', 'data/raw/camden/2019-10__camden-payments.csv', 4, '{}'),
  -- islington, September 2019: total 6000.00 over 5 rows
  ('islington', '2019-09-03', '2019/20', 'Capita Business Services Ltd', 'Housing', 'Cap Prog Delivery', 'Consultants - Fees',     2500.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 1, '{}'),
  ('islington', '2019-09-09', '2019/20', 'Reed Agency Staff',            'Housing', 'Estates',           'Agency Staff',           1500.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 2, '{}'),
  ('islington', '2019-09-16', '2019/20', 'Reed Agency Staff',            'Children', 'Social Work',      'Agency Staff',           1000.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 3, '{}'),
  ('islington', '2019-09-23', '2019/20', '10 Ability Limited',           'Housing', 'Cap Prog Delivery', 'Consultants - Fees',      600.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 4, '{}'),
  ('islington', '2019-09-30', '2019/20', 'Big Build Construction Ltd',   'Housing', 'Estates',           'Works - Construction',    400.00, NULL, NULL, 'data/raw/islington/2019-09__islington.csv', 5, '{}'),
  -- islington, October 2019: total 2100.00 over 3 rows
  ('islington', '2019-10-04', '2019/20', 'Reed Agency Staff',            'Children', 'Social Work',      'Agency Staff',           1200.00, NULL, NULL, 'data/raw/islington/2019-10__islington.csv', 1, '{}'),
  ('islington', '2019-10-11', '2019/20', 'Capita Business Services Ltd', 'Housing', 'Cap Prog Delivery', 'Consultants - Fees',      500.00, NULL, NULL, 'data/raw/islington/2019-10__islington.csv', 2, '{}'),
  ('islington', '2019-10-25', '2019/20', '10 Ability Limited',           'Housing', 'Cap Prog Delivery', 'Consultants - Fees',      400.00, NULL, NULL, 'data/raw/islington/2019-10__islington.csv', 3, '{}');
