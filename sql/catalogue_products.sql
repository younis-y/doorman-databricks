-- Doorman catalogue: richer descriptions, desk grouping, and three more real data products
-- built from data already in hackathon_gold.sierra. Ran 21 Oct 20:00. Safe to re-run.

-- Existing products: better copy, plus a `domain` tag the app uses to group the Desk dropdown.
ALTER TABLE hackathon_gold.sierra.eod_prices SET TAGS (
  'description' = 'Licensed end-of-day OHLCV from Yahoo and Nasdaq, 60 EM and GCC names, Jan 2024 to date',
  'domain' = 'Market data');
ALTER TABLE hackathon_gold.sierra.positions SET TAGS (
  'description' = 'Live desk positions by ticker and book. Confidential: desk head approval only',
  'domain' = 'Trading book');
ALTER TABLE hackathon_gold.sierra.vendor_faults SET TAGS (
  'description' = 'Daily price faults where Yahoo and Nasdaq disagree, priced in GBP exposure',
  'domain' = 'Operations');

-- New: free delayed summary (the thing to point people at when the licensed feed is refused).
CREATE OR REPLACE VIEW hackathon_gold.sierra.daily_summary
COMMENT 'Close only, one row per ticker per day, from the Yahoo leg. Free for internal use.'
AS SELECT ticker, venue, date, close FROM hackathon_gold.sierra.eod_prices WHERE vendor = 'yahoo';
ALTER VIEW hackathon_gold.sierra.daily_summary SET TAGS (
  'data_owner' = 'younis@sierra.example', 'sensitivity' = 'internal', 'licence_cost_gbp' = '0',
  'description' = 'Delayed daily closes, free for internal use. Need OHLCV or the Nasdaq leg? Request eod_prices',
  'domain' = 'Market data');

-- New: licensed corporate actions, rebuilt from the landed bars (dividends and splits were dropped from eod_prices).
CREATE OR REPLACE TABLE hackathon_gold.sierra.corporate_actions
COMMENT 'Dividends and splits by ticker and date, from the vendor bars'
AS SELECT ticker, venue, CAST(date AS DATE) AS date, dividends AS dividend, splits AS split_ratio
FROM read_files('/Volumes/hackathon_bronze/sierra/landing/bronze_vendor_bars.csv', format => 'csv', header => true, inferSchema => true)
WHERE vendor = 'yahoo' AND (dividends > 0 OR splits > 0);
ALTER TABLE hackathon_gold.sierra.corporate_actions SET TAGS (
  'data_owner' = 'younis@sierra.example', 'sensitivity' = 'licensed', 'licence_cost_gbp' = '40',
  'description' = 'Dividends and splits for the 60-name universe, Jan 2024 to date. Licensed per user',
  'domain' = 'Market data');

-- New: vendor quality by venue, owned by Jose (a second owner with a second product).
CREATE OR REPLACE VIEW hackathon_gold.sierra.venue_vendor_quality
COMMENT 'Fault counts and GBP exposure by venue and fault type, from vendor_faults'
AS SELECT venue, fault, COUNT(*) AS faults, ROUND(SUM(gbp_exposure), 0) AS gbp_exposure, MAX(date) AS last_seen
FROM hackathon_gold.sierra.vendor_faults GROUP BY venue, fault;
ALTER VIEW hackathon_gold.sierra.venue_vendor_quality SET TAGS (
  'data_owner' = 'jose@sierra.example', 'sensitivity' = 'internal', 'licence_cost_gbp' = '0',
  'description' = 'Which vendor to trust on which venue: fault counts and exposure, by venue',
  'domain' = 'Operations');

-- Patrick's synthetic test table: keep the table, take it out of the catalogue.
-- Restore with: ALTER TABLE hackathon_gold.sierra.patrick_routing_test SET TAGS ('data_owner' = 'patrick@sierra.example');
ALTER TABLE hackathon_gold.sierra.patrick_routing_test UNSET TAGS ('data_owner');
