# Team Sierra: backend onboarding (Desk Data Access)

Read `AGENTS.md` first (theme, contract, timeline). This file is your slice: the platform
and operations side. Jose and his helper build the UI with Codex; Younis (with Claude Code)
writes `governance.py`; you make sure the app can run, the grants can happen and the demo
can be rehearsed twice.

## Who does what

| Person | Owns |
|---|---|
| Jose + helper (Codex) | `app.py`, `db.py`, `app.yaml`, UI, demo narration |
| Younis (+ Claude Code) | `governance.py` (request / approve = real GRANT / reject / revoke), `setup.sql` |
| **You** | App permissions, mentor asks, Genie space, deploy, demo accounts, reset, rehearsal |

## Workspace

- https://dbc-ea0a1678-b98c.cloud.databricks.com
- CLI: `brew install databricks/tap/databricks` then
  `databricks auth login --host https://dbc-ea0a1678-b98c.cloud.databricks.com --profile hack`
- Warehouse `hackathon-sandbox-bi`, id `a24300104bf8ac6c` (running). We hold CAN_USE only.
- Our schema: `hackathon_gold.sierra`. Live already: `eod_prices` (74,588 rows), `positions`
  (24), `vendor_faults` (394), `access_requests` (empty). All three data tables carry the tags
  `data_owner`, `sensitivity`, `licence_cost_gbp`, `description`.
- Raw CSVs: `/Volumes/hackathon_bronze/sierra/landing/`
- App: `sierra-front-door` (created 18:05, no code yet). Get its service principal (SP) id with
  `databricks apps get sierra-front-door -p hack -o json | grep service_principal`.
- Repo: github.com/younis-y/sierra-front-door (ask Younis for collaborator access).

## Your tasks, in order

### 1. Mentor message (now; everything else waits on it)

One message, three asks, with the SP client id:

> We're team sierra, building Track 3. Our app `sierra-front-door` runs as SP `<client id>`.
> (a) Please add that SP to group `hackathon_sierra` (or at least
> `GRANT USE CATALOG ON CATALOG hackathon_gold TO <sp>`): we can't grant on the catalog.
> (b) Please give the SP CAN_USE on warehouse `hackathon-sandbox-bi`: attaching it as an app
> resource needs MANAGE on the warehouse, which we don't have.
> (c) We need one login outside `hackathon_sierra` to play the analyst who is denied first.
> A team-summit member works.

Why (c): Unity Catalog has no DENY. Our group has ALL PRIVILEGES on the schema, so no sierra
member can ever be refused. Younis is in both groups, so he can't be the analyst either.

### 2. Fallback grants we can do ourselves (SQL editor, as a sierra member)

```sql
GRANT MANAGE, USE SCHEMA ON SCHEMA hackathon_gold.sierra TO `<sp client id>`;
GRANT SELECT, MODIFY ON TABLE hackathon_gold.sierra.access_requests TO `<sp client id>`;
```

MANAGE on the schema is what lets the SP run GRANT on our tables. The SP still needs USE
CATALOG from the mentor.

### 3. Share the app

```
databricks permissions set apps <app id> --json '{"access_control_list":[{"group_name":"users","permission_level":"CAN_USE"}]}' -p hack
```

Without this the demo analyst gets a 403 when they open the app.

### 4. Genie space (18:15 to 18:45, in the UI: sidebar > Genie Agents)

Genie picks tables and joins on its own, so we fence it in:

1. Run `genie_views.sql` (SQL editor). It creates `v_request_log` and `v_entitlements`, every
   column commented. Genie reads the comments as its data dictionary.
2. New Genie space: title "Desk Data Access audit", warehouse `hackathon-sandbox-bi`, tables:
   **only the two views**. Nothing else.
3. General instructions, paste exactly:
   > Answer only from the two views. Costs are GBP per month. "Who has access" means
   > status = approved. "Pending" means status = pending. Never guess a table that is not
   > in the views. If a question is outside access requests, say so.
4. Test these three questions and add each as a sample question with its SQL once it is right:
   - Who has access to positions right now?
   - What is our total licence spend per month, by table?
   - Which requests are still pending and how old are they?
   Also ask "What is the price of TSM?" and check it refuses. If an answer drifts, add a
   one-line instruction and re-test. **Only the three tested questions get asked live.**
5. Note the space id (in the URL) and tell Jose: it goes in `app.yaml` as `GENIE_SPACE_ID`.
   Share the space with the app SP (CAN_RUN) and grant the SP SELECT on the two views.

### 5. Demo analyst prep

Save a query in the SQL editor for the analyst account:
`SELECT * FROM hackathon_gold.sierra.positions LIMIT 5` (denied before approval, rows after).
That query is the money shot, not the app: the app's forwarded user token has only `iam.*`
scopes and cannot run SQL as the user.

### 6. Deploy (19:15, once code is merged to main)

```
databricks sync . /Workspace/Users/younis@sierra.example/sierra-front-door -p hack
databricks apps deploy sierra-front-door --source-code-path /Workspace/Users/younis@sierra.example/sierra-front-door -p hack
```

`.venv` is git-ignored, and sync honours `.gitignore`. Deploy only from main.

### 7. Rehearse (19:45) and reset

Run the script in `AGENTS.md` end to end with the analyst, then `reset_demo.sql` (replace
`ANALYST` with their email), then rehearse again.

## Gotchas (verified tonight)

- Statement API returns every value as a string (`'120'`, not `120`).
- Attaching a warehouse as an app resource needs MANAGE on the warehouse; a plain
  `DATABRICKS_WAREHOUSE_ID` value in `app.yaml` works if the SP has CAN_USE.
- `ai_classify` works on this warehouse (used to flag vague reasons).
- Never run `apps create` again; the app exists.
