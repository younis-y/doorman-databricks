"""Governance side of Desk Data Access: request, approve (real GRANT), reject, revoke.

Everything runs as the app's service principal through db.run_sql. Values travel as
:named parameters; identifiers (table names, principals) are validated first.
"""
import os
import re
import uuid

from db import run_sql

CATALOG = os.getenv("DATA_CATALOG", "hackathon_gold")
SCHEMA = os.getenv("DATA_SCHEMA", "sierra")
REQUESTS = f"{CATALOG}.{SCHEMA}.access_requests"
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def requestable() -> dict[str, dict]:
    """{fully.qualified.table: {tag: value}} for every table carrying a data_owner tag."""
    rows = run_sql(
        f"SELECT table_name, tag_name, tag_value FROM {CATALOG}.information_schema.table_tags "
        "WHERE schema_name = :s",
        {"s": SCHEMA},
    )
    tags: dict[str, dict] = {}
    for r in rows:
        tags.setdefault(f"{CATALOG}.{SCHEMA}.{r['table_name']}", {})[r["tag_name"]] = r["tag_value"]
    return {t: v for t, v in tags.items() if v.get("data_owner")}


def _principal(email: str) -> str:
    if not EMAIL.match(email or ""):
        raise ValueError(f"not an email: {email!r}")
    return f"`{email}`"


def _row(request_id: str) -> dict:
    rows = run_sql(f"SELECT * FROM {REQUESTS} WHERE id = :id", {"id": request_id})
    if not rows:
        raise ValueError(f"no request {request_id}")
    return rows[0]


def _decide(request_id: str, decided_by: str, status: str, note: str) -> None:
    run_sql(
        f"UPDATE {REQUESTS} SET status = :st, decided_by = :by, decided_at = current_timestamp(), "
        "note = :note WHERE id = :id",
        {"st": status, "by": decided_by, "note": note, "id": request_id},
    )


def submit_request(requester: str, table_name: str, reason: str) -> str:
    """Insert a pending row (approver + cost read from tags). Returns the request id."""
    if not (reason or "").strip():
        raise ValueError("a reason is required")
    _principal(requester)
    tags = requestable().get(table_name)
    if not tags:
        raise ValueError(f"{table_name} is not requestable (no data_owner tag)")
    dup = run_sql(
        f"SELECT 1 FROM {REQUESTS} WHERE requester = :r AND table_name = :t AND status = 'pending'",
        {"r": requester, "t": table_name},
    )
    if dup:
        raise ValueError("you already have a pending request for this table")
    rid = str(uuid.uuid4())
    params = {"id": rid, "r": requester, "t": table_name, "reason": reason.strip(),
              "cost": tags.get("licence_cost_gbp", "0"), "appr": tags["data_owner"]}
    insert = (f"INSERT INTO {REQUESTS} SELECT :id, :r, :t, :reason, CAST(:cost AS DOUBLE), :appr, "
              "'pending', NULL, NULL, {label}, current_timestamp()")
    try:
        run_sql(insert.format(label="ai_classify(:reason, ARRAY('specific business need', 'vague'))"), params)
    except Exception:  # noqa: BLE001 - the AI label is a nice-to-have; the request must land
        run_sql(insert.format(label="NULL"), params)
    return rid


def _check_pending(row: dict, decided_by: str) -> None:
    if row["status"] != "pending":
        raise ValueError(f"request is already {row['status']}")
    if row["approver"] != decided_by:
        raise PermissionError(f"only {row['approver']} can decide this request")


def approve(request_id: str, decided_by: str, user_token: str | None = None) -> None:
    """GRANT USE SCHEMA + SELECT to the requester, then mark approved. On failure mark failed and raise."""
    row = _row(request_id)
    _check_pending(row, decided_by)
    if row["table_name"] not in requestable():
        raise ValueError(f"{row['table_name']} is no longer requestable")
    who = _principal(row["requester"])
    try:
        run_sql(f"GRANT SELECT ON TABLE {row['table_name']} TO {who}")
        run_sql(f"GRANT USE SCHEMA ON SCHEMA {CATALOG}.{SCHEMA} TO {who}")
    except Exception as e:  # noqa: BLE001 - the audit row must record whatever went wrong
        _decide(request_id, decided_by, "failed", f"GRANT failed: {e}"[:1000])
        raise
    _decide(request_id, decided_by, "approved", "granted SELECT")


def reject(request_id: str, decided_by: str, note: str) -> None:
    if not (note or "").strip():
        raise ValueError("a reason for rejecting is required")
    _check_pending(_row(request_id), decided_by)
    _decide(request_id, decided_by, "rejected", note.strip())


def revoke(request_id: str, decided_by: str) -> None:
    """REVOKE the grant behind an approved request (used by the demo reset, not the UI)."""
    row = _row(request_id)
    if row["status"] != "approved":
        raise ValueError("only approved requests can be revoked")
    who = _principal(row["requester"])
    run_sql(f"REVOKE SELECT ON TABLE {row['table_name']} FROM {who}")
    still = run_sql(
        f"SELECT 1 FROM {REQUESTS} WHERE requester = :r AND status = 'approved' AND id <> :id",
        {"r": row["requester"], "id": request_id},
    )
    if not still:
        run_sql(f"REVOKE USE SCHEMA ON SCHEMA {CATALOG}.{SCHEMA} FROM {who}")
    _decide(request_id, decided_by, "revoked", "revoked SELECT")
