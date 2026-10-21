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

## Visual cleanup: a Revolut-style pass (after tonight, ~1 hour)

Revolut's ethos in five words: one accent, big numbers, no borders, generous space, calm.
The current page is close in spirit (dark, restrained, tabular numbers) but still looks like
a styled Streamlit form. Concrete changes, each small:

10. **One accent only** (`app.py:51-54`). The palette uses blue, green, amber and red as
    first-class colours. Keep blue for actions; demote green/amber/red to small status dots or
    pill text, never fills or borders. Revolut cards never shout.

11. **Drop the borders, use fills** (`app.py:378`, `app.py:564`, `app.py:585`,
    `.state`, `.empty`, `[data-testid="stMetric"]`). Every card is `border=True` plus a
    1px rule. Replace with `border=False` and a slightly lighter surface (`--slate` on
    `--navy`), radius 16px, padding 20px. Dashed empty-state boxes become plain muted text.

12. **One number per card, big** (`.quote .amt`). The £ figure is already the hero at
    2.1rem; make it 2.6rem, weight 600, and put the unit as a small muted line under it
    everywhere a cost appears (approvals, active access, audit metrics). Metric tiles on the
    Audit page: value 2.2rem, label 0.8rem uppercase with letter-spacing, no box.

13. **Pills, not badges with borders** (`.badge`). Remove `border: 1px solid currentColor`;
    use a 12% tint fill, 999px radius, 0.72rem, medium weight. Sensitivity and access state
    become the same pill style.

14. **Progress tracker as a thin line** (`.track`). The three-step strip is the most
    "dashboard" element. Revolut would show one short sentence ("Waiting on Younis since
    14:02") with a single thin progress line under it. Keep the dots, drop the pulse
    animation, lose the boxes.

15. **Tighter header** (`.dda-head`). Title at 1.6rem, drop the subtitle sentence (it reads
    as marketing), move "Signed in as" into the sidebar bottom as a small avatar-less row.

16. **Buttons** (`st.button` / `form_submit_button`). Primary: filled accent, 12px radius,
    no border, full width inside cards. Secondary (Reject, Revoke): text-only in muted ink,
    no outline. Streamlit's default secondary button has a grey border; override
    `button[kind="secondary"] { border: 0; background: transparent }`.

17. **Typography** (`.streamlit/config.toml`). `font = "sans serif"` gives system Helvetica.
    Inter or Söhne-like faces are closest to Revolut; Inter is available via Google Fonts
    only if the Apps CSP allows it, so test once. Body 15px, line-height 1.45, headings
    weight 600, uppercase labels at 0.72rem with 0.06em tracking.

18. **Sidebar** (`section[data-testid="stSidebar"]`). Remove the right border; page names
    as plain text with the active one in accent, no pill background. "Refresh data" becomes
    an icon-sized text button at the bottom, not a full-width box at the top.

19. **Tables** (`st.dataframe` on all three pages). Default Streamlit grids look like
    spreadsheets. Hide the toolbar (`toolbarMode` is already minimal), set row height 40px,
    zebra off, header muted uppercase, and colour only the Status cell text. If time allows,
    replace the Catalogue grid with the cards only; the grid duplicates them.

Order of impact for the least work: 11 → 13 → 10 → 12 → 16. Those five are CSS-only and
take about 30 minutes.

## Demo-day notes for whoever drives

- After Patrick submits, press **Refresh data** in the sidebar before switching to Approvals.
- The Approvals tab title shows a count only after that refresh.
- Genie answers take 10 to 20 s; the spinner is there. Talk over it.
- If the SQL warehouse has gone cold, the first page load takes ~30 s. Open the app before
  walking up.
