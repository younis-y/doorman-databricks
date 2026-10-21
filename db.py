"""Thin SQL helper over the Databricks Statement Execution API.

Shared with governance.py: keep the run_sql signature stable. Every value comes back
as a string; callers cast what they need.
"""
import os

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem

WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
_w = WorkspaceClient()


def client() -> WorkspaceClient:
    """The shared workspace client (used by the app for Genie)."""
    return _w


def run_sql(statement: str, params: dict | None = None) -> list[dict]:
    r = _w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement, wait_timeout="50s",
        parameters=[StatementParameterListItem(name=k, value=str(v))
                    for k, v in (params or {}).items()])
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(r.status.error.message if r.status.error else r.status.state)
    if not (r.manifest and r.manifest.schema and r.manifest.schema.columns):
        return []  # GRANT / UPDATE / INSERT return no result set
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]
