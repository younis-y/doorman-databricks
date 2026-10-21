-- Doorman catalogue, balanced: three products per owner, same mix each
-- (one licensed with a £ cost, one free internal, one confidential). Ran 21 Oct 20:10.
--
--   Younis: eod_prices (licensed £120) · daily_summary (internal) · positions (confidential)
--   Jose:   corporate_actions (licensed £40) · vendor_faults (internal) · desk_mtm (confidential)

-- corporate_actions moves to Jose.
ALTER TABLE hackathon_gold.sierra.corporate_actions SET TAGS ('data_owner' = 'jose@sierra.example');

-- New confidential product for Jose: positions marked to the latest Yahoo close.
CREATE OR REPLACE VIEW hackathon_gold.sierra.desk_mtm
COMMENT 'Mark-to-market by book: quantity times the latest close, local currency'
AS WITH latest AS (
  SELECT ticker, close FROM hackathon_gold.sierra.eod_prices WHERE vendor = 'yahoo'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) = 1)
SELECT p.book, p.ticker, p.quantity, l.close, ROUND(p.quantity * l.close, 0) AS mtm_local
FROM hackathon_gold.sierra.positions p LEFT JOIN latest l USING (ticker);
ALTER VIEW hackathon_gold.sierra.desk_mtm SET TAGS (
  'data_owner' = 'jose@sierra.example', 'sensitivity' = 'confidential', 'licence_cost_gbp' = '0',
  'description' = 'Mark-to-market by book from live positions and the latest close. Confidential: desk head approval only',
  'domain' = 'Trading book');

-- venue_vendor_quality stays as a view but leaves the catalogue (vendor_faults covers operations).
-- Restore: ALTER VIEW hackathon_gold.sierra.venue_vendor_quality SET TAGS ('data_owner' = 'jose@sierra.example');
ALTER VIEW hackathon_gold.sierra.venue_vendor_quality UNSET TAGS ('data_owner');
