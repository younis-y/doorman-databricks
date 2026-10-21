-- Two curated views for the Genie space. Genie sees ONLY these (plus their comments).

CREATE OR REPLACE VIEW hackathon_gold.sierra.v_request_log
  (id COMMENT 'Request id',
   requester COMMENT 'Email of the person asking for access',
   table_name COMMENT 'Fully qualified table requested',
   reason COMMENT 'Business reason given by the requester',
   licence_cost_gbp_per_month COMMENT 'Monthly licence cost in GBP if this access is granted',
   approver COMMENT 'Email of the data owner who must decide',
   status COMMENT 'pending, approved, rejected, failed or revoked',
   decided_by COMMENT 'Who made the decision',
   decided_at COMMENT 'When the decision was made (UTC)',
   note COMMENT 'Rejection reason, or error text if the grant failed',
   requested_at COMMENT 'When the request was made (UTC)',
   age_hours COMMENT 'Hours since the request was made')
COMMENT 'Every data-access request on the desk and what happened to it: the approval queue and the audit trail.'
AS SELECT id, requester, table_name, reason, licence_cost, approver, status, decided_by, decided_at, note,
          requested_at, ROUND((unix_timestamp(current_timestamp()) - unix_timestamp(requested_at)) / 3600, 1)
FROM hackathon_gold.sierra.access_requests;

CREATE OR REPLACE VIEW hackathon_gold.sierra.v_entitlements
  (user_email COMMENT 'Person who currently has access',
   table_name COMMENT 'Fully qualified table they can read',
   sensitivity COMMENT 'licensed, confidential or internal',
   licence_cost_gbp_per_month COMMENT 'What this access costs the desk per month in GBP',
   approved_by COMMENT 'Data owner who approved',
   approved_at COMMENT 'When access was granted (UTC)')
COMMENT 'Who has access to which table right now (approved requests only) and what it costs per month.'
AS SELECT r.requester, r.table_name, t.tag_value, r.licence_cost, r.decided_by, r.decided_at
FROM hackathon_gold.sierra.access_requests r
LEFT JOIN hackathon_gold.information_schema.table_tags t
  ON t.schema_name = 'sierra' AND t.tag_name = 'sensitivity'
 AND concat(t.catalog_name, '.', t.schema_name, '.', t.table_name) = r.table_name
WHERE r.status = 'approved';
