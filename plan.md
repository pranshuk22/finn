# FINN build plan

First written Sat 31 Oct 2026, 01:47 IST. Updated Sat 31 Oct, 04:20 IST. Deadline Sun 1 Nov 2026.

The brief decides the trade-offs: "Thin-but-working beats broad-but-broken" and "A demo that doesn't run is the worst outcome." So: deploy early, keep the backend honest, spend the remaining time on the frontend, and cut scope before cutting quality.

## Ground rules

- No em dashes or en dashes anywhere: UI copy, code, comments, docs, commits. The API also replaces any that arrive inside exchange filings. Check before every commit: `grep -rn $'—\|–' --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=data .`
- Commits: short title, one or two crisp lines of body. No co-author trailers.
- Every number in the README or UI that is not live data comes from `docs/EVIDENCE.md` or the telemetry table.
- Models never do arithmetic. Python computes every percentage, ratio and unit conversion.
- Flash has 20 requests a day (E19). Never run a model in a loop without checking `llm.budget()` first, and never rebuild a stored ledger without a reason.

## Done

| Area | What exists | Evidence |
| --- | --- | --- |
| Setup | uv project, git repo, `.env` with Gemini key, all three model families reachable | E10, E12 |
| Ingestion | NSE filings (cookie warm-up, 0.8 s pacing), yfinance EOD with the NaN-close filter, NSE integrated-filing iXBRL results, Screener tables, ratios and document links. `python -m backend.jobs.refresh` | E1, E2, E6, E7, E9 |
| Results parser | Companies, NBFCs and banks; old and new iXBRL formats; lakh, crore and actual units. Matches Screener for 20 of 22 on revenue | E6, E15, E23 |
| Classifier | Label map (94 labels seen live), ordered text rules, Flash-Lite in batches of 20; priority rules in code | E3 |
| Filing reader | Flash-Lite reads vague and management filings, 5 per call: one-liner, people, amounts, subsidiary flag. `python -m backend.enrich` | E17, E18 |
| Bios | Filing profile first, then career search; confident only if a source names the company; zip attachments handled | E5, E18 |
| Alerts | Price and volume scan with replay over 60 sessions; rules stored | E23 |
| Research | Snapshot, trajectory, cash quality, results card; works on unseen tickers (TITAN, 5.6 s) and aliases | E23 |
| Promise ledger | One Flash call per company; every quote verified; growth judged in Python; margins rest on quotes; revisions detected in Python. Built for TCS and ASIANPAINT | E14, E16, E19, E20 |
| Bull and bear | Flash-Lite over numbered facts; points without a valid id dropped. Built for ASIANPAINT | E19 |
| Model layer | Per-minute spacing, daily budget per model, fallback chain, telemetry in `llm_calls` | E17, E19 |
| API | `/api/brief`, `/api/alerts/rules`, `/api/alerts/scan`, `/api/research/{t}`, `/api/research/{t}/ledger`, `/api/research/{t}/ask`, `/api/companies`, `/api/meta`; gzip; dash-free JSON | E21 |
| Tests | Results parser (TCS, HDFCBANK), quote check (ligature, page break, wrong page, invented quote, changed number). 7 passing | |
| Hosting research | Lightsail Mumbai over Render free | E22 |

## Left, in order

Owner in brackets. Time is my estimate, not a measurement.

### 1. Deploy probe [you, then me] about 30 min, blocked on the instance

The biggest unknown: does NSE answer a datacenter IP? Test before building anything on top.

- You: Lightsail, Mumbai, Ubuntu 24.04, $7 plan (1 GB). Attach a static IP, open ports 80 and 443. Check in Billing that the credits cover Lightsail and note their expiry. Send me the SSH key path and the IP.
- Me: from the instance, call the NSE announcements and integrated-filing endpoints, Screener, a BSE transcript PDF and yfinance. Record results as E25.
- If NSE blocks it: refresh runs on your Mac and the database is copied to the server on a schedule. The app does not change.

### 2. Scheduled refresh inside the server [me] about 45 min

- Filings every 30 minutes from 09:00 to 20:00 IST, then classify and read new filings.
- EOD prices once after 16:30 IST on trading days.
- Results whenever a results filing arrives for a ticker.
- One lock so two refreshes never overlap; the brief shows the last refresh time.

### 3. Prebuild demo ledgers [me] mostly waiting on quota

- Budget today: 3.8 Flash about 19 calls; 3.6 Flash resets at 12:30 IST (midnight Pacific).
- Each company costs 1 Flash call (ledger) and 1 Flash-Lite call (bull and bear).
- Order: HAL, PIDILITIND, BAJFINANCE (ad-hoc), then portfolio names with fresh results in the brief: RELIANCE, INFY, HDFCBANK, LT, DIXON, TRENT, POLYCAB. Rebuild TCS once on the new single-call format.
- Keep at least 8 Flash calls a day unused for reviewers who try a new ticker.
- Read one full ledger against its PDFs by hand and record the error count in EVIDENCE.

### 4. Paths built but not run end to end [me] about 1 h

- Ask: run 3 questions on TCS, including one the transcripts cannot answer; check refusals and citations.
- Ledger build through the API in the background thread, and the `jobs` status the UI will poll.
- Results card when a quarter's iXBRL is missing: fall back to Screener for QoQ and YoY, labelled.
- A ledger for a bank (HDFCBANK) and an NBFC (BAJFINANCE).
- What the brief shows when the window has no filings, and when NSE is unreachable.

### 5. Classifier eval [me, then you] about 45 min plus 10 min of yours

- 60 October filings, picked so every stage is represented. I label them from the filing text; you spot-check at least 15.
- Accuracy per stage (label, rules, model) and for priority. Saved as `eval/filings_labelled.json`, results as E27 and in the README.

### 6. Tests for the judgment code [me] about 30 min

- Brief grouping and ordering, `priority` rules, `management_priority`, numeric checks for growth, `scale`.

### 7. Frontend [me] about 6 to 8 h

Screens, in build order:

1. **Brief.** Window chips (24h, 3d, 7d, 30d). "Needs you", then "Worth knowing", then price and volume moves, then one line "N routine filings" that expands. Each card: ticker, category, headline, the data block (results table with QoQ and YoY, people with bios and sources, amount as share of revenue), and two actions: Done and Dig in. Done is stored on the device. Empty state: "You're caught up", with the last refresh time.
2. **Research.** Search with alias resolution. Sections: snapshot, results, promise ledger, trajectory, cash quality, bull and bear. Every quote opens a bottom sheet with the page and a link to the PDF. Ledger shows status chips and who judged it (numbers, quotes, or timeframe). "Build ledger" for a new ticker, with progress while it runs.
3. **Alerts.** Two sliders and category toggles; the replay count updates as you drag.
4. **Ask.** A bar at the bottom of Research; answers with citations, or a plain "the transcripts do not cover this".

Across all screens: loading, empty and error states; tabular numbers; touch targets at least 44 px; no horizontal scroll at 360 px; last response shown instantly from the device and refreshed in the background; installable PWA. Dig in from a results card opens Research at the ledger.

Design: muted slate with a taupe accent, from the reference you chose (E24). Tokens are in `frontend/src/styles/tokens.css`; every text colour passes WCAG AA. Fixes seen in the preview: show tiny amounts as "under 0.01% of yearly revenue", show every time in IST, put the moves list on a fixed grid so sparklines line up.

### 8. Full deploy [me] about 1 h, after 1 and 7

- systemd service for uvicorn; Caddy for HTTPS (try an sslip.io hostname first; buy a cheap domain if Let's Encrypt refuses it).
- `.env` on the server only; database snapshot copied up; refresh scheduler on.
- Smoke test on a real phone over mobile data, not Wi-Fi. Install to home screen.

### 9. Submission [me, then you] Sunday

- README: live link, measured telemetry totals for a full run, classifier eval numbers, remove *(planned)* from what got built and keep it on what did not.
- Export the Claude Code sessions into `build-history/`.
- Draft the covering email: what was built, key decisions and trade-offs, what was left out, what is next. The README sections map onto it.
- Final dash check, tests, lint.
- You: create the GitHub repo (public or private until submission is your call) and approve the push.
- You: send to `assessment@enam.com`, subject `ENAM - IIT screening - 2027`, with the deployed link, repo link, build history and writeup.

## Schedule

| When (IST) | Work |
| --- | --- |
| Sat 04:30 to 06:00 | 4 (untested paths), 6 (tests), ledgers on remaining 3.8 Flash quota |
| As soon as the instance exists | 1 (deploy probe), then 2 (scheduler) |
| Sat 12:30 | Flash quota resets: rest of 3 (ledgers) |
| Sat afternoon | 7 (frontend), the long block |
| Sat evening | 5 (eval, with your spot-check), 8 (full deploy) |
| Sun morning | Polish frontend from your feedback, refresh snapshot |
| Sun afternoon | 9 (submission) |

**Checkpoint, Sat 23:00:** a phone can open the deployed link, see the brief, change thresholds, and open research with a ledger. If not, Sunday morning goes to that, not to polish.

## Cut order if time runs short

Last added, first cut: Ask UI, per-category overrides, bull and bear UI, alert replay UI (keep the sliders), bios (keep name and role). Never cut: the brief, results card, promise ledger, deploy.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| NSE blocks the Lightsail IP | Unknown until step 1 | Refresh on your Mac, copy the database up |
| Flash daily quota runs out during review | Medium | 1 call per ledger, stored ledgers, fallback to the other Flash model, clear message when both are out |
| Free tier 503s ("high demand") | Seen on 3.1 Flash-Lite and 3.8 Flash | Retries, then sibling model; nothing in the brief depends on a live model call |
| Ledger quality varies by company | Medium | Quote check drops unsupported rows; show how many were dropped; hand-check one ledger |
| Credits do not cover Lightsail | Unknown | $7 for the month on the card, or fall back to Render paid |

## Decisions waiting on you

1. Create the Lightsail instance and confirm the credits cover it.
2. GitHub: repo name, public or private until submission, and approval to push.
3. Spot-check of the classifier labels (step 5).
