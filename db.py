"""Thin SQL helper over the Databricks Statement Execution API.

Shared with governance.py: keep the run_sql signature stable. Every value comes back
as a string; callers cast what they need.

LOCAL_DB=<path> runs the same queries against a SQLite file instead (built from
local/*.csv on first use), so the app runs with no Databricks at all. Three-part
names (catalog.schema.table) lose their first two parts, which is all the local
queries need: the tag lookup and the CSV download.
"""
import os
import re
import sqlite3
from pathlib import Path

LOCAL_DB = os.getenv("LOCAL_DB")

if not LOCAL_DB:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementParameterListItem

    WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
    _w = WorkspaceClient()


def _user_token() -> str | None:
    """The signed-in user's token, forwarded by Databricks Apps when the app has the `sql`
    user scope. Absent locally and in tests."""
    try:
        import streamlit as st
        return st.context.headers.get("X-Forwarded-Access-Token") or None
    except Exception:  # noqa: BLE001 - no Streamlit context
        return None


def client():
    """Runs as the signed-in user when their token is forwarded (so grants, reads and Genie
    carry their identity and their Unity Catalog rights); otherwise as the app's service
    principal."""
    if LOCAL_DB:
        raise RuntimeError("no Databricks client in local mode")
    tok = _user_token()
    if tok:
        return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=tok, auth_type="pat")
    return _w


def _run_local(statement: str, params: dict | None) -> list[dict]:
    path = Path(LOCAL_DB)
    if not path.exists():
        from local.build import build
        build(path)
    statement = re.sub(r"\b\w+\.\w+\.(\w+)\b", r"\1", statement)
    with sqlite3.connect(path) as con:
        cur = con.execute(statement, params or {})
        cols = [c[0] for c in cur.description or []]
        rows = [dict(zip(cols, (None if v is None else str(v) for v in row))) for row in cur]
    con.close()
    return rows


def run_sql(statement: str, params: dict | None = None) -> list[dict]:
    if LOCAL_DB:
        return _run_local(statement, params)
    r = client().statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement, wait_timeout="50s",
        parameters=[StatementParameterListItem(name=k, value=str(v))
                    for k, v in (params or {}).items()])
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(r.status.error.message if r.status.error else r.status.state)
    if not (r.manifest and r.manifest.schema and r.manifest.schema.columns):
        return []  # GRANT / UPDATE / INSERT return no result set
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]
