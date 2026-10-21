"""Offline AppTest checks for the UI against governance_stub (no Databricks calls).

Run: .venv/bin/python -m pytest -q tests
"""
import os
import sys
import types

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_md5

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")
OWNER = "owner@desk.com"
ANALYST = "analyst@desk.com"
TAGS = [
    ("eod_prices", "data_owner", OWNER), ("eod_prices", "sensitivity", "licensed"),
    ("eod_prices", "licence_cost_gbp", "120"), ("eod_prices", "description", "EOD bars"),
    ("positions", "data_owner", OWNER), ("positions", "sensitivity", "confidential"),
    ("positions", "licence_cost_gbp", "0"), ("positions", "description", "Desk book"),
    ("vendor_faults", "data_owner", "other.owner@desk.com"), ("vendor_faults", "sensitivity", "internal"),
    ("vendor_faults", "licence_cost_gbp", "0"), ("vendor_faults", "description", "Vendor faults"),
    ("scratch", "sensitivity", "internal"),  # no data_owner: must not appear
]
CALLS = []


def fake_run_sql(statement, params=None):
    CALLS.append(statement)
    if "table_tags" in statement:
        return [{"table_name": t, "tag_name": k, "tag_value": v} for t, k, v in TAGS]
    raise AssertionError(f"unexpected SQL in stub mode: {statement}")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    fake = types.ModuleType("db")
    fake.run_sql = fake_run_sql
    fake.client = lambda: None
    monkeypatch.setitem(sys.modules, "db", fake)
    monkeypatch.setenv("DEV_USER", ANALYST)
    monkeypatch.setenv("DEV_TOOLS", "1")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "test")
    monkeypatch.delenv("GENIE_SPACE_ID", raising=False)
    monkeypatch.delenv("STUB_FAIL_GRANT", raising=False)
    sys.modules.pop("governance_stub", None)
    CALLS.clear()


def run(at=None):
    at = at or AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def goto(at, url_path):
    """switch_page only knows file pages; callable pages are keyed by md5(url_path)."""
    at._page_hash = calc_md5(url_path)
    return at


def select_asset(at, row):
    """Pick a data product in the Request access dropdown (0 = eod_prices, 1 = positions)."""
    table = ["hackathon_gold.sierra.eod_prices", "hackathon_gold.sierra.positions",
             "hackathon_gold.sierra.vendor_faults"][row]
    at.selectbox(key="product_pick").set_value(table)
    return run(at)


def click(at, label, row=None):
    next(b for b in at.button if b.label == label).click()
    return run(at)


def stub_rows(at):
    return at.session_state["_stub_access_requests"]


def test_catalogue_is_tag_driven():
    at = run()
    df = at.dataframe[0].value
    assert list(df["Asset"]) == ["eod_prices", "positions", "vendor_faults"]
    assert "scratch" not in df["Asset"].tolist()
    assert not any("Local" in m.value for m in at.markdown)
    src = open(APP).read()
    assert "positions" not in src and "eod_prices" not in src  # AC-001 grep
    assert "GRANT" not in src and "REVOKE" not in src  # AC-005: only governance grants


def test_blank_reason_refused_and_request_lands_with_owner():
    at = select_asset(run(), 1)  # positions
    at = click(at, "Request access", 1)  # empty reason
    assert any("Add a reason" in e.value for e in at.error)
    assert stub_rows(at) == []
    at.text_area[0].input("Intraday risk report for the EM book")
    at = click(at, "Request access", 1)
    rows = stub_rows(at)
    assert len(rows) == 1 and rows[0]["approver"] == OWNER and rows[0]["status"] == "pending"
    assert rows[0]["licence_cost"] == "0.0"
    # AC-004: while pending the card swaps the form for the tracker, so it can't be sent twice
    assert not any(b.label == "Request access" for b in at.button)
    assert any("Waiting on" in m.value for m in at.markdown)


def _request_as_analyst(at, row=0, reason="Pricing the GCC basket for the morning call"):
    at = select_asset(at, row)
    at.text_area[0].input(reason)
    return click(at, "Request access", row)


def _switch(at, who, page):
    at.sidebar.selectbox[0].select(who)
    at = run(at)
    goto(at, page)
    return run(at)


def test_approver_sees_and_approves_once():
    at = _request_as_analyst(run())
    # analyst has no approvals
    goto(at, "approvals")
    at = run(at)
    assert any("Nothing waiting on you" in m.value for m in at.markdown)
    at = _switch(at, OWNER, "approvals")
    assert any("£120" in m.value for m in at.markdown)
    at = click(at, "Approve access")
    assert stub_rows(at)[0]["status"] == "approved"
    assert any("Access granted" in s.value for s in at.success)


def test_failed_grant_shows_error(monkeypatch):
    monkeypatch.setenv("STUB_FAIL_GRANT", "1")
    at = _request_as_analyst(run())
    at = _switch(at, OWNER, "approvals")
    at = click(at, "Approve access")
    assert stub_rows(at)[0]["status"] == "failed"
    assert any("Grant failed" in e.value and "PERMISSION_DENIED" in e.value for e in at.error)


def test_reject_needs_note_and_requester_sees_it():
    at = _request_as_analyst(run(), 1, "stuff")
    at = _switch(at, OWNER, "approvals")
    assert any("Vague reason" in m.value for m in at.markdown)
    at = click(at, "Reject request")
    assert stub_rows(at)[0]["status"] == "pending"
    at.text_input[0].input("Use the delayed feed instead")
    at = click(at, "Reject request")
    assert stub_rows(at)[0]["status"] == "rejected"
    at = _switch(at, ANALYST, "catalogue")
    mine = at.dataframe[-1].value
    assert "Use the delayed feed instead" in mine["Note from approver"].tolist()


def test_audit_is_complete():
    at = _request_as_analyst(run())
    at = _request_as_analyst(at, 1, "Intraday risk report for the EM book")
    goto(at, "audit")
    at = run(at)
    df = at.dataframe[0].value
    assert len(df) == 2
    for col in ["Requester", "Table", "Reason", "£ / month", "Approver", "Decided by",
                "Decided at", "Status", "Note"]:
        assert col in df.columns
    assert [m.value for m in at.metric][:2] == ["2", "0"]


def test_genie_hidden_without_space():
    at = run()
    goto(at, "audit")
    at = run(at)
    assert not any("Ask the audit trail" in getattr(h, "value", "") for h in at.subheader)


def test_no_act_as_without_dev_user(monkeypatch):
    monkeypatch.delenv("DEV_USER")
    monkeypatch.setenv("GOVERNANCE", "stub")
    at = run()
    assert len(at.sidebar.selectbox) == 0
    assert any("Not signed in" in m.value for m in at.markdown)


def test_revoke_from_approvals():
    at = _request_as_analyst(run())
    at = _switch(at, OWNER, "approvals")
    at = click(at, "Approve access")
    assert any("Active access you own" in h.value for h in at.subheader)
    at = click(at, "Confirm revoke")
    assert stub_rows(at)[0]["status"] == "revoked"
    assert any("Access revoked" in s.value for s in at.success)


def test_tracker_states_for_requester():
    at = _request_as_analyst(run())
    assert any("Waiting on" in m.value for m in at.markdown)
    at = _switch(at, OWNER, "approvals")
    at = click(at, "Approve access")
    at = _switch(at, ANALYST, "catalogue")
    at = select_asset(at, 0)
    card = next(m.value for m in at.markdown if 'class="group"' in m.value)
    assert "d-approved" in card and "Granted by" in card and 'prog approved' in card
    assert any("SELECT * FROM hackathon_gold.sierra.eod_prices" in c.value for c in at.code)


def test_requests_route_to_each_tables_own_owner():
    at = _request_as_analyst(run(), 2, "Reconcile vendor breaks for the morning call")
    assert stub_rows(at)[0]["approver"] == "other.owner@desk.com"
    at = _switch(at, OWNER, "approvals")
    assert not any(b.label == "Approve access" for b in at.button)
    at = _switch(at, "other.owner@desk.com", "approvals")
    assert any(b.label == "Approve access" for b in at.button)


def test_act_as_hidden_without_dev_tools(monkeypatch):
    monkeypatch.delenv("DEV_TOOLS")
    at = run()
    assert len(at.sidebar.selectbox) == 0
