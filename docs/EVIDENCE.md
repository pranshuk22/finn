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

## E24. Colour palette: sampled from the chosen reference, then checked for contrast

- **Reference:** Pinterest pin 885872189202118303 ("Meet Marcus Insights" onboarding screen), chosen by the owner on 2026-10-31 over pure black and light options.
- **Sampled** with PyMuPDF from the 736 x 1104 pin image: screen background `#2e3736`, cards about `#3a4342` to `#4f5759`, button taupe `#9e9189`, page behind the phone `#445255`.
- **Contrast** (WCAG 2 formula, computed from `frontend/src/styles/tokens.css`): the reference's white text on its taupe button is 3.06:1, below the 4.5:1 AA minimum, so FINN puts dark text `#1e2524` on taupe (5.1:1). Muted grey was raised to `#b8c1bf` and the sheet colour darkened to `#414b4a` so every text colour passes 4.5:1 on background, cards and sheets. Lowest: muted text on sheets, 4.90:1. The faint grey (3.77:1 on background) is kept for icons and large text only.
- **Preview** of the Brief rendered from the live 7-day API response confirmed a bug: DIXON's results card was headlined with a director appointment filed in the same board outcome. Fixed in `backend/main.py`; the results line now stays the headline and the appointment keeps its own management card.

## E25. Deploy probe: every source answers from AWS Lightsail Mumbai

Instance: Lightsail, ap-south-1, Ubuntu 24.04.4, 2 vCPU, 909 MB RAM, 38 GB disk, static IP 15.206.124.235. Probed 2026-10-31 around 13:30 IST.

| Request from the server | Result |
| --- | --- |
| NSE homepage | 403 in 0.06 s, same as from a home IP (E1); the cookie it sets is still enough |
| NSE `corporate-announcements` for TCS | 200, 2.5 MB in 1.07 s |
| NSE `integrated-filing-results` for TCS | 200 in 0.16 s |
| NSE archive transcript PDF | 200, 3.7 MB in 0.22 s |
| Screener TCS page | 200 in 0.06 s |
| BSE annual report PDF (with Referer) | 200, 26 MB in 0.13 s |
| Yahoo chart API by plain curl | 429 "Too Many Requests" |
| yfinance (what FINN uses) | works: `refresh --only eod` stored 2,157 rows for all 18 tickers |

- The full pipeline ran on the server: `refresh --only filings --days 3` found and classified 1 new filing in 27 s; `--only results` ran clean. So the scheduled refresh lives on the server and nothing depends on a laptop.
- HTTPS: Caddy obtained a Let's Encrypt certificate for `15-206-124-235.sslip.io` (issuer YE2, expires 29 Jan 2027). From inside the server every page and API returns 200 over it.
- Two things outside the server: port 443 was closed in the Lightsail firewall (80 and 22 open), and the owner's network answers every DNS query for `sslip.io`, even one sent to 1.1.1.1, with `208.91.112.55`, which whois lists as Fortinet Inc., a web filter block page. A reviewer behind a similar filter would see the same, which is the case for a real domain.
- **Public link through Vercel (free plan):** the app is served from `finn-mu-three.vercel.app` and `/api/*` is rewritten to the Lightsail server. Vercel waits up to 120 seconds for an external origin (https://vercel.com/changelog/cdn-origin-timeout-increased-to-two-minutes); Netlify's proxy limit is 26 seconds (https://docs.netlify.com/manage/routing/redirects/rewrites-proxies/). From the same filtered network that blocked sslip.io, every page and API route returned 200 through Vercel, the brief in 0.58 s and research for HAL in 0.57 s; an Ask on TCS (a POST) returned a cited answer in 3.3 s. A fresh phone-sized browser rendered the brief 1 s after navigation.
- Schedules, as systemd timers in IST (`deploy/`): filings, results and filing reads every 30 minutes 08:00 to 22:30; EOD at 16:45 and 19:30 on weekdays; Screener daily at 21:15. A shared lock stops two refreshes overlapping.

## E26. Ledger batch for 11 companies, and a hand check of HAL

Built 2026-10-31 between 13:24 and 13:36 IST, one company at a time.

| Company | Promises | Statuses | Seconds |
| --- | --- | --- | --- |
| HAL | 10 | 6 missed, 2 pending, 1 delivered, 1 on track | 37 |
| PIDILITIND | 4 | 2 delivered, 2 pending | 40 |
| BAJFINANCE | 10 | 8 pending, 1 revised, 1 on track | 16 |
| HDFCBANK | 6 | 3 pending, 2 delivered, 1 off track | 18 |
| RELIANCE | 8 | 4 pending, 1 delivered, 1 revised, 1 unclear, 1 dropped | 404 |
| INFY | 6 | 3 on track, 3 pending | 43 |
| LT | 5 | 4 pending, 1 on track | 23 |
| DIXON | 11 | 9 pending, 2 revised; 2 quotes not found in the PDF and dropped | 63 |
| TRENT | 0 | no transcripts | 9 |
| POLYCAB | 11 | 7 pending, 2 revised, 1 delivered, 1 on track; 1 quote dropped | 62 |
| TCS (rebuilt) | 8 | 5 pending, 1 missed, 1 delivered, 1 unclear | 21 |

- **Cost:** 16 Flash requests for 11 companies. Five 3.6 Flash requests failed (503 or timeout) and were retried; RELIANCE fell back to 3.8 Flash, which took 338 s on 107,523 input tokens. 25 of the day's 40 Flash requests were left.
- **TRENT has no ledger, correctly:** its 117 NSE filings in the last 12 months include many analyst-meet schedules and no earnings call transcript.
- **HAL, read against the quotes:** the Nashik third line was promised for "October 2024" (May 2024 call, page 5) and inaugurated on 17 October 2025 (May 2026 call, page 3); HTT-40 deliveries due September 2025 were still "expected during the current year" in May 2026; FY25 revenue grew 2.0% against "10% from '24-'25 onwards". Two verdicts are weaker: the LCA Mk1A evidence quote says deliveries would scale up in FY25 without saying none came in FY24, and the CY25 engine item is GE's supply promise relayed by HAL, not HAL's own target. FY26 revenue growth was judged missed at 6.8% (Screener) against "7% to 8%", while HAL reported "an increase of 7%"; the check now states the gap ("0.2 points below the 7% low end") instead of a bare "missed".
- **Ask, run on TCS** (gemini-3.5-flash-lite, 2026-10-31): "deal wins and TCV in the latest quarter" answered in 9.7 s with 2 citations ("TCV for the quarter was US$9.6 billion", Oct 2026 call, page 3); "guidance on operating margin" in 9.2 s, citing that TCS gives no formal guidance (Jan 2026, page 3) and the "26%-28%" band (Oct 2026, page 27); "plan for entering the electric vehicle battery business" in 7.3 s returned covered = false with no citations. No quote was dropped in the three answers.
- **Bull and bear wording:** Flash-Lite wrote "Net profit grew 23% over 5 years" for a 23% five-year CAGR, and kept doing so after a prompt rule against it. The phrase is now rewritten in code to "a year over 5 years", and facts carry their units ("ROCE: 37% in Mar 2022").

## E27. Classifier eval: 60 blind-labelled filings, then 30 held out

**Method** (`eval/`). 20 filings per sorting stage (exchange label, text rule, model), fixed seed 2027, drawn from the 301 October filings. The labeller (Claude) saw only what the exchange published: the label, the summary text and the attachment from its subject line, with the stage and FINN's answer hidden and the order shuffled. Category and priority were labelled against the README priority table. For filings that honestly fit two categories (a trading-window notice as unclassified or insider trading), acceptable alternatives were written down before scoring; "strict" ignores them, "lenient" accepts them. `eval/score.py` joins FINN's stored answer only after the labels are saved.

**Result before any fixes (the headline):**

| Stage | Category, lenient | Priority, lenient |
| --- | --- | --- |
| Exchange label | 18/20 | 19/20 |
| Text rule | 20/20 | 15/20 |
| Model | 19/20 | 14/20 |
| All | 57/60 (95.0%) | 48/60 (80.0%) |

Strict: category 51/60, priority 47/60. One label was wrong, not FINN: an HDFC Bank filing re-appointing an independent director also records the Deputy Managing Director ceasing, which sits beyond the excerpt the labeller saw; FINN's filing reader had found it. With that label corrected, priority before fixes is 49/60 (81.7%). The correction is recorded in the label file.

**What the misses showed, and the fixes:**
- A Rs 4,265 crore QIP allocation (7.68 million shares at Rs 5,550) came under the exchange label "Committee Meeting Updates", which the label map treated as always routine. That label, and "Shareholders meeting" (also used for postal ballots), now go to rules and the model. Re-sorting them found five Persistent QIP filings, now fund raises.
- Press releases were judged on a short keyword list, so a facility opening, a market entry, a client collaboration, a revenue update and a completed takeover ("Secures Strong Majority Stake", about 94% of Nagarro) were all Routine. Takeovers and stakes now count as M&A, facility openings as capex, and the press-release list covers entries, collaborations, wins and business updates.
- Companion documents (a results press release, a shareholders' letter) were Needs you next to the results filing itself; they are now Worth knowing, keyed on the exchange's "Press Release" label rather than the words "press release", which also appear in genuine results announcements.

**Held out: 30 filings** (seed 2028, 10 per stage, none from the first 60), drawn and labelled after those fixes. Category 30/30 lenient (27/30 strict); **priority 25/30 (83.3%)**. This is the out-of-sample figure to quote. Two of the five misses contradicted the README: a CEO change at subsidiary ICICI Life and an independent director at Bajaj Auto were Needs you because the filing reader's model marks almost every person "senior". Seniority is now decided in code from the role (CEO, CFO, COO, MD, whole-time or executive director, chair, KMP; never independent or non-executive directors). Also fixed: an analyst presentation of a quarter is Worth knowing, and "award" means a contract award, not an awards ceremony. Still missed: an Infosys client adopting Finacle, filed with no keyword a rule could use.

**After both rounds** (in-sample now, so optimistic): the 60 agree on 58 priorities, the 30 on 29. The two disagreements left in the 60 are judgment calls: a GST show-cause notice to ICICI Bank (FINN Needs you, labeller Worth knowing) and a postal ballot approving a share plan (FINN Worth knowing, labeller Routine). The labelled filings are a regression test in CI (`tests/test_classifier_eval.py`): the deterministic stages place 61 of the 90 and must keep agreeing with the labels. The owner's spot-check of 15 is in `eval/SPOTCHECK.md`.

## E28. Beyond the brief's two examples: what each card adds, and the reference glossary

**Against the reference document** (`2. ENAM_AI_Engineer_Build_Challenge_Reference.pdf`):
- EBITDA is defined there as earnings before interest, tax, depreciation and amortisation, "a rough proxy for operating profitability, how profitable the core business is". FINN computes operating EBITDA, PBT + finance costs + depreciation - other income, so interest on cash and investment gains do not count as core business. The card labels it "Operating EBITDA" and prints the formula.
- Margin is defined as profit / revenue. The results card now shows EBITDA and PAT margins with their change in basis points.
- Its category table files "results decks and shareholder letters, and ads confirming results were published" under results. Results presentations and shareholder letters now go to results (Worth knowing); a results newspaper ad goes to results (Routine). ESOP allotments, compliance certificates and ESG reports stay unclassified, as the table says.

**Added to the cards, all computed in Python from stored filings, results and prices** (`analytics.reaction`, `analytics.scale`, `results_card`, `main._filed_before`):

| Card | Added | Example from the live data, 31 Oct |
| --- | --- | --- |
| Results | EBITDA and PAT margin, change in bps QoQ and YoY | DIXON EBITDA margin 2.7%, -110 bps YoY; PAT margin 1.9%, -310 bps YoY |
| Results | Other income as a share of PBT, flagged at 25% or more | L&T 30%: "a large part of profit does not come from operations" |
| Results, people, litigation, deals | The first session after the filing (same day if filed before 15:30 IST) | Sona BLW +8.95% on 8.1x usual volume after Q2; Tata Consumer +6.78% on 5.4x; TCS +3.85% on 3.5x |
| Results | The company's promise ledger in one line, linked | TCS: 1 missed, 1 delivered, 5 pending, 1 unclear |
| Management | Top management, board or senior staff (from the role, E27), entity, effective date | Pallavi Joshi Bakhru: Board, effective 1 Jan 2027 |
| Fund raise, M&A | Size as a share of market cap as well as revenue | Persistent QIP Rs 4,265 crore: 4.2% of market cap |
| Every card | How many filings and since when | Polycab litigation: 9 filings since 7 Oct |
| Price and volume | What was filed between the previous close and that close, one line per category | Trent +5.4% on 30 Oct: Results, Management; Dixon -4.25%: no filing explains it (its results came at 16:19) |

One bug found on the way: the move context first kept the two latest filings, so Trent's results (16:08) were hidden behind four Chairman-change filings (16:32). It now keeps one per category, most important first.

## E29. Blank Brief after a deploy: an old saved copy crashed the new code

**Report** (31 Oct, 19:49 IST, phone test): the Brief showed a blank page; another screen said "Offline".

**What the logs showed:**
- Server and proxy were healthy: every endpoint the app calls returned 200 through Vercel in under 0.6 s, and the API log had no errors.
- Vercel's request log for the phone (Android, Chrome 150) between 19:46 and 19:49 IST had nine app opens (`/sw.js` checks) and no `/api/` request at all. The app failed on the phone before asking the network.

**Cause, reproduced on production** (headless Chrome in phone emulation: seed the saved 7-day brief from before E28, reload):
- The app renders the saved copy first, then fetches. Moves saved before E28 have no `filed` field, and the new code read `m.filed.length`.
- The render threw `TypeError: Cannot read properties of undefined (reading 'length')` and React unmounted the page (`#root` empty).
- The fetch runs in an effect, which never ran, so the app could not heal itself.
- The "Offline" note was also wrong: it showed for any failed refresh, not only a failed network.

**Fix** (`api.ts`, `components/ScreenBoundary.tsx`, `vite.config.ts`):
1. Each saved response is tagged with the build that wrote it (`__BUILD__`, set at build time). A new build ignores older copies, so a deploy never renders an old shape.
2. Each screen sits in an error boundary. A render failure shows "This screen could not be shown" and a Reload button that clears saved responses (not settings or done cards).
3. The note says "Offline." only when the network failed (status 0), and "Could not refresh." otherwise.

**Verified on production after deploy:**
- The same old copy now renders the fresh 7-day brief ("15 filings need you ...").
- Forcing the crash (the old copy tagged with the current build) shows the recovery screen with the tab bar intact.
- Reload brings the Brief back.
- `src/api.test.ts` covers the build check and what Reload clears; frontend tests 25 pass.

## E30. The research brief, section by section, and segment data from the results filing

**Checked against the brief's eight research items.** Before this change: business snapshot (description only, no segments), balance sheet (one line inside Cash quality), guidance and narrative vs numbers (merged in one ledger list). Now each has its own section, in the brief's order.

**Segments are in the primary source we already parse.** The NSE integrated filing carries a segment table: revenue and profit before interest and tax per segment, for the quarter and year to date. `sources.nse._segments` reads the quarter column; single-segment companies are named from the filing's general table.
- Backfill (`backend.jobs.segments`): 111 of 111 stored quarters, 0 failures, locally and on the server. 15 of 23 companies report several segments; 8 report one (e.g. DIXON "Electronic Goods", TRENT "Retail").
- LT Q2 FY27: segment revenue 79,615.57 less inter-segment 865.63 equals revenue from operations 78,749.94 (test `test_segments_tie_to_revenue_and_skip_adjustments`).
- RELIANCE's segment table totals 3,62,268 crore against 3,32,861 in its P&L, so mix is always a share of segment revenue, never of headline revenue. The page says so.
- Hand check, RELIANCE O2C revenue: 1,60,558 (Q2 FY26 filing) to 2,31,601 (Q2 FY27) = +44.2%, as shown.
- ASIANPAINT's Jun 2026 filing itself contains a broken character ("D\ufffdcor"); its other three filings read "Décor". Left as filed.

**Balance sheet** (`analytics.balance_sheet`): interest coverage = (PBT + interest) / interest from the latest full year (Screener's latest balance-sheet column can be a half year, e.g. Sep 2026). Not shown for lenders. Funding mix includes deposits for banks: HDFCBANK Sep 2026 deposits 64.3%, borrowings 11.5%, equity 11.7%, other 12.5%. DIXON coverage 15.7x, TCS 54.4x, RELIANCE 5.6x (Mar 2026).

**Guidance** is the ledger's open items (pending or on track) grouped by the metric key the ledger already records (revenue_growth, operating_margin, capex, other). No new model call. Bare-number targets get their unit ("100000" in Rs crore reads "Rs 1,00,000 crore").

**Reliance looked thin** (owner's review, 31 Oct). Measured: 8 promises from 138 transcript pages, the lowest yield of any company, and bull and bear used only consolidated facts. Changes:
- Segment revenue and result by quarter are now in the ledger's numbers table, and the prompt asks for each segment's guidance. The Reliance ledger rebuild was refused by the API for quota on both Flash models (our counter showed 14 of 20 used); nothing was overwritten. To rerun after the 12:30 IST reset.
- Segment facts are now in bull and bear's numbered facts, and the prompt asks for one segment point each side when there are segments. Rebuilt for all 12 companies with a ledger (backup kept on the server). RELIANCE now: bull "O2C revenue +44.2% YoY, share +6.8 points"; bear "Retail revenue +1.3% YoY while losing 5.8 points of share".
- Fixed promise facts that repeated the timeframe ("ready by March by by March"); test `test_promise_timeframe_is_not_said_twice`.

Tests: backend 36, frontend 27, all passing.

## E31. Independent review, the promise sheet crash, and charts

**Review.** A separate agent saw only the two challenge PDFs and the live site at 390px (no code, README or this log) and drove it in headless Chrome for about 19 minutes. Scores out of 10: saves time 7, shows what matters 6, trust 6, density 7, visual design 8, interactivity 6, thought-through 7, mobile fit 8. Its findings are the to-do list for the last day.

**Crash, confirmed and fixed.** Tapping a promise or guidance item showed "This screen could not be shown". Cause: the detail sheet read `repeated_in.length`, and the ledger set `repeated_in` only for measurable metrics; 60 of 97 stored promises had no such field. Fixed at both ends: every promise gets the field, and the sheet tolerates its absence.
- Before, on production, tapping every item (headless script): RELIANCE 8 of 8 crashed, HDFCBANK 5 of 6, DIXON 10 of 11.
- After deploy: RELIANCE, HDFCBANK, DIXON and TITAN, 31 items, 0 crashed.
- "effective Invalid Date" on management cards: 9 people had a date written in words ("12th November 2026"); such dates are now shown as written (`format.filedDate`, tested).

**Charts** (`components/Charts.tsx`), following the dataviz method: one hue for magnitude, a validated pair for gains and losses with direction also shown by position, thin marks, hairline axes, tap to read.
- Brief hero: every portfolio stock's move on the day, best to worst.
- Research header: daily closes (about six months held) with Needs you and Worth knowing filings placed on the session they could first move the price (after 15:30 IST means the next session; tested).
- Narrative vs numbers: track record ("2 of 8 promises that could be checked were kept", HAL) and guided range against the reported figure for numeric promises.
- Cash quality: cash from operations as columns with operating profit as a tick on each, one axis.
- Colour check (dataviz validator): the text pair for gains and losses failed as chart fills (CVD delta E 2.9 on slate). Chart pair now #2ea58f / #d9714a on slate, #00876c / #c8472a on paper: CVD delta E 10.5 or more, contrast 3:1 or more on card and hero surfaces.

## Open questions (not yet verified)

- Does NSE answer requests from a cloud host (Render, Fly, Railway) the same way it answers a home IP? Test on deploy. Fallback is a committed SQLite snapshot refreshed from a local machine.
- Free tier RPM and RPD for our key. Check in AI Studio.
- Rule precision: measured in E27.
