# UI review: app.py (Jose + Malik), 21 Oct 20:10

Reviewed `app.py`, `db.py`, `app.yaml`, `requirements.txt`, `.streamlit/config.toml`,
`genie_presets.json`, `tests/test_app.py` (11 passed) against the live schema and the
`governance.py` contract. Ranked by what matters for the 20:00 demo first.

**What it does:** three Streamlit pages (Catalogue, Approvals, Audit) that read the tag-driven
catalogue and the `access_requests` table, call `governance.*` for every change, and ask Genie
through three preset buttons. Identity comes from the `X-Forwarded-Email` header; a local
"Act as" switch appears only when `DEV_USER` is set.

**Verdict: deploy as is.** Nothing below blocks the demo. Items 1 and 2 are two-line changes
worth doing if there is a quiet minute; the rest is for after tonight.

## Should fix

1. **`pandas` is not in `requirements.txt`** (`requirements.txt:1`)
   - `app.py` imports pandas directly. Streamlit depends on pandas, so it is present today,
     but an explicit import deserves an explicit requirement.
   - Fix: add `pandas` as a second line. Zero risk.

2. **Approve has no confirmation; Revoke does** (`app.py:600`, `app.py:570`)
   - Approving applies a real Unity Catalog grant with one click. Revoke, the reversible
     action, asks "Confirm". The weights are the wrong way round.
   - Fix: wrap Approve in the same `st.popover` pattern as Revoke, or leave it for the demo
     (one click is faster on stage) and note it as a follow-up. Judges may ask.

3. **Backend gap the UI exposed: `revoke` did not check who clicked** (`governance.py`)
   - The UI only shows "Active access you own", so the button is scoped, but the function
     accepted any `decided_by`. Fixed on the backend 20:10: `PermissionError` unless the
     caller is the approver, with a test. No UI change needed.

4. **Stale queue for up to 15 s** (`app.py:214`)
   - `_live_requests` is cached for 15 s per session. When Patrick submits on his laptop,
     Younis's Approvals page may not show it until the cache expires or "Refresh data" is
     pressed. On stage, press Refresh after the request is submitted; say so in the script.
   - Fix later: drop the ttl to 5 s, or clear the cache on page navigation.

## Nice to have

5. **Approved-licences caption is duplicated** (`app.py:679-683`): the metric already has a
   `help` tooltip with the same sentence as the caption beneath. Delete the caption.

6. **Colours live twice** (`app.py:51-54` and `app.py:177-179`): the CSS variables and
   `status_style` hard-code the same hex values. A Styler cannot read CSS variables, so keep
   `status_style`, but take the hex strings from one Python dict used to render the `:root`
   block. −6 lines.

7. **Six metrics in one row** (`app.py:673`): at laptop width they fit; on the projector at
   lower resolution they may wrap unevenly. If the demo screen is small, show four (Pending,
   Approved, Rejected, Approved licences) and move Failed/Revoked into the filter.

8. **Genie preset buttons carry full questions** (`app.py:639-641`): three wide buttons whose
   labels wrap to two lines. Fine for three; a fourth would need a selectbox instead.

9. **Desk dropdown adds a click** (`app.py:462`): "Desk" then "Data product" is two picks
   before the card appears. With three tables the grouping is not earning its place; a single
   product selector would be faster on stage. Keep it if the team wants the "many desks"
   story, since the `domain` tag mechanism is real.

## Confirmed fine

- No table or owner names hard-coded; everything comes from tags (AC-001 holds).
- Every user-provided string goes through `esc()` before `unsafe_allow_html` (reason, note,
  emails, table names). No injection path found.
- `governance.approve(rid, ME, TOKEN)` is the only grant path; `grep -n GRANT app.py` is empty.
- "Act as" renders only when `DEV_USER` is set and no forwarded header exists, so it cannot
  appear behind Databricks Apps auth.
- The `vague` badge reads the pending row's `note`; with the new backend fallback the note can
  be `NULL`, which renders as no badge. Correct.
- Error states are specific and say what to do ("Check the SQL warehouse is running, then
  choose Refresh data").
- `app.yaml` matches the backend: plain warehouse id, `GENIE_SPACE_ID` set.

## Demo-day notes for whoever drives

- After Patrick submits, press **Refresh data** in the sidebar before switching to Approvals.
- The Approvals tab title shows a count only after that refresh.
- Genie answers take 10 to 20 s; the spinner is there. Talk over it.
- If the SQL warehouse has gone cold, the first page load takes ~30 s. Open the app before
  walking up.
