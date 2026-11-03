import { createContext, useContext, useState, type ReactNode } from "react";
import { STATUS, StatusChip } from "./Ledger";
import { Sheet } from "./ui";

// How to read FINN, opened from a "?" next to each title. Each tab shows only the parts about that tab; Settings holds
// the whole guide (owner, 3 Nov: the same long page on every tab was more than anyone needed there).

export type HelpTopic = "brief" | "research" | "company" | "alerts" | "all";

const TITLE: Record<HelpTopic, string> = {
  brief: "Reading the brief",
  research: "Researching a company",
  company: "Reading a company page",
  alerts: "Setting alerts",
  all: "How FINN works",
};

const Topic = createContext<HelpTopic>("all");

export function HelpButton({ className = "", topic = "all" }: { className?: string; topic?: HelpTopic }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={TITLE[topic]}
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line text-[15px] font-semibold text-muted ${className}`}
      >
        ?
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title={TITLE[topic]}>
        <HelpContent topic={topic} />
        {topic !== "all" && <p className="mt-7 text-[13px] text-muted">The full guide is in Settings, under How FINN works.</p>}
      </Sheet>
    </>
  );
}

function Part({ title, on, children }: { title: string; on: HelpTopic[]; children: ReactNode }) {
  const topic = useContext(Topic);
  if (topic !== "all" && !on.includes(topic)) return null;
  return (
    <section>
      <h3 className="mb-2 text-[13px] font-semibold tracking-wide text-muted uppercase">{title}</h3>
      <div className="space-y-2 text-[14px] leading-relaxed">{children}</div>
    </section>
  );
}

function Term({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 font-semibold">{name}</dt>
      <dd className="m-0 text-muted">{children}</dd>
    </div>
  );
}

const PROMISE = ["delivered", "on_track", "missed", "off_track", "revised", "dropped", "unclear", "awaiting", "pending"];
const PROMISE_MEANS: Record<string, string> = {
  delivered: "Reported numbers or a later call show it happened.",
  on_track: "Not due yet, and the latest numbers are at or above the target.",
  missed: "The date passed and it did not happen, or management said so.",
  off_track: "Not due yet, and the latest numbers are below the target.",
  revised: "A later call changed the target or the date.",
  dropped: "No later call brings it up. Not proof it was abandoned.",
  unclear: "Later calls mention it but do not settle it.",
  awaiting: "Its date has passed, but no reported number or later call settles it yet.",
  pending: "Said on the latest call, or not due yet. Shown under Guidance.",
};

export function HelpContent({ topic = "all" }: { topic?: HelpTopic }) {
  return (
    <Topic.Provider value={topic}>
      <Guide />
    </Topic.Provider>
  );
}

function Guide() {
  return (
    <div className="space-y-7">
      <Part title="The brief" on={["brief"]}>
        <p>Every filing your companies made in the window you pick, sorted so you can stop reading once the important part is done.</p>
        <dl className="space-y-2">
          <Term name="Needs you">Quarterly results; a CEO, MD, CFO, chair or other key manager joining or leaving; insolvency or regulator action; a rating downgrade; a promoter pledge created or invoked.</Term>
          <Term name="Worth knowing">Board changes, deals, fund raises and capex, dividends, other legal matters, promoters selling, results decks.</Term>
          <Term name="Routine">Meeting notices, certificates, investor meet schedules. Folded away.</Term>
        </dl>
        <p className="text-muted">
          FINN sorts a filing by the exchange's own label first, then fixed text rules, and only when neither fits does a small model read it. Tap a
          card to see its filings. Mark it done when you have read it, or swipe it right on a phone; you can undo.
        </p>
      </Part>

      <Part title="Alerts" on={["alerts"]}>
        <p className="text-muted">
          Set what counts as unusual on the Alerts tab: a price move, volume against its 20-day average, and filing types to always flag. Turn
          on Notify this phone and FINN sends a notification after each refresh when something new crosses those rules. On an iPhone, add
          FINN to the Home Screen first.
        </p>
      </Part>

      <Part title="Reading a results card" on={["brief", "company"]}>
        <dl className="space-y-2">
          <Term name="EBITDA*">Operating EBITDA: profit before tax + finance costs + depreciation - other income, so interest on cash does not count as business profit.</Term>
          <Term name="bps">Basis points: 100 bps is one percentage point. A margin going from 17.0% to 15.6% is -140 bps.</Term>
          <Term name="Stock next session">How the share price and volume moved in the first session the market could react, against the usual volume of the 20 sessions before.</Term>
          <Term name="Amber notes">FINN found something to check: tax explaining most of a profit change, a number that disagrees with Screener, or profit leaning on other income.</Term>
        </dl>
      </Part>

      <Part title="Research" on={["research", "company"]}>
        <p>
          Built only from primary sources: NSE filings, Screener's standardised financials (taken from the companies' statements) and earnings call
          transcripts. No news, no broker notes.
        </p>
        <p className="text-muted">
          Narrative vs numbers lists what management promised on past calls and what happened. Each promise links to its exact quote and page, and
          FINN checks every quote word for word against the transcript PDF.
        </p>
        <ul className="space-y-1.5">
          {PROMISE.map((s) => (
            <li key={s} className="flex items-start gap-3">
              <span className="w-36 shrink-0">
                <StatusChip status={s} />
              </span>
              <span className="text-[13px] text-muted">{PROMISE_MEANS[s] ?? STATUS[s]?.label}</span>
            </li>
          ))}
        </ul>
        <p className="text-muted">
          A promise is decided by the numbers when the filings report it: revenue and profit growth, full-year revenue against the quarters
          filed so far, a margin in the definition the promise names (EBIT, EBITDA or PBDIT, rebuilt from the filed line items), or a
          reported segment's revenue and margin. Volumes, launches, plants and capex are not in the filings, so a later call settles those.
        </p>
        <p className="text-muted">
          Ask answers number questions from the results filed with NSE first, then adds what management said on the last four calls, and
          searches the latest annual report for what calls do not cover: auditors, directors, subsidiaries, related parties, risks. Ask what a term means ("What does EBITDA mean here?") and it answers from FINN's own glossary, with this company's figure. Every
          quote is checked against its PDF, a sentence whose number is in no source is removed, and if nothing can be traced it says so.
        </p>
      </Part>

      <Part title="The scorecard" on={["company"]}>
        <p className="text-muted">The six tiles at the top of a company page are fixed rules on the numbers below them:</p>
        <dl className="space-y-2">
          <Term name="Growth">Revenue a year over 3 years: 15% or more strong, 8% steady, 0% slow, below that shrinking.</Term>
          <Term name="Margins">Latest quarter against a year earlier: up a point or more expanding, down a point or more slipping. Lenders show credit cost instead: provisions as a share of pre-provision profit, 15% or less low, 30% moderate.</Term>
          <Term name="Cash">Cash from operations over operating profit, 3 years: 90% or more strong, 70% fair. Lenders show return on equity: 15% strong, 10% fair.</Term>
          <Term name="Balance sheet">Debt to equity: 0.3 or less light, up to 1 moderate, above 1 heavy. Banks show asset quality instead: net NPA 0.5% or less clean, up to 1.5% watch, above that stressed.</Term>
          <Term name="Track record">Promises kept of those a later result settled: 60% or more reliable, 40% mixed. Revised and not mentioned again are not counted as misses, and fewer than 3 settled is too early to say.</Term>
          <Term name="Valuation">P/E against 3-year profit growth a year: up to 1x cheap for its growth, up to 2x fair, above rich. If PAT fell 20% or more YoY in the latest quarter, growth is in doubt.</Term>
        </dl>
      </Part>

      <Part title="New to investing?" on={["research", "company"]}>
        <p className="text-muted">
          Turn on Explain the numbers in Settings, or tap Explain on a company page. Each scorecard verdict and results figure then gets a
          plain line saying what it means and how to read this company's number, worked out from the figure itself.
        </p>
      </Part>

      <Part title="Words you will see" on={["brief", "company"]}>
        <dl className="space-y-2">
          <Term name="QoQ, YoY">Against the previous quarter, and against the same quarter a year earlier.</Term>
          <Term name="PBT, PAT">Profit before tax, profit after tax.</Term>
          <Term name="TTM">Trailing twelve months: the last four quarters added up.</Term>
          <Term name="CAGR">Compound annual growth: a yearly rate, not a total.</Term>
          <Term name="Debt to equity">Borrowings divided by shareholders' equity.</Term>
          <Term name="Interest coverage">Profit before interest and tax divided by interest: how many times over the company earns its interest bill.</Term>
          <Term name="NII, NPA">Net interest income: what a bank earns on loans and investments less what it pays on deposits and borrowings. A non-performing asset (NPA) is a loan unpaid for 90 days; net NPA is what is left after provisions.</Term>
          <Term name="CET1">Common equity tier 1: the bank's core capital as a share of its risk-weighted assets.</Term>
          <Term name="Cash conversion">Cash from operations as a share of operating profit. Near or above 100% means profits are turning into cash.</Term>
        </dl>
      </Part>
    </div>
  );
}
