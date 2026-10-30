# FINN build plan

Written Sat 31 Oct 2026, 01:47 IST. Deadline Sun 1 Nov 2026. That leaves about 46 hours, including sleep.

Starting point: README, pyproject.toml and requirements.txt. No code, no git repo, `uv` not installed ([E12](docs/EVIDENCE.md#e12-local-toolchain)).

The brief's own words decide the trade-offs: "Thin-but-working beats broad-but-broken" and "A demo that doesn't run is the worst outcome." So the plan is ordered to have a deployed, working thin slice by Saturday night, and spends Sunday on depth and polish.

## Ground rules

- No em dashes or en dashes anywhere: UI copy, code, comments, docs, commits. Run `grep -rn $'—\|–' .` before every commit.
- Commits: short title (under 50 characters), one or two crisp lines of body if needed. No co-author trailers.
- Every number in the README or UI that is not live data comes from `docs/EVIDENCE.md` or the telemetry table.
- Models never do arithmetic. Python computes every percentage, ratio, and unit conversion.
- If a step overruns its time box by 50%, cut its P1 parts and move on.

## Scope

**P0: must ship.** Without these there is no submission.

1. Ingest: NSE filings, EOD prices, results iXBRL, Screener financials and transcript links.
2. Classifier: label map, then rules, then Flash-Lite.
3. Brief screen: windowed digest, three priority groups, collapsed routine line, "caught up" state.
4. Results card with QoQ and YoY, parsed not generated.
5. Threshold alerts with sliders (price ±X%, volume Y times 20-day average).
6. Research brief for any ticker: snapshot, trajectory, cash quality, promise ledger.
7. "Dig in" from a push card opens research at the right section.
8. Deployed URL that works on a phone, backed by a committed SQLite snapshot.

**P1: should ship.** Each one is independent, so they can drop without breaking anything.

9. Management change card with background and sources.
10. Alert backtest preview: "these settings would have fired N alerts in 60 days".
11. Bull and bear.
12. Ask bar with cited answers and quote verification.
13. Telemetry: per-call token and latency log, totals in README.

**P2: only if time is left.**

14. New transcript updates the promise ledger and pushes a card.
15. Order and capex size as a share of revenue.
16. Web push notifications.

## Schedule

| Block | When (IST) | Work | Done when |
| --- | --- | --- | --- |
| 0 | Sat 02:00 to 02:30 | Setup | Repo initialised, first commit pushed |
| 1 | Sat 09:00 to 12:00 | Ingestion | Four ingest scripts fill SQLite for all 18 tickers |
| 2 | Sat 12:00 to 14:30 | Classifier and results parser | Labelled eval passes; TCS and one bank parse correctly |
| 3 | Sat 14:30 to 16:00 | API | `/brief`, `/alerts`, `/research/{ticker}` return real data |
| 4 | Sat 16:00 to 21:00 | Frontend thin slice | Brief, alerts and research screens work on a phone |
| 5 | Sat 21:00 to 23:00 | Deploy | Public URL opens on a phone |
| 6 | Sun 09:00 to 13:00 | Promise ledger | Ledger renders for TCS and ASIANPAINT with verified quotes |
| 7 | Sun 13:00 to 16:00 | P1 features | As many of 9 to 13 as fit |
| 8 | Sun 16:00 to 19:00 | Design pass | Matches the reference design; tested at 390 px |
| 9 | Sun 19:00 to 21:00 | Refresh snapshot, final checks, submit | Email sent |

The promise ledger is the hero feature but sits on Sunday morning on purpose: it depends on transcripts and the research endpoint from Saturday, and Saturday must end with something deployed.

## Steps

### Block 0. Setup

- Install `uv` (`brew install uv`). `git init`, `.gitignore` (`.env`, `.venv`, `node_modules`, `__pycache__`, `*.db-wal`).
- Fix dependencies from [E11](docs/EVIDENCE.md#e11-package-versions-on-pypi-2026-10-31): replace `duckduckgo-search` with `ddgs`. Pin `yfinance==1.7.0`, which is the version tested.
- `.env.example` with `GEMINI_API_KEY`.
- Create the Gemini key in AI Studio and **write down the free tier RPM and RPD shown there** in EVIDENCE.md. They are not printed on the docs page ([E10](docs/EVIDENCE.md#e10-gemini-model-availability-and-free-tier-checked-against-google-docs)).
- Run one call each to `gemini-3.1-flash-lite`, `gemini-3.5-flash-lite` and `gemini-3.8-flash` to confirm the key can reach them.
- Create the GitHub repo and push.

### Block 1. Ingestion

Layout:

```text
backend/
  config.py           tickers, aliases, category map
  db.py               SQLite schema and helpers
  sources/
    nse.py            session with cookie warm-up, announcements, integrated filings
    eod.py            yfinance download, NaN-close filter, 20-day average volume
    screener.py       quarterly and annual tables, transcript and AR links
    pdf.py            download with correct Referer, PyMuPDF text per page
  jobs/refresh.py     runs all of the above, idempotent
```

Tables:

- `filings(id, ticker, an_dt, nse_label, text, pdf_url, category, priority, summary, classified_by)`
- `eod(ticker, date, close, volume)`; moves and multiples are computed at query time.
- `results(ticker, period_end, consolidated, revenue, ebitda, pbt, pat, unit, source_url)`
- `financials(ticker, statement, period, line_item, value)`, from Screener.
- `documents(ticker, kind, period, url, pages_json)`; transcripts and annual report text, page by page.
- `llm_calls(id, task, model, tokens_in, tokens_out, cached_tokens, latency_ms, ts)`

Checks:

- NSE: use one `httpx.Client`, hit the homepage first, sleep 0.8 s between symbols ([E2](docs/EVIDENCE.md#e2-filing-volume-for-the-18-stock-portfolio-october-2026) did 18 calls with zero failures at this pace).
- EOD: drop rows where close is NaN ([E9](docs/EVIDENCE.md#e9-yfinance-works-with-one-data-quality-trap)). Download 90 days so the 20-day average and the 60-day backtest both have data.
- Screener: consolidated page first, standalone if the consolidated table is empty.
- Transcripts: last 4 per ticker, BSE links get `Referer: https://www.bseindia.com/` ([E8](docs/EVIDENCE.md#e8-concall-transcripts-are-text-pdfs-of-manageable-size)).
- Annual report: download the latest one only, keep page text, and pull out pages that mention "segment" and "Management Discussion" for the snapshot. Do not send 300 pages to a model.

Commit after each source works.

### Block 2. Classifier and results parser

**Classifier.**

1. Label map: NSE `desc` to category, for the labels that map one-to-one.
2. Text rules on `attchmntText` for the ambiguous labels (`General Updates`, `Updates`, `Outcome of Board Meeting`, `Press Release`, `Analysts/Institutional Investor Meet/Con. Call Updates`).
3. Flash-Lite for whatever is left, with structured output: `{category, priority, one_line}`. Batch 20 filings per call to cut overhead.

**Classifier eval** (this is the evidence for the routing claim):

- Hand-label 60 October filings, picked so that every stage gets some. Save as `eval/filings_labelled.json`.
- Measure accuracy per stage, and for the model stage run both `gemini-3.1-flash-lite` and `gemini-3.5-flash-lite`. Pick the cheaper one unless it is more than 5 points worse.
- Write the numbers into EVIDENCE.md as E14. Replace the "23% need a model" figure if tuned rules change it.

**Results parser.**

- From the integrated-filing iXBRL ([E6](docs/EVIDENCE.md#e6-quarterly-results-numbers-are-available-as-structured-data)): Revenue from operations, Other income, Finance costs, Depreciation, PBT, PAT. Anchor on the P&L table, not the first match, because "Profit before tax" also appears in the segment table.
- Convert lakh to crore in Python. EBITDA = PBT + finance costs + depreciation - other income, shown with a "derived" tag.
- QoQ and YoY need the previous quarter and the same quarter last year: take those from Screener's quarterly table and check the current quarter against it. If they disagree by more than 1%, show the iXBRL number and a "check" marker.
- Banks (HDFCBANK, ICICIBANK, BAJFINANCE): the iXBRL uses a different format. Show what parses (total income, PBT, PAT) and print "EBITDA is not meaningful for banks" instead of a number.
- Tests: TCS Sep 2026 revenue must equal 73,188 crore. One bank must parse without crashing.

### Block 3. API

- `GET /api/brief?window=24h` returns groups (needs_you, worth_knowing, routine_count, routine_items), data freshness, and alert hits.
- `GET /api/alerts/rules`, `PUT /api/alerts/rules`
- `GET /api/alerts/backtest?price_pct=3&vol_mult=2&days=60` (P1)
- `GET /api/research/{ticker}` returns cached sections at once and builds the missing ones. Resolve aliases first.
- `POST /api/research/{ticker}/ask` (P1)
- `GET /api/meta` returns data as-of times and the telemetry totals.

The API never calls a source synchronously for the brief. Only research for an uncached ticker does live work, and the UI shows progress per section while it runs.

### Block 4. Frontend thin slice

Stack: Vite, React, Tailwind, shadcn/ui, `vite-plugin-pwa`. One codebase, served by FastAPI in production.

Screens:

1. **Brief.** Window chips. "Needs you" cards, then "Worth knowing", then one line "N routine filings" that expands. Each card: ticker, category, one line on why it matters, the data block (results table, bio), and two actions: **Done** and **Dig in**. Done hides the card for this window, stored locally. Empty state: "You're caught up" with the time of the last refresh.
2. **Alerts.** Two sliders and category toggles. Hits listed below. Backtest count next to the sliders (P1).
3. **Research.** Search with alias resolution. Sections as a vertical scroll with a sticky section index. Every model-written line has a citation chip that opens the quote in a bottom sheet.

Navigation: bottom tab bar (Brief, Alerts, Research). "Dig in" passes `?section=` so research opens at the right place.

Every screen has a loading state, an empty state and an error state. Test at 390 px wide in Chrome device mode and on a real phone.

### Block 5. Deploy

- One service: FastAPI serves the API and the built frontend.
- Commit `data/finn.db` as the snapshot. On boot, if live refresh fails, serve the snapshot and show "Data as of ...".
- Test from the deployed host whether NSE answers. This is an open question in EVIDENCE.md. If NSE blocks it, keep refresh local and redeploy the snapshot.
- Host candidates: Render, Railway, Fly. Choose by testing, and record what happened in EVIDENCE.md.

**Saturday night checkpoint:** a phone can open the URL, see the brief, change thresholds, and open research for a portfolio ticker. If this is not true by 23:00, Sunday morning goes to fixing it, not to the ledger.

### Block 6. Promise ledger

1. **Extract** with `gemini-3.8-flash` from each of the last 4 transcripts, structured output, one item per promise: `{metric, target_low, target_high, unit, timeframe, quote, page, speaker}`. Only explicit forward-looking statements by management. Analyst questions are context, not promises.
2. **Verify quotes** in Python: normalise whitespace and case, check the quote is a substring of that page's text. Drop items that fail and count them in telemetry.
3. **Match outcomes:**
   - Numeric promise whose timeframe has ended: compare in Python with Screener numbers and set Delivered or Missed.
   - Timeframe not ended: Pending.
   - Same metric guided again later with a different target: Revised, show both quotes.
   - Never mentioned in any later transcript: Dropped. Use the model to check mentions, since wording changes, and require a quote if it says the promise was revisited.
   - Qualitative: model judgment with the supporting later quote, tagged "model judgment".
4. **Cache** the transcripts with 3.8 Flash context caching, which is free on this model ([E10](docs/EVIDENCE.md#e10-gemini-model-availability-and-free-tier-checked-against-google-docs)), so Ask reuses them.
5. **Test** on TCS and ASIANPAINT. Read every ledger row against the PDF by hand for one company and write down the error count in EVIDENCE.md.

### Block 7. P1 features

Do them in this order, each in its own commit, each easy to drop:

- **Management bio:** Flash-Lite extracts `{name, role, joining_or_leaving}` from the filing PDF. Then `ddgs` with `"{name}" {company} {role}`, top 5 results, and Flash-Lite condenses them into 3 lines with links. Prefer the company website when sources disagree ([E5](docs/EVIDENCE.md#e5-person-search-is-ambiguous-so-bios-need-disambiguation)). Demo cases from October: LT, BAJAJ-AUTO, TATACONSUM ([E4](docs/EVIDENCE.md#e4-management-change-filings-do-not-name-the-person-in-the-summary)).
- **Backtest preview:** pure SQL over `eod`, cheap and very visible.
- **Bull and bear:** 3.8 Flash over the computed sections and the ledger. At most 3 points a side, each with a citation.
- **Ask:** cached transcripts plus the annual report pages already extracted. Same quote check as the ledger.
- **Telemetry:** wrap the model client once so every call lands in `llm_calls`.

### Block 8. Design pass

The reference design from Pinterest is still to come. When it arrives:

- Pull out tokens: colours (light and dark), type scale, radius, spacing, elevation. Put them in `frontend/src/styles/tokens.css` and in Tailwind config.
- Map the reference's components to ours: card, chip, bottom sheet, tab bar, slider, table.
- Keep numbers in `tabular-nums`, positive and negative deltas in colours that hold up in both themes, and touch targets of at least 44 px.
- Check for horizontal scroll at 360 px and 390 px.
- Remove every placeholder and lorem line. Read every UI string aloud once.

### Block 9. Ship

- Run `jobs/refresh.py` and commit the new snapshot.
- Fill the README: deployed link, measured telemetry totals, classifier eval numbers, and remove the *(planned)* tags that are now built, or keep them if not.
- Export the Claude Code sessions into `build-history/`.
- Dash check: `grep -rn $'—\|–' --exclude-dir=node_modules --exclude-dir=.venv .` must return nothing.
- Open the deployed URL on a phone over mobile data, not Wi-Fi, and click through the demo path below.
- Email `assessment@enam.com`, subject `ENAM - IIT screening - 2027`, with: deployed link, repo link, build history, and the writeup (what was built, key decisions and trade-offs, what was left out, what is next). The README's sections map one to one onto that writeup.

## Demo path (what a reviewer should see in 2 minutes)

1. Open the brief. A short list, with Polycab's NCLAT insolvency update and Reliance's Jio Platforms IPO near the top, and a "N routine filings" line at the bottom. These are real October filings ([E3](docs/EVIDENCE.md#e3-exchange-labels-alone-are-not-enough-to-classify)).
2. Tap a results card. Headline table with QoQ and YoY.
3. Tap "Dig in". Research opens at the promise ledger for that company.
4. Tap a citation. The exact transcript quote with its page.
5. Alerts: drag the volume slider and watch the count change.
6. Research: type a ticker that is not in the portfolio, for example PIDILITIND.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| NSE blocks the cloud host | Unknown, test in Block 5 | Snapshot plus local refresh |
| Free tier rate limits hit during ledger build | Medium | Batch calls, cache results in SQLite, build demo tickers ahead of time |
| iXBRL format differs for banks | Known | Partial card with a clear note |
| Ledger quality is poor on some companies | Medium | Quote check drops unsupported rows; show "N promises could not be verified" instead of hiding it |
| Time | High | P1 and P2 drop in order; Saturday night checkpoint |
