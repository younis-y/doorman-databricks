-- Reset between rehearsals. Replace ANALYST with the demo analyst's email, run in the SQL editor
-- as a sierra member. Safe to run when nothing is granted (REVOKE of a missing grant is a no-op).
REVOKE SELECT ON TABLE hackathon_gold.sierra.positions FROM `ANALYST`;
REVOKE SELECT ON TABLE hackathon_gold.sierra.eod_prices FROM `ANALYST`;
REVOKE SELECT ON TABLE hackathon_gold.sierra.vendor_faults FROM `ANALYST`;
REVOKE USE SCHEMA ON SCHEMA hackathon_gold.sierra FROM `ANALYST`;
DELETE FROM hackathon_gold.sierra.access_requests WHERE requester = 'ANALYST';
