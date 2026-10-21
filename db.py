"""Thin SQL helper over the Databricks Statement Execution API.

Shared with governance.py: keep the run_sql signature stable. Every value comes back
as a string; callers cast what they need.
"""
import os

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


def client() -> WorkspaceClient:
    """Runs as the signed-in user when their token is forwarded (so grants, reads and Genie
    carry their identity and their Unity Catalog rights); otherwise as the app's service
    principal."""
    tok = _user_token()
    if tok:
        return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=tok, auth_type="pat")
    return _w


def run_sql(statement: str, params: dict | None = None) -> list[dict]:
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
