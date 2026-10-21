"""Doorman: request, approve and audit access to Unity Catalog tables.

Reads only. Every change goes through governance (submit_request / approve / reject).
The catalogue is whatever carries a data_owner tag; no table names live in this file.
"""
import html
import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
st.set_page_config(page_title="Doorman", page_icon=os.path.join(ASSETS, "emblem.svg"),
                   layout="wide", initial_sidebar_state="expanded")

# --------------------------------------------------------------------------- look

st.markdown("""
<style>
/* Flat graphite UI: solid surfaces, one hairline border weight, one action blue (#2563EB, 5.2:1
   with white), status on small dots. No gradients, inset highlights, blur or press animations. */
:root {
  --bg: #16181D; --card: #1E2126; --raised: #262A31; --hover: #2E333B;
  --line: rgba(255,255,255,.08); --line-2: rgba(255,255,255,.14);
  --ink: #F2F4F7; --muted: #A3ACB9; --faint: #8E98A8;
  --blue: #2563EB; --blue-hover: #1D4ED8; --blue-ink: #7FAEFF; --blue-soft: rgba(37,99,235,.16);
  --green: #6CC28A; --amber: #E0A451; --red: #E07A74;
  --radius: 12px; --radius-sm: 8px; --ctl: 40px;
}
html, body, .stApp, .stApp *:not(code):not(pre):not(.material-icons):not([data-testid="stIconMaterial"]) {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "Segoe UI", Roboto, Arial, sans-serif !important;
  -webkit-font-smoothing: antialiased; }
.stApp pre, .stApp pre *, .stApp code, .stApp code * {
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace !important; }
.stApp { background: var(--bg); color: var(--ink); }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding-top: 1.5rem; max-width: 1180px; margin: 0 auto !important; }
*:focus-visible { outline: 2px solid var(--blue-ink) !important; outline-offset: 2px; }
.num { font-variant-numeric: tabular-nums; }
[data-stale="true"] { opacity: 1 !important; transition: none !important; }
[data-testid="InputInstructions"] { display: none !important; }
[data-testid="stHeaderActionElements"], [data-testid="stHeadingWithActionElements"] a[href^="#"] { display: none !important; }
[data-testid="stElementContainer"]:has(> iframe[height="0"]), .element-container:has(> iframe[height="0"]),
div:has(> iframe[title="streamlit_components_v1.html"][height="0"]) { display: none !important; }

/* Type */
h1, h2, h3 { letter-spacing: -0.02em; font-weight: 650 !important; color: var(--ink); }
[data-testid="stHeading"] h3 { font-size: 1.15rem !important; font-weight: 600 !important; padding-top: 1.4rem; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }
[data-testid="stWidgetLabel"] p { color: var(--muted); font-size: .85rem; font-weight: 500; }
.lt { font-size: 2rem; font-weight: 700; letter-spacing: -0.03em; color: var(--ink); line-height: 1.1; margin: 0; padding: 0 !important; }
.lt-sub { color: var(--muted); font-size: .95rem; margin: .35rem 0 1.4rem; max-width: 70ch; line-height: 1.45; }

/* Sidebar */
section[data-testid="stSidebar"] { background: var(--card); border-right: 1px solid var(--line); }
section[data-testid="stSidebar"][aria-expanded="true"] { width: 15rem !important; min-width: 15rem !important; max-width: 15rem !important; }
section[data-testid="stSidebar"][aria-expanded="true"] > div { width: 15rem !important; }
section[data-testid="stSidebar"][aria-expanded="false"] { width: 0 !important; min-width: 0 !important; }
[data-testid="stSidebarHeader"] { height: 0 !important; min-height: 0 !important; padding: 0 !important; margin: 0 !important;
  position: relative; overflow: visible; }
[data-testid="stSidebarCollapseButton"] { position: fixed; top: .75rem; left: calc(15rem + .6rem); right: auto; z-index: 1000;
  display: block !important; visibility: visible !important; opacity: 1 !important; }
[data-testid="stSidebarCollapseButton"] button { visibility: visible !important; opacity: 1 !important; }
[data-testid="stSidebarCollapsedControl"] { top: .75rem !important; left: .6rem !important; }
[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapsedControl"] button {
  width: 34px; height: 34px; padding: 0 !important; display: grid !important; place-items: center;
  border-radius: var(--radius-sm) !important; color: var(--ink) !important;
  background: var(--raised) !important; border: 1px solid var(--line-2) !important; box-shadow: none !important; }
[data-testid="stSidebarCollapseButton"] button:hover, [data-testid="stSidebarCollapsedControl"] button:hover {
  background: var(--hover) !important; }
[data-testid="stSidebarNavItems"] { padding: 1.9rem .75rem 1rem; margin: 0; max-height: none !important; }
[data-testid="stSidebarNavViewButton"] { display: none !important; }
[data-testid="stSidebarNavSeparator"] { margin: 0 1rem; }
[data-testid="stSidebarUserContent"] { padding: 1.25rem .75rem 1rem !important; }
[data-testid="stSidebarNav"] a { border-radius: var(--radius-sm); padding: .45rem .8rem; margin: .1rem 0;
  min-height: 38px; display: flex; align-items: center; background: transparent; }
[data-testid="stSidebarNav"] a span { color: var(--muted); font-weight: 500; }
[data-testid="stSidebarNav"] a:hover { background: rgba(255,255,255,.05) !important; }
[data-testid="stSidebarNav"] a:hover span { color: var(--ink); }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: var(--blue-soft) !important; }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: #FFFFFF; font-weight: 600; }

/* Buttons: one height, centred content, solid fills. */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button, [data-testid="stPopover"] button {
  min-height: var(--ctl); padding: 0 1.1rem; border-radius: var(--radius-sm); font-weight: 600;
  display: inline-flex; align-items: center; justify-content: center; gap: .5rem;
  color: var(--ink); background: var(--raised); border: 1px solid var(--line-2); box-shadow: none;
  transition: background .12s ease, border-color .12s ease, color .12s ease; }
.stButton > button p, .stFormSubmitButton > button p, .stDownloadButton > button p, [data-testid="stPopover"] button p {
  margin: 0; line-height: 1.2; }
.stButton > button:hover, .stFormSubmitButton > button:hover, .stDownloadButton > button:hover, [data-testid="stPopover"] button:hover {
  background: var(--hover); border-color: var(--line-2); color: #FFFFFF; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"], .stDownloadButton > button[kind="primary"] {
  color: #FFFFFF; background: var(--blue); border-color: var(--blue); }
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primaryFormSubmit"]:hover, .stDownloadButton > button[kind="primary"]:hover {
  background: var(--blue-hover); border-color: var(--blue-hover); color: #FFFFFF; }
.stButton > button:disabled, .stFormSubmitButton > button:disabled { opacity: .45; }
.stButton > button:focus:not(:focus-visible), .stFormSubmitButton > button:focus:not(:focus-visible),
[data-testid="stPopover"] button:focus:not(:focus-visible) { color: inherit !important; border-color: var(--line-2) !important; box-shadow: none !important; }
.stButton > button[kind="primary"]:focus:not(:focus-visible),
.stFormSubmitButton > button[kind="primaryFormSubmit"]:focus:not(:focus-visible) { color: #FFFFFF !important; border-color: var(--blue) !important; }
/* Secondary actions in the content area read as links. */
.block-container .stButton > button[kind="secondary"] {
  background: transparent; border-color: transparent; color: var(--blue-ink); }
.block-container .stButton > button[kind="secondary"]:hover { background: var(--blue-soft); border-color: transparent; color: #A9C8FF; }

/* Inputs and selects: same height, radius and border as buttons; text vertically centred. */
[data-baseweb="select"] > div, .stTextInput [data-baseweb="input"], .stTextArea [data-baseweb="textarea"] {
  background: var(--raised) !important; border: 1px solid var(--line-2) !important;
  border-radius: var(--radius-sm) !important; box-shadow: none !important; transition: border-color .12s ease; }
[data-baseweb="select"] > div { min-height: var(--ctl); align-items: center; cursor: pointer; }
.stTextInput [data-baseweb="input"] { min-height: var(--ctl); }
.stTextInput [data-baseweb="input"] > div, .stTextArea [data-baseweb="textarea"] > div,
.stTextInput input, .stTextArea textarea { background: transparent !important; }
[data-baseweb="select"] > div:hover, .stTextInput [data-baseweb="input"]:hover, .stTextArea [data-baseweb="textarea"]:hover {
  border-color: rgba(255,255,255,.22) !important; }
[data-baseweb="select"] > div:focus-within, .stTextInput [data-baseweb="input"]:focus-within,
.stTextArea [data-baseweb="textarea"]:focus-within { border-color: var(--blue) !important; box-shadow: 0 0 0 3px rgba(37,99,235,.25) !important; }

/* Floating layers: menus, popovers, tooltips. */
[data-baseweb="popover"]:has(ul), [data-baseweb="popover"]:has(ul) > div:not([data-testid="stPopoverBody"]) {
  background: transparent !important; box-shadow: none !important; }
[data-baseweb="popover"] ul, [data-testid="stSelectboxVirtualDropdown"], [data-testid="stPopoverBody"],
[data-baseweb="tooltip"] > div, [data-testid="stTooltipContent"] {
  background: #23262C !important; border: 1px solid var(--line-2) !important; border-radius: 10px !important;
  color: var(--ink) !important; box-shadow: 0 10px 28px rgba(0,0,0,.45) !important; }
[data-baseweb="popover"] ul, [data-testid="stSelectboxVirtualDropdown"] { padding: 4px !important; }
[data-baseweb="tooltip"] { background: transparent !important; }
[data-baseweb="popover"] li[role="option"] { border-radius: 6px; margin: 1px 0; min-height: 36px; display: flex; align-items: center; }
[data-baseweb="popover"] li[role="option"]:hover, [data-baseweb="popover"] li[aria-selected="true"] { background: var(--blue-soft) !important; }
[data-testid="stPopoverBody"] { min-width: 0 !important; width: max-content !important; max-width: 22rem; padding: .4rem !important; }
[data-testid="stPopoverBody"] > div { background: transparent !important; }
[data-testid="stPopoverBody"] .stTextInput { min-width: 14rem; }
[data-testid="stPopoverBody"] .stButton > button[kind="secondary"] {
  justify-content: flex-start; min-height: 36px; padding: 0 .7rem; background: transparent; border-color: transparent;
  color: var(--ink); font-weight: 500; }
[data-testid="stPopoverBody"] .stButton > button[kind="secondary"]:hover { background: var(--blue-soft); color: #FFFFFF; }
[data-testid="stPopoverBody"] .stButton:has(> button[kind="secondary"]) { margin-bottom: -.6rem; }

/* Panels: only real cards, never Streamlit's layout wrappers. */
.group, .empty, [data-testid="stMetric"], [class*="st-key-card-"] {
  background: var(--card) !important; border: 1px solid var(--line) !important; border-radius: var(--radius) !important;
  box-shadow: none !important; }
[class*="st-key-card-"] { padding: 1rem 1.1rem !important; }
/* Streamlit draws its own border on the wrapper around a bordered container: drop it, the keyed block is the card. */
[data-testid="stVerticalBlockBorderWrapper"]:has(> [class*="st-key-card-"]),
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-card-"]) { border: 0 !important; padding: 0 !important; background: transparent !important; }
/* Markdown blocks carry a -1rem bottom margin; in a centred row that drops text below the buttons. */
[data-testid="stHorizontalBlock"] [data-testid="stMarkdownContainer"]:has(.meta, .quote) { margin-bottom: 0 !important; }
[data-testid="stDataFrame"] > div:not([data-testid="stElementToolbar"]) {
  border: 1px solid var(--line) !important; border-radius: var(--radius) !important; overflow: hidden; }
.stCode, [data-testid="stCode"] pre { background: var(--card) !important; border: 1px solid var(--line) !important;
  border-radius: var(--radius-sm) !important; }
.empty { text-align: center; padding: 1.6rem 1.3rem !important; color: var(--muted); font-size: .95rem; }

/* Metrics: label row and value both left, value on a fixed baseline. */
[data-testid="stMetric"] { padding: .9rem 1.1rem !important; }
[data-testid="stMetricLabel"] { display: flex; align-items: center; min-height: 1.2rem; }
[data-testid="stMetricLabel"] p { color: var(--muted); font-size: .85rem; margin: 0; display: flex; align-items: center; }
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; font-weight: 700; letter-spacing: -0.03em; }
[data-testid="stMetricValue"] > div { font-size: 1.9rem; line-height: 1.15; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div [data-testid="stMetricLabel"] p::before {
  content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .45rem; flex: none; background: var(--faint); }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(1) [data-testid="stMetricLabel"] p::before { background: var(--amber); }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(2) [data-testid="stMetricLabel"] p::before { background: var(--green); }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(3) [data-testid="stMetricLabel"] p::before,
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(4) [data-testid="stMetricLabel"] p::before { background: var(--red); }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(6) [data-testid="stMetricLabel"] p::before { background: var(--blue-ink); }

/* Messages: a flat tinted bar with a status dot (marker element set by flash()). */
[data-testid="stAlertContainer"] { border-radius: var(--radius-sm) !important; border: 0 !important; }
[data-testid="stAlertContainer"] a { color: inherit !important; text-decoration: none !important; font-weight: 600; }
.element-container:has(.flash-mark), [data-testid="stElementContainer"]:has(.flash-mark) { display: none; }
:is(.element-container, [data-testid="stElementContainer"]):has(.flash-mark) + * [data-testid="stAlertContainer"] {
  color: var(--ink) !important; border: 1px solid var(--line) !important; background: var(--card) !important; }
:is(.element-container, [data-testid="stElementContainer"]):has(.flash-ok) + * [data-testid="stAlertContainer"] { background: rgba(108,194,138,.10) !important; }
:is(.element-container, [data-testid="stElementContainer"]):has(.flash-err) + * [data-testid="stAlertContainer"] { background: rgba(224,122,116,.11) !important; }
:is(.element-container, [data-testid="stElementContainer"]):has(.flash-mark) + * [data-testid="stAlertContainer"] p::before {
  content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .55rem; vertical-align: middle; background: var(--green); }
:is(.element-container, [data-testid="stElementContainer"]):has(.flash-err) + * [data-testid="stAlertContainer"] p::before { background: var(--red); }

/* Loader shown by the helper script while a rerun takes longer than a moment. */
.dda-hud { position: fixed; left: 50%; top: 42%; z-index: 3000; display: flex; align-items: center; gap: .7rem;
  padding: .75rem 1.1rem; border-radius: 10px; color: var(--ink); font-size: .92rem; font-weight: 600;
  background: #23262C; border: 1px solid var(--line-2); box-shadow: 0 10px 28px rgba(0,0,0,.45);
  opacity: 0; pointer-events: none; transform: translate(-50%, -50%); transition: opacity .15s ease; }
.dda-hud.on { opacity: 1; }
.dda-hud .sp { width: 16px; height: 16px; border-radius: 50%; flex: none; border: 2px solid var(--line-2);
  border-top-color: var(--blue-ink); animation: dda-spin .8s linear infinite; }
@keyframes dda-spin { to { transform: rotate(360deg); } }

/* Genie preset questions: flat tiles, text left. */
[data-testid="stVerticalBlock"]:has(> :is(.element-container, [data-testid="stElementContainer"]) .genie-chips) .stButton > button {
  min-height: 4.2rem; padding: .6rem .9rem !important; justify-content: flex-start; text-align: left; font-weight: 500;
  line-height: 1.35; color: var(--ink) !important; background: var(--card) !important; border: 1px solid var(--line) !important; }
[data-testid="stVerticalBlock"]:has(> :is(.element-container, [data-testid="stElementContainer"]) .genie-chips) .stButton > button:hover {
  background: var(--raised) !important; border-color: var(--line-2) !important; }
[data-testid="stVerticalBlock"]:has(> :is(.element-container, [data-testid="stElementContainer"]) .genie-chips) .stButton > button p { text-align: left; }

/* Top bar: wordmark left, bell and account pill right, all on one centre line. */
[data-testid="stHorizontalBlock"]:has(.appname) { align-items: center !important; }
[data-testid="stHorizontalBlock"]:has(.appname) > div { display: flex; align-items: center; min-height: 44px; }
[data-testid="stHorizontalBlock"]:has(.appname) > div > div { width: 100%; }
/* Bell and account pill hug their content and sit together at the right edge; the wordmark takes the rest. */
[data-testid="stHorizontalBlock"]:has(.appname) { gap: .6rem !important; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:first-child { flex: 1 1 auto !important; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(n+2) { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
.appname { display: flex; align-items: center; gap: .7rem; margin: 0; }
[data-testid="stMarkdownContainer"]:has(> .appname), [data-testid="stMarkdownContainer"]:has(> div > .appname) { margin: 0 !important; }
.appname .emblem { flex: none; width: 44px; height: 44px; }
.appname .name { font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; color: #FFFFFF; line-height: 1; }
.topbar-rule { border-bottom: 1px solid var(--line); margin: .5rem 0 1.4rem; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(n+2) [data-testid="stPopover"] { display: flex; justify-content: flex-end; }
/* Account pill: avatar initial centred in its circle, email beside it. */
[data-testid="stHorizontalBlock"]:has(.appname) > div:last-child [data-testid="stPopover"] button {
  min-height: 40px; padding: 0 .75rem 0 .35rem; border-radius: 999px; font-weight: 500; font-size: .88rem;
  background: var(--raised) !important; border: 1px solid var(--line-2) !important; color: var(--ink) !important; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:last-child [data-testid="stPopover"] button:hover { background: var(--hover) !important; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:last-child [data-testid="stPopover"] button p {
  display: inline-flex; align-items: center; gap: .55rem; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:last-child [data-testid="stPopover"] button p::before {
  width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex: none;
  background: #4B5260; color: #FFFFFF; font-size: .75rem; font-weight: 600; line-height: 1; }
/* Bell: a 40px circle, the icon drawn with a mask at the exact centre. */
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(2) [data-testid="stPopover"] button {
  position: relative; width: 40px; height: 40px; min-height: 40px; padding: 0 !important; border-radius: 50% !important;
  background: var(--raised) !important; border: 1px solid var(--line-2) !important; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(2) [data-testid="stPopover"] button:hover { background: var(--hover) !important; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(2) [data-testid="stPopover"] button p,
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(2) [data-testid="stPopover"] button svg,
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(2) [data-testid="stPopover"] button [data-testid="stMarkdownContainer"] + div { display: none !important; }
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(2) [data-testid="stPopover"] button::before {
  content: ""; position: absolute; left: 50%; top: 50%; width: 18px; height: 18px; transform: translate(-50%, -50%); background: #F2F4F7;
  -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'><path d='M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9'/><path d='M10.3 21a1.94 1.94 0 0 0 3.4 0'/></svg>") center / contain no-repeat;
  mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'><path d='M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9'/><path d='M10.3 21a1.94 1.94 0 0 0 3.4 0'/></svg>") center / contain no-repeat; }
[data-testid="stPopoverBody"]:has(.notif-panel) { width: 18.25rem !important; min-width: 18.25rem !important; max-width: 18.25rem !important; }
.notif-panel { padding: .15rem .1rem 1rem; }
.notif-panel .nh { display: flex; justify-content: space-between; align-items: center; padding: .1rem .5rem .55rem;
  margin-bottom: .35rem; border-bottom: 1px solid var(--line); }
.notif-panel .nh b { font-size: .88rem; font-weight: 600; color: var(--ink); }
.notif-panel .nh span { color: #FFFFFF; background: var(--blue); font-size: .7rem; font-weight: 600; line-height: 1;
  padding: .22rem .45rem; border-radius: 999px; }
.notif { display: flex; gap: .6rem; align-items: flex-start; padding: .55rem .6rem; border-radius: 8px; }
.notif + .notif { margin-top: .15rem; }
.notif.unread { background: rgba(255,255,255,.045); }
.notif .dot { margin-top: .42rem; flex: none; }
.notif div { color: var(--ink); font-size: .88rem; line-height: 1.4; }
.notif small { display: block; color: var(--muted); font-size: .78rem; margin-top: .1rem; }
.notif-empty { color: var(--muted); font-size: .85rem; text-align: center; padding: .5rem .5rem 0; }

/* Tags: neutral pill, status on a dot, text always present. */
.badge { display: inline-flex; align-items: center; gap: .4rem; padding: .16rem .6rem; border-radius: 999px;
  font-size: .75rem; font-weight: 600; line-height: 1.4; white-space: nowrap; vertical-align: middle;
  background: var(--raised); color: var(--ink); border: 1px solid var(--line); }
.badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--faint); flex: none; }
.b-pending::before, .b-vague::before, .b-acc-pending::before { background: var(--amber); }
.b-approved::before, .b-acc-approved::before { background: var(--green); }
.b-confidential::before, .b-rejected::before, .b-failed::before, .b-acc-rejected::before, .b-acc-failed::before { background: var(--red); }
.b-licensed::before { background: var(--blue-ink); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .45rem; vertical-align: middle; background: var(--faint); }
.d-approved { background: var(--green); } .d-pending { background: var(--amber); }
.d-rejected, .d-failed, .d-confidential { background: var(--red); }
.d-licensed { background: var(--blue-ink); }

/* Ticket and card content */
.asset { font-size: 1.2rem; font-weight: 650; color: var(--ink); letter-spacing: -0.01em; display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.fq { color: var(--faint); font-size: .8rem; font-family: ui-monospace, "SF Mono", Menlo, monospace; margin-top: .15rem; }
.desc { color: var(--ink); margin: .55rem 0 .35rem; max-width: 68ch; line-height: 1.5; }
.meta { color: var(--muted); font-size: .88rem; }
.meta b { color: var(--ink); font-weight: 600; }
.reason { background: var(--raised); border-radius: var(--radius-sm); padding: .65rem .85rem; margin: .6rem 0; color: var(--ink); max-width: 72ch; line-height: 1.5; }
.quote { text-align: right; }
.quote .amt { font-size: 2.3rem; font-weight: 700; color: var(--ink); line-height: 1; font-variant-numeric: tabular-nums; letter-spacing: -0.03em; }
.quote .amt.zero { color: var(--faint); }
.quote .per { color: var(--faint); font-size: .72rem; margin-top: .35rem; }
@media (max-width: 640px) { .quote { text-align: left; } }
/* Approve is the primary action on a ticket; Reject is a plain secondary button beside it. */
[class*="st-key-card-ticket"] [data-testid="stPopover"] button { color: #FFFFFF !important; background: var(--blue) !important; border-color: var(--blue) !important; }
[class*="st-key-card-ticket"] [data-testid="stPopover"] button:hover { background: var(--blue-hover) !important; }
[class*="st-key-card-ticket"] .stButton > button[kind="secondary"] { color: var(--ink); background: var(--raised); border-color: var(--line-2); }
[class*="st-key-card-ticket"] .stButton > button[kind="secondary"]:hover { background: var(--hover); color: #FFFFFF; }
.state { border-radius: var(--radius-sm); padding: .7rem .95rem; margin: .2rem 0 .6rem; font-size: .92rem; color: var(--ink); max-width: 80ch; line-height: 1.5; background: var(--raised); }
.s-pending { background: rgba(224,164,81,.10); } .s-approved { background: rgba(108,194,138,.10); }
.s-rejected, .s-failed { background: rgba(224,122,116,.10); }

/* Grouped list (catalogue detail, my requests) */
.group { overflow: hidden; margin: .25rem 0 .9rem; }
.g-head { display: flex; justify-content: space-between; align-items: center; gap: 1.2rem; padding: 1rem 1.1rem; }
.g-title { font-size: 1.15rem; font-weight: 650; color: var(--ink); letter-spacing: -0.02em; }
.g-desc { color: var(--muted); font-size: .92rem; margin-top: .2rem; line-height: 1.45; max-width: 62ch; }
.g-price { text-align: right; white-space: nowrap; }
.g-price b { display: block; font-size: 2.2rem; font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; letter-spacing: -0.03em; line-height: 1.1; }
.g-price b.zero { color: var(--muted); }
.g-price small { color: var(--faint); font-size: .72rem; }
.g-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-left: 1.1rem;
  padding: .62rem 1.1rem .62rem 0; border-top: 1px solid var(--line); font-size: .92rem; min-height: 2.6rem; }
.g-row > span:first-child { color: var(--ink); }
.g-row > span:last-child { color: var(--muted); text-align: right; overflow-wrap: anywhere; display: inline-flex; align-items: center; }
.g-foot { color: var(--faint); font-size: .8rem; margin: -.5rem 0 1rem 1.1rem; }

/* Progress: one track, three segments. */
.prog { padding: .95rem 1.1rem 1rem; border-top: 1px solid var(--line); }
.prog-track { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; }
.prog-track i { height: 6px; border-radius: 3px; background: rgba(255,255,255,.10); }
.prog-track i.on { background: var(--green); }
.prog.pending .prog-track i.on { background: var(--amber); }
.prog.rejected .prog-track i.on, .prog.failed .prog-track i.on { background: var(--red); }
.prog.revoked .prog-track i.on { background: var(--faint); }
.prog.rejected .prog-track i.on:not(.cur), .prog.failed .prog-track i.on:not(.cur) { background: var(--green); }
.prog-steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; margin-top: .5rem; font-size: .8rem; color: var(--faint); }
.prog-steps span.cur { color: var(--ink); font-weight: 600; }
.prog-steps span:nth-child(2) { text-align: center; } .prog-steps span:nth-child(3) { text-align: right; }
.prog-note { margin-top: .7rem; font-size: .9rem; color: var(--ink); line-height: 1.45; }
.prog-note em { font-style: normal; color: var(--muted); }
@media (prefers-reduced-motion: no-preference) {
  .prog.pending .prog-track i.cur { animation: waiting 1.6s ease-in-out infinite; }
  @keyframes waiting { 50% { opacity: .45; } }
}

/* Table toolbar: a small flat pill. */
[data-testid="stElementToolbar"] { border: 0 !important; background: transparent !important; box-shadow: none !important; }
[data-testid="stElementToolbar"] > div { background: #23262C; border: 1px solid var(--line-2); border-radius: 999px; padding: 2px 3px; }
[data-testid="stElementToolbar"] button { border-radius: 999px !important; background: transparent !important; color: var(--muted) !important;
  width: 30px; height: 30px; display: grid; place-items: center; }
[data-testid="stElementToolbar"] button:hover { background: var(--blue-soft) !important; color: #FFFFFF !important; }
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
    c = {"pending": "#E0A451", "approved": "#6CC28A", "granted": "#6CC28A", "rejected": "#E07A74",
         "failed": "#E07A74", "grant failed": "#E07A74",
         "licensed": "#8FB3F0", "confidential": "#E07A74"}.get(str(v).lower())
    return f"color: {c}; font-weight: 500" if c else "color: #A3ACB9"


def when(t) -> str:
    # A space, not "": Streamlit shows the raw value ("None") when a formatted cell is empty.
    return " " if t is None or pd.isna(t) else t.strftime("%d %b %Y, %H:%M:%S")


def styled(df: pd.DataFrame, cols: list[str]):
    """Colour status-like columns. A Styler's display values override column_config formats,
    so money and times are formatted here too."""
    # Dates go in as text: the grid shows an empty date as "None" whatever the Styler says.
    df = df.assign(**{c: df[c].map(when) for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])})
    s = df.style
    fn = getattr(s, "map", None) or s.applymap
    fmt = {c: money for c in df.columns if c.startswith("£")}
    return fn(status_style, subset=cols).format(na_rep=" ").format(fmt, na_rep=" ")


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


@st.cache_data(ttl=5, show_spinner=False)
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
    # First line only, capped: SDK errors can embed the full request log, including the
    # Authorization header, and that must never be rendered.
    lines = (str(e).strip() or e.__class__.__name__).splitlines()
    msg = lines[0][:300]
    # Keep the HTTP status line ("< 403 Forbidden < Invalid scope ...") if the SDK buried it below.
    status = next((l.strip(" `") for l in lines[1:] if l.lstrip().startswith("< ")), "")
    if status:
        msg = f"{msg.split('. Request log')[0]}. {status[:160]}"
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

# Switching identity exists only off-platform (DEV_USER set, no Databricks header). Behind
# Databricks Apps auth the forwarded email is the only identity, so nobody can act as an owner.
LOCAL = bool(DEV_USER) and not forwarded
if LOCAL:
    people = [DEV_USER, *CATALOGUE["owner"].tolist(), *(REQ["requester"].tolist() if not REQ.empty else [])]
    people = list(dict.fromkeys(p for p in people if p))
    ME = st.session_state.get("act_as", DEV_USER)
    if ME not in people:
        people.append(ME)
else:
    ME = forwarded


def _act_as(who: str | None) -> None:
    """Local only: become another user. Their requests, queue and access drive every page,
    and the previous user's outcome messages are cleared so nothing carries over."""
    who = (who or "").strip()
    if who and who != st.session_state.get("act_as", DEV_USER):
        st.session_state["act_as"] = who
        for k in ("flash_request", "flash_decision", "genie"):
            st.session_state.pop(k, None)


def _act_as_other() -> None:
    _act_as(st.session_state.get("act_as_other"))
    st.session_state["act_as_other"] = ""

with st.sidebar:
    if st.button("Refresh data", use_container_width=True):
        refresh()
        st.rerun()

DECIDED = ("approved", "rejected", "failed", "revoked")


def notifications() -> tuple[list[dict], int]:
    """What the signed-in user should know about, from the request log alone: requests waiting on
    their decision (counted until decided) and decisions on their own requests from the last 7 days
    (counted until marked read). Returns (items, badge count)."""
    if not ME or REQ.empty:
        return [], 0
    seen = st.session_state.setdefault("notif_seen", set())
    items = []
    for r in REQ[(REQ["status"] == "pending") & (REQ["approver"] == ME)].itertuples():
        items.append({"id": r.id, "dot": "pending", "unread": True, "when": r.requested_at,
                      "text": f"<b>{esc(r.requester)}</b> wants <b>{esc(short(r.table_name))}</b>",
                      "small": f"{esc(money(r.licence_cost))} / month, {esc(ago(r.requested_at))}. Decide in Approvals."})
    week = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)
    mine = REQ[(REQ["requester"] == ME) & REQ["status"].isin(DECIDED) & (REQ["decided_at"] >= week)]
    for r in mine.itertuples():
        verb = {"approved": "Approved", "rejected": "Rejected", "failed": "Grant failed", "revoked": "Revoked"}[r.status]
        note = f" {esc(r.note)}" if r.status in ("rejected", "failed") and r.note else ""
        items.append({"id": r.id, "dot": r.status, "unread": r.id not in seen, "when": r.decided_at,
                      "text": f"{verb}: <b>{esc(short(r.table_name))}</b>",
                      "small": f"By {esc(r.decided_by)}, {esc(ago(r.decided_at))}.{note}"})
    items.sort(key=lambda i: i["when"], reverse=True)
    return items, sum(i["unread"] for i in items)


def _mark_read(ids: list[str]) -> None:
    st.session_state.setdefault("notif_seen", set()).update(ids)


NOTES, UNREAD = notifications()
bar_l, bar_bell, bar_r = st.columns([3, .32, 1.4], vertical_alignment="center")
with bar_bell:
    with st.popover(f"Notifications, {UNREAD} unread" if UNREAD else "Notifications"):
        st.markdown(
            f'<div class="notif-panel"><div class="nh"><b>Notifications</b>{f"<span>{UNREAD} new</span>" if UNREAD else ""}</div>'
            + ("".join(f'<div class="notif{" unread" if n["unread"] else ""}"><span class="dot d-{esc(n["dot"])}"></span>'
                       f'<div>{n["text"]}<small>{n["small"]}</small></div></div>' for n in NOTES)
               or '<div class="notif-empty">You\'re all caught up.</div>')
            + '</div>', unsafe_allow_html=True)
        decided_unread = [n["id"] for n in NOTES if n["unread"] and n["dot"] != "pending"]
        if decided_unread:
            st.button("Mark all as read", key="notif_read", use_container_width=True,
                      on_click=_mark_read, args=(decided_unread,))
# Header mark: an open padlock, white line work, no tile. assets/emblem.svg is the same padlock on a
# blue glass tile for the favicon; change both together.
EMBLEM = ('<svg class="emblem" viewBox="0 0 28 28" fill="none" aria-hidden="true">'
          '<rect x="7" y="12.5" width="14" height="10" rx="2.2" stroke="#FFFFFF" stroke-width="1.6"/>'
          '<path d="M10.5 12.5V9a3.5 3.5 0 0 1 7 0" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"/>'
          '<circle cx="14" cy="17.5" r="1.3" fill="#FFFFFF"/></svg>')
bar_l.markdown(f'<div class="appname">{EMBLEM}<span class="name">Doorman</span></div>',
               unsafe_allow_html=True)
with bar_r:
    with st.popover(ME or "Not signed in"):
        if LOCAL:
            # Only the people you can switch to; you're already shown on the pill.
            for person in (p for p in people if p != ME):
                st.button(person, key=f"as::{person}", use_container_width=True,
                          on_click=_act_as, args=(person,))
            st.text_input("Someone else", key="act_as_other", placeholder="Other email",
                          on_change=_act_as_other, label_visibility="collapsed")
        elif ME:
            st.markdown(f"Signed in through Databricks as **{ME}**.")
            st.caption("To use the app as someone else, open it in a private window and sign in as them.")
        else:
            st.markdown("Not signed in. Requests and decisions are disabled.")
initial = esc((ME or "?")[:1].upper()).replace('"', "")
BADGE = "" if not UNREAD else f"""
[data-testid="stHorizontalBlock"]:has(.appname) > div:nth-child(2) [data-testid="stPopover"] button::after {{
  content: "{min(UNREAD, 99)}"; position: absolute; top: -5px; right: -6px; min-width: 19px; height: 19px; padding: 0 5px;
  border-radius: 999px; display: grid; place-items: center; font-size: .68rem; font-weight: 700; color: #FFFFFF;
  background: #2563EB; border: 2px solid #16181D; line-height: 1; }}"""
# Open the account menu on hover (Streamlit popovers are click-only). Same-origin component, so it
# can reach the app document; it only clicks the pill's own button, and clicking still works.
components.html("""<script>
// Installs once into the app page itself (not this iframe): Streamlit re-mounts the iframe on reruns,
// and Chrome stops running callbacks that belong to a detached iframe.
const install = (P, d) => {
  if (P.__ddaHoverMenu) return;
  P.__ddaHoverMenu = true;
  let timer = null, ours = false;
  const pill = () => d.querySelector('[data-testid="stHorizontalBlock"]:has(.appname) > div:last-child [data-testid="stPopover"] button');
  const open = () => !!d.querySelector('[data-testid="stPopoverBody"]');
  d.addEventListener("mouseover", (e) => {
    const b = pill(); if (!b) return;
    const inside = b.contains(e.target) || e.target.closest('[data-testid="stPopoverBody"]');
    if (inside) {
      P.clearTimeout(timer);
      if (b.contains(e.target) && !open()) { ours = true; b.click(); }
    } else if (ours && open()) {
      P.clearTimeout(timer);
      timer = P.setTimeout(() => { if (ours && open()) { ours = false; pill() && pill().click(); } }, 320);
    }
  });
  d.addEventListener("click", (e) => { const b = pill(); if (b && b.contains(e.target) && e.isTrusted) ours = false; }, true);
  // Streamlit 1.38 shows a false "Page not found" dialog on direct links to a page (the page still
  // loads). Close only that dialog, as soon as it appears.
  const dismiss = () => d.querySelectorAll('[role="dialog"]').forEach((dlg) => {
    if (/Page not found/.test(dlg.textContent || "")) {
      const close = dlg.querySelector('button[aria-label="Close"], button');
      if (close) close.click();
    }
  });
  dismiss();
  new P.MutationObserver(dismiss).observe(d.body, { childList: true, subtree: true });
  // Full screen as a matched-geometry move (FLIP): the table grows from where it sits on the page to
  // fill the screen with a spring, and shrinks back into place on exit. Skipped with reduced motion.
  const calm = P.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const spring = "cubic-bezier(.22, 1.18, .36, 1)";
  const full = new P.WeakMap(), before = new P.WeakMap();
  // Record the frame's rect at the moment the toolbar is pressed, before Streamlit re-lays it out.
  d.addEventListener("pointerdown", (e) => {
    const f = e.target.closest && e.target.closest('[data-testid="stFullScreenFrame"]');
    if (f && e.target.closest('[data-testid="stElementToolbar"]')) before.set(f, f.getBoundingClientRect());
  }, true);
  const watchFull = () => d.querySelectorAll('[data-testid="stFullScreenFrame"]').forEach((f) => {
    const now = P.getComputedStyle(f).position === "fixed";
    if (full.has(f) && full.get(f) !== now && !calm) {
      const from = before.get(f), to = f.getBoundingClientRect();
      if (from && to.width && to.height) {
        const dx = from.left - to.left, dy = from.top - to.top, sx = from.width / to.width, sy = from.height / to.height;
        f.animate([{ transformOrigin: "0 0", transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`, borderRadius: "16px" },
                   { transformOrigin: "0 0", transform: "none", borderRadius: now ? "0px" : "14px" }],
                  { duration: now ? 460 : 400, easing: spring });
      }
      before.delete(f);
    }
    full.set(f, now);
  });
  watchFull();
  new P.MutationObserver(watchFull).observe(d.body, { attributes: true, attributeFilter: ["class", "style"], subtree: true });
  // Loader: a glass panel named after the button just pressed, shown if the rerun takes > 180ms.
  const hud = d.createElement("div");
  hud.className = "dda-hud"; hud.setAttribute("role", "status"); hud.setAttribute("aria-live", "polite");
  hud.innerHTML = '<span class="sp" aria-hidden="true"></span><span class="tx">Updating</span>';
  d.body.appendChild(hud);
  const verbs = [["Confirm approve", "Granting access"], ["Reject request", "Rejecting"],
                 ["Confirm revoke", "Revoking access"], ["Request access", "Sending request"],
                 ["Refresh data", "Refreshing"], ["Ask", "Asking Genie"]];
  let pressed = "", showT = null, hideT = null;
  d.addEventListener("click", (e) => { const b = e.target.closest && e.target.closest("button");
    if (b) pressed = (b.innerText || "").trim(); }, true);
  const sync = () => {
    const app = d.querySelector(".stApp");
    const running = app && app.getAttribute("data-test-script-state") === "running";
    if (running) {
      P.clearTimeout(hideT); hideT = null;  // back-to-back reruns keep one panel up, no flicker
      if (!showT && !hud.classList.contains("on")) {
        showT = P.setTimeout(() => { const v = verbs.find(([k]) => pressed.startsWith(k));
          hud.querySelector(".tx").textContent = v ? v[1] : "Updating"; hud.classList.add("on"); showT = null; }, 180);
      }
    } else if (!hideT) {
      hideT = P.setTimeout(() => { P.clearTimeout(showT); showT = null; hud.classList.remove("on"); pressed = ""; hideT = null; }, 160);
    }
  };
  const app0 = d.querySelector(".stApp");
  if (app0) new P.MutationObserver(sync).observe(app0, { attributes: true, attributeFilter: ["data-test-script-state"] });
};
const host = window.parent.document;
if (!window.parent.__ddaHoverMenu) {
  const sc = host.createElement("script");
  sc.textContent = "(" + install.toString() + ")(window, document);";
  host.head.appendChild(sc);
}
</script>""", height=0)
st.markdown(f"""<div class="topbar-rule"></div><style>
[data-testid="stHorizontalBlock"]:has(.appname) > div:last-child [data-testid="stPopover"] button p::before {{
  content: "{initial}"; }}
{BADGE}
</style>""", unsafe_allow_html=True)


def large_title(title: str, sub: str) -> None:
    st.markdown(f'<h1 class="lt">{esc(title)}</h1><p class="lt-sub">{esc(sub)}</p>', unsafe_allow_html=True)

if REQ_ERROR is not None:
    st.error(f"Couldn't read the request log ({REQUESTS}): {friendly(REQ_ERROR)}. "
             "Check the SQL warehouse is running, then choose Refresh data.")


def flash(slot: str) -> None:
    """Show (and keep) the last outcome stored under slot."""
    msg = st.session_state.get(slot)
    if msg:
        kind, text = msg
        # Invisible marker so CSS can give the next alert its glass tint (Streamlit gives none).
        st.markdown(f'<span class="flash-mark flash-{"ok" if kind == "ok" else "err"}"></span>',
                    unsafe_allow_html=True)
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
    """Determinate three-segment progress: Requested, Owner review, Access granted."""
    def at(k):
        v = (row or {}).get(k)
        return "" if v is None or pd.isna(v) else ago(v)
    who = (row or {}).get("decided_by") or owner
    filled, _colour, labels, cur, note = {
        "none":     (0, "--faint", ["Request", "Owner review", "Access granted"], 0,
                     f"Send a reason and {owner} decides."),
        "pending":  (2, "--amber", ["Requested", "Owner review", "Access granted"], 1,
                     f"Waiting on {owner}. <em>Sent {at('requested_at')}.</em>"),
        "approved": (3, "--green", ["Requested", "Approved", "Access granted"], 2,
                     f"Granted by {who}. <em>{at('decided_at').capitalize()}.</em>"),
        "rejected": (2, "--red", ["Requested", "Rejected", "Access granted"], 1,
                     f"Rejected by {who}. <em>{at('decided_at').capitalize()}.</em>"),
        "failed":   (3, "--red", ["Requested", "Approved", "Grant failed"], 2,
                     f"Approved by {who}, but the grant failed. <em>{at('decided_at').capitalize()}.</em>"),
        "revoked":  (3, "--faint", ["Requested", "Approved", "Revoked"], 2,
                     f"Access revoked by {who}. <em>{at('decided_at').capitalize()}.</em>"),
    }[state]
    segs = "".join(f'<i class="{"on" if i < filled else ""} {"cur" if i == cur else ""}"></i>' for i in range(3))
    steps = "".join(f'<span class="{"cur" if i == cur else ""}">{esc(t)}</span>' for i, t in enumerate(labels))
    # note carries pre-built <em>; escape the dynamic parts only
    safe = note.replace(owner, esc(owner)).replace(str(who), esc(who)) if note else ""
    return (f'<div class="prog {state}" role="img" aria-label="{esc(labels[cur])}, step {cur + 1} of 3">'
            f'<div class="prog-track">{segs}</div>'
            f'<div class="prog-steps">{steps}</div><div class="prog-note">{safe}</div></div>')


DOWNLOAD_ROWS = 5000


def download_box(a) -> None:
    """Fetch and offer the granted table as CSV. The SELECT runs as the signed-in user, so
    Unity Catalog enforces the grant: without one it fails here too. `a.table` comes from
    the tag-driven catalogue (an allowlist), never from input."""
    slot = f"csv::{a.table}"
    if st.button(f"Download CSV (first {DOWNLOAD_ROWS:,} rows)", key=f"dl::{a.table}", type="primary"):
        try:
            with st.spinner("Reading from Unity Catalog..."):
                rows = run_sql(f"SELECT * FROM {a.table} LIMIT {DOWNLOAD_ROWS}")
            st.session_state[slot] = pd.DataFrame(rows).to_csv(index=False).encode()
        except Exception as e:  # noqa: BLE001 - a denied read is the point of showing it
            st.session_state.pop(slot, None)
            st.error(f"Couldn't read {a.asset}: {friendly(e)}")
    if slot in st.session_state:
        st.download_button(f"Save {a.asset}.csv", st.session_state[slot], type="primary",
                           file_name=f"{a.asset}.csv", mime="text/csv", key=f"dlb::{a.table}")


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
    note = str((row or {}).get("note") or "")
    rows = [("Owner", esc(a.owner)),
            ("Sensitivity", f'<span class="dot d-{esc(a.sensitivity)}"></span>{esc(a.sensitivity.capitalize())}'),
            ("Your access", f'<span class="dot d-{esc(state)}"></span>{esc(ACCESS_LABEL[state])}'),
            ("Location", esc(a.table))]
    if state in ("rejected", "failed", "revoked") and note:
        rows.append(("Note from owner" if state == "rejected" else "Detail", esc(note)))
    if state == "pending":
        rows.append(("Your reason", esc(row["reason"])))
        if note.strip().lower() == "vague":
            rows.append(("Reason check", '<span class="dot d-pending"></span>Flagged as vague'))
    body = "".join(f'<div class="g-row"><span>{k}</span><span>{v}</span></div>' for k, v in rows)
    st.markdown(f"""<div class="group">
<div class="g-head"><div><div class="g-title">{esc(a.asset)}</div><div class="g-desc">{esc(a.description)}</div></div>
<div class="g-price"><b class="{'zero' if a.cost == 0 else ''}">{esc(money(a.cost))}</b><small>per month</small></div></div>
{body}
{tracker(state, row, a.owner)}
</div>""", unsafe_allow_html=True)
    if state == "approved":
        st.caption("Query it in the SQL editor")
        st.code(f"SELECT * FROM {a.table} LIMIT 5", language="sql")
        download_box(a)

    if state not in ("pending", "approved"):
        key = f"reason::{a.table}"
        with st.form(f"request::{a.table}", clear_on_submit=False, border=False):
            st.text_area("Reason", key=key, height=76,
                         placeholder="What will you use it for? For example: intraday risk "
                                     "report for the EM book")
            st.form_submit_button("Request access", type="primary", disabled=not ME,
                                  on_click=_submit, args=(a.table, a.asset, a.owner, key))
        if not ME:
            st.caption("Sign in through Databricks to request access.")
    # A sent-request confirmation is stale once the owner has decided.
    msg = st.session_state.get("flash_request")
    if msg and (msg[0] == "err" or state == "pending"):
        flash("flash_request")


def catalogue_page() -> None:
    large_title("Catalogue", "Every data product with an owner. Pick one below to request access.")
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
    pick_desk = c1.selectbox("Desk", ["All desks", *desks], key="desk_pick")
    options = cat if pick_desk == "All desks" else cat[cat["desk"] == pick_desk]
    # Labels must stay stable across reruns: Streamlit 1.38 keys the widget on them.
    labels = {r.table: f"{r.asset}  ({money(r.cost)} / month)" for r in options.itertuples()}
    table = c2.selectbox("Data product", list(labels), format_func=labels.get, key="product_pick")
    if table:
        product_card(cat[cat["table"] == table].iloc[0])

    st.subheader("Your requests")
    mine = REQ[REQ["requester"] == ME] if ME else REQ.iloc[0:0]
    if mine.empty:
        st.markdown('<div class="empty">No requests yet.</div>', unsafe_allow_html=True)
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
    large_title("Approvals", "Requests for tables you own.")
    flash("flash_decision")
    if not ME:
        st.warning("Sign in through Databricks to see requests assigned to you.")
        return
    queue = REQ[(REQ["status"] == "pending") & (REQ["approver"] == ME)].sort_values("requested_at")
    if queue.empty:
        st.markdown('<div class="empty">Nothing waiting on you.</div>', unsafe_allow_html=True)
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
        st.markdown('<div class="empty">No active access yet.</div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="meta" style="margin-bottom:.6rem">{len(live)} active, '
                f'<b class="num">{esc(money(live["licence_cost"].sum()))}</b> / month</div>', unsafe_allow_html=True)
    for r in live.itertuples():
        asset = short(r.table_name)
        with st.container(border=True, key=f"card-live-{r.id}"):
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
                f'<b class="num">{esc(money(total))}</b> / month if all approved</div>',
                unsafe_allow_html=True)
    for r in queue.itertuples():
        asset = short(r.table_name)
        with st.container(border=True, key=f"card-ticket-{r.id}"):
            left, right = st.columns([4, 1.3])
            vague = badge("Vague reason", "vague") if str(r.note).strip().lower() == "vague" else ""
            with left:
                st.markdown(f"""
<div class="asset">{esc(asset)} &nbsp;{badge(sens.get(r.table_name, 'unclassified').capitalize(), sens.get(r.table_name, 'unclassified'))} {vague}</div>
<div class="meta"><b>{esc(r.requester)}</b> asked {esc(ago(r.requested_at))}</div>
<div class="reason">{esc(r.reason)}</div>
""", unsafe_allow_html=True)
            with right:
                st.markdown(f"""<div class="quote"><div class="amt {'zero' if r.licence_cost == 0 else ''}">
{esc(money(r.licence_cost))}</div><div class="per">per month if approved</div></div>""",
                            unsafe_allow_html=True)
            key = f"note::{r.id}"
            c1, c2, c3 = st.columns([1.1, 3.2, 1.1], vertical_alignment="bottom")
            with c1.popover("Approve access", use_container_width=True):
                st.markdown(f"Give **{r.requester}** SELECT on **{asset}**? This runs a real Unity Catalog "
                            f"grant and adds **{money(r.licence_cost)}** a month.")
                st.button("Confirm approve", key=f"approve::{r.id}", type="primary", use_container_width=True,
                          on_click=_approve, args=(r.id, r.requester, asset))
            c2.text_input("Rejection note", key=key, placeholder="Required to reject")
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
    with st.container():
        st.markdown('<span class="genie-chips"></span>', unsafe_allow_html=True)
        cols = st.columns(len(GENIE_PRESETS))
        for i, (c, q) in enumerate(zip(cols, GENIE_PRESETS)):
            if c.button(q, key=f"genie_preset_{i}", use_container_width=True):
                with st.spinner("Asking Genie..."):
                    _ask(q)
    with st.form("genie_form", border=False):
        q = st.text_input("Your question", placeholder="For example: who approved the most requests?")
        if st.form_submit_button("Ask", type="primary"):
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
    large_title("Audit", "Every request, newest first.")
    counts = REQ["status"].value_counts()
    granted = REQ.loc[REQ["status"] == "approved", "licence_cost"].sum()
    m = st.columns([1, 1, 1, 1, 1, 1.6])
    m[0].metric("Pending", int(counts.get("pending", 0)))
    m[1].metric("Approved", int(counts.get("approved", 0)))
    m[2].metric("Rejected", int(counts.get("rejected", 0)))
    m[3].metric("Failed", int(counts.get("failed", 0)))
    m[4].metric("Revoked", int(counts.get("revoked", 0)))
    m[5].metric("Recorded licences", f"{money(granted)} / mo",
                help="Sum of licence costs on approved requests in this log. "
                     "Recorded approvals, not verified billing.")

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
        st.markdown('<div class="empty">No requests yet.</div>', unsafe_allow_html=True)
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
# Streamlit 1.38 gives the current nav link no attribute, so mark it by its href.
here = f'[data-testid="stSidebarNav"] a[href$="/{pg.url_path}"]'
st.markdown(f"""<style>
{here}, {here}:hover {{
  background: rgba(37,99,235,.16) !important; }}
{here} span {{ color: #FFFFFF !important; font-weight: 600; }}
</style>""", unsafe_allow_html=True)
pg.run()
