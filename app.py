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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
/* Graphite surfaces, one action blue (#2563EB: 5.2:1 with white text), Apple-style status hues. */
:root {
  --bg: #0E1116; --card: #161A21; --raised: #1E232C; --rule: rgba(255,255,255,.07);
  --ink: #F2F4F7; --muted: #A3ACB9; --faint: #8E98A8;
  --blue: #2563EB; --blue-hover: #1D4ED8; --blue-ink: #7FAEFF;
  --green: #30D158; --amber: #FF9F0A; --red: #FF6961;
  --radius: 16px; --radius-sm: 10px;
}
html, body, .stApp, .stMarkdown, p, label, button, input, textarea,
[data-baseweb="select"], [data-testid="stMetric"] {
  font-family: Inter, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif !important;
  -webkit-font-smoothing: antialiased;
}
.stApp { background: var(--bg); color: var(--ink); }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding-top: 2rem; max-width: 1180px; }
*:focus-visible { outline: 2px solid var(--blue-ink) !important; outline-offset: 2px; }
.num { font-variant-numeric: tabular-nums; }

/* Headings: weight and size carry hierarchy, no ornaments. */
h1, h2, h3 { letter-spacing: -0.02em; font-weight: 650 !important; color: var(--ink); }
[data-testid="stHeading"] h3 { font-size: 1.3rem; padding-top: 1.4rem; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }

/* Sidebar */
section[data-testid="stSidebar"] { background: var(--card); border-right: 1px solid var(--rule); }
[data-testid="stSidebarNav"] a { border-radius: var(--radius-sm); padding: .45rem .7rem; }
[data-testid="stSidebarNav"] a span { font-size: .95rem; color: var(--ink); }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: rgba(37,99,235,.16); }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: var(--blue-ink); font-weight: 600; }

/* Cards: bordered containers become soft rounded panels. */
/* Unbordered wrappers carry the empty emotion class; only st.container(border=True) differs. */
[data-testid="stVerticalBlockBorderWrapper"]:not(.st-emotion-cache-0) {
  background: var(--card); border: 1px solid var(--rule) !important; border-radius: var(--radius) !important;
  padding: .4rem .5rem; }
[data-testid="stDataFrame"] > div { border-radius: 12px; overflow: hidden; border: 1px solid var(--rule); }

/* Controls: 40px targets, rounded, calm until focused. */
.stButton > button, .stFormSubmitButton > button, [data-testid="stPopover"] button {
  min-height: 40px; border-radius: var(--radius-sm); font-weight: 600; padding: 0 1.1rem;
  border: 1px solid var(--rule); background: var(--raised); color: var(--ink);
  transition: background .15s ease, border-color .15s ease; }
.stButton > button:hover, .stFormSubmitButton > button:hover, [data-testid="stPopover"] button:hover {
  border-color: rgba(255,255,255,.16); color: var(--ink); }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"] {
  background: var(--blue); border-color: var(--blue); color: #FFFFFF; }
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primaryFormSubmit"]:hover {
  background: var(--blue-hover); border-color: var(--blue-hover); color: #FFFFFF; }
.stTextInput [data-baseweb="input"], .stTextArea [data-baseweb="textarea"], [data-baseweb="select"] > div {
  background: var(--raised) !important; border-radius: var(--radius-sm) !important;
  border: 1px solid var(--rule) !important; }
.stTextInput [data-baseweb="input"]:focus-within, .stTextArea [data-baseweb="textarea"]:focus-within {
  border-color: var(--blue) !important; box-shadow: 0 0 0 3px rgba(37,99,235,.25); }
[data-testid="stAlert"] { border-radius: 12px; }

/* Header: wordmark left, identity chip right. */
.dda-head { display: flex; justify-content: space-between; align-items: center; gap: 1rem;
  flex-wrap: wrap; padding-bottom: 1.2rem; margin-bottom: 1.2rem; border-bottom: 1px solid var(--rule); }
.dda-title { font-size: 1.75rem; font-weight: 700; color: var(--ink); line-height: 1.15; letter-spacing: -0.03em; }
.dda-sub { color: var(--muted); font-size: .95rem; margin-top: .25rem; }
.dda-who { display: flex; align-items: center; gap: .65rem; background: var(--card);
  border: 1px solid var(--rule); border-radius: 999px; padding: .35rem .9rem .35rem .35rem; }
.dda-who .av { width: 32px; height: 32px; border-radius: 50%; background: var(--blue); color: #fff;
  display: grid; place-items: center; font-weight: 700; font-size: .85rem; }
.dda-who .lab { color: var(--faint); font-size: .72rem; line-height: 1.1; }
.dda-who b { color: var(--ink); font-weight: 600; font-size: .9rem; }
.dda-who.out { padding: .5rem .9rem; color: var(--muted); font-size: .88rem; }
@media (max-width: 640px) { .quote { text-align: left; } }
.dda-sim { display: inline-block; background: rgba(255,159,10,.12); color: var(--amber);
  padding: .3rem .8rem; border-radius: 999px; font-size: .82rem; font-weight: 600; margin: -.2rem 0 1rem; }

/* Pills: tinted fill, no outline, text always present. */
.badge { display: inline-block; padding: .14rem .6rem; border-radius: 999px; font-size: .75rem;
  font-weight: 600; line-height: 1.45; white-space: nowrap; vertical-align: middle; }
.b-confidential, .b-rejected, .b-failed, .b-acc-rejected, .b-acc-failed { color: var(--red); background: rgba(255,105,97,.14); }
.b-licensed { color: var(--blue-ink); background: rgba(37,99,235,.18); }
.b-internal, .b-revoked, .b-other, .b-unclassified, .b-acc-none, .b-acc-revoked { color: var(--muted); background: rgba(163,172,185,.12); }
.b-pending, .b-vague, .b-acc-pending { color: var(--amber); background: rgba(255,159,10,.14); }
.b-approved, .b-acc-approved { color: var(--green); background: rgba(48,209,88,.14); }

.asset { font-size: 1.25rem; font-weight: 650; color: var(--ink); letter-spacing: -0.01em; }
.fq { color: var(--faint); font-size: .8rem; font-family: ui-monospace, "SF Mono", Menlo, monospace; margin-top: .15rem; }
.desc { color: var(--ink); margin: .55rem 0 .35rem; max-width: 68ch; line-height: 1.5; }
.meta { color: var(--muted); font-size: .88rem; }
.meta b { color: var(--ink); font-weight: 600; }
.reason { background: var(--raised); border-radius: 12px; padding: .7rem .9rem; margin: .6rem 0;
  color: var(--ink); max-width: 72ch; line-height: 1.5; }

/* The price: the one big number on each card. */
.quote { text-align: right; }
.quote .amt { font-size: 2.4rem; font-weight: 700; color: var(--ink); line-height: 1;
  font-variant-numeric: tabular-nums; letter-spacing: -0.035em; }
.quote .amt.zero { color: var(--faint); }
.quote .per { color: var(--faint); font-size: .78rem; margin-top: .3rem; }

/* Access tracker */
.track { display: flex; align-items: flex-start; gap: .6rem; margin: 1.2rem 0 .9rem; flex-wrap: wrap;
  background: var(--raised); border-radius: 12px; padding: .9rem 1rem; }
.step { display: flex; gap: .55rem; align-items: flex-start; min-width: 9.5rem; }
.step b { display: block; color: var(--ink); font-size: .9rem; font-weight: 600; }
.step small { display: block; color: var(--muted); font-size: .8rem; }
.step .dot { width: 12px; height: 12px; border-radius: 50%; margin-top: .3rem; flex: none;
  border: 2px solid rgba(255,255,255,.18); background: transparent; }
.step.done .dot { background: var(--green); border-color: var(--green); }
.step.now .dot { background: var(--amber); border-color: var(--amber); box-shadow: 0 0 0 4px rgba(255,159,10,.2); }
.step.bad .dot { background: var(--red); border-color: var(--red); }
.step.todo b { color: var(--muted); }
.bar { flex: 1; min-width: 1.5rem; height: 2px; border-radius: 2px; background: rgba(255,255,255,.12); margin-top: .62rem; }
.bar.done { background: var(--green); }
@media (prefers-reduced-motion: no-preference) {
  .step.now .dot { animation: pulse 1.8s ease-in-out infinite; }
  @keyframes pulse { 50% { box-shadow: 0 0 0 7px rgba(255,159,10,.06); } }
}
.state { border-radius: 12px; padding: .7rem .95rem; margin: .2rem 0 .6rem; font-size: .92rem;
  color: var(--ink); max-width: 80ch; line-height: 1.5; background: var(--raised); }
.s-pending { background: rgba(255,159,10,.10); }
.s-approved { background: rgba(48,209,88,.10); }
.s-rejected, .s-failed { background: rgba(255,105,97,.10); }

.empty { color: var(--muted); background: var(--card); border-radius: var(--radius); padding: 1.2rem 1.3rem; }
[data-testid="stMetric"] { background: var(--card); border: 1px solid var(--rule); border-radius: var(--radius);
  padding: .9rem 1.1rem; }
[data-testid="stMetricLabel"] p { color: var(--muted); font-size: .85rem; }
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; font-weight: 700; letter-spacing: -0.03em; }
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
    c = {"pending": "#FF9F0A", "approved": "#30D158", "granted": "#30D158", "rejected": "#FF6961",
         "failed": "#FF6961", "grant failed": "#FF6961", "confidential": "#FF6961",
         "licensed": "#7FAEFF"}.get(str(v).lower())
    return f"color: {c}; font-weight: 600" if c else "color: #A3ACB9"


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
  {(f'<div class="dda-who"><span class="av" aria-hidden="true">{esc(ME[:1].upper())}</span>'
    f'<span><span class="lab">Signed in as</span><br><b>{esc(ME)}</b></span></div>') if ME else
   '<div class="dda-who out"><b>Not signed in</b>, requests and decisions are disabled</div>'}
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
