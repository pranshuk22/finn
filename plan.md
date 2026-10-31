# FINN build plan

First written Sat 31 Oct 2026, 01:47 IST. Updated Sat 31 Oct, 14:15 IST. Deadline Sun 1 Nov 2026.

The brief decides the trade-offs: "Thin-but-working beats broad-but-broken" and "A demo that doesn't run is the worst outcome." So: deploy early, keep the backend honest, spend the remaining time on the frontend, and cut scope before cutting quality.

## Ground rules

- No em dashes or en dashes anywhere: UI copy, code, comments, docs, commits. The API also replaces any that arrive inside exchange filings. CI enforces it; locally: `git grep -nIP '\x{2013}|\x{2014}'`
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
| Tests and CI | Backend 16 (parser, quote check, verdicts, wording, brief grouping, breadth); frontend 20 (formatting, summary, routing); GitHub Actions workflow with a no-dash check, runs once the repo is pushed | |
| Hosting | Lightsail Mumbai: every source answers from it; app, Caddy HTTPS and timers running (`deploy/`) | E22, E25 |
| Ledgers | 11 companies built, TRENT correctly empty; HAL read against its quotes; checks state their gap and rerun on new results | E26 |
| Ask | Tested on TCS: 2 cited answers, 1 refusal, no quote dropped | E26 |
| Classifier eval | 60 blind-labelled, 30 held out; fixes for a hidden QIP, press releases, seniority | E27 |
| Frontend | Brief with a computed summary and portfolio breadth, Research (ledger, quote sheets, charts, Ask), Alerts with live replay, Search, Settings (theme, accent, typeface, size); PWA with on-device cache; every pairing AA | E24 |

## Left, in order

Owner in brackets.

### 1. Public link [done]

- Port 443 open; the app is live at https://finn-mu-three.vercel.app, with `/api` forwarded to Lightsail (E25). No domain needed.

### 2. Phone test [me, then you] 30 minutes, after 1

- Open the link on a real phone over mobile data, install to the home screen, go through every screen. Fix what breaks.

### 3. Classifier eval [done, your spot-check pending]

- 60 blind-labelled plus 30 held out: priority 80% before fixes, 83% held out; fixes and method in E27. Regression test in CI.
- You: `eval/SPOTCHECK.md`, 15 rows, reply with the numbers you disagree with.

### 4. Polish [me]

- Screenshot pass on the ledger and Ask sheets, empty states (a 24h window with nothing), and the offline note.
- Build one ledger from the app on the server for a new ticker, to prove that path on the live box.

### 5. Submission [me, then you] Sunday

- README: live link, measured telemetry totals from `/api/meta`, classifier eval numbers.
- Export the Claude Code sessions into `build-history/`.
- Draft the covering email: what was built, key decisions and trade-offs, what was left out, what is next.
- Final dash check, tests, lint.
- You: create the GitHub repo (public or private until submission is your call) and approve the push.
- You: send to `assessment@enam.com`, subject `ENAM - IIT screening - 2027`, with the deployed link, repo link, build history and writeup.

## Schedule

| When (IST) | Work |
| --- | --- |
| Sat afternoon | 2 (phone test), 4 |
| Sat evening | 3 (eval, with your spot-check) |
| Sun morning | Polish from your feedback |
| Sun afternoon | 5 (submission) |

**Checkpoint, Sat 23:00:** a phone can open the deployed link, see the brief, change thresholds, and open research with a ledger. Met on Sat afternoon: the link works from a filtered network and a phone-sized browser.

## Cut order if time runs short

Last added, first cut: Ask UI, per-category overrides, bull and bear UI, alert replay UI (keep the sliders), bios (keep name and role). Never cut: the brief, results card, promise ledger, deploy.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| NSE blocks the Lightsail IP | Checked: it does not (E25) | Refresh on your Mac, copy the database up |
| Flash daily quota runs out during review | Medium | 1 call per ledger, stored ledgers, fallback to the other Flash model, clear message when both are out |
| Free tier 503s ("high demand") | Seen on all three; 5 of 16 ledger requests on 31 Oct (E26) | Retries, then sibling model; nothing in the brief depends on a live model call |
| A reviewer's network filters sslip.io | Seen on your network (E25) | Public link is on vercel.app |
| Ledger quality varies by company | Medium | Quote check drops unsupported rows; show how many were dropped; hand-check one ledger |
| Credits do not cover Lightsail | Not yet confirmed | $7 for the month on the card |

## Decisions waiting on you

1. GitHub: repo name, public or private until submission, and approval to push.
2. Spot-check of the classifier labels (step 3).
