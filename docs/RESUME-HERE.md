# Resume here (saved 21 Oct 2026, 20:20, just before the live demo)

**Doorman is live:** https://desk-data-access-7474652817268861.aws.databricksapps.com
Anyone in the hackathon workspace can open it; first open shows a consent screen for SQL.

## What exists

| Piece | Where | State |
|---|---|---|
| App (Streamlit, three pages, CSV download, Genie box) | `app.py`, `db.py`, `app.yaml`, `assets/` | Deployed from main `77a1225` |
| Governance (request, approve = real GRANT, reject, revoke) | `governance.py` | 40 tests pass (`python3 -m pytest -q tests`) |
| Data products (3 per owner) | `hackathon_gold.sierra`, see `sql/catalogue_balance.sql` | Younis: eod_prices £120, daily_summary, positions. Jose: corporate_actions £40, vendor_faults, desk_mtm |
| Audit table | `hackathon_gold.sierra.access_requests` | Emptied for the demo |
| Genie space "Doorman audit" | id `01f1cd6fabb61c01a2d9f522b79791d0`, views in `sql/genie_views.sql` | 3 tested questions in `genie_presets.json` |
| Deck | `docs/Doorman-deck.pptx` (8 slides) | Final |
| Reviews and briefs | `docs/UI_REVIEW.md`, `docs/BACKEND.md`, `AGENTS.md` | Historical; UI_REVIEW has the follow-up list |

## How to deploy

```bash
databricks sync . /Workspace/Users/younis@sierra.example/desk-data-access -p hack --full
databricks apps deploy desk-data-access --source-code-path /Workspace/Users/younis@sierra.example/desk-data-access -p hack
```

If you ever change the app's scopes or description, pass **both** in one `apps update` call
(`{"description": "...", "user_api_scopes": ["sql"]}`), then `apps stop` + `apps start`, or
users get "Invalid scope" until they re-consent.

## How to reset a demo

Revoke every individual SELECT on the products and empty the log (one requester:
`sql/reset_demo.sql`; everyone: the snippet in the memory notes, or ask Claude "reset the demo").

## Open follow-ups

1. Expiring access: `expires_at` on the request plus a scheduled revoke.
2. Notifications on request and decision (Teams or email).
3. Run as the app's own service principal once an admin grants it USE CATALOG and warehouse
   CAN_USE (SP `7f190212-e21d-4beb-84f5-9e4d73a6dfd9`).
4. Delete the dead app `sierra-front-door` (admin only).
5. `docs/UI_REVIEW.md` items 5 to 9 and 14 to 19.
