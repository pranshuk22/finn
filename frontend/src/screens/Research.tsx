import { useEffect, useRef, useState } from "react";
import { api, ApiError, useQuery } from "../api";
import { Bars } from "../components/Bars";
import { CashVsProfit, PriceChart } from "../components/Charts";
import { HelpButton } from "../components/Help";
import { Monogram } from "../components/Identity";
import { ResultsTiles } from "../components/ResultsTiles";
import { Scorecard } from "../components/Scorecard";
import { GuidanceView, LedgerBuilder, LedgerView, TrackRecord } from "../components/Ledger";
import { Card, ErrorState, ExtLink, Pct, SectionTitle, Sheet, Skeleton, StaleNote, Tabs, Icon } from "../components/ui";
import { crore, dayMonthYear, inr, plain, when } from "../format";
import { navigate } from "../router";
import type { Answer, BalanceSheet, Research, Segments, Trajectory } from "../types";

// In the order of the research brief: business, financials, trajectory, balance sheet, cash, narrative, guidance, cases.
const SECTIONS = [
  { id: "business", label: "Business" },
  { id: "results", label: "Results" },
  { id: "trajectory", label: "Trajectory" },
  { id: "balance", label: "Balance sheet" },
  { id: "cash", label: "Cash" },
  { id: "ledger", label: "Narrative vs numbers" },
  { id: "guidance", label: "Guidance" },
  { id: "bullbear", label: "Bull and bear" },
  { id: "sources", label: "Sources" },
];

export function ResearchScreen({ ticker, section }: { ticker: string; section: string | null }) {
  const q = useQuery<Research>(`/api/research/${encodeURIComponent(ticker)}`);
  const r = q.data;

  // A ticker FINN has not seen is fetched live; once it resolves to a different symbol, show that one.
  useEffect(() => {
    if (r && r.ticker !== ticker) history.replaceState(null, "", `/research/${r.ticker}${location.hash}`);
  }, [r, ticker]);

  useEffect(() => {
    if (r && section) document.getElementById(section)?.scrollIntoView({ block: "start" });
  }, [r, section]);

  if (!r) {
    return (
      <>
        <TopBar ticker={ticker} />
        {q.loading && (
          <>
            <p className="px-4 pb-3 text-[13px] text-muted">Loading {ticker}. A company FINN has not seen before takes about 5 seconds.</p>
            <Skeleton lines={3} />
          </>
        )}
        {q.error && <ErrorState message={q.error.message} onRetry={q.error.status === 404 ? undefined : q.reload} />}
      </>
    );
  }

  const s = r.snapshot;
  const price = s.ratios["Current Price"] as number | undefined;
  const hl = s.ratios["High / Low"] as number[] | undefined;
  const stats: [string, string][] = [
    // P/E, margin and debt to equity are in the scorecard above
    ["Market cap", s.ratios["Market Cap"] != null ? crore(s.ratios["Market Cap"] as number) : "n/a"],
    [s.is_financial ? "ROE" : "ROCE", `${(s.is_financial ? s.ratios["ROE"] : s.ratios["ROCE"]) ?? "n/a"}%`],
    ["52w range", hl ? `${inr(hl[1])} to ${inr(hl[0])}` : "n/a"],
    ["TTM revenue", crore(s.ttm.revenue)],
    ["TTM net profit", crore(s.ttm.net_profit)],
    ["Price to book", pToB(price, s.ratios["Book Value"] as number | undefined)],
  ];

  return (
    <div className="pb-20">
      <TopBar ticker={r.ticker} />
      <header className="px-4 pb-4">
        <div className="flex items-center gap-3">
          <Monogram ticker={r.ticker} size={44} />
          <div className="min-w-0">
            <p className="text-[13px] text-muted">
              <span className="font-semibold text-ink">{r.ticker}</span>
              {r.resolved_from && ` · was ${r.resolved_from}`}
              {r.in_portfolio && " · In your portfolio"}
            </p>
            <h1 className="font-display text-[26px] leading-tight font-semibold">{s.name}</h1>
          </div>
        </div>
        {price != null && !r.price && <p className="tabular mt-1 text-[24px] font-semibold">Rs {inr(price, 2)}</p>}
        {r.price && <PriceChart key={r.ticker} price={r.price} />}
        <Scorecard r={r} />
        <dl className="mt-4 grid grid-cols-2 overflow-hidden rounded-[12px] bg-card">
          {stats.map(([k, v], i) => (
            <div key={k} className={`px-4 py-2.5 ${i % 2 ? "border-l border-line" : ""} ${i > 1 ? "border-t border-line" : ""}`}>
              <dt className="text-[12px] text-muted">{k}</dt>
              <dd className="tabular m-0 text-[15px] font-medium">{v}</dd>
            </div>
          ))}
        </dl>
        {s.about && <About text={s.about} />}
      </header>

      <SectionNav />

      <StaleNote savedAt={q.savedAt} offline={q.error?.status === 0} onRetry={q.reload} />

      <SectionTitle id="business">Business</SectionTitle>
      <Business seg={r.segments} />

      <SectionTitle id="results">Latest results</SectionTitle>
      {r.results ? (
        <Card>
          <p className="mb-3 text-[13px] text-muted">
            {r.results.quarter}, quarter ended {dayMonthYear(r.results.period_end)}
            {r.results.broadcast_at && `. Filed ${when(r.results.broadcast_at)}`}
          </p>
          <ResultsTiles r={r.results} />
        </Card>
      ) : (
        <p className="mx-4 text-[14px] text-muted">No quarterly results found in NSE's integrated filings for this company.</p>
      )}

      {r.trajectory && (
        <>
          <SectionTitle id="trajectory">Trajectory</SectionTitle>
          <Card className="space-y-7">
            <Bars title="Revenue, Rs crore" points={r.trajectory.annual["Revenue"] ?? []} format={(v) => inr(v)} />
            <Bars title="Net profit, Rs crore" points={r.trajectory.annual["Net profit"] ?? []} format={(v) => inr(v)} />
            <Bars title={`${s.ttm.margin_label}, by quarter`} points={r.trajectory.quarterly["Margin %"] ?? []} format={(v) => `${v}%`} />
            <Growth growth={r.trajectory.growth} />
          </Card>
        </>
      )}

      {r.balance_sheet && r.balance_sheet.years.length > 0 && (
        <>
          <SectionTitle id="balance">Balance sheet</SectionTitle>
          <Balance bs={r.balance_sheet} wc={r.cash_quality?.working_capital ?? {}} />
        </>
      )}

      {r.cash_quality && (
        <>
          <SectionTitle id="cash">Cash quality</SectionTitle>
          <Cash r={r} />
        </>
      )}

      <SectionTitle id="ledger">Narrative vs numbers</SectionTitle>
      <p className="mx-4 -mt-1 mb-3 text-[13px] text-muted">What management promised on past calls, checked against what was reported since.</p>
      {r.ledger?.status === "ok" && <TrackRecord ledger={r.ledger} />}
      {r.ledger ? <LedgerView ledger={r.ledger} hide={["pending"]} /> : <LedgerBuilder ticker={r.ticker} onBuilt={q.reload} />}

      <SectionTitle id="guidance">Guidance</SectionTitle>
      {r.ledger ? (
        <GuidanceView ledger={r.ledger} />
      ) : (
        <p className="mx-4 text-[14px] text-muted">Read from the same calls as the ledger. Build the ledger above to see it.</p>
      )}

      {r.bull_bear && (
        <>
          <SectionTitle id="bullbear">Bull and bear</SectionTitle>
          <Card>
            <BullBearList title="Bull case" tone="up" points={r.bull_bear.bull} />
            <div className="my-4 border-t border-line" />
            <BullBearList title="Bear case" tone="down" points={r.bull_bear.bear} />
            <p className="mt-4 text-[12px] text-muted">Written by Flash-Lite from the numbered facts shown under each point; points citing no valid fact are removed.</p>
          </Card>
        </>
      )}

      {r.documents.some((d) => d.kind === "transcript") && (
        <>
          <SectionTitle id="ask-calls">Ask the calls</SectionTitle>
          <div className="mx-4 flex flex-wrap gap-2">
            {SUGGESTED.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => window.dispatchEvent(new CustomEvent("finn:ask", { detail: q }))}
                className="min-h-9 rounded-full border border-line bg-card px-3.5 py-1.5 text-left text-[13px]"
              >
                {q}
              </button>
            ))}
          </div>
          <p className="mx-4 mt-2 text-[12px] text-muted">Answers come only from the last four calls, each with a quote checked against the transcript.</p>
        </>
      )}

      <SectionTitle id="sources">Sources</SectionTitle>
      <ul className="mx-4">
        {r.documents.map((d) => (
          <li key={d.url} className="flex min-h-11 items-center justify-between gap-3 border-b border-line py-2 text-[14px]">
            <span>
              {d.kind === "transcript" ? "Earnings call" : "Annual report"}, {d.period}
              {d.loaded ? <span className="text-muted"> · read</span> : null}
            </span>
            <ExtLink href={d.url}>PDF</ExtLink>
          </li>
        ))}
        <li className="py-3 text-[12px] text-muted">{s.source}. Quarterly results from NSE integrated filings.</li>
      </ul>

      <AskBar ticker={r.ticker} hasTranscripts={r.documents.some((d) => d.kind === "transcript")} />
    </div>
  );
}

function SectionNav() {
  const [active, setActive] = useState("business");
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const tab = bar.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    const list = tab?.parentElement;
    if (tab && list) list.scrollTo({ left: tab.offsetLeft - 16, behavior: "smooth" });
  }, [active]);
  useEffect(() => {
    const els = SECTIONS.map((x) => document.getElementById(x.id)).filter((e): e is HTMLElement => !!e);
    const io = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActive(top.target.id);
      },
      { rootMargin: "-90px 0px -60% 0px" },
    );
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, []);
  return (
    <div ref={bar} className="sticky top-0 z-20 bg-base/95 backdrop-blur">
      <Tabs
        label="Sections"
        value={active}
        items={SECTIONS.map((x) => ({ value: x.id, label: x.label }))}
        onChange={(id) => {
          setActive(id);
          document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
          history.replaceState(null, "", `#${id}`);
        }}
      />
    </div>
  );
}

function TopBar({ ticker }: { ticker: string }) {
  return (
    <div className="flex items-center justify-between px-2 pt-[calc(8px+env(safe-area-inset-top))]">
      <button type="button" onClick={() => (history.length > 1 ? history.back() : navigate("/research"))} className="flex h-11 items-center gap-1 px-2 text-[15px] text-accent-ink">
        <span className="rotate-180">
          <Icon.chevron />
        </span>
        Back
      </button>
      <span className="sr-only">{ticker}</span>
      <HelpButton className="mr-2" />
    </div>
  );
}

function About({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button type="button" onClick={() => setOpen(!open)} className="mt-3 block text-left text-[13px] text-muted" aria-expanded={open}>
      <span className={open ? "" : "line-clamp-2"}>{text}</span>
    </button>
  );
}

function Growth({ growth }: { growth: Trajectory["growth"] }) {
  const rows = ["Revenue", "Operating profit", "Net profit"].filter((k) => growth[k]);
  if (rows.length === 0) return null;
  return (
    <table className="w-full border-collapse text-[13px]">
      <thead>
        <tr className="text-muted">
          <th className="border-b border-line py-1.5 text-left font-medium">Growth a year</th>
          <th className="border-b border-line py-1.5 text-right font-medium">Last year</th>
          <th className="border-b border-line py-1.5 text-right font-medium">3y</th>
          <th className="border-b border-line py-1.5 text-right font-medium">5y</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((k) => (
          <tr key={k} className="border-b border-line last:border-0">
            <td className="py-2">{k}</td>
            <td className="py-2 text-right">
              <Pct value={growth[k].last_year} />
            </td>
            <td className="py-2 text-right">
              <Pct value={growth[k].cagr_3y} />
            </td>
            <td className="py-2 text-right">
              <Pct value={growth[k].cagr_5y} />
            </td>
          </tr>
        ))}
      </tbody>
      {growth["Margin %"]?.change_pts_5y != null && (
        <tfoot>
          <tr>
            <td colSpan={4} className="pt-2 text-[12px] text-muted">
              {growth["Margin %"].change_pts_5y === 0
                ? "Margin is where it was five years ago."
                : `Margin moved ${growth["Margin %"].change_pts_5y! > 0 ? "up" : "down"} ${Math.abs(growth["Margin %"].change_pts_5y!)} points over five years.`}
            </td>
          </tr>
        </tfoot>
      )}
    </table>
  );
}

function Cash({ r }: { r: Research }) {
  const cq = r.cash_quality!;
  if (cq.is_financial) {
    return (
      <p className="mx-4 text-[14px] text-muted">
        Operating cash flow is not a useful quality test for a lender, because lending itself shows up as operating cash outflow. See ROE and
        the results card instead.
      </p>
    );
  }
  return (
    <Card className="space-y-7">
      {cq.cfo_to_ebitda_3y != null && (
        <div>
          <p className="tabular text-[30px] leading-none font-semibold">{cq.cfo_to_ebitda_3y}%</p>
          <p className="mt-1 text-[13px] text-muted">of operating profit turned into operating cash over the last three years</p>
        </div>
      )}
      <CashVsProfit years={cq.years} />
      <Bars title="Free cash flow, Rs crore" points={cq.years.map((y) => ({ period: y.period, value: y.fcf }))} format={(v) => inr(v)} />
    </Card>
  );
}

function pToB(price: number | undefined, book: number | undefined): string {
  return price != null && book ? `${(price / book).toFixed(1)}x` : "n/a";
}

function Business({ seg }: { seg: Segments | null }) {
  if (!seg) return <p className="mx-4 text-[14px] text-muted">No segment table in the latest results filing.</p>;
  const source = seg.source_url && (
    <>
      From the segment table of the {seg.quarter} results filing (<ExtLink href={seg.source_url}>NSE</ExtLink>).
    </>
  );
  if (seg.items.length === 0) {
    return (
      <Card>
        <p className="text-[15px]">
          Reports one business segment: <span className="font-semibold">{seg.single ?? "not named"}</span>.
        </p>
        <p className="mt-2 text-[12px] text-muted">{source}</p>
      </Card>
    );
  }
  const top = Math.max(...seg.items.map((i) => i.share_pct ?? 0));
  return (
    <Card>
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-muted">
            <th className="border-b border-line py-1.5 text-left font-medium">{seg.quarter}</th>
            <th className="border-b border-line py-1.5 text-right font-medium">Mix</th>
            <th className="border-b border-line py-1.5 text-right font-medium">Margin</th>
            <th className="border-b border-line py-1.5 text-right font-medium">YoY</th>
          </tr>
        </thead>
        <tbody>
          {seg.items.map((i) => (
            <tr key={i.name} className="border-b border-line last:border-0">
              <td className="py-2 pr-2">
                <span className="block">{i.name}</span>
                <span className="mt-1 block h-1 rounded-full bg-line">
                  <span className="block h-1 rounded-full bg-accent" style={{ width: `${top ? (100 * (i.share_pct ?? 0)) / top : 0}%` }} />
                </span>
              </td>
              <td className="tabular py-2 text-right align-top">
                {i.share_pct != null ? `${i.share_pct}%` : "n/a"}
                {i.share_change_pts != null && Math.abs(i.share_change_pts) >= 1 && (
                  <span className="block text-[11px] text-muted">
                    {i.share_change_pts > 0 ? "+" : ""}
                    {i.share_change_pts} pts
                  </span>
                )}
              </td>
              <td className="tabular py-2 text-right align-top">{i.margin_pct != null ? `${i.margin_pct}%` : "n/a"}</td>
              <td className="py-2 text-right align-top">
                <Pct value={i.yoy} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-[12px] leading-relaxed text-muted">
        Mix is each segment's share of segment revenue; pts is the change from a year ago. Margin is segment profit before interest and
        tax over segment revenue. YoY is blank where the segment was renamed or is new. {source}
      </p>
    </Card>
  );
}

const MIX: [keyof BalanceSheet["years"][number]["mix"], string][] = [
  ["deposits", "Deposits"],
  ["debt", "Borrowings"],
  ["equity", "Equity"],
  ["other", "Other liabilities"],
];

function Balance({ bs, wc }: { bs: BalanceSheet; wc: Record<string, { period: string; value: number | null }[]> }) {
  const y = bs.years[bs.years.length - 1];
  const first = bs.years[0];
  const stats: [string, string][] = [
    ["Borrowings", `Rs ${inr(y.debt)} cr`],
    ["Debt to equity", `${y.debt_to_equity ?? "n/a"}`],
    bs.interest_coverage
      ? ["Interest coverage", `${bs.interest_coverage.value}x (${bs.interest_coverage.period})`]
      : ["Interest coverage", bs.is_financial ? "not used for lenders" : "n/a"],
    ["Capital work in progress", y.cwip != null ? `Rs ${inr(y.cwip)} cr` : "n/a"],
  ];
  return (
    <Card className="space-y-6">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        {stats.map(([k, v]) => (
          <div key={k}>
            <dt className="text-[12px] text-muted">{k}</dt>
            <dd className="tabular m-0 text-[15px] font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      <div>
        <p className="mb-2 text-[13px] text-muted">How the balance sheet is funded, {y.period}</p>
        <ul className="space-y-1.5 text-[13px]">
          {MIX.filter(([k]) => y.mix[k] != null).map(([k, label]) => (
            <li key={k} className="flex items-center gap-3">
              <span className="w-32 shrink-0">{label}</span>
              <span className="h-1.5 flex-1 rounded-full bg-line">
                <span className="block h-1.5 rounded-full bg-accent" style={{ width: `${y.mix[k]}%` }} />
              </span>
              <span className="tabular w-12 text-right">{y.mix[k]}%</span>
            </li>
          ))}
        </ul>
      </div>
      {first !== y && first.debt_to_equity != null && y.debt_to_equity != null && (
        <p className="text-[13px] text-muted">
          Debt to equity went from {first.debt_to_equity} in {first.period} to {y.debt_to_equity} in {y.period}.
        </p>
      )}
      {!bs.is_financial && <WorkingCapital wc={wc} />}
      <p className="text-[12px] text-muted">Annual balance sheets from Screener; the latest column may be a half year.</p>
    </Card>
  );
}

function WorkingCapital({ wc }: { wc: Record<string, { period: string; value: number | null }[]> }) {
  const keys = ["Debtor Days", "Inventory Days", "Days Payable", "Cash Conversion Cycle"].filter((k) => wc[k]?.length);
  if (keys.length === 0) return null;
  const periods = wc[keys[0]].map((p) => p.period);
  const first = periods[0];
  const last = periods[periods.length - 1];
  return (
    <table className="w-full border-collapse text-[13px]">
      <thead>
        <tr className="text-muted">
          <th className="border-b border-line py-1.5 text-left font-medium">Days</th>
          <th className="border-b border-line py-1.5 text-right font-medium">{first}</th>
          <th className="border-b border-line py-1.5 text-right font-medium">{last}</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((k) => {
          const s = wc[k];
          return (
            <tr key={k} className="border-b border-line last:border-0">
              <td className="py-2">{k}</td>
              <td className="tabular py-2 text-right text-muted">{s[0].value ?? "n/a"}</td>
              <td className="tabular py-2 text-right">{s[s.length - 1].value ?? "n/a"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function BullBearList({ title, tone, points }: { title: string; tone: "up" | "down"; points: { text: string; refs: { id: string; fact: string }[] }[] }) {
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-2 text-[15px] font-semibold">
        <span className={`h-2 w-2 rounded-[2px] ${tone === "up" ? "bg-up" : "bg-down"}`} />
        {title}
      </h3>
      <ul className="space-y-3">
        {points.map((p) => (
          <li key={p.text}>
            <p className="text-[14px]">{p.text}</p>
            <p className="mt-1 text-[12px] text-muted">{p.refs.map((f) => f.fact).join(" · ")}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Most people do not know what to ask a set of earnings calls; these show what Ask is good at.
export const SUGGESTED = [
  "What did they guide for revenue growth?",
  "What did they say about margins?",
  "Any capex or capacity plans?",
  "What risks did management flag?",
];

function AskBar({ ticker, hasTranscripts }: { ticker: string; hasTranscripts: boolean }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [focused, setFocused] = useState(false);
  const [answer, setAnswer] = useState<{ q: string; a: Answer | null; err: string | null } | null>(null);
  useEffect(() => {
    // the in-page suggestions ask through here, so both share one answer sheet
    const onAsk = (e: Event) => ask((e as CustomEvent<string>).detail);
    window.addEventListener("finn:ask", onAsk);
    return () => window.removeEventListener("finn:ask", onAsk);
  });

  const ask = async (preset?: string) => {
    const question = (preset ?? text).trim();
    if (question.length < 3 || busy) return;
    setBusy(true);
    setAnswer({ q: question, a: null, err: null });
    try {
      const a = await api.post<Answer>(`/api/research/${ticker}/ask`, { question });
      setAnswer({ q: question, a, err: null });
      setText("");
    } catch (e) {
      setAnswer({ q: question, a: null, err: (e as ApiError).message });
    } finally {
      setBusy(false);
    }
  };

  if (!hasTranscripts) return null;

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask();
        }}
        className="fixed inset-x-0 bottom-[calc(64px+env(safe-area-inset-bottom))] z-20 mx-auto flex max-w-[480px] flex-wrap gap-2 border-t border-line bg-base/95 px-4 py-2 backdrop-blur"
      >
        {focused && !text && !busy && (
          <div className="no-scrollbar -mx-4 flex w-[calc(100%+32px)] gap-2 overflow-x-auto px-4 pb-1">
            {SUGGESTED.map((q) => (
              <button
                key={q}
                type="button"
                onPointerDown={(e) => e.preventDefault()}
                onClick={() => ask(q)}
                className="h-8 shrink-0 rounded-full border border-line bg-card px-3 text-[13px] text-ink"
              >
                {q}
              </button>
            ))}
          </div>
        )}
        <label htmlFor="ask" className="sr-only">
          Ask about {ticker}'s earnings calls
        </label>
        <input
          id="ask"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={`Ask ${ticker}'s earnings calls`}
          maxLength={500}
          enterKeyHint="send"
          className="h-11 min-w-0 flex-1 rounded-[10px] border border-line bg-card px-3 text-[16px] text-ink placeholder:text-muted focus:border-accent focus:outline-none"
        />
        <button type="submit" disabled={busy || text.trim().length < 3} className="h-11 shrink-0 rounded-[10px] bg-accent px-4 font-semibold text-on-accent disabled:opacity-50">
          Ask
        </button>
      </form>
      <Sheet open={!!answer} onClose={() => !busy && setAnswer(null)} title="From the earnings calls">
        {answer && (
          <div className="space-y-4">
            <p className="text-[13px] text-muted">{answer.q}</p>
            {busy && <p className="text-[14px] text-muted">Reading the transcripts. This usually takes a few seconds.</p>}
            {answer.err && <p className="text-[14px] text-down">{answer.err}</p>}
            {answer.a && (
              <>
                {!answer.a.covered && (
                  <p className="text-[13px] font-semibold text-needs">{answer.a.unverified ? "No quote could be verified" : "Not covered by the calls"}</p>
                )}
                <p className="text-[15px]">{plain(answer.a.answer)}</p>
                {answer.a.citations.map((c) => (
                  <figure key={`${c.source}-${c.page}-${c.quote.slice(0, 20)}`} className="m-0 border-l-2 border-accent pl-4">
                    <blockquote className="m-0 font-serif text-[17px] leading-relaxed">{plain(c.quote)}</blockquote>
                    <figcaption className="mt-2 text-[12px] text-muted">
                      {c.source} call, page {c.page} · <ExtLink href={`${c.url}#page=${c.page}`}>Open PDF</ExtLink>
                    </figcaption>
                  </figure>
                ))}
                {!!answer.a.unverified_dropped && (
                  <p className="text-[12px] text-muted">
                    {answer.a.unverified_dropped} quote{answer.a.unverified_dropped > 1 ? "s" : ""} could not be found in the PDF and{" "}
                    {answer.a.unverified_dropped > 1 ? "were" : "was"} removed
                    {answer.a.covered && answer.a.citations.length > 0 && ". Read only what the quotes above support"}.
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </Sheet>
    </>
  );
}
