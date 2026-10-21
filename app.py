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
DEV_TOOLS = os.getenv("DEV_TOOLS") == "1"  # "Act as" switcher for local rehearsal only

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
/* Graphite surfaces, one action blue (#2563EB: 5.2:1 with white text), Apple-style status hues. */
:root {
  --bg: #17191E; --card: #212429; --raised: #2B2F36; --rule: rgba(255,255,255,.07);
  --ink: #F2F4F7; --muted: #A3ACB9; --faint: #8E98A8;
  --blue: #2563EB; --blue-hover: #1D4ED8; --blue-ink: #7FAEFF;
  --green: #30D158; --amber: #FF9F0A; --red: #FF6961;
  --radius: 16px; --radius-sm: 10px;
}
/* One typeface (HIG typography: minimise typefaces): the system font, SF on Apple devices. */
html, body, .stApp, .stApp *:not(code):not(pre):not(.material-icons):not([data-testid="stIconMaterial"]) {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Helvetica Neue",
               "Segoe UI", Roboto, Arial, sans-serif !important;
  -webkit-font-smoothing: antialiased;
}
.stApp { background: var(--bg); color: var(--ink); }
.stCode, [data-testid="stCode"] pre { background: var(--card) !important; border-radius: 12px; }
/* Clicked buttons keep their own colours; keyboard focus still gets the ring. */
.stButton > button:focus:not(:focus-visible), .stFormSubmitButton > button:focus:not(:focus-visible),
[data-testid="stPopover"] button:focus:not(:focus-visible) { color: var(--ink) !important; border-color: rgba(255,255,255,.12) !important; }
.stButton > button[kind="primary"]:focus:not(:focus-visible),
.stFormSubmitButton > button[kind="primaryFormSubmit"]:focus:not(:focus-visible) { color: #fff !important; border-color: #1A47B5 !important; }

/* Pending: the current segment breathes so a waiting request reads as live. */
@media (prefers-reduced-motion: no-preference) {
  .prog.pending .prog-track i.cur { animation: waiting 1.6s ease-in-out infinite; }
  @keyframes waiting { 50% { opacity: .45; } }
}
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding-top: 2rem; max-width: 1180px; }
*:focus-visible { outline: 2px solid var(--blue-ink) !important; outline-offset: 2px; }
.num { font-variant-numeric: tabular-nums; }

/* Headings: weight and size carry hierarchy, no ornaments. */
h1, h2, h3 { letter-spacing: -0.02em; font-weight: 650 !important; color: var(--ink); }
[data-testid="stHeading"] h3 { font-size: 1.3rem; padding-top: 1.4rem; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }

/* Sidebar: sized to its content (Streamlit's default is 21rem). */
section[data-testid="stSidebar"] { background: var(--card); border-right: 1px solid var(--rule);
  width: 15rem !important; min-width: 15rem !important; max-width: 15rem !important; }
section[data-testid="stSidebar"] > div { width: 15rem !important; }
[data-testid="stSidebarUserContent"] { padding: 0 1rem 1rem; }
[data-testid="stSidebarNav"] { padding-top: .5rem; }
/* No header band: the collapse arrow floats in the corner, nav starts level with the top bar. */
[data-testid="stSidebarHeader"] { height: 0 !important; min-height: 0 !important; padding: 0 !important;
  margin: 0 !important; position: relative; overflow: visible; }
[data-testid="stSidebarCollapseButton"] { position: absolute; top: .4rem; right: .5rem; z-index: 3; }
[data-testid="stSidebarNavItems"] { padding: 1.9rem 1rem .5rem; margin: 0; }
[data-testid="stSidebarNavSeparator"] { margin: 0 1rem; }
[data-testid="stSidebarUserContent"] { padding-top: .5rem !important; }
[data-testid="stSidebarNav"] a { border-radius: 999px; padding: .3rem .85rem; margin: .12rem 0;
  border: 1px solid transparent; background: transparent; transition: background .15s ease, border-color .15s ease; }
[data-testid="stSidebarNav"] a:hover { background: rgba(255,255,255,.045) !important; border-color: rgba(255,255,255,.08); }
[data-testid="stSidebarNav"] a:hover span { color: #FFFFFF; }


/* Cards: bordered containers become soft rounded panels. */
/* Unbordered wrappers carry the empty emotion class; only st.container(border=True) differs. */
[data-testid="stVerticalBlockBorderWrapper"]:not(.st-emotion-cache-0) {
  background: var(--card); border: 1px solid var(--rule) !important; border-radius: var(--radius) !important;
  padding: .4rem .5rem; }
[data-testid="stDataFrame"] > div { border-radius: 12px; overflow: hidden; border: 1px solid var(--rule); }

/* Controls: pill buttons with a soft gloss (top highlight, darker base, hairline edge).
   Hover presses in: 1px down, darker, shadow tightens. Gloss stops keep white text >= 4.8:1. */
.stButton > button, .stFormSubmitButton > button, [data-testid="stPopover"] button {
  min-height: 42px; border-radius: 999px; font-weight: 600; letter-spacing: -0.005em; padding: 0 1.35rem;
  color: var(--ink);
  background: linear-gradient(180deg, rgba(255,255,255,.11) 0%, rgba(255,255,255,.04) 100%), var(--raised);
  border: 1px solid rgba(255,255,255,.12);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.16), inset 0 -1px 0 rgba(0,0,0,.25), 0 2px 6px rgba(0,0,0,.35);
  backdrop-filter: blur(12px) saturate(140%); -webkit-backdrop-filter: blur(12px) saturate(140%);
  transition: transform .12s ease, background .15s ease, box-shadow .15s ease, filter .15s ease; }
.stButton > button:hover, .stFormSubmitButton > button:hover, [data-testid="stPopover"] button:hover {
  color: #FFFFFF !important; border-color: rgba(127,174,255,.45) !important; transform: translateY(1px);
  background: linear-gradient(180deg, rgba(45,105,234,.38) 0%, rgba(30,85,212,.30) 100%), var(--raised);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.10), inset 0 2px 5px rgba(5,20,70,.40), 0 1px 3px rgba(0,0,0,.3); }
.stButton > button:active, .stFormSubmitButton > button:active, [data-testid="stPopover"] button:active {
  transform: translateY(2px); box-shadow: inset 0 2px 4px rgba(0,0,0,.45); }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"] {
  color: #FFFFFF; border: 1px solid #1A47B5;
  background: linear-gradient(180deg, #2D69EA 0%, #2563EB 45%, #1E55D4 100%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.30), inset 0 -2px 0 rgba(10,30,90,.35),
              0 3px 10px rgba(37,99,235,.35), 0 1px 2px rgba(0,0,0,.4); }
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primaryFormSubmit"]:hover {
  color: #FFFFFF; border-color: #173F9F; transform: translateY(1px);
  background: linear-gradient(180deg, #2459D8 0%, #1E51CC 50%, #1A47B5 100%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.18), inset 0 2px 5px rgba(5,20,70,.45), 0 1px 4px rgba(37,99,235,.25); }
.stButton > button[kind="primary"]:active, .stFormSubmitButton > button[kind="primaryFormSubmit"]:active {
  transform: translateY(2px);
  background: linear-gradient(180deg, #1E51CC 0%, #1A47B5 100%);
  box-shadow: inset 0 3px 7px rgba(5,20,70,.55); }
.stButton > button:disabled, .stFormSubmitButton > button:disabled {
  opacity: .45; transform: none; box-shadow: none; }
@media (prefers-reduced-motion: reduce) {
  .stButton > button, .stFormSubmitButton > button, [data-testid="stPopover"] button { transition: none; }
  .stButton > button:hover, .stButton > button:active, .stFormSubmitButton > button:hover,
  .stFormSubmitButton > button:active, [data-testid="stPopover"] button:hover { transform: none; }
}
[data-baseweb="select"] > div {
  border-radius: 14px !important; border: 1px solid rgba(255,255,255,.12) !important; cursor: pointer;
  background: linear-gradient(180deg, rgba(255,255,255,.10) 0%, rgba(255,255,255,.035) 100%), var(--raised) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.14), inset 0 -1px 0 rgba(0,0,0,.22), 0 2px 6px rgba(0,0,0,.25);
  backdrop-filter: blur(12px) saturate(140%); -webkit-backdrop-filter: blur(12px) saturate(140%);
  transition: border-color .15s ease, box-shadow .15s ease; }
[data-baseweb="select"] > div:hover { border-color: rgba(127,174,255,.40) !important; }
[data-baseweb="select"] > div:focus-within { border-color: var(--blue) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 0 0 3px rgba(37,99,235,.28); }
[data-baseweb="popover"] ul[role="listbox"], [data-baseweb="popover"] [data-baseweb="menu"] {
  background: rgba(36,40,47,.82) !important; border: 1px solid rgba(255,255,255,.12); border-radius: 14px !important;
  backdrop-filter: blur(20px) saturate(160%); -webkit-backdrop-filter: blur(20px) saturate(160%);
  box-shadow: 0 12px 32px rgba(0,0,0,.45); padding: 4px !important; }
[data-baseweb="popover"] li[role="option"] { border-radius: 9px; margin: 1px 0; }
[data-baseweb="popover"] li[role="option"]:hover, [data-baseweb="popover"] li[aria-selected="true"] {
  background: rgba(37,99,235,.30) !important; }
.stTextInput [data-baseweb="input"], .stTextArea [data-baseweb="textarea"] {
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
.quote .amt { font-size: 1.6rem; font-weight: 700; color: var(--ink); line-height: 1;
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

/* Top bar and large title, macOS/iOS style. */
.topbar { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;
  padding-bottom: .9rem; border-bottom: 1px solid var(--rule); margin-bottom: 1.1rem; }
.appname { font-size: .95rem; font-weight: 600; color: var(--ink); letter-spacing: -0.01em; }
.appname span { color: var(--faint); font-weight: 400; }
.acct { display: flex; align-items: center; gap: .55rem; color: var(--ink); font-size: .86rem; font-weight: 500;
  padding: .28rem .85rem .28rem .3rem; border-radius: 999px; border: 1px solid rgba(255,255,255,.12);
  background: linear-gradient(180deg, rgba(255,255,255,.11) 0%, rgba(255,255,255,.04) 100%), var(--raised);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.16), inset 0 -1px 0 rgba(0,0,0,.25), 0 2px 6px rgba(0,0,0,.3); }
.acct .av { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
  background: linear-gradient(180deg, #8E8E93, #636366); color: #fff; font-size: .72rem; font-weight: 600; }
.lt { font-size: 2rem; font-weight: 700; letter-spacing: -0.035em; color: var(--ink); line-height: 1.1; margin: 0; }
.lt-sub { color: var(--muted); font-size: .95rem; margin: .35rem 0 1.4rem; max-width: 70ch; line-height: 1.45; }
[data-testid="stHeading"] h3 { font-size: 1.15rem !important; font-weight: 600 !important; letter-spacing: -0.015em; }

/* Inset grouped list (HIG lists and tables, grouped style). */
.group { background: var(--card); border-radius: 14px; overflow: hidden; margin: .25rem 0 .9rem; }
.g-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1.2rem; padding: 1rem 1.1rem .95rem; }
.g-title { font-size: 1.2rem; font-weight: 650; color: var(--ink); letter-spacing: -0.02em; }
.g-desc { color: var(--muted); font-size: .92rem; margin-top: .2rem; line-height: 1.45; max-width: 62ch; }
.g-price { text-align: right; white-space: nowrap; }
.g-price b { display: block; font-size: 1.45rem; font-weight: 650; color: var(--ink);
  font-variant-numeric: tabular-nums; letter-spacing: -0.03em; line-height: 1.1; }
.g-price b.zero { color: var(--muted); }
.g-price small { color: var(--faint); font-size: .78rem; }
.g-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem;
  margin-left: 1.1rem; padding: .62rem 1.1rem .62rem 0; border-top: 1px solid var(--rule); font-size: .92rem; }
.g-row > span:first-child { color: var(--ink); }
.g-row > span:last-child { color: var(--muted); text-align: right; overflow-wrap: anywhere; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .45rem;
  vertical-align: middle; background: var(--faint); }
.d-approved { background: var(--green); } .d-pending { background: var(--amber); }
.d-rejected, .d-failed { background: var(--red); }
.g-foot { color: var(--faint); font-size: .8rem; margin: -.5rem 0 1rem 1.1rem; }

/* Determinate progress (HIG progress indicators): one track, three segments. */
.prog { padding: .95rem 1.1rem 1rem; border-top: 1px solid var(--rule); }
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
/* Liquid glass panels: one material for every surface that holds content. */
.group, .empty, [data-testid="stMetric"],
[data-testid="stVerticalBlockBorderWrapper"]:not(.st-emotion-cache-0) {
  background: linear-gradient(180deg, rgba(255,255,255,.075) 0%, rgba(255,255,255,.025) 60%, rgba(255,255,255,.015) 100%),
              var(--card) !important;
  border: 1px solid rgba(255,255,255,.09) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.10), 0 8px 24px rgba(0,0,0,.22), 0 1px 2px rgba(0,0,0,.3);
  backdrop-filter: blur(18px) saturate(150%); -webkit-backdrop-filter: blur(18px) saturate(150%); }
[data-testid="stDataFrame"] > div {
  border: 1px solid rgba(255,255,255,.09) !important; border-radius: 14px !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 8px 24px rgba(0,0,0,.22); }
.stCode, [data-testid="stCode"] pre {
  border: 1px solid rgba(255,255,255,.09); box-shadow: inset 0 1px 0 rgba(255,255,255,.08); }
/* Empty states: centred and quiet, an invitation rather than a box of text. */
.empty { text-align: center; padding: 1.6rem 1.3rem !important; color: var(--muted); font-size: .95rem; }
[data-testid="stMetric"] { padding: 1rem 1.15rem !important; }
[data-testid="stMetricValue"] > div { font-size: 2rem; }
.lt { margin-top: -.2rem !important; }
/* Code keeps a monospace face (the one-typeface rule above would otherwise reach its tokens). */
.stApp pre, .stApp pre *, .stApp code, .stApp code * {
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace !important; }
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
    # First line only, capped: SDK errors can embed the full request log, including the
    # Authorization header, and that must never be rendered.
    msg = (str(e).strip() or e.__class__.__name__).splitlines()[0][:300]
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
if DEV_TOOLS and DEV_USER and not forwarded:  # opt-in local tool, never behind Databricks Apps auth
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
        if SIMULATED:
            st.caption("Simulated: no permissions are changed.")
        st.divider()

with st.sidebar:
    if st.button("Refresh data", use_container_width=True):
        refresh()
        st.rerun()

st.markdown(f"""
<div class="topbar">
  <div class="appname">Desk Data Access <span>&nbsp;Unity Catalog entitlements</span></div>
  {(f'<div class="acct" title="Signed in"><span class="av" aria-hidden="true">{esc(ME[:1].upper())}</span>'
    f'<span>{esc(ME)}</span></div>') if ME else
   '<div class="acct">Not signed in. Requests and decisions are disabled.</div>'}
</div>
""", unsafe_allow_html=True)


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
    rows = [("Owner", esc(a.owner)), ("Sensitivity", esc(a.sensitivity.capitalize())),
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
<div class="g-price"><b class="{'zero' if a.cost == 0 else ''}">{esc(money(a.cost))}</b><small>per user, per month</small></div></div>
{body}
{tracker(state, row, a.owner)}
</div>""", unsafe_allow_html=True)
    if state == "approved":
        st.caption("Query it in the SQL editor")
        st.code(f"SELECT * FROM {a.table} LIMIT 5", language="sql")

    if state not in ("pending", "approved"):
        key = f"reason::{a.table}"
        with st.form(f"request::{a.table}", clear_on_submit=False, border=False):
            st.text_area("Reason", key=key, height=76,
                         placeholder="What will you use it for? For example: intraday risk "
                                     "report for the EM book")
            st.caption("Required. The owner reads it before deciding.")
            st.form_submit_button("Request access", type="primary", disabled=not ME,
                                  on_click=_submit, args=(a.table, a.asset, a.owner, key))
        if not ME:
            st.caption("Sign in through Databricks to request access.")
    # A sent-request confirmation is stale once the owner has decided.
    msg = st.session_state.get("flash_request")
    if msg and (msg[0] == "err" or state == "pending"):
        flash("flash_request")


def catalogue_page() -> None:
    large_title("Catalogue", "Every table with a data_owner tag in Unity Catalog. Tag a table and it "
                             "appears here, with no code change.")
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
    large_title("Approvals", "Requests for tables you own. Approving runs a real Unity Catalog grant.")
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
<div class="asset">{esc(asset)} <span class="meta">&nbsp;{esc(sens.get(r.table_name, 'unclassified').capitalize())}</span> {vague}</div>
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
    large_title("Audit", f"Every request in {REQUESTS}, newest first, in {DESK_TZ} time.")
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
# Streamlit 1.38 gives the current nav link no attribute, so mark it by its href.
here = f'[data-testid="stSidebarNav"] a[href$="/{pg.url_path}"]'
st.markdown(f"""<style>
{here}, {here}:hover {{
  background: linear-gradient(180deg, rgba(45,105,234,.34) 0%, rgba(30,85,212,.24) 100%) !important;
  border-color: rgba(127,174,255,.35) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 2px 8px rgba(37,99,235,.18); }}
{here} span {{ color: #FFFFFF !important; font-weight: 600; }}
</style>""", unsafe_allow_html=True)
pg.run()
