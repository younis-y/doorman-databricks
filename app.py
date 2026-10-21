"""Desk Data Access: request, approve and audit access to Unity Catalog tables.

Reads only. Every change goes through governance (submit_request / approve / reject).
The catalogue is whatever carries a data_owner tag; no table names live in this file.
"""
import html
import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

DEV_USER = os.getenv("DEV_USER")

# Local runs with DEV_USER default to the stub so nothing touches Unity Catalog.
# GOVERNANCE=live forces the real module, GOVERNANCE=stub forces the simulation.
_mode = os.getenv("GOVERNANCE", "stub" if DEV_USER else "live")
if _mode == "stub":
    import governance_stub as governance
else:
    try:
        import governance
    except ImportError:
        import governance_stub as governance
SIMULATED = getattr(governance, "SIMULATED", False)

from db import client, run_sql  # noqa: E402  (after the governance switch on purpose)

CATALOG = os.getenv("DATA_CATALOG", "hackathon_gold")
SCHEMA = os.getenv("DATA_SCHEMA", "sierra")
REQUESTS = f"{CATALOG}.{SCHEMA}.access_requests"
GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "").strip()
DESK_TZ = os.getenv("DESK_TZ", "Europe/London")
STATUSES = ["pending", "approved", "rejected", "failed", "revoked"]
# Dropdown grouping when a table has no `domain` tag. Tag `domain` to override.
SENSITIVITY_DESK = {"licensed": "Market data", "confidential": "Trading book", "internal": "Operations"}
CATALOGUE_COLS = ["table", "asset", "description", "sensitivity", "owner", "cost", "domain"]
REQUEST_COLS = ["id", "requester", "table_name", "reason", "licence_cost", "approver", "status",
                "decided_by", "decided_at", "note", "requested_at"]
# The exact questions the backend validated in the Genie space (BACKEND.md section 4).
with open(os.path.join(os.path.dirname(__file__), "genie_presets.json")) as _f:
    GENIE_PRESETS: list[str] = json.load(_f)

st.set_page_config(page_title="Desk Data Access", layout="wide", initial_sidebar_state="expanded")

# --------------------------------------------------------------------------- look

st.markdown("""
<style>
:root {
  --navy: #0B1422; --slate: #131F33; --slate-2: #1A2840; --rule: #22324B;
  --ink: #E4EAF4; --muted: #9AABC3; --blue: #3D7EFF; --blue-ink: #8DB4FF;
  --green: #4CC38A; --amber: #F2B65A; --red: #FF7A80;
}
.stApp { background: var(--navy); }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding-top: 1.6rem; max-width: 1280px; }
section[data-testid="stSidebar"] { background: var(--slate); border-right: 1px solid var(--rule); }
*:focus-visible { outline: 2px solid var(--blue-ink) !important; outline-offset: 2px; }
h1, h2, h3 { letter-spacing: -0.01em; }
.num { font-variant-numeric: tabular-nums; }

.dda-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem;
  flex-wrap: wrap; padding-bottom: .9rem; margin-bottom: 1.1rem; border-bottom: 1px solid var(--rule); }
.dda-title { font-size: 1.35rem; font-weight: 650; color: var(--ink); line-height: 1.2; }
.dda-sub { color: var(--muted); font-size: .92rem; margin-top: .15rem; }
.dda-who { text-align: right; color: var(--muted); font-size: .85rem; line-height: 1.35; }
.dda-who b { color: var(--ink); font-weight: 600; font-size: .95rem; }
@media (max-width: 640px) { .dda-who { text-align: left; } .quote { text-align: left; } }
.dda-sim { border: 1px solid rgba(242,182,90,.45); background: rgba(242,182,90,.08); color: var(--amber);
  padding: .45rem .8rem; border-radius: 8px; font-size: .88rem; margin: -.3rem 0 1.1rem; }

.badge { display: inline-block; padding: .08rem .5rem; border-radius: 6px; font-size: .78rem;
  font-weight: 600; border: 1px solid currentColor; line-height: 1.5; white-space: nowrap; }
.b-confidential, .b-rejected, .b-failed { color: var(--red); background: rgba(255,122,128,.10); }
.b-licensed { color: var(--blue-ink); background: rgba(61,126,255,.12); }
.b-internal, .b-revoked, .b-other { color: var(--muted); background: rgba(154,171,195,.10); }
.b-pending, .b-vague { color: var(--amber); background: rgba(242,182,90,.10); }
.b-approved { color: var(--green); background: rgba(76,195,138,.10); }

.asset { font-size: 1.15rem; font-weight: 650; color: var(--ink); }
.fq { color: var(--muted); font-size: .82rem; font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.desc { color: var(--ink); margin: .45rem 0 .3rem; max-width: 70ch; }
.meta { color: var(--muted); font-size: .88rem; }
.meta b { color: var(--ink); font-weight: 600; }
.reason { border-left: 2px solid var(--rule); padding: .1rem 0 .1rem .75rem; margin: .55rem 0;
  color: var(--ink); max-width: 70ch; }

.quote { text-align: right; }
.quote .amt { font-size: 2.1rem; font-weight: 650; color: var(--ink); line-height: 1.05;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.quote .amt.zero { color: var(--muted); }
.quote .per { color: var(--muted); font-size: .82rem; }

.b-acc-approved { color: var(--green); background: rgba(76,195,138,.10); }
.b-acc-pending { color: var(--amber); background: rgba(242,182,90,.10); }
.b-acc-rejected, .b-acc-failed { color: var(--red); background: rgba(255,122,128,.10); }
.b-acc-none, .b-acc-revoked { color: var(--muted); background: rgba(154,171,195,.10); }

.track { display: flex; align-items: flex-start; gap: .6rem; margin: 1rem 0 .8rem; flex-wrap: wrap; }
.step { display: flex; gap: .55rem; align-items: flex-start; min-width: 9.5rem; }
.step b { display: block; color: var(--ink); font-size: .9rem; font-weight: 600; }
.step small { display: block; color: var(--muted); font-size: .8rem; }
.step .dot { width: 12px; height: 12px; border-radius: 50%; margin-top: .3rem; flex: none;
  border: 2px solid var(--rule); background: var(--navy); }
.step.done .dot { background: var(--green); border-color: var(--green); }
.step.now .dot { background: var(--amber); border-color: var(--amber);
  box-shadow: 0 0 0 4px rgba(242,182,90,.18); }
.step.bad .dot { background: var(--red); border-color: var(--red); }
.step.todo b { color: var(--muted); }
.bar { flex: 1; min-width: 1.5rem; height: 2px; background: var(--rule); margin-top: .62rem; }
.bar.done { background: var(--green); }
@media (prefers-reduced-motion: no-preference) {
  .step.now .dot { animation: pulse 1.8s ease-in-out infinite; }
  @keyframes pulse { 50% { box-shadow: 0 0 0 7px rgba(242,182,90,.05); } }
}
.state { border-radius: 8px; padding: .6rem .85rem; margin: .2rem 0 .6rem; font-size: .92rem;
  color: var(--ink); border: 1px solid var(--rule); max-width: 80ch; }
.s-pending { border-color: rgba(242,182,90,.45); background: rgba(242,182,90,.07); }
.s-approved { border-color: rgba(76,195,138,.45); background: rgba(76,195,138,.07); }
.s-rejected, .s-failed { border-color: rgba(255,122,128,.45); background: rgba(255,122,128,.07); }
.s-revoked { background: rgba(154,171,195,.07); }

.empty { color: var(--muted); border: 1px dashed var(--rule); border-radius: 10px; padding: 1.1rem 1.2rem; }
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; font-weight: 650; }
[data-testid="stMetric"] { background: var(--slate); border: 1px solid var(--rule); border-radius: 10px;
  padding: .75rem .95rem; }
</style>
""", unsafe_allow_html=True)


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def badge(text: str, kind: str | None = None) -> str:
    kind = (kind or text or "other").lower().replace(" ", "-")
    return f'<span class="badge b-{esc(kind)}">{esc(text)}</span>'


def money(v: float) -> str:
    return f"£{v:,.0f}" if float(v).is_integer() else f"£{v:,.2f}"


def short(table: str) -> str:
    return str(table).rsplit(".", 1)[-1]


def ago(ts) -> str:
    if ts is None or pd.isna(ts):
        return "unknown"
    mins = int((datetime.now(timezone.utc) - ts.to_pydatetime()).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    if mins < 60 * 24:
        return f"{mins // 60} h {mins % 60} min ago"
    return f"{mins // (60 * 24)} days ago"


def _ts(s: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(s, utc=True, errors="coerce", format="ISO8601")
    except (TypeError, ValueError):
        return pd.to_datetime(s, utc=True, errors="coerce")


def local(s: pd.Series) -> pd.Series:
    """Desk time for display; the log itself stays in UTC."""
    return s.dt.tz_convert(DESK_TZ)


def status_style(v: str) -> str:
    c = {"pending": "#F2B65A", "approved": "#4CC38A", "granted": "#4CC38A", "rejected": "#FF7A80",
         "failed": "#FF7A80", "grant failed": "#FF7A80", "confidential": "#FF7A80",
         "licensed": "#8DB4FF"}.get(str(v).lower())
    return f"color: {c}; font-weight: 600" if c else "color: #9AABC3"


def when(t) -> str:
    return "" if t is None or pd.isna(t) else t.strftime("%d %b %Y, %H:%M:%S")


def styled(df: pd.DataFrame, cols: list[str]):
    """Colour status-like columns. A Styler's display values override column_config formats,
    so money and times are formatted here too."""
    s = df.style
    fn = getattr(s, "map", None) or s.applymap
    fmt = {c: money for c in df.columns if c.startswith("£")}
    fmt |= {c: when for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])}
    return fn(status_style, subset=cols).format(na_rep="").format(fmt, na_rep="")


# --------------------------------------------------------------------------- data

@st.cache_data(ttl=60, show_spinner=False)
def load_catalogue() -> pd.DataFrame:
    """One row per table with a data_owner tag, straight from governance.requestable()."""
    out = [{
        "table": table,
        "asset": short(table),
        "description": t.get("description", ""),
        "sensitivity": (t.get("sensitivity") or "unclassified").lower(),
        "owner": t["data_owner"],
        "cost": float(t.get("licence_cost_gbp") or 0),
        "domain": t.get("domain", ""),
    } for table, t in sorted(governance.requestable().items())]
    return pd.DataFrame(out, columns=CATALOGUE_COLS)


@st.cache_data(ttl=15, show_spinner=False)
def _live_requests() -> list[dict]:
    return run_sql(f"SELECT * FROM {REQUESTS} ORDER BY requested_at DESC")


def load_requests() -> pd.DataFrame:
    rows = governance.list_requests() if SIMULATED else _live_requests()
    df = pd.DataFrame(rows, columns=REQUEST_COLS)
    df["licence_cost"] = pd.to_numeric(df["licence_cost"], errors="coerce").fillna(0.0)
    df["requested_at"] = _ts(df["requested_at"])
    df["decided_at"] = _ts(df["decided_at"])
    df["status"] = df["status"].fillna("").str.lower()
    return df.sort_values("requested_at", ascending=False, na_position="last").reset_index(drop=True)


def refresh() -> None:
    load_catalogue.clear()
    _live_requests.clear()


def friendly(e: Exception) -> str:
    msg = str(e).strip() or e.__class__.__name__
    return msg[0].upper() + msg[1:]


# --------------------------------------------------------------------------- identity

headers = st.context.headers
forwarded = headers.get("X-Forwarded-Email")
TOKEN = headers.get("X-Forwarded-Access-Token")

CATALOGUE_ERROR = REQ_ERROR = None
try:
    CATALOGUE = load_catalogue()
except Exception as e:  # noqa: BLE001 - shown on screen
    CATALOGUE, CATALOGUE_ERROR = pd.DataFrame(columns=CATALOGUE_COLS), e
try:
    REQ = load_requests()
except Exception as e:  # noqa: BLE001 - shown on screen
    REQ, REQ_ERROR = pd.DataFrame(columns=REQUEST_COLS), e

ME = forwarded or DEV_USER
if DEV_USER and not forwarded:  # local only: never rendered behind Databricks Apps auth
    people = [DEV_USER, *CATALOGUE["owner"].tolist(),
              *(REQ["requester"].tolist() if not REQ.empty else [])]
    people = list(dict.fromkeys(p for p in people if p))
    with st.sidebar:
        st.markdown("**Act as**")
        pick = st.selectbox("Act as", people + ["Someone else"], key="act_as",
                            label_visibility="collapsed",
                            help="Local only. Switch between analyst and data owner.")
        if pick == "Someone else":
            ME = st.text_input("Email", key="act_as_other", placeholder="analyst@desk.com").strip() or None
        else:
            ME = pick
        st.caption("Local development only. Hidden in the deployed app.")
        st.divider()

with st.sidebar:
    if st.button("Refresh data", use_container_width=True,
                 help="Re-read Unity Catalog tags and the request log"):
        refresh()
        st.rerun()

st.markdown(f"""
<div class="dda-head">
  <div>
    <div class="dda-title">Desk Data Access</div>
    <div class="dda-sub">Market-data entitlements, owned, reasoned and recorded in Unity Catalog</div>
  </div>
  <div class="dda-who">{'Signed in as<br><b>' + esc(ME) + '</b>' if ME else
                        '<b>Not signed in</b><br>Requests and decisions are disabled'}</div>
</div>
{'<div class="dda-sim">Local simulation — no access permissions changed</div>' if SIMULATED else ''}
""", unsafe_allow_html=True)

if REQ_ERROR is not None:
    st.error(f"Couldn't read the request log ({REQUESTS}): {friendly(REQ_ERROR)}. "
             "Check the SQL warehouse is running, then choose Refresh data.")


def flash(slot: str) -> None:
    """Show (and keep) the last outcome stored under slot."""
    msg = st.session_state.get(slot)
    if msg:
        kind, text = msg
        (st.success if kind == "ok" else st.error)(text)


# --------------------------------------------------------------------------- page 1

def desk(row) -> str:
    """Desk grouping for the dropdown: the optional `domain` tag, else a label from sensitivity."""
    return row.get("domain") or SENSITIVITY_DESK.get(row.get("sensitivity"), "Other data")


def access_of(table: str) -> tuple[str, dict | None]:
    """The signed-in user's standing on a table and the row that explains it.
    An approved grant wins, then an open request, then the latest outcome."""
    if not ME:
        return "none", None
    mine = REQ[(REQ["requester"] == ME) & (REQ["table_name"] == table)]
    for status in ("approved", "pending"):
        hit = mine[mine["status"] == status]
        if not hit.empty:
            return status, hit.iloc[0].to_dict()
    if mine.empty:
        return "none", None
    last = mine.iloc[0].to_dict()  # REQ is newest first
    return last["status"], last


ACCESS_LABEL = {"none": "No access", "pending": "Pending", "approved": "Granted",
                "rejected": "Rejected", "failed": "Grant failed", "revoked": "Revoked"}


def tracker(state: str, row: dict | None, owner: str) -> str:
    """Three-step strip: Requested, Owner review, Access granted. Every step carries text."""
    at = lambda k: esc(ago(row[k])) if row is not None and row.get(k) is not None and not pd.isna(row[k]) else ""
    who = esc((row or {}).get("decided_by") or owner)
    steps = {
        "none":     [("todo", "Request", "Tell the owner why you need it"),
                     ("todo", "Owner review", esc(owner)), ("todo", "Access granted", "SELECT in Unity Catalog")],
        "pending":  [("done", "Requested", at("requested_at")),
                     ("now", "Owner review", f"Waiting on {esc(owner)}"), ("todo", "Access granted", "Not yet")],
        "approved": [("done", "Requested", at("requested_at")),
                     ("done", "Approved", f"by {who}"), ("done", "Access granted", at("decided_at"))],
        "rejected": [("done", "Requested", at("requested_at")),
                     ("bad", "Rejected", f"by {who}"), ("todo", "Access granted", "Not granted")],
        "failed":   [("done", "Requested", at("requested_at")),
                     ("done", "Approved", f"by {who}"), ("bad", "Grant failed", at("decided_at"))],
        "revoked":  [("done", "Requested", at("requested_at")),
                     ("done", "Approved", "earlier"), ("bad", "Revoked", at("decided_at"))],
    }.get(state)
    parts = []
    for i, (kind, title, sub) in enumerate(steps):
        if i:
            parts.append(f'<div class="bar {"done" if kind in ("done", "now", "bad") else ""}"></div>')
        parts.append(f'<div class="step {kind}"><span class="dot" aria-hidden="true"></span>'
                     f'<div><b>{esc(title)}</b><small>{sub}</small></div></div>')
    return f'<div class="track" role="list" aria-label="Access progress">{"".join(parts)}</div>'


def _submit(table: str, asset: str, owner: str, key: str) -> None:
    reason = st.session_state.get(key, "")
    if not reason.strip():
        st.session_state["flash_request"] = ("err", "Add a reason before requesting access. "
                                                    "The data owner sees it when deciding.")
        return
    try:
        governance.submit_request(ME, table, reason)
    except Exception as e:  # noqa: BLE001 - governance explains the refusal
        text = friendly(e)
        if "already" in text.lower() and "pending" in text.lower():
            text = f"You already have a pending request for {asset}. {owner} hasn't decided yet."
        st.session_state["flash_request"] = ("err", f"Request not sent. {text}")
        return
    st.session_state[key] = ""
    st.session_state["flash_request"] = ("ok", f"Request sent to {owner}. You'll see it move to Granted here.")
    _live_requests.clear()


def product_card(a) -> None:
    state, row = access_of(a.table)
    with st.container(border=True):
        left, right = st.columns([4, 1.3])
        with left:
            st.markdown(f"""
<div class="asset">{esc(a.asset)} &nbsp;{badge(a.sensitivity)} {badge(ACCESS_LABEL[state], "acc-" + state)}</div>
<div class="fq">{esc(a.table)}</div>
<div class="desc">{esc(a.description)}</div>
<div class="meta">Data owner <b>{esc(a.owner)}</b>, from the Unity Catalog tag</div>
""", unsafe_allow_html=True)
        with right:
            st.markdown(f"""<div class="quote"><div class="amt {'zero' if a.cost == 0 else ''}">
{esc(money(a.cost))}</div><div class="per">licence per user, per month</div></div>""",
                        unsafe_allow_html=True)

        st.markdown(tracker(state, row, a.owner), unsafe_allow_html=True)

        note = str((row or {}).get("note") or "")
        if state == "pending":
            vague = note.strip().lower() == "vague"
            st.markdown(f'<div class="state s-pending">Your request is with <b>{esc(a.owner)}</b>, sent '
                        f'{esc(ago(row["requested_at"]))}. It turns to Granted as soon as they approve.'
                        + (' <br>The reason was flagged as vague; a specific reason gets a faster yes.'
                           if vague else '') + '</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="reason">{esc(row["reason"])}</div>', unsafe_allow_html=True)
        elif state == "approved":
            st.markdown(f'<div class="state s-approved">Granted {esc(ago(row["decided_at"]))} by '
                        f'<b>{esc(row["decided_by"])}</b>. Unity Catalog now lets you read this table.</div>',
                        unsafe_allow_html=True)
            st.caption("Try it in the SQL editor:")
            st.code(f"SELECT * FROM {a.table} LIMIT 5", language="sql")
        elif state in ("rejected", "failed", "revoked"):
            what = {"rejected": f"Rejected by {row['decided_by']}", "failed": "Approved, but the grant failed",
                    "revoked": f"Access revoked by {row['decided_by']}"}[state]
            st.markdown(f'<div class="state s-{state}"><b>{esc(what)}</b>'
                        + (f': {esc(note)}' if note else '') + '. You can request again below.</div>',
                        unsafe_allow_html=True)

        if state not in ("pending", "approved"):
            key = f"reason::{a.table}"
            with st.form(f"request::{a.table}", clear_on_submit=False, border=False):
                st.text_area("Reason for access", key=key, height=90,
                             placeholder="What will you use it for? For example: intraday risk "
                                         "report for the EM book",
                             help="Required. The data owner reads this before deciding.")
                st.form_submit_button("Request access", type="primary", disabled=not ME,
                                      on_click=_submit, args=(a.table, a.asset, a.owner, key))
            if not ME:
                st.caption("Sign in through Databricks to request access.")
        # A sent-request confirmation is stale once the owner has decided.
        msg = st.session_state.get("flash_request")
        if msg and (msg[0] == "err" or state == "pending"):
            flash("flash_request")


def catalogue_page() -> None:
    st.subheader("Catalogue")
    st.caption("Every table here carries a data_owner tag in Unity Catalog. Tag a table and it "
               "appears; no code change.")
    if CATALOGUE_ERROR is not None:
        st.error(f"Couldn't read the catalogue tags: {friendly(CATALOGUE_ERROR)}. "
                 "Check the SQL warehouse is running, then choose Refresh data.")
        return
    if CATALOGUE.empty:
        st.markdown(f'<div class="empty">No requestable tables yet. Add a <b>data_owner</b> tag to a '
                    f'table in {esc(CATALOG)}.{esc(SCHEMA)} and choose Refresh data.</div>',
                    unsafe_allow_html=True)
        return

    cat = CATALOGUE.assign(desk=CATALOGUE.apply(desk, axis=1),
                           access=[ACCESS_LABEL[access_of(t)[0]] for t in CATALOGUE["table"]])
    view = cat.rename(columns={"asset": "Asset", "desk": "Desk", "description": "Description",
                               "sensitivity": "Sensitivity", "owner": "Owner", "cost": "£ / month",
                               "access": "Your access"})[
        ["Asset", "Your access", "Desk", "Sensitivity", "£ / month", "Owner", "Description"]]
    st.dataframe(styled(view, ["Sensitivity", "Your access"]), hide_index=True,
                 use_container_width=True,
                 column_config={
                     "Description": st.column_config.TextColumn(width="large"),
                     "£ / month": st.column_config.Column(help="Licence cost per user per month"),
                 })

    st.subheader("Request access")
    desks = sorted(cat["desk"].unique())
    c1, c2 = st.columns([1, 2])
    pick_desk = c1.selectbox("Desk", ["All desks", *desks], key="desk_pick",
                             help="Grouped by the table's domain tag, or by its sensitivity")
    options = cat if pick_desk == "All desks" else cat[cat["desk"] == pick_desk]
    # Labels must stay stable across reruns: Streamlit 1.38 keys the widget on them.
    labels = {r.table: f"{r.asset}  ({money(r.cost)} / month)" for r in options.itertuples()}
    table = c2.selectbox("Data product", list(labels), format_func=labels.get, key="product_pick")
    if table:
        product_card(cat[cat["table"] == table].iloc[0])

    st.subheader("Your requests")
    mine = REQ[REQ["requester"] == ME] if ME else REQ.iloc[0:0]
    if mine.empty:
        st.markdown('<div class="empty">You haven\'t requested anything yet. Pick a data product '
                    'above to start.</div>', unsafe_allow_html=True)
        return
    # While pending, note holds the governance reason classifier; only decisions are shown.
    show = pd.DataFrame({
        "Asset": mine["table_name"].map(short),
        "Status": mine["status"],
        "£ / month": mine["licence_cost"],
        "Requested": local(mine["requested_at"]),
        "Approver": mine["approver"],
        "Decided": local(mine["decided_at"]),
        "Note from approver": mine["note"].where(mine["status"].isin(["rejected", "failed", "revoked"]), ""),
        "Reason": mine["reason"],
    })
    st.dataframe(styled(show, ["Status"]), hide_index=True, use_container_width=True,
                 column_config={
                     "Note from approver": st.column_config.TextColumn(width="large"),
                 })


# --------------------------------------------------------------------------- page 2

def _approve(rid: str, requester: str, asset: str) -> None:
    try:
        governance.approve(rid, ME, TOKEN)
    except Exception as e:  # noqa: BLE001 - show the governance error verbatim
        st.session_state["flash_decision"] = (
            "err", f"Grant failed for {requester} on {asset}. The request is marked failed. "
                   f"Error: {friendly(e)}")
    else:
        st.session_state["flash_decision"] = (
            "ok", f"Access granted. {requester} can now read {asset}; the grant is recorded in the audit trail.")
    _live_requests.clear()


def _reject(rid: str, requester: str, asset: str, key: str) -> None:
    note = st.session_state.get(key, "")
    if not note.strip():
        st.session_state["flash_decision"] = (
            "err", f"Add a note before rejecting {requester}'s request. They see it on their Catalogue page.")
        return
    try:
        governance.reject(rid, ME, note)
    except Exception as e:  # noqa: BLE001
        st.session_state["flash_decision"] = ("err", f"Request not rejected. {friendly(e)}")
    else:
        st.session_state["flash_decision"] = ("ok", f"Request rejected. {requester} will see your note.")
    _live_requests.clear()


def approvals_page() -> None:
    st.subheader("Approvals")
    st.caption("Requests waiting on your decision as data owner. Approving runs a real Unity "
               "Catalog grant for the requester.")
    flash("flash_decision")
    if not ME:
        st.warning("Sign in through Databricks to see requests assigned to you.")
        return
    queue = REQ[(REQ["status"] == "pending") & (REQ["approver"] == ME)].sort_values("requested_at")
    if queue.empty:
        st.markdown('<div class="empty">Nothing waiting on you. New requests for tables you own '
                    'appear here.</div>', unsafe_allow_html=True)
    else:
        pending_queue(queue)
    active_grants()


def _revoke(rid: str, requester: str, asset: str) -> None:
    try:
        governance.revoke(rid, ME)
    except Exception as e:  # noqa: BLE001
        st.session_state["flash_decision"] = ("err", f"Access not revoked for {requester} on {asset}. "
                                                     f"Error: {friendly(e)}")
    else:
        st.session_state["flash_decision"] = ("ok", f"Access revoked. {requester} can no longer read {asset}.")
    _live_requests.clear()


def active_grants() -> None:
    """Approved requests on tables this owner decides: the live entitlements, with a way back."""
    live = REQ[(REQ["status"] == "approved") & (REQ["approver"] == ME)]
    st.subheader("Active access you own")
    if live.empty:
        st.markdown('<div class="empty">No one holds access through you yet.</div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="meta" style="margin-bottom:.6rem">{len(live)} active, '
                f'<b class="num">{esc(money(live["licence_cost"].sum()))}</b> per month in recorded '
                f'licences</div>', unsafe_allow_html=True)
    for r in live.itertuples():
        asset = short(r.table_name)
        with st.container(border=True):
            c1, c2, c3 = st.columns([3.2, 1, 1.1], vertical_alignment="center")
            c1.markdown(f'<div class="meta"><b>{esc(r.requester)}</b> reads <b>{esc(asset)}</b>, granted '
                        f'{esc(ago(r.decided_at))}</div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="meta num" style="text-align:right"><b>{esc(money(r.licence_cost))}</b>'
                        f' / month</div>', unsafe_allow_html=True)
            with c3.popover("Revoke access", use_container_width=True):
                st.markdown(f"Remove **{r.requester}**'s SELECT on **{asset}**? The audit trail keeps "
                            "the record as revoked.")
                st.button("Confirm revoke", key=f"revoke::{r.id}", type="primary",
                          on_click=_revoke, args=(r.id, r.requester, asset))


def pending_queue(queue: pd.DataFrame) -> None:
    sens = dict(zip(CATALOGUE["table"], CATALOGUE["sensitivity"]))
    total = queue["licence_cost"].sum()
    st.markdown(f'<div class="meta" style="margin-bottom:.6rem">{len(queue)} waiting, '
                f'<b class="num">{esc(money(total))}</b> per month if all approved</div>',
                unsafe_allow_html=True)
    for r in queue.itertuples():
        asset = short(r.table_name)
        with st.container(border=True):
            left, right = st.columns([4, 1.3])
            vague = badge("Vague reason", "vague") if str(r.note).strip().lower() == "vague" else ""
            with left:
                st.markdown(f"""
<div class="asset">{esc(asset)} &nbsp;{badge(sens.get(r.table_name, 'unclassified'))} {vague}</div>
<div class="meta"><b>{esc(r.requester)}</b> asked {esc(ago(r.requested_at))}</div>
<div class="reason">{esc(r.reason)}</div>
""", unsafe_allow_html=True)
            with right:
                st.markdown(f"""<div class="quote"><div class="amt {'zero' if r.licence_cost == 0 else ''}">
{esc(money(r.licence_cost))}</div><div class="per">per month if approved</div></div>""",
                            unsafe_allow_html=True)
            key = f"note::{r.id}"
            c1, c2, c3 = st.columns([1.1, 3.2, 1.1], vertical_alignment="bottom")
            c1.button("Approve access", key=f"approve::{r.id}", type="primary", use_container_width=True,
                      on_click=_approve, args=(r.id, r.requester, asset))
            c2.text_input("Rejection note (required to reject)", key=key,
                          placeholder=f"Tell {r.requester} why, for example: use the delayed feed instead")
            c3.button("Reject request", key=f"reject::{r.id}", use_container_width=True,
                      on_click=_reject, args=(r.id, r.requester, asset, key))


# --------------------------------------------------------------------------- page 3

def _ask(question: str) -> None:
    question = (question or "").strip()
    if not question:
        st.session_state["genie"] = {"q": "", "error": "Type a question or pick one of the presets."}
        return
    try:
        w = client()
        msg = w.genie.start_conversation_and_wait(GENIE_SPACE_ID, question)
        att = next((a for a in (msg.attachments or []) if a.query), None)
        if att is None:
            text = next((a.text.content for a in (msg.attachments or []) if a.text and a.text.content), "")
            st.session_state["genie"] = {"q": question, "error": (
                "Genie didn't return a query result for that question. " + text).strip()}
            return
        res = w.genie.get_message_attachment_query_result(
            msg.space_id, msg.conversation_id, msg.id, att.attachment_id)
        sr = res.statement_response
        cols = [c.name for c in sr.manifest.schema.columns]
        rows = (sr.result.data_array if sr.result else None) or []
        st.session_state["genie"] = {"q": question, "cols": cols, "rows": rows,
                                     "desc": att.query.description or "", "sql": att.query.query or ""}
    except Exception as e:  # noqa: BLE001
        st.session_state["genie"] = {"q": question, "error": f"Genie couldn't answer: {friendly(e)}"}


def genie_box() -> None:
    st.subheader("Ask the audit trail")
    st.caption("Answered by a Genie space that reads only the request log and entitlement views."
               + (" It reads the live log, not this local simulation." if SIMULATED else ""))
    cols = st.columns(len(GENIE_PRESETS))
    for i, (c, q) in enumerate(zip(cols, GENIE_PRESETS)):
        if c.button(q, key=f"genie_preset_{i}", use_container_width=True):
            with st.spinner("Asking Genie..."):
                _ask(q)
    with st.form("genie_form", border=False):
        q = st.text_input("Your question", placeholder="For example: who approved the most requests?")
        if st.form_submit_button("Ask"):
            with st.spinner("Asking Genie..."):
                _ask(q)
    g = st.session_state.get("genie")
    if not g:
        return
    if g.get("error"):
        st.warning(g["error"])
        return
    st.markdown(f'<div class="meta">Q: <b>{esc(g["q"])}</b></div>', unsafe_allow_html=True)
    if g["desc"]:
        st.caption(g["desc"])
    if g["rows"]:
        st.dataframe(pd.DataFrame(g["rows"], columns=g["cols"]), hide_index=True, use_container_width=True)
    else:
        st.info("The query ran and returned no rows.")
    if g["sql"]:
        with st.expander("SQL that Genie ran"):
            st.code(g["sql"], language="sql")


def audit_page() -> None:
    st.subheader("Audit")
    st.caption(f"Every request in {REQUESTS}, newest first, in {DESK_TZ} time. "
               "One table is both the queue and the receipt.")
    counts = REQ["status"].value_counts()
    granted = REQ.loc[REQ["status"] == "approved", "licence_cost"].sum()
    m = st.columns([1, 1, 1, 1, 1, 1.6])
    m[0].metric("Pending", int(counts.get("pending", 0)))
    m[1].metric("Approved", int(counts.get("approved", 0)))
    m[2].metric("Rejected", int(counts.get("rejected", 0)))
    m[3].metric("Failed", int(counts.get("failed", 0)))
    m[4].metric("Revoked", int(counts.get("revoked", 0)))
    m[5].metric("Approved licences", f"{money(granted)} / mo",
                help="Sum of licence costs on approved requests in this log. "
                     "Recorded approvals, not verified billing.")
    st.caption("Approved licences is the sum of licence costs on approved requests recorded here, "
               "not verified billing.")

    f1, f2 = st.columns(2)
    statuses = list(dict.fromkeys(STATUSES + sorted(s for s in REQ["status"].unique() if s)))
    tables = sorted(set(CATALOGUE["table"]) | set(REQ["table_name"].dropna()))
    pick_s = f1.multiselect("Status", statuses, placeholder="All statuses")
    pick_t = f2.multiselect("Table", tables, format_func=short, placeholder="All tables")
    view = REQ
    if pick_s:
        view = view[view["status"].isin(pick_s)]
    if pick_t:
        view = view[view["table_name"].isin(pick_t)]

    if REQ.empty:
        st.markdown('<div class="empty">No requests recorded yet. The first request made on the '
                    'Catalogue page lands here.</div>', unsafe_allow_html=True)
    else:
        show = pd.DataFrame({
            "Requested": local(view["requested_at"]),
            "Status": view["status"],
            "Requester": view["requester"],
            "Table": view["table_name"],
            "£ / month": view["licence_cost"],
            "Reason": view["reason"],
            "Approver": view["approver"],
            "Decided by": view["decided_by"],
            "Decided at": local(view["decided_at"]),
            "Note": view["note"],
            "Request id": view["id"],
        })
        st.dataframe(styled(show, ["Status"]), hide_index=True, use_container_width=True,
                     column_config={
                         "Reason": st.column_config.TextColumn(width="medium"),
                         "Note": st.column_config.TextColumn(width="medium"),
                     })
        st.caption(f"Showing {len(view)} of {len(REQ)} requests.")

    if GENIE_SPACE_ID:
        st.divider()
        genie_box()


# --------------------------------------------------------------------------- navigation

waiting = int(((REQ["status"] == "pending") & (REQ["approver"] == ME)).sum()) if ME and not REQ.empty else 0
pg = st.navigation([
    st.Page(catalogue_page, title="Catalogue", url_path="catalogue", default=True),
    st.Page(approvals_page, title=f"Approvals ({waiting})" if waiting else "Approvals", url_path="approvals"),
    st.Page(audit_page, title="Audit", url_path="audit"),
])
pg.run()
