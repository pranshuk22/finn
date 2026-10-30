# Evidence log

Every design decision in the README and plan points back to a row here. Each entry says what was checked, how, when, and what came back. If a later probe contradicts an entry, the entry gets updated, not deleted.

All probes were run on 2026-10-31 (IST) from a home connection in India, unless noted.

## E1. NSE corporate announcements API works without a browser

- **How:** `GET https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=TCS` with a desktop User-Agent and the cookie jar from one hit to `https://www.nseindia.com/`.
- **Result:** HTTP 200, JSON list. 3,383 historical TCS filings. Each item carries `desc` (exchange label), `attchmntText` (one-line summary written by the company), `attchmntFile` (PDF), `an_dt`, `hasXbrl`.
- **Note:** the homepage itself returned 403 but still set the cookies the API needs.
- **Decision:** NSE is the primary filings source. BSE is a fallback only.

## E2. Filing volume for the 18-stock portfolio (October 2026)

- **How:** same endpoint with `from_date=01-10-2026&to_date=31-10-2026`, one call per ticker, 0.8 s apart. 0 failures out of 18.
- **Result:** 275 filings in 31 days, about 9 per day across the portfolio.
- **Top labels:** Analysts/Institutional Investor Meet/Con. Call Updates 46, General Updates 32, Outcome of Board Meeting 24, Updates 22, Copy of Newspaper Publication 17, Certificate under SEBI (Depositories and Participants) Regulations 17, ESOP/ESOS/ESPS 16, Press Release 14, Credit Rating 9.
- **Decision:** at this volume, a daily digest with routine filings collapsed is the right default. An unfiltered feed would show 9 items a day, most of them paperwork.

## E3. Exchange labels alone are not enough to classify

- **How:** split the 275 October filings by whether the NSE label maps to exactly one challenge category.
- **Result:**
  - 137 of 275 (50%) resolve from the label alone (for example `ESOP/ESOS/ESPS` is routine, `Credit Rating` is credit_rating).
  - 76 more (28%) resolve with a first, untuned set of keyword rules on `attchmntText`.
  - 62 (23%) still need a model.
- **Why labels fail, concretely:** Reliance's filings about the Jio Platforms IPO (14 Oct, 24 Oct, 27 Oct) were all labelled `General Updates`. Reliance's newspaper clippings and a media statement were both labelled `Updates`. A label-only filter would bury a subsidiary IPO, one of the most material Reliance events of the month.
- **Re-run inside the app (2026-10-31 02:03, 35-day window, 301 filings, expanded label map and reordered rules):** 140 label (47%), 98 rules (33%), 63 model (21%). The model stage for 63 filings took one batch of 20 per call, 4 calls, about 9 seconds in total on `gemini-3.1-flash-lite`.
- **Caveat:** rule precision is not measured yet. See plan.md, step "classifier eval".
- **Decision:** three-stage classifier: label map, then text rules, then a small model for what is left.

## E4. Management-change filings do not name the person in the summary

- **How:** read `attchmntText` for October `Change in Management` filings.
- **Result:** LT (7 Oct), BAJAJ-AUTO (27 Oct), TATACONSUM (26 Oct) all say only "has informed the Exchange about change in Management".
- **Decision:** the bio feature must open the PDF, extract name and role, then search. A summary-line-only approach cannot work.

## E5. Person search is ambiguous, so bios need disambiguation

- **How:** `ddgs` 9.16.1, query `K Krithivasan TCS CEO linkedin career`.
- **Result:** two different LinkedIn profiles named K Krithivasan, both listing TCS, plus the official tcs.com leadership page.
- **Decision:** the bio card shows its sources and prefers the company's own site over LinkedIn when they disagree. Bio search query always includes company name and role.

## E6. Quarterly results numbers are available as structured data

- **How:** `GET https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=TCS&type=Integrated%20Filing-%20Financials`.
- **Result:** HTTP 200. Latest row: quarter ended 30-SEP-2026, consolidated, broadcast 08-Oct-2026 22:07, with an iXBRL HTML link.
- **Parsed from that iXBRL (values in Rs lakh):** Revenue from operations 73,18,800.00; Finance costs 25,200.00; Depreciation 1,26,200.00; Other income 1,33,700.00.
- **Cross-check:** Screener's quarterly table shows Sep 2026 Sales 73,188 (Rs crore) and Net Profit 13,934. iXBRL revenue 73,18,800 lakh = 73,188 crore. Match.
- **Gotcha found:** the older endpoint `corporates-financial-results` stops at Dec 2024 for TCS and returns nothing for 2026 date ranges. Only the integrated-filing endpoint has current quarters.
- **Gotcha found:** the phrase "Profit before tax" appears in more than one table (P&L and segment results). The parser must anchor on the P&L table, not on first match. In the P&L table the rows are named "Total profit before tax" (18,638 crore for TCS) and "Total profit (loss) for period" (13,934 crore). An early probe that took the first "Profit before tax" on the page read the segment table instead.
- **Layouts:** three seen live. Companies (TCS, RELIANCE) and NBFCs (BAJFINANCE, which uses "Total Revenue From Operations") share the Ind-AS layout. Banks (HDFCBANK) use "Interest earned", "Total expenditure excluding provisions", "Operating profit before provision and contingencies". The parser handles all three; tests in `tests/test_results_parser.py`.
- **Depth:** the integrated-filing endpoint returned 14 rows (7 quarters, consolidated and standalone) for HDFCBANK, RELIANCE and BAJFINANCE, so QoQ and YoY can come from filings alone.
- **Decision:** headline results (Revenue, EBITDA, PBT, PAT, QoQ, YoY) are parsed, not generated. No LLM touches these numbers. EBITDA is derived as PBT + finance costs + depreciation - other income, and labelled as derived.

## E7. Screener has 5 quarters of standard financials and concall links

- **How:** `GET https://www.screener.in/company/TCS/consolidated/`, HTML 249 KB, HTTP 200.
- **Result:** quarterly table (last 5 headers Sep 2025 to Sep 2026), plus a Concalls section with Transcript, PPT and REC links. Transcript links point to `bseindia.com/stockinfo/AnnPdfOpen.aspx` or the company IR site.
- **All 18 portfolio tickers** return HTTP 200 on `/company/{TICKER}/consolidated/`.
- **Decision:** Screener is the source for multi-year financials and transcript discovery.

## E8. Concall transcripts are text PDFs of manageable size

- **How:** downloaded the latest TCS transcript via its BSE link with a `Referer: https://www.bseindia.com/` header; parsed with PyMuPDF.
- **Result:** HTTP 200, `application/pdf`, 723 KB, 29 pages, 52,478 characters, about 13k tokens by the chars/4 rule of thumb. Text layer present (not scanned).
- **Decision:** four quarters of transcripts is roughly 50k to 60k tokens, which fits in one model call. No vector database needed for the prototype. Page numbers are kept per chunk so every claim can cite a page.

## E9. yfinance works, with one data-quality trap

- **How:** `yfinance==1.7.0`, `download()` for all 18 tickers plus ZOMATO, `period="1mo"`.
- **Result:** 20 rows per ticker, last valid close 2026-10-29. The 2026-10-30 row exists for every ticker but Close is NaN while Volume is populated.
- **ZOMATO.NS:** 404 "Quote not found". Screener `/company/ZOMATO/` also 404. The listed symbol is ETERNAL.
- **Decision:** drop rows with NaN close before computing moves. Keep an alias map (ZOMATO to ETERNAL) for search.

## E10. Gemini model availability and free tier (checked against Google docs)

Sources: https://ai.google.dev/gemini-api/docs/models, https://ai.google.dev/gemini-api/docs/pricing, model pages for gemini-3.5-flash-lite and gemini-3.8-flash. Pages last updated 2026-10-28 to 2026-10-30.

- Google: "we are limiting access to the 2.5 models to users who have actively used them in the past." and "For any new projects, use our latest models: 3.5 Flash-Lite or 3.8 Flash." The old README planned on 2.5, which a new key may not be able to call.
- Free tier input and output: free of charge for gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-3.8-flash.
- Paid prices per 1M tokens (input / output): 3.1 Flash-Lite $0.25 / $1.50; 3.5 Flash-Lite $0.30 / $2.50; 3.8 Flash $0.75 / $3.75 until 31 Dec 2026.
- Context caching on the free tier: only 3.8 Flash and 3.6 Flash.
- Google Search grounding: not included in the free tier for Gemini 3 and newer models. The old README's plan to ground executive bios with Google Search would fail on a free key.
- Both 3.5 Flash-Lite and 3.8 Flash: 1,048,576 input tokens, structured outputs supported.
- Free tier rate limits are not printed on the docs page; they show in AI Studio. To check with the real key before building.

## E11. Package versions on PyPI (2026-10-31)

| Package | Latest | Note |
| --- | --- | --- |
| yfinance | 1.7.0 | tested, works |
| google-genai | 2.34.0 | |
| fastapi | 0.162.0 | |
| pymupdf | 2.0 | tested, works |
| duckduckgo-search | 8.1.1 | no newer release |
| ddgs | 9.16.1 | tested, works; replaces duckduckgo-search in deps |

## E12. Local toolchain

- Python 3.12.11, Node 26.5.0, Bun 1.3.0 present.
- `uv` not installed. Install before step 1 of the plan, or fall back to `venv` + `pip`.

## E13. Ad-hoc research picks have the sources Pull needs

- **How:** Screener consolidated page for each candidate; counted "Transcript" links in the Concalls section and read the latest quarterly header.
- **Result:** ASIANPAINT 16 transcripts, latest quarter Sep 2026. HAL 16, Jun 2026. PIDILITIND 19, Sep 2026. BAJFINANCE 16, Sep 2026. CDSL 19, Jun 2026.
- **Decision:** demo Pull on ASIANPAINT, HAL, PIDILITIND and BAJFINANCE. BAJFINANCE is an NBFC, so it tests that the engine does not assume EBITDA exists.

## E14. Reasoning model latency on the free tier

- **Trivial prompt ("Reply with the single word: ok"), 2026-10-31 01:55 to 02:05 IST:** 3.1 Flash-Lite 1.5 s, 3.5 Flash-Lite 1.4 s, 3.8 Flash 128 s. Retest of 3.8 Flash: 298 s with thinking level low, then two 503 "This model is currently experiencing high demand" errors.
- **Real workload:** the TCS Oct 2026 transcript (13,850 input tokens) with "list every explicit forward-looking guidance statement".

| Model | Thinking | Time | Items | Notes |
| --- | --- | --- | --- | --- |
| gemini-3.6-flash | low | 7.3 s | 5 | Found the 26 to 28% margin band, the ~50 bp MHP dilution, data-centre revenue in 18 to 24 months. Two items were client case studies, not company guidance. |
| gemini-3.5-flash-lite | default | 1.7 s | 1 | Only the margin band. Under-extracts. |
| gemini-3.8-flash | low | 40.0 s | 3 | The same three real items, no case studies. Best precision, slowest. |

- **Decision:** reasoning default is `gemini-3.6-flash`, with a prompt that excludes client case studies and the quote check to drop anything unsupported. `gemini-3.8-flash` is the fallback, not the default. One run each, so this is a direction, not a benchmark; re-check if quality looks off.

## E15. Parsed results agree with Screener across all 22 companies

- **How:** for each company's latest quarter, compare iXBRL-parsed values (refresh run 2026-10-31 02:06) with Screener's quarterly table.
- **Revenue:** within 0.02% for 20 of 22. RELIANCE and SONACOMS differ by 0.68%.
- **PAT:** within 0.8% for 21 of 22. HDFCBANK differs by 3.9% (filing 20,700 crore, Screener 21,537 crore).
- **PBT:** within 1% for 18 of 22. Larger gaps: TRENT +3.4%, HDFCBANK -2.9%, ASIANPAINT -2.9%. Likely exceptional items or share of associates treated differently; not yet confirmed line by line.
- **HAL Jun 2025:** iXBRL had no rounding unit row, so the parser refused it rather than guess. Older quarter, not needed for QoQ or YoY of the latest.
- **Decision:** the app shows the filing's own numbers, and marks a field "check" when it differs from Screener by more than 1%.

## E16. Screener's transcript links can be wrong; NSE filings are the better source

- **How:** built the TCS promise ledger from Screener's last four transcript links.
- **Result:** the link Screener lists as "Jul 2026" points to `tcs.com/.../Transcript of the Q1 2025-26 Earnings Conference Call held ... on Jul 10, 2025.pdf`, a call from a year earlier. tcs.com also answered 403 to the download.
- **Fix:** FINN now takes transcripts from the company's own NSE filings first (announcements whose label or text mentions "transcript", excluding audio recordings), one per month, for the last 12 months. Screener links fill gaps only. After the change, all four TCS transcripts (Jan, Apr, Jul, Oct 2026) loaded from `nsearchives.nseindia.com`.

## E17. Free tier limits hit in practice

- **Requests per minute:** a burst of parallel calls to `gemini-3.1-flash-lite` returned 429 with `quotaValue: 15` and `quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier`. So 15 RPM for that model on this key.
- **503s are not only a 3.8 Flash problem:** `gemini-3.1-flash-lite` also returned "503 UNAVAILABLE ... high demand" on 2026-10-31 around 03:00 IST after four retries.
- **Changes made:** a per-model rate limiter in `backend/llm.py` (spacing calls at 60/RPM seconds, across threads); honouring the `retry in Ns` hint from 429 bodies; falling back to a sibling model after repeated 503s (3.1 Flash-Lite to 3.5 Flash-Lite, 3.6 Flash to 3.8 Flash); reading filing PDFs five per call instead of one, which cut 59 calls to 12.
- **Implicit caching observed:** `usage_metadata.cached_content_token_count` reported 124,242 of 324,155 input tokens as cached across 17 calls to 3.6 Flash during ledger builds, without any explicit cache setup, because the ledger re-sends the same transcripts.

## E18. Model mistakes caught while enriching filings, and the guards added

- **Subsidiary presented as parent.** An ICICIBANK filing labelled `General Updates` was summarised as "Mr. Anup Bagchi resigned as MD and CEO". The PDF says the change is at "ICICI Life Insurance Limited (ICICI Life)", a subsidiary. Fix: the extraction schema now has an `entity` field for subsidiaries, the prompt requires naming the subsidiary, and Python ranks subsidiary-only changes as Worth knowing instead of Needs you.
- **Bios that only restated the appointment.** Searching `"{name}" {company} {role}` returned nothing; `{name} {company}` returned mostly news of the appointment, so bios read like "Anup Bagchi serves as the MD and CEO of HDFC Bank". Searching `{name} career previously worked` returned earlier employers and education (Bahram Vakil: founding partner of AZB & Partners; Madhusudan Gopalan: SVP and Country Head, P&G India and South Asia).
- **Namesakes.** The top results for Trent's new independent director Kalpana Merchant describe a US neuroscientist (Eli Lilly, University of Utah). Trent's filing says the profile is "Attached separately", so the PDF cannot settle it. The model still marked its answer confident. Fix: Python marks a bio confident only if at least one source it cites mentions the appointing company; otherwise the card says the background may belong to someone else.
- **Filing profile first.** SEBI disclosures for appointments include a brief profile of the appointee, so FINN now reads up to 6 pages of management-change filings and extracts that profile before any web search. Example: Dixon's filing for Prithvi Vachani gives his current role, Bentley University 2017, and the boAt collaboration.
- **Zip attachments.** Two KMP filings (TRENT, PERSISTENT) attach a `.zip` holding the PDF. The downloader now unpacks it.

## E19. Free tier daily limits, and the routing they forced

- **Source:** the project's AI Studio rate-limit page, read by the author on 2026-10-31 around 03:30 IST.

| Model | RPM | TPM | RPD | Used at the time |
| --- | --- | --- | --- | --- |
| gemini-3.6-flash | 5 | 250K | 20 | 21 / 20 (exhausted) |
| gemini-3.8-flash | 5 | 250K | 20 | 5 / 20 |
| gemini-3.1-flash-lite | 15 | 250K | 500 | 178 / 500 |
| gemini-3.5-flash-lite | 15 | 250K | 500 | 14 / 500 |

- Google's rate-limit docs: "Requests per day (RPD) quotas reset at midnight Pacific time." and "Rate limits are applied per project, not per API key."
- **Why it matters:** the first ledger design spent 5 Flash calls per company (4 extractions and 1 assessment) plus 1 for bull and bear. At 20 a day per Flash model, that is 3 companies a day, and a reviewer pointing FINN at a new ticker could find it out of quota.
- **Test of the cheaper option:** both Flash-Lite models, given the extraction prompt on the TCS Oct 2026 transcript, found 2 of the 3 items that 3.6 and 3.8 Flash found (operating margin band, data-centre revenue timeline) and missed the ~50 bp MHP margin dilution. All their quotes verified. Fast (1.9 s and 12.2 s) but lower recall.
- **Decision:** the ledger is now one Flash call per company that reads all four transcripts in date order, extracts promises and judges them against later calls. First run, ASIANPAINT on 3.8 Flash (3.6 was out of quota, the fallback took over by itself): 52,831 tokens in, 4,033 out, 109 s, 13 promises, 0 dropped for unverifiable quotes. Bull and bear moved to 3.5 Flash-Lite (500 a day): 1.7 s, every point cites a fact or promise id that Python checks. So a new company costs 1 Flash call and 1 Flash-Lite call.
- **Guard:** `backend/llm.py` counts each model's calls since Pacific midnight and skips a model at its daily limit; a 429 whose quota id contains `PerDay` marks the model exhausted for the day and moves to its sibling.

## E20. Margin promises cannot be judged by our margin number alone

- **Case:** Asian Paints guided "PBDIT margin 18% to 20%". Its Jun 2026 call says "PBDIT margins at 18.9%". FINN's first numeric check compared the guidance with Screener's operating margin for Sep 2026, 16.0%, and marked the promise off track.
- **Why:** Screener's operating margin excludes other income; Asian Paints' PBDIT includes it. Companies define EBITDA, PBDIT and operating margin differently.
- **Decision:** growth promises (revenue, profit) are still decided in Python from reported numbers. For margin promises the verdict rests on the verified quotes from later calls, and FINN's own margin is shown beside it as context, labelled "excluding other income".

## E21. API speed and payload, and what that says about caching

- **How:** local uvicorn, `curl` three times per endpoint, 2026-10-31 around 03:45 IST, SQLite file 3.3 MB.

| Endpoint | Average time | Payload | With gzip |
| --- | --- | --- | --- |
| `/api/brief?hours=24` | 7 ms | 17 KB | 4.6 KB |
| `/api/brief?hours=168` | 14 ms | 71 KB | |
| `/api/brief?hours=720` | 24 ms | 157 KB | 29 KB |
| `/api/research/TCS` (cached sections) | 7 ms | 17 KB | |
| `/api/alerts/scan` (60 days, 18 tickers) | 7 ms | 5 KB | |

- **Reading:** SQLite already acts as the cache: ingestion and every model output are precomputed and stored, and the API only reads. A server-side response cache (Redis or in-memory) would save single-digit milliseconds. On a phone, the network and payload size dominate, so the API compresses responses and the app keeps the last response on the device and refreshes it in the background.
- **Where caching really matters:** model outputs, because Flash has 20 requests a day (E19). Ledgers, bull and bear, filing reads and classifications are computed once and stored; PDFs are cached on disk by URL hash.

## E22. Hosting: Render free versus AWS Lightsail

Checked 2026-10-31 against https://render.com/docs/free, https://render.com/docs/regions, https://aws.amazon.com/lightsail/pricing/ and https://aws.amazon.com/awscredits/.

- **Render free:** "spins down a Free web service that goes 15 minutes without receiving any inbound traffic"; waking takes about one minute. "Free web services cannot" attach a persistent disk, and local file changes are lost on redeploy, restart or spin-down. Only web services, Postgres and Key Value can be free, so no free cron job or worker. Regions: Oregon, Ohio, Virginia, Frankfurt, Singapore; no India.
- **AWS Lightsail:** Linux with public IPv4 at $5/month (0.5 GB RAM, 20 GB SSD) or $7/month (1 GB, 40 GB). Mumbai (ap-south-1) has the same prices with half the data transfer allowance. Disk persists.
- **AWS credits:** apply "only to the specific Services designated by your AWS contracting entity" and expire on a date shown with the code. The terms page does not mention Lightsail, so eligibility has to be checked in the billing console.
- **What FINN needs:** an always-on process for scheduled refresh, a disk that keeps SQLite (ledgers built by reviewers, refreshed filings), and ideally an Indian IP close to NSE. Render free meets none of the three.

## E23. Alert thresholds matter, and research works on a ticker FINN never saw

- **Alert replay** (`analytics.eod_scan` over stored EOD data for the 18 portfolio stocks, last 60 sessions, 2026-10-31): price ±3% or volume 2x the 20-day average fires 119 alerts, about 2 per trading day. At ±4% or 2.5x it fires 51. At ±5% or 3x it fires 25. The defaults change the alert load by almost 5x, which is why the alerts screen shows the replay count next to the sliders.
- **Unseen ticker:** `GET /api/research/TITAN`, with TITAN not in any list and not in the database, returned 200 in 5.6 s: Screener tables, NSE results (Q1 FY27 revenue 21,356 crore, YoY +29.3% after the parser fix in E15's HAL note), trajectory, cash quality and four transcript links. `ZOMATO` resolves to `ETERNAL`; a made-up symbol returns 404 with "Check the NSE symbol".
- **Older iXBRL format:** Jun 2025 filings for TITAN and HAL state the unit as "INR (in Actuals)" in the currency row and dates as `30-Jun-2025`. The parser now reads both, which filled in their YoY comparisons.

## Open questions (not yet verified)

- Does NSE answer requests from a cloud host (Render, Fly, Railway) the same way it answers a home IP? Test on deploy. Fallback is a committed SQLite snapshot refreshed from a local machine.
- Free tier RPM and RPD for our key. Check in AI Studio.
- Rule precision on the 76 text-rule classifications in E3.
