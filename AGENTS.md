# Team Sierra: Desk Data Access (brief for Codex)

Codex reads this file automatically. Read it fully before writing code, and re-read the
**Contract** section before touching anything another person owns.

## The event in one paragraph

Colibri Digital hackathon, Wed 21 Oct 2026. Track 3, "The Governed Front Door": a Databricks
App where a user requests access to a Unity Catalog table, the right owner approves or
rejects, approval applies a **real** grant, and every step is logged to a Delta table.
Five-minute live demo at **20:00**, no slides. Scoring: governance 25%, reusability 25%,
self-service 25%, polish 15%, innovation 10%. Their golden rule: *a small build that works
beats a big one that doesn't.*

## Our theme

**Market-data entitlements on a trading desk.** Price data is licensed per user and
positions are confidential, so every grant needs an owner, a reason and a receipt. Each
table carries a monthly licence cost; the approver sees the £ before deciding.

Pitch line: *"On a trading desk, access to data costs money and creates compliance risk,
so every grant needs an owner, a reason and a receipt."*

## Who owns what

| Owner | Files | Job |
|---|---|---|
| **Jose + Malik (Codex)** | `app.py`, `db.py`, `app.yaml`, `requirements.txt` | The app: three pages, reads, UI, demo script |
| **Younis (+ Claude Code) + Patrick** | `governance.py`, `setup.sql`, `BACKEND.md` | Tables, tags, the grant logic, permissions, deploying the app |

Do not edit the other side's files. If you need a change there, say so to Younis.
`governance.py` does not exist yet: create `governance_stub.py` with the same signatures
(see Contract) and import through one line you can switch later:

```python
try:
    import governance
except ImportError:
    import governance_stub as governance
```

## Environment (verified 21 Oct, 17:30)

- Workspace: `https://dbc-ea0a1678-b98c.cloud.databricks.com`
- SQL warehouse: `hackathon-sandbox-bi`, id `a24300104bf8ac6c` (running)
- Catalogs: `hackathon_bronze`, `hackathon_silver`, `hackathon_gold`. Our schema in each is
  **`sierra`**. Group `hackathon_sierra` has ALL PRIVILEGES on those schemas.
- We **cannot** create new schemas or catalogs. Everything lives in `hackathon_gold.sierra`.
- App slots are limited (Free Edition, 2 of 3 used by organisers). **Only Younis deploys,
  once, then redeploys.** Never run `databricks apps create`.
- No Lakebase. Delta tables through the warehouse are enough.

## Contract (agreed, do not change without telling Younis)

### Tables (all in `hackathon_gold.sierra`, created by Younis's `setup.sql`)

Requestable data products (names final by 17:45; **never hard-code them**, discover them):

| Table | What it is | `sensitivity` | `licence_cost_gbp` |
|---|---|---|---|
| `eod_prices` | Real Yahoo + Nasdaq daily bars, 62 EM/GCC names | `licensed` | e.g. `120` |
| `positions` | Desk book: ticker, quantity, book | `confidential` | `0` |
| `vendor_faults` | Where the two vendors disagree | `internal` | `0` |

Every requestable table carries these Unity Catalog **tags**:
`data_owner` (approver email), `sensitivity`, `licence_cost_gbp`, `description`.
A table is requestable **only if it has a `data_owner` tag**. That is the whole
"catalogue" rule, and it is what makes the app reusable: tag a new table and it appears.

Discover them with:

```sql
SELECT table_name, tag_name, tag_value
FROM hackathon_gold.information_schema.table_tags
WHERE schema_name = 'sierra'
```

Pivot to one row per table in Python.

### Audit / request table

```sql
CREATE TABLE hackathon_gold.sierra.access_requests (
  id            STRING,     -- uuid4
  requester     STRING,     -- email
  table_name    STRING,     -- fully qualified, e.g. hackathon_gold.sierra.positions
  reason        STRING,
  licence_cost  DOUBLE,
  approver      STRING,     -- email, from the data_owner tag at request time
  status        STRING,     -- pending | approved | rejected | failed
  decided_by    STRING,
  decided_at    TIMESTAMP,
  note          STRING,     -- reject reason, or the GRANT error if status = failed
  requested_at  TIMESTAMP
)
```

This one table is both the queue and the audit trail. Rows are updated in place by
`governance.py` only; the app only reads it.

### `governance.py` signatures (Younis writes the real one; you stub it)

```python
def submit_request(requester: str, table_name: str, reason: str) -> str:
    """Insert a pending row (approver + cost read from tags). Returns request id.
    Raises ValueError if reason is blank, table is not requestable,
    or the requester already has a pending request for that table."""

def approve(request_id: str, decided_by: str, user_token: str | None) -> None:
    """Runs GRANT SELECT ON TABLE <t> TO `<requester>` and marks the row approved.
    If the GRANT fails, marks the row failed with the error in note, then raises."""

def reject(request_id: str, decided_by: str, note: str) -> None:
    """Marks the row rejected with note. Raises ValueError if note is blank."""
```

The stub should write nothing to Databricks: keep rows in `st.session_state` so the UI
can be built and demoed before 18:30.

### `db.py` (yours; governance.py will import it, so keep this signature)

```python
import os
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem

WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
_w = WorkspaceClient()

def run_sql(statement: str, params: dict | None = None) -> list[dict]:
    r = _w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement, wait_timeout="30s",
        parameters=[StatementParameterListItem(name=k, value=str(v))
                    for k, v in (params or {}).items()])
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(r.status.error.message if r.status.error else r.status.state)
    if not (r.manifest and r.manifest.schema and r.manifest.schema.columns):
        return []  # GRANT / UPDATE / INSERT return no result set
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]
```

Use `wait_timeout="50s"` (the maximum): with 30s a slow statement comes back RUNNING and
raises.

Tested live on 21 Oct (SDK 0.155). **Every value comes back as a string** (`'1'`, not
`1`): cast `licence_cost` with `float()` before summing. Values always go in as `:named` parameters. Table names cannot be parameters, so only
ever interpolate a table name that came back from the tag query above (an allowlist).

### Who is the user

```python
email = st.context.headers.get("X-Forwarded-Email") or os.getenv("DEV_USER")
token = st.context.headers.get("X-Forwarded-Access-Token")  # may be None
```

Locally there are no headers: set `DEV_USER` and add a sidebar "Act as" box **only when
`DEV_USER` is set**, so one laptop can play analyst and approver. It must not appear in
the deployed app.

## What to build

Three pages (Streamlit `st.navigation` or tabs). Dark, clean, finance-desk look; no
emoji clutter. Show the signed-in email top right.

1. **Catalogue / Request**: card or table per requestable asset: name, description,
   sensitivity badge, licence £/month, owner. "Request access" opens a reason box.
   Show the requester's own requests and their status underneath, with the reject note.
2. **Approvals**: pending requests where `approver = current user`. Each shows who,
   which table, reason, **£ cost per month**, age. Approve button; Reject needs a note.
   After a decision, show the result (success, or the GRANT error) and refresh.
3. **Audit**: all rows of `access_requests`, newest first, filter by status and table.
   Headline counts: pending, approved, rejected, £/month currently granted.

**Page 3 also gets a Genie box** (after AC-001 to AC-007 pass): a text input "Ask the
audit trail" that calls

```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
msg = w.genie.start_conversation_and_wait(os.environ["GENIE_SPACE_ID"], question)
att = next(a for a in msg.attachments if a.query)
res = w.genie.get_message_attachment_query_result(msg.space_id, msg.conversation_id, msg.id, att.attachment_id)
cols = [c.name for c in res.statement_response.manifest.schema.columns]
rows = res.statement_response.result.data_array or []
```

and renders `rows` as a dataframe, with `att.query.description` as a caption. If
`GENIE_SPACE_ID` is unset, hide the box. Offer three preset buttons with the exact
questions the backend tested (see `BACKEND.md` §4); free text is allowed but we only
press the presets live.

**Vague-reason badge** (page 2): `governance.submit_request` stores an `ai_classify`
label in `note` while the request is pending (`specific business need` or `vague`).
Show "vague reason" in amber when the note says `vague`.

Update 21:00: the app now has the `sql` user scope, so `db.py` runs SQL as the signed-in
user when a token is forwarded. Still no "run a query as the user" box: the SQL editor
is the denied-then-allowed money shot.

## Acceptance criteria

**AC-001 Catalogue is tag-driven** (Required)
Scenario: three tables in `hackathon_gold.sierra` carry a `data_owner` tag. Action: open
page 1. Expected: exactly those three appear with their four tag values; a table without
the tag does not appear. Must not: any table name hard-coded in `app.py`.
Verification: `grep -n "positions\|eod_prices" app.py` returns nothing; tag a fourth
table and it appears after refresh.

**AC-002 Request needs a reason** (Required)
Action: submit with an empty reason. Expected: inline error, no row written.
Verification: manual, then check `access_requests` row count unchanged.

**AC-003 Request lands with the right approver** (Required)
Action: analyst requests `positions` with a reason. Expected: a `pending` row whose
`approver` equals the table's `data_owner` tag and whose `licence_cost` matches the tag;
it appears on that approver's page 2 and on nobody else's.
Verification: manual with two identities (or "Act as" locally).

**AC-004 No duplicate pending requests** (Important)
Action: same user requests the same table twice. Expected: second attempt shows "already
pending", one row only.

**AC-005 Approve calls governance, shows the outcome** (Required)
Action: approver clicks Approve. Expected: `governance.approve(id, me, token)` is called
once; on success the row shows `approved`, on exception the error text is shown and the
row shows `failed`. Must not: the app itself running any GRANT/REVOKE SQL.
Verification: code review (only `governance.py` contains the word GRANT) + manual.

**AC-006 Reject needs a note and tells the requester** (Required)
Action: Reject with blank note is refused; with a note, the row is `rejected` and the
requester sees the note on page 1.

**AC-007 Audit is complete** (Required)
Expected: page 3 shows every row with requester, table, reason, cost, approver,
decided_by, decided_at, status, note. Verification: compare with
`SELECT count(*) FROM hackathon_gold.sierra.access_requests`.

**AC-008 Runs locally without Databricks headers** (Required)
`DEV_USER=you@x.com DATABRICKS_WAREHOUSE_ID=a24300104bf8ac6c streamlit run app.py`
starts and works with the stub. Verification: run it.

## Local setup for the friend

```bash
brew install databricks/tap/databricks   # if missing
databricks auth login --host https://dbc-ea0a1678-b98c.cloud.databricks.com --profile hack
python -m venv .venv && source .venv/bin/activate
pip install streamlit databricks-sdk
export DATABRICKS_CONFIG_PROFILE=hack DATABRICKS_WAREHOUSE_ID=a24300104bf8ac6c DEV_USER=<your email>
streamlit run app.py
```

## `app.yaml` and `requirements.txt` (deployed by Younis)

```yaml
command: ["streamlit", "run", "app.py"]
env:
  - name: DATABRICKS_WAREHOUSE_ID
    value: a24300104bf8ac6c
  - name: GENIE_SPACE_ID
    value: 01f1cd6fabb61c01a2d9f522b79791d0
```

(Attaching the warehouse as a resource needs MANAGE on it, which we don't have, so the
id is a plain value and the SP gets CAN_USE from a mentor.)

`requirements.txt`: `databricks-sdk` only (Streamlit is in the Apps runtime). No other
dependencies without asking.

## Out of scope tonight

Email or Teams notifications, expiring access, column masks, Lakebase, a second app,
login screens (Databricks Apps does auth), Genie. Stretch only if everything above passes.

## Blocking question (Younis is resolving with the mentors)

The demo needs a requester who is **denied** first. Anyone in `hackathon_sierra` already
has ALL PRIVILEGES on the schema, so they can never be denied. The requester for the demo
must be an account **outside** that group. Until that is settled, build against the stub.

## Timeline

| Time | You | Younis |
|---|---|---|
| 17:45 | Stub + `db.py` + page 1 against the stub | Tables, tags, `access_requests` live |
| 18:30 | Pages 2 and 3; switch page 1 to live tag query | `governance.py` handed over |
| 19:15 | Swap stub for real `governance.py`, merge | Deploy app, grant its service principal access |
| 19:45 | **Freeze.** Rehearse twice | Rehearse twice |

## Demo script (5 minutes, you drive the app)

1. (30s) The problem: on a desk, data access is a ticket and an email chain; nobody can
   say who has what, why, or what it costs.
2. (30s) Analyst runs `SELECT * FROM positions` in the SQL editor: **permission denied.**
3. (60s) Page 1: catalogue built from Unity Catalog tags. Request `positions`, reason
   "intraday risk report". Point out: approver was found from the tag, not hard-coded.
4. (60s) Page 2 as the desk head: sees the reason and the £/month. Approve.
5. (30s) Same query again: **it works.** The grant is real Unity Catalog, not an app flag.
6. (60s) Page 3: the audit trail. Reuse: "tag any table with `data_owner` and it is in
   the catalogue; no code change."
7. (30s) What's next: expiring access, Teams notifications, chargeback by cost centre.
