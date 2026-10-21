"""Local stand-in for governance.py. Same signatures, writes nothing to Databricks.

Requests live in st.session_state, so one browser session can play analyst and
approver with the sidebar "Act as" box. Tags are still read live (read-only) so the
approver and cost come from Unity Catalog exactly as in the real module.

Set STUB_FAIL_GRANT=1 to rehearse the failed-grant path.
"""
import os
import re
import uuid
from datetime import datetime, timezone

import streamlit as st

CATALOG = os.getenv("DATA_CATALOG", "hackathon_gold")
SCHEMA = os.getenv("DATA_SCHEMA", "sierra")
SIMULATED = True
_KEY = "_stub_access_requests"
_VAGUE = re.compile(r"^(need(ed)?|want(ed)?|for work|work|access|pls|please|asap|testing?|"
                    r"just (looking|checking)|curious|n/?a|-+|\.+|stuff|data)\W*$", re.I)


def _rows() -> list[dict]:
    return st.session_state.setdefault(_KEY, [])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _classify(reason: str) -> str:
    """Rough stand-in for ai_classify(reason, ARRAY('specific business need', 'vague'))."""
    words = reason.split()
    return "vague" if len(words) < 3 or _VAGUE.match(reason.strip()) else "specific business need"


def requestable() -> dict[str, dict]:
    from db import run_sql  # read-only tag lookup
    rows = run_sql(
        f"SELECT table_name, tag_name, tag_value FROM {CATALOG}.information_schema.table_tags "
        "WHERE schema_name = :s",
        {"s": SCHEMA},
    )
    tags: dict[str, dict] = {}
    for r in rows:
        tags.setdefault(f"{CATALOG}.{SCHEMA}.{r['table_name']}", {})[r["tag_name"]] = r["tag_value"]
    return {t: v for t, v in tags.items() if v.get("data_owner")}


def list_requests() -> list[dict]:
    """All simulated rows, newest first, with every value as a string like the SQL API."""
    return [dict(r) for r in sorted(_rows(), key=lambda r: r["requested_at"], reverse=True)]


def _row(request_id: str) -> dict:
    for r in _rows():
        if r["id"] == request_id:
            return r
    raise ValueError(f"no request {request_id}")


def _check_pending(row: dict, decided_by: str) -> None:
    if row["status"] != "pending":
        raise ValueError(f"request is already {row['status']}")
    if row["approver"] != decided_by:
        raise PermissionError(f"only {row['approver']} can decide this request")


def _decide(row: dict, decided_by: str, status: str, note: str) -> None:
    row.update(status=status, decided_by=decided_by, decided_at=_now(), note=note)


def submit_request(requester: str, table_name: str, reason: str) -> str:
    if not (reason or "").strip():
        raise ValueError("a reason is required")
    tags = requestable().get(table_name)
    if not tags:
        raise ValueError(f"{table_name} is not requestable (no data_owner tag)")
    if any(r["requester"] == requester and r["table_name"] == table_name and r["status"] == "pending"
           for r in _rows()):
        raise ValueError("you already have a pending request for this table")
    rid = str(uuid.uuid4())
    _rows().append({
        "id": rid, "requester": requester, "table_name": table_name, "reason": reason.strip(),
        "licence_cost": str(float(tags.get("licence_cost_gbp") or 0)), "approver": tags["data_owner"],
        "status": "pending", "decided_by": None, "decided_at": None,
        "note": _classify(reason.strip()), "requested_at": _now(),
    })
    return rid


def approve(request_id: str, decided_by: str, user_token: str | None = None) -> None:
    row = _row(request_id)
    _check_pending(row, decided_by)
    if os.getenv("STUB_FAIL_GRANT"):
        err = (f"[PERMISSION_DENIED] User does not have MANAGE on Table '{row['table_name']}'. "
               "(simulated)")
        _decide(row, decided_by, "failed", f"GRANT failed: {err}")
        raise RuntimeError(err)
    _decide(row, decided_by, "approved", "granted SELECT (simulated)")


def reject(request_id: str, decided_by: str, note: str) -> None:
    if not (note or "").strip():
        raise ValueError("a reason for rejecting is required")
    row = _row(request_id)
    _check_pending(row, decided_by)
    _decide(row, decided_by, "rejected", note.strip())


def revoke(request_id: str, decided_by: str) -> None:
    row = _row(request_id)
    if row["status"] != "approved":
        raise ValueError("only approved requests can be revoked")
    _decide(row, decided_by, "revoked", f"revoked {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z (simulated)")
