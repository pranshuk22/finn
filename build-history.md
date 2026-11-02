# Build history

**How FINN was built with AI, in five days.**

FINN was built in [Claude Code](https://claude.com/claude-code), Anthropic's coding agent, between 30 Oct and 3 Nov 2026. I set the direction, the rules and the design, and checked everything myself, several times over: the app on my phone, the numbers against the filings, and every change before it shipped. Claude Code wrote the code, ran the tests and deploys, and checked every claim against live data. Inside the product, Gemini models read and judge text; Python does all the arithmetic.

| At a glance | |
| --- | --- |
| **Working time** | 30 Oct to 3 Nov 2026, one session (the context was summarised and continued as it grew) |
| **My instructions** | about 40, plus screenshots and pasted briefs |
| **Agent work** | 400+ replies, 1,300+ tool calls (reading, running, testing, deploying) |
| **Independent reviews** | 2 blind reviews of the live app, 31 Oct and 2 Nov |
| **Commits** | all mine, none with an AI co-author |
| **Model cost** | Rs 0, on the Gemini free tier |

## Five days

| Day | Focus | What happened |
| --- | --- | --- |
| **Fri 30 Oct** | Problem and plan | Read the challenge and critiqued my draft README. Probed NSE, Screener, BSE and Gemini live before designing anything. Built ingestion, the results parser and the classifier. |
| **Sat 31 Oct** | The product | API, analytics and the promise ledger, cut from 5 model calls to 1 to fit the free tier ([R9](docs/RESEARCH.md#r9-gemini-models-availability-speed-and-free-tier-limits)). Deployed to Lightsail Mumbai behind Vercel. I chose a reference design; the look was reworked on my feedback ("looks AI-ish", "all text and numbers") until it was quiet and readable. First blind review. |
| **Sun 1 Nov** | Reliability | I saw a 502 in Ask. The cause was security updates restarting the API; fixed with a watchdog and retries ([R12](docs/RESEARCH.md#r12-hosting-speed-and-uptime)). |
| **Mon 2 Nov** | Ask and review two | Ask answers number questions from filed results first ([R11](docs/RESEARCH.md#r11-keeping-model-answers-traceable-ask-and-bull-and-bear)). The second blind review scored 6 to 8 out of 10 in each category; ten findings fixed ([R15](docs/RESEARCH.md#r15-two-independent-blind-reviews)). |
| **Tue 3 Nov** | Closing the gaps | Bank NPA and NII from filings, annual reports in Ask, more promises decided by numbers, sharper bull and bear, phone notifications. |

## Checks, not trust

Nothing was taken on trust. I went through the app and its numbers by hand, more than once, and every result from the agent or a model was also checked against the source before it shipped. Some of what those checks caught:

- **A wrong number in an answer.** Ask once quoted Dixon's revenue growth as 39.7%, from an older call; the filing says 40.2%. Numbers in answers are now matched to a source at the precision written.
- **A false finding.** A reviewer said the prices looked seeded. NSE's own closing-price file for 2 Nov has the same round closes, so nothing was changed.
- **A definition before a verdict.** "TCS's operating margin means EBIT" was tested against the filing (23.98%) and the call ("24%") before the ledger used it.
- **Its own test.** A push signature check failed; the bug was in the test's header parsing, not the server, and was fixed there.

## What the agent did not decide

- **What FINN is for:** a brief you can finish, not a feed.
- **What counts as important:** which filings need you, and the trade-offs in the README.
- **How it looks:** the reference design and the feedback rounds.
- **What ships:** every deploy, and every change to the public repo.
