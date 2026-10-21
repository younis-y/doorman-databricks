-- Team sierra: data products + request/audit table for the Governed Front Door.
-- RAN ONCE on 21 Oct 17:40. Do NOT re-run: CREATE OR REPLACE rebuilds the tables and can drop
-- the grants that the demo depends on.
-- CSVs are landed in /Volumes/hackathon_bronze/sierra/landing/ first (databricks fs cp).

CREATE VOLUME IF NOT EXISTS hackathon_bronze.sierra.landing;

CREATE OR REPLACE TABLE hackathon_gold.sierra.eod_prices
COMMENT 'Daily bars from two vendors (Yahoo, Nasdaq), 62 EM/GCC names, Jan 2024 to Oct 2026'
AS SELECT vendor, ticker, venue, CAST(date AS DATE) AS date, open, high, low, close, volume, adj_close
FROM read_files('/Volumes/hackathon_bronze/sierra/landing/bronze_vendor_bars.csv', format => 'csv', header => true, inferSchema => true);

CREATE OR REPLACE TABLE hackathon_gold.sierra.positions
COMMENT 'Desk book: ticker, quantity, book (illustrative)'
AS SELECT ticker, quantity, book
FROM read_files('/Volumes/hackathon_bronze/sierra/landing/positions.csv', format => 'csv', header => true, inferSchema => true);

CREATE OR REPLACE TABLE hackathon_gold.sierra.vendor_faults
COMMENT 'Where the two price vendors disagree, priced in GBP exposure'
AS SELECT ticker, venue, CAST(date AS DATE) AS date, fault, detail, severity, gbp_exposure, book, status
FROM read_files('/Volumes/hackathon_bronze/sierra/landing/gold_faults_preview.csv', format => 'csv', header => true, inferSchema => true);

ALTER TABLE hackathon_gold.sierra.eod_prices SET TAGS (
  'data_owner' = 'younis@sierra.example', 'sensitivity' = 'licensed', 'licence_cost_gbp' = '120',
  'description' = 'End-of-day prices from Yahoo and Nasdaq for 62 EM and GCC names');
ALTER TABLE hackathon_gold.sierra.positions SET TAGS (
  'data_owner' = 'younis@sierra.example', 'sensitivity' = 'confidential', 'licence_cost_gbp' = '0',
  'description' = 'Desk positions by ticker and book');
-- Second owner so the demo shows routing: vendor_faults requests go to Jose, not Younis.
ALTER TABLE hackathon_gold.sierra.vendor_faults SET TAGS (
  'data_owner' = 'jose@sierra.example', 'sensitivity' = 'internal', 'licence_cost_gbp' = '0',
  'description' = 'Price faults where the two vendors disagree, with GBP exposure');

CREATE TABLE IF NOT EXISTS hackathon_gold.sierra.access_requests (
  id STRING, requester STRING, table_name STRING, reason STRING, licence_cost DOUBLE,
  approver STRING, status STRING, decided_by STRING, decided_at TIMESTAMP, note STRING,
  requested_at TIMESTAMP
) COMMENT 'Access requests: the approval queue and the audit trail';
