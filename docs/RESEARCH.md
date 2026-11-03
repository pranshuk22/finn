# Research log

What was checked before FINN relied on it: data sources, models, and the numbers FINN computes. Each entry says how it was checked, what came back, and the decision it led to. The README and the code cite entries by number (R1 to R17). A later check that contradicts an entry updates it.

Checks were run between 31 Oct and 3 Nov 2026 (IST), from a home connection in India unless noted.

## R1. NSE filings: the primary source

- **Access:** `GET https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=TCS` with a desktop User-Agent and the cookies from one hit to the homepage returns JSON: 3,383 TCS filings, each with the exchange label (`desc`), the company's one-line summary (`attchmntText`), the PDF and the time. The homepage itself answers 403 but still sets the cookies the API needs.
- **Volume:** October 2026 for the 18-stock portfolio, one call per ticker 0.8 s apart, 0 failures in 18: 275 filings, about 9 a day. Top labels: analyst meets 46, general updates 32, board outcomes 24, newspaper copies 17, depository certificates 17, ESOP 16, press releases 14, credit ratings 9.
- **Decision:** NSE is the filings source; BSE is a fallback. At this volume a daily brief with routine filings folded away is the right default; an unfiltered feed would be mostly paperwork.

## R2. Classifying filings: labels, then rules, then a model

- **Labels are not enough.** Of the 275 October filings, 137 (50%) resolve from the exchange label alone, 76 more (28%) from keyword rules on the summary, and 62 (23%) need a model. Reliance's three filings on the Jio Platforms IPO were all labelled "General Updates"; a label-only filter would bury one of its most material events of the month.
- **Inside the app** (35 days, 301 filings): 140 by label, 98 by rule, 63 by the model, which took 4 calls and about 9 s on `gemini-3.1-flash-lite`.
- **Eval** (`eval/`). 60 filings, 20 per stage, labelled blind: the labeller saw only what the exchange published, with FINN's answer hidden. Acceptable alternatives were written down before scoring.
  - Before fixes: category 57/60, priority 48/60. One label was wrong, not FINN (a deputy MD's exit sat beyond the excerpt the labeller saw).
  - Misses that led to fixes: a Rs 4,265 crore QIP under the label "Committee Meeting Updates"; press releases about a takeover, a facility opening and a market entry marked Routine; results press releases ranked equal to the results.
  - **Held out:** 30 more filings drawn after the fixes. Category 30/30, priority 25/30 (83.3%), the out-of-sample figure. Two misses showed the model marks almost everyone "senior", so seniority is now decided in code from the role.
  - The 90 labelled filings are a regression test in CI (`tests/test_classifier_eval.py`).
- **Second review** found two inversions: Bajaj Auto's monthly sales were Routine and an ESG score was Worth knowing. Both rules changed, and the eval still passes.
- **Decision:** label map, then text rules, then a small model for what is left.

## R3. Management changes and executive bios

- **The summary does not name the person.** LT, BAJAJ-AUTO and TATACONSUM's October management filings all say only "has informed the Exchange about change in Management". The PDF has to be read.
- **The filing often has the profile.** SEBI disclosures include a brief profile of the appointee, so FINN reads up to 6 pages of the filing before any web search (Dixon's filing for Prithvi Vachani gives his role, Bentley University 2017 and the boAt collaboration).
- **Web search is ambiguous.** `K Krithivasan TCS CEO` returns two different LinkedIn profiles that both list TCS. The top results for Trent's new director Kalpana Merchant describe a US neuroscientist, and the model still called its answer confident. Rule: a bio is confident only if a source it cites mentions the appointing company.
- **Query wording matters.** `{name} {company}` returns news of the appointment itself; `{name} career previously worked` returns earlier employers and education (Bahram Vakil: founding partner of AZB & Partners).
- **Subsidiary shown as parent.** A filing was summarised as "Anup Bagchi resigned as MD and CEO" of ICICI Bank; the PDF says ICICI Life. The schema now has an entity field, and subsidiary-only changes rank Worth knowing.
- **Sources to avoid:** grokipedia.com, an AI-written encyclopedia, appeared as a bio source; such sites are filtered out.

## R4. Quarterly results from NSE's iXBRL filings

- **Source:** `GET /api/integrated-filing-results?index=equities&symbol=TCS&type=Integrated Filing- Financials` lists each quarter's iXBRL filing. The older `corporates-financial-results` endpoint stops at Dec 2024. Seven quarters are available, consolidated and standalone, so QoQ and YoY come from filings alone.
- **Cross-check, TCS Q2 FY27:** revenue 73,18,800 lakh = Rs 73,188 crore, PBT 18,638, PAT 13,934, equal to Screener. Across all 22 companies' latest quarter: revenue within 0.02% for 20, PAT within 0.8% for 21 (HDFCBANK 3.9% apart), PBT within 1% for 18.
- **Traps found:**
  - "Profit before tax" also appears in the segment table, so the parser anchors on the P&L table.
  - Three layouts: companies and NBFCs (Ind-AS) and banks ("Interest earned", "Operating profit before provision").
  - Older filings (TITAN, HAL, Jun 2025) give the unit as "INR (in Actuals)" and dates as `30-Jun-2025`.
  - COFORGE's Q2 FY27 filing has six-month figures in both columns. Read naively, revenue was +111.6% QoQ. A 6, 9 or 12-month filing now becomes a quarter by subtracting stored quarters; it was the only one of 116 stored filings affected.
- **Segments** are in the same filing: revenue and result (before interest and tax) per segment. 15 of 23 companies report several.
  - LT's segment revenue less inter-segment revenue equals revenue from operations (78,749.94 crore).
  - RELIANCE's segment total is 3,62,268 against 3,32,861 in its P&L, so a segment's share is taken of segment revenue, never of headline revenue.
- **Any NSE ticker works.** TITAN, not in any list or the database, returned research in 5.6 s. ZOMATO resolves to ETERNAL.
- **Decision:** headline numbers are parsed, never generated. A line more than 1% from Screener is marked "check" on the card; more than 10%, it is not headlined.

## R5. What a results card has to explain

- **EBITDA,** per the challenge's reference document, is a proxy for how profitable the core business is. FINN computes operating EBITDA (PBT + finance costs + depreciation - other income), so interest on cash does not count as business profit, and prints the formula.
- **Tax can explain a profit change.** MAXHEALTH's PAT fell 15.6% while PBT rose 21.3%, because a year earlier tax was a credit (PAT was 110% of PBT). SUZLON's "profit fell 69.2%" is the same case. The card says so and headlines PBT.
- **Other income can explain it.** DIXON Q2 FY27: EBITDA +6.3% but PBT -42.6%, because other income fell from Rs 495.74 crore to Rs 68.73 crore. The card names the line between EBITDA and PBT that moved most. L&T's other income is 30% of PBT, which is flagged at 25%.
- **The market's reaction** is the first session the filing could move: the same day if filed before 15:30 IST. Sona BLW rose 8.95% on 8.1x usual volume after its results.
- **Size against the company.** Persistent's Rs 4,265 crore QIP is 4.2% of market cap. A RELIANCE penalty that is 0.0% of revenue gets no alert tag.
- **A vague label can hide a small matter.** Polycab's insolvency filings (7 to 9 Oct, filed as litigation) concern "an alleged 2.79 crore operational debt", against Rs 9,898.9 crore of revenue that quarter. Only reading the PDF shows that.

## R6. Bank figures come from the standalone filing

- **Consolidated filings leave asset quality blank.** HDFCBANK's consolidated Q2 FY27 filing has "% of gross NPAs | 0". The standalone one has gross NPA 1.11%, net NPA 0.37%, CET1 18.87%, interest earned Rs 83,426.60 crore and interest expended Rs 48,807.42 crore. On the Oct 2026 call management said "GNPA at 1.11%". FINN reads the standalone filing and treats a 0 ratio as the placeholder.
- **Seven quarters** are on NSE for each bank, from Mar 2025. Net interest income for Q2 FY27: HDFCBANK Rs 34,619 crore (+9.7% YoY), ICICIBANK Rs 25,339 crore (+17.7%).
- **FINN's own ratios, labelled so:**
  - NII to assets is quarterly NII x 4 over total assets (HDFCBANK 3.02%). Banks report NIM on interest-earning assets, a smaller base, so theirs reads higher.
  - Credit cost is provisions x 4 over advances (0.45%).
- **The industrial template fails for lenders.** Screener's "financing margin" for HDFCBANK ran -2% to -17% a quarter, and capital work in progress read Rs 0. Lenders get credit cost, asset quality and return on equity instead.
- **NBFCs:** BAJFINANCE's filing has "Impairment on financial instruments" but no NPA or stage 3 rows, so no asset-quality figure is shown.

## R7. Transcripts and annual reports

- **Transcripts are text PDFs of manageable size.** TCS's latest: 29 pages, 52,478 characters, about 13k tokens. Four quarters is 50k to 60k tokens, which fits one model call, so no vector search is needed. Page numbers are kept so every claim can cite one.
- **Screener's transcript links can be wrong.** Its "Jul 2026" TCS link pointed to the call from a year earlier, and tcs.com answered 403. FINN takes transcripts from the company's own NSE filings first. All four TCS calls then loaded from NSE's archive.
- **BSE serves PDFs only with a BSE Referer** header.
- **Ad-hoc picks have the sources Pull needs:** ASIANPAINT, HAL, PIDILITIND and BAJFINANCE each have 16 to 19 transcripts on Screener. BAJFINANCE is an NBFC, which tests that nothing assumes EBITDA exists.
- **Annual reports** are 187 (RELIANCE) to 756 (LT) pages: too long for one call. All 22 were read once and stored, about 32 MB of text. Ask picks the six pages that best match the question by keyword weight, and two question words side by side on a page count far more. "Who is the statutory auditor?" on TITAN: "M/s. BSR & Co., LLP", quoted from page 136 and checked against the PDF. On DIXON the page naming its auditor (152) first ranked third behind audit committee pages; with the phrase weight it ranks second, and Ask answers "S.N. Dhawan & Co. LLP".

## R8. Prices, and how many alerts a threshold fires

- **yfinance trap:** the 30 Oct row existed for every ticker with volume but a missing close. Rows without a close are dropped before computing moves.
- **Coverage:** all 18 portfolio tickers return prices on yfinance and a page on Screener.
- **Symbols change.** yfinance and Screener both answer 404 for ZOMATO; the listed symbol is ETERNAL, so FINN keeps an alias map for search.
- **Round closes are real.** A reviewer suspected seeded prices (RELIANCE 1,300.00, HDFCBANK 700.00). NSE's own bhavcopy for 2 Nov has exactly those closes: RELIANCE 1,300.00 after 1,164.90, on 88.1 million shares.
- **Thresholds change the load fivefold.** Replayed over 60 sessions for 18 stocks: ±3% or 2x volume fires 119 alerts, about 2 a day; ±4% or 2.5x fires 51; ±5% or 3x fires 25. So the Alerts screen shows the replay count next to the sliders.

## R9. Gemini models: availability, speed and free-tier limits

- **Availability** (Google's docs, updated 28 to 30 Oct 2026): 2.5 models are limited to past users; new projects should use 3.5 Flash-Lite or 3.8 Flash. Search grounding is not in the free tier for Gemini 3 models, so bios use a separate web search.
- **Speed and recall** on the TCS Oct 2026 transcript (13,850 tokens), asked for every forward-looking guidance statement:

| Model | Time | Items | Notes |
| --- | --- | --- | --- |
| gemini-3.6-flash, low thinking | 7.3 s | 5 | all three real items, plus two client case studies |
| gemini-3.5-flash-lite | 1.7 s | 1 | under-extracts |
| gemini-3.8-flash, low thinking | 40.0 s | 3 | the same three, best precision, slowest |

- **Free-tier limits** (AI Studio, 31 Oct): 3.6 and 3.8 Flash allow 5 requests a minute and 20 a day; the Flash-Lite models 15 a minute and 500 a day. Daily quotas reset at midnight Pacific and apply per project. In practice we hit 429s at 15 a minute, and 503 "high demand" on both Flash and Flash-Lite.
- **What the limits forced:**
  - The ledger went from 5 Flash calls per company to 1 that reads all four transcripts. First run, ASIANPAINT: 52,831 tokens in, 109 s, 13 promises, 0 quotes dropped.
  - Bull and bear and Ask moved to 3.5 Flash-Lite.
  - A per-model limiter honours retry hints, counts calls since Pacific midnight, and falls back to a sibling model.
  - Reading filing PDFs five per call cut 59 calls to 12.
- **Large calls need slow retries.** The Reliance ledger failed on two 503s and then a 429: each retry resent about 160k tokens, tripping the per-minute input-token limit. Calls over 200k characters now wait 60 s, then 120 s. The rebuild then went from 8 promises to 12, with 0 quotes dropped.
- **Implicit caching:** 124,242 of 324,155 input tokens across 17 ledger calls were served from cache with no setup.

## R10. Promise ledger: what can be checked against numbers

- **Batch, 31 Oct:** 11 companies in 16 Flash requests. HAL had 10 promises (6 missed). DIXON had 11, and 2 quotes not found in the PDF were dropped. TRENT has no ledger, correctly: 117 NSE filings in a year and no transcript.
- **Hand check of HAL against the quotes:**
  - Nashik's third line was promised for "October 2024" and inaugurated 17 October 2025.
  - HTT-40 deliveries due September 2025 were still "expected" in May 2026.
  - FY26 revenue grew 6.8% against a "7% to 8%" target, while HAL said "an increase of 7%". So every numbers check states its gap: "0.2 points below the 7% low end".
- **Margins depend on the definition.** Asian Paints guided "PBDIT margin 18% to 20%" and reported 18.9%; Screener's operating margin (16.0%) excludes other income and wrongly read off track. So a margin is decided by numbers only when the promise names its definition, rebuilt from the filed lines:
  - EBIT = PBT + finance costs - other income;
  - EBITDA adds depreciation;
  - PBDIT keeps other income.
- **IT services say "operating margin" for EBIT.** TCS Q2 FY27 is (18,638 + 252 - 1,337) / 73,188 = 23.98%, and TCS said "operating margin of 24%". INFY: 20.98% and "21%".
- **Scope:** a promise for part of the business is never checked against company totals. HDFCBANK's MSME loan growth was once judged against bank revenue. A reported segment is checked against its own rows, and a segment result (before interest and tax) can confirm an EBITDA target but never refute one. A full-year revenue target is checked against the quarters filed so far.
- **Result, 3 Nov:** 15 of 101 stored promises are decided by numbers, up from 8.
  - INFY's EBIT margin is 21.0%, on track for 20% to 22%.
  - HAL's EBITDA margin is 27.7%, off track for 30% to 31%.
  - TITAN's jewellery segment margin is 12.4% against "around 11%".
  - A later call that settled an open target still stands.
  - The other 77 are volumes, launches, plants and capex, which the filings do not report.

## R11. Keeping model answers traceable: Ask and bull and bear

- **Ask from the calls alone mixed kinds of profit.** "What are the profits?" on RELIANCE gave the group's Q1 profit next to the retail and Jio subsidiaries' profits, and missed the Q2 results filed two days earlier. Ask now gets the filed figures as numbered facts first, then the calls, then annual report pages. Every number in the answer must match a source at the precision written.
- **Why exact rounding:** a 1% tolerance let DIXON's "39.7%" from an older call pass for the filed 40.2%.
- **Live runs:**

| Question | Answer starts with | Sources |
| --- | --- | --- |
| RELIANCE: What are the profits? | Q2 FY27 consolidated PAT Rs 29,550 crore, up 33.8% YoY | 3 figures, 2 quotes, 4.5 s |
| HDFCBANK: How is asset quality trending? | Gross NPA 1.11%, net NPA 0.37% | filing, Oct 2026 call page 4 |
| TITAN: Who is the statutory auditor? | BSR & Co., LLP | annual report page 136 |
| TCS: plan for an EV battery business | not covered, no citations | none |

- **Bull and bear restated numbers.** On 2 Nov, 11 of 17 points on DIXON, HDFCBANK and RELIANCE cited a single fact ("ROCE improved from 23% to 29%"). Each point must now join at least two cited facts, and Python drops the rest. DIXON's bear case now reads "PAT fell 44.9% ... because other income dropped from 496 crore to 69 crore".
- **Wording fixed in code:** Flash-Lite kept writing "grew 23% over 5 years" for a 23% CAGR even when told not to, so the phrase is rewritten to "a year".

## R12. Hosting, speed and uptime

- **Render free does not fit:** it sleeps after 15 minutes of no traffic and takes about a minute to wake, keeps no disk, has no free cron, and has no India region. AWS Lightsail Mumbai keeps a disk and is always on (2 vCPU, 1 GB).
- **Every source answers from Lightsail Mumbai:**

| Request | Result |
| --- | --- |
| NSE homepage | 403, cookies still set |
| NSE announcements | 200, 2.5 MB in 1.07 s |
| NSE results | 200 in 0.16 s |
| Screener | 200 in 0.06 s |
| BSE annual report | 200, 26 MB in 0.13 s |
| yfinance | works (plain curl to Yahoo gets 429) |

- **Office web filters block IP-based domains.** On a filtered network we tested from, every `sslip.io` name resolved to the filter's block page. Served through Vercel, every route returned 200 from the same network. Vercel waits up to 120 s for an origin; Netlify's proxy waits 26 s.
- **Speed:** the API only reads SQLite. The 24-hour brief takes 7 ms locally and the 30-day brief 24 ms (157 KB, 29 KB gzipped). A response cache would save milliseconds; the costly part, model output, is stored once.
- **Uptime:** one 502 in 20 hours came from a deploy restart. A second, during an Ask, came from Ubuntu's security updates: needrestart restarted the API 3 times in 3 minutes. FINN is now excluded from needrestart, a watchdog restarts a hung API (tested by freezing it, back in 4 s), and the app retries a 502 or 503 after 1.5 s and 4 s.

## R13. Push notifications

- **Web Push** with the server's own VAPID key (P-256, kept out of git). After each refresh, new filings that need you or are in a flagged category, and the latest session's moves past the thresholds, are sent once to every subscribed phone.
- **Protocol check** (`tests/test_push.py`): a local endpoint stands in for Google's or Apple's. The received body decrypts with the phone's key (RFC 8291), and the token verifies with the server's public key (RFC 8292).
- **Delivery:** headless Chrome refuses push subscriptions, so delivery was checked by hand. On 3 Nov a notification from the live server reached the owner's Android phone; iPhone delivery is untested. iPhones allow web push only for apps added to the Home Screen.
- **Latency:** turning on takes a second or two, mostly the browser registering with its push service.

## R14. Colour and contrast

- **Palette** sampled from the chosen reference design: background `#2e3736`, cards `#3a4342` to `#4f5759`, taupe `#9e9189`.
- **The reference fails contrast.** White on its taupe button is 3.06:1, below the 4.5:1 AA minimum, so FINN uses dark text on taupe (5.1:1).
- **All 12 theme and accent pairs** (Slate, Paper, Navy by four accents), computed from `tokens.css` on 3 Nov: every text colour, including gains, losses and Needs you, is at least 4.5:1 on every surface. Lowest 4.66:1 (Needs you on Paper's hero); button text on the accent at least 5.1:1.
- **Chart colours** for gains and losses failed a colour-blindness check as fills (delta E 2.9 on slate). The chart pair is now `#2ea58f` / `#d9714a` on slate and `#00876c` / `#c8472a` on paper: delta E 10.5 or more, contrast 3:1 or more.

## R15. Three independent blind reviews

All three reviewers were agents given only the two challenge PDFs and the live app at phone width, with no code, README or this log. Each finding was checked against the data before anything changed.

| Area | 31 Oct | 2 Nov | 3 Nov |
| --- | --- | --- | --- |
| Saves time | 7 | 6 | 8 |
| Shows what matters | 6 | 6 | 7 |
| Trust and grounding | 6 | 7 | 7 |
| Density | 7 | 6 | 8 |
| Visual design | 8 | 8 | 8 |
| Interactivity | 6 | 7 | 7 |
| Thought-through | 7 | 7 | 8 |
| Mobile fit | 8 | 8 | 8 |

- **31 Oct, confirmed:**
  - COFORGE's six-month filing (R4).
  - Tax-driven profit changes (R5).
  - A segment promise judged on company totals (R10).
  - A legal adjournment ranked Needs you because a rule matched "SEBI" in boilerplate.
- **2 Nov, confirmed:**
  - On a Monday the 24-hour brief started on Sunday night and hid Friday's results. The brief now covers N trading sessions of price moves plus every filing since the close before them.
  - The track record counted revised promises as misses.
  - "Cheap for its growth" showed the week DIXON's profit fell 45%.
  - Bank pages used the industrial template (R6).
  - DIXON's other-income swing was missed (R5).
- **Not true:** "prices look seeded" (R8).
- **Gaps closed on 3 Nov:**
  - Annual reports read (R7).
  - Bank KPIs (R6).
  - More promises decided by numbers (R10).
  - Bull and bear points that join facts (R11).
  - Push notifications (R13).
- **3 Nov, held against outside sources:** all 18 closes against NSE's bhavcopy; DIXON, MAXHEALTH and HDFCBANK results and bank ratios against the filings; the alert replay counts recomputed from Yahoo; ledger and annual-report quotes on their stated pages.
- **3 Nov, confirmed and fixed:**
  - A new ticker showed 18-month-old results. JYOTHYLAB filed consolidated results only up to Mar 2025 and standalone since; FINN now uses consolidated only when it is current (NSE and Screener alike), and warns when a card's quarter is over about 140 days old.
  - HDFCBANK's Growth read "26.9% a year, Strong" from the merger year (+66% in FY24; last year +3.6%). A single year of 40% or more, with last year under half the 3-year rate, is now named as a one-off and the tiles judge on last year.
  - ASIANPAINT, GRAVITA and KAYNES showed QoQ only: revised filings listed some quarters twice and pushed the year-ago quarter out of the last five. Quarters are now deduplicated first.
  - The track record read "2 of 2" on the tile and "2 of 5" in the section; both now use one count.
  - "NIM was 4.18%" stayed on screen after its quote failed: numbers under 10 were skipped as counts, and 4.18 also matched a Rs 4,18,000 crore figure read as lakh crore. Decimals are now checked, and lakh crore is read only when the answer says so. A quote is also looked for in every call, not only the one the model named.
  - The Jio Platforms listing was filed as a Routine results notice, and a Rs 6.95 lakh penalty kept an Alert tag (its size was in the summary, not read from the PDF).
  - The summary called EBITDA "profit" and named only the biggest mover; it now says EBITDA, and gives the biggest rise and the biggest fall.
  - Margin changes in bps were taken from rounded margins (DIXON -110 bps, actual -104).


## R16. Measuring the AI: Ask and the promise ledger

**Ask eval** (`eval/ask_set.json`, `eval/ask_eval.py`): 31 questions with known answers, scored by script.
- Five kinds:
  - 12 figures from the filings: the number must appear.
  - 5 glossary questions: FINN's definition must be shown.
  - 6 call questions: a quote must be found word for word in the transcript.
  - 3 annual report questions: the expected words, with a quote from the report.
  - 5 questions the sources cannot answer (a share price next week, broker targets, another company's call): Ask must say so.
- Expected figures are from the Q2 FY27 NSE filings.

| Run, 3 Nov | Passed | Notes |
| --- | --- | --- |
| Live app, before fixes | 25 of 31 | refusals 5 of 5, annual report 3 of 3, figures 8 of 12 |
| Same questions after the fixes below | 31 of 31 | all four transcripts in one call |
| Live app after the fixes, questions every few seconds | 24 of 31 | 6 requests dropped: see the modes below |

What the misses showed, and the fixes:
- L&T's other income share of PBT was on the card but not in Ask's facts.
- "Is this valuation high?" did not show the rule it rested on.
- CET1 was answered from March, not the latest quarter.
- HAL's order book numbers came without a quote, so the guard removed them all.

The fixes add the missing fact, link question words to glossary terms, and tell the model to give the latest quarter when no period is named, and to quote whatever it takes from a call. Across the runs, the guard removed a sentence with an unsupported number in 4 of 31 live answers.

**Three ways to answer, same questions, same checks.**
- **Context:** one call that reads all four transcripts.
- **Pages:** one call with only the three transcript pages per call that best match the question, by the same keyword search the annual report uses.
- **Agent:** the model first looks things up with four tools (filed figures, glossary, call search, annual report search), and only what it retrieved reaches the answering call.

| Mode | Passed | Input tokens per question | Rate-limit refusals | Calls per question | Median answer |
| --- | --- | --- | --- | --- | --- |
| Context | 31 of 31 | 80,353 | 10 | 1 | 5.2 s |
| Pages (default) | 30 of 31 | 18,027 | 0 | 1 | 6.0 s |
| Agent | 30 of 31 | 8,445 | 0 | 3.1 | 12.6 s |

- **Why context failed live:** the free tier allows 250k input tokens a minute, so context mode stalls after about three questions. On the live app, questions a few seconds apart made Gemini ask for waits past the proxy's limit, and 6 of 31 requests were dropped. The server logged no restart and no memory kill.
- **Decision:** pages mode is the default. It gives up one question (HAL's order inflow, where the guard withheld an answer it could not quote) for a 4.5x token cut and no refusals, so about 13 questions a minute fit instead of 3, at nearly the same speed. The agent uses the fewest tokens but takes twice as long; both other modes are one setting away (`FINN_ASK=context` or `agent`).
- **Fail fast:** Ask now stops when the model asks it to wait more than 20 s, and the app says the model is busy, instead of the request being dropped.

**Ledger eval** (`eval/ledger_labels.json`): 20 promises drawn at random (seed 2026) from the 193 in the 23 stored ledgers, each read against its quote, the later evidence and the filed numbers.
- **Targets:** 18 of 20 right. Twice the quoted words were not management's own promise: an analyst restating guidance, and a target that is not in the quoted sentence.
- **Verdicts:** 16 of 20 correct, 1 conservative (unclear where pending fitted), and 3 overclaims. All three were "delivered" on weak evidence: "our fastest growing business", a deal size repeated, "the first phase will commence by August".
- **Fix:** the prompt now defines delivered as a result stated as achieved, not progress or a plan restated. It applies to ledgers built from now on and has not yet been re-measured.

## R17. Ledgers that follow new calls, and a note on each quarter

**A new call updates the ledger by itself.** After each filings refresh, a transcript filed in the last three days whose call is not yet in the company's ledger triggers a rebuild, at most two a run while the reasoning quota lasts. The old and new ledgers are compared: a promise is matched by its quote, else by its metric and call. The Brief and the phone then say what moved.

First run, 3 Nov: RELIANCE's Nov 2026 transcript, filed 1 Nov, was missing from its ledger. The scheduled refresh rebuilt it in about 30 s and reported "Promise ledger after the Nov 2026 call: 2 new promises". Both have their quotes found in the PDF: 20 GW of solar modules (page 24), and New Energy earnings from FY28 (page 3).

**Analyst note.** Two sentences on each latest quarter, from numbered facts about that quarter only. Python keeps a sentence only if it cites real facts and every number in it is in the facts it cites. The note sits inside Details, labelled as written by AI.
- The first prompt restated the tiles: DIXON's note missed that other income, not the business, explained the profit fall.
- With the explanatory facts first, and the rule that sentence one must use them, DIXON's note now reads "EBITDA rose 6.3% YoY while PBT dropped 42.6% because other income fell from Rs 496 crore to Rs 69 crore." MAXHEALTH's names its year-ago tax credit.
