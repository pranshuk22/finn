import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { ago, monthYear, plain, target } from "../format";
import type { Ledger, LedgerItem } from "../types";
import { GuidedVsActual } from "./Charts";
import { Button, ExtLink, Icon, Sheet, Tabs } from "./ui";

export const STATUS: Record<string, { label: string; color: string }> = {
  delivered: { label: "Delivered", color: "var(--up)" },
  on_track: { label: "On track", color: "var(--up)" },
  missed: { label: "Missed", color: "var(--down)" },
  off_track: { label: "Off track", color: "var(--down)" },
  revised: { label: "Revised", color: "var(--needs-you)" },
  dropped: { label: "Not mentioned again", color: "var(--needs-you)" }, // no later call brings it up
  pending: { label: "Pending", color: "var(--text-muted)" },
  unclear: { label: "Unclear", color: "var(--text-muted)" },
};

const ORDER = ["missed", "off_track", "revised", "dropped", "delivered", "on_track", "pending", "unclear"];

const JUDGED: Record<string, string> = {
  numbers: "Decided by reported numbers",
  model: "Judged from later calls",
  "later guidance": "Target changed in a later call",
};

export function StatusChip({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, color: "var(--text-muted)" };
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-[13px] font-semibold" style={{ color: s.color }}>
      <span className="h-2 w-2 rounded-[2px]" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

function pdfAt(url: string, page: number | null | undefined) {
  return page ? `${url}#page=${page}` : url;
}

/** Promises whose outcome can already be read against reported numbers or later calls. Pending ones are Guidance. */
export function LedgerView({ ledger, hide = [] }: { ledger: Ledger; hide?: string[] }) {
  const [filter, setFilter] = useState<string | null>(null);
  const [open, setOpen] = useState<LedgerItem | null>(null);

  if (ledger.status !== "ok") {
    return <p className="mx-4 text-[14px] text-muted">{ledger.note ?? "No ledger could be built for this company."}</p>;
  }

  const shown = ledger.items.filter((i) => !hide.includes(i.status));
  const statuses = ORDER.filter((s) => !hide.includes(s) && ledger.counts[s]);
  const items = [...shown]
    .filter((i) => !filter || i.status === filter)
    .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  const calls = ledger.transcripts.map((t) => t.period);

  if (shown.length === 0) {
    return <p className="mx-4 text-[14px] text-muted">No promise from these calls has come due yet. What is still open is under Guidance.</p>;
  }

  return (
    <div>
      <Tabs
        label="Filter promises"
        value={filter ?? "all"}
        onChange={(v) => setFilter(v === "all" ? null : v)}
        items={[{ value: "all", label: "All", count: shown.length }, ...statuses.map((s) => ({ value: s, label: STATUS[s]?.label ?? s, count: ledger.counts[s] }))]}
      />

      <ul className="mx-4 mt-3 overflow-hidden rounded-[12px] bg-card">
        {items.map((it) => (
          <li key={it.id} className="border-t border-line first:border-0">
            <button type="button" onClick={() => setOpen(it)} className="flex w-full items-start gap-3 px-4 py-3.5 text-left">
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[15px] font-semibold">{it.metric}</p>
                  <StatusChip status={it.status} />
                </div>
                <p className="tabular mt-0.5 text-[15px]">{target(it.target, it.unit)}</p>
                {it.judged_by === "numbers" && <GuidedVsActual it={it} />}
                <p className="mt-1.5 text-[13px] text-muted">
                  {it.judged_by === "numbers" && it.check ? it.check.basis : it.assessment.note}
                </p>
                <p className="mt-1.5 text-[12px] text-muted">
                  {it.source} call · {it.due ? `due ${monthYear(it.due)}` : it.timeframe || "no date given"} · {JUDGED[it.judged_by] ?? it.judged_by}
                </p>
              </div>
              <span className="mt-1 text-faint">
                <Icon.chevron />
              </span>
            </button>
          </li>
        ))}
      </ul>

      <p className="mx-4 mt-3 text-[12px] leading-relaxed text-muted">
        From {calls.length} earnings calls ({calls[0]} to {calls[calls.length - 1]}). Every quote was found in the transcript PDF
        {ledger.unverified_dropped > 0
          ? `; ${ledger.unverified_dropped} that could not be found were dropped.`
          : "; none had to be dropped."}{" "}
        Built {ago(ledger.built_at)}.
      </p>

      <Sheet open={!!open} onClose={() => setOpen(null)} title={open ? open.metric : ""}>
        {open && <ItemDetail it={open} />}
      </Sheet>
    </div>
  );
}

const HEADLINE: [string, string][] = [
  ["revenue_growth", "Revenue growth"],
  ["operating_margin", "Margins"],
  ["capex", "Capex"],
  ["other", "Other targets"],
];

/** What management has put a number on and is still open: pending or on track, grouped by headline metric. */
export function GuidanceView({ ledger }: { ledger: Ledger }) {
  const [open, setOpen] = useState<LedgerItem | null>(null);
  if (ledger.status !== "ok") return null;
  // The same target guided on several calls (DIXON's "IT hardware revenue" three times) shows once: the latest
  // call's words, with the earlier calls named.
  const said = (i: LedgerItem) => Date.parse(`1 ${i.source}`) || 0;
  const earlier = new Map<string, string[]>();
  const live = ledger.items
    .filter((i) => i.status === "pending" || i.status === "on_track")
    .sort((a, b) => said(b) - said(a))
    .filter((i) => {
      const key = i.metric.toLowerCase();
      if (!earlier.has(key)) {
        earlier.set(key, []);
        return true;
      }
      earlier.get(key)!.push(i.source);
      return false;
    });
  if (live.length === 0) {
    return <p className="mx-4 text-[14px] text-muted">No open numeric guidance in the last {ledger.transcripts.length} calls.</p>;
  }
  const newest = (a: LedgerItem, b: LedgerItem) => (b.due ?? "").localeCompare(a.due ?? "");
  return (
    <div className="space-y-3">
      {HEADLINE.map(([key, title]) => {
        const items = live.filter((i) => (HEADLINE.some(([k]) => k === i.metric_key) ? i.metric_key : "other") === key).sort(newest);
        if (items.length === 0) return null;
        return (
          <div key={key} className="mx-4 overflow-hidden rounded-[12px] bg-card">
            <p className="px-4 pt-3 text-[12px] font-semibold tracking-wide text-muted uppercase">{title}</p>
            <ul>
              {items.map((it) => (
                <li key={it.id} className="border-t border-line first:border-0">
                  <button type="button" onClick={() => setOpen(it)} className="flex w-full items-start gap-3 px-4 py-3 text-left">
                    <div className="min-w-0 flex-1">
                      <p className="text-[14px] text-muted">{it.metric}</p>
                      <p className="tabular text-[15px] font-semibold">{target(it.target, it.unit)}</p>
                      <p className="mt-1 text-[12px] text-muted">
                        {it.speaker ? `${it.speaker}, ` : ""}
                        {it.source} call · {it.due ? `by ${monthYear(it.due)}` : it.timeframe || "no date given"}
                        {(earlier.get(it.metric.toLowerCase())?.length ?? 0) > 0 && ` · earlier calls: ${earlier.get(it.metric.toLowerCase())!.join(", ")}`}
                      </p>
                    </div>
                    {it.status === "on_track" && <StatusChip status="on_track" />}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      <p className="mx-4 text-[12px] text-muted">Only targets management put a number on, each tied to its quote in the transcript. Tap one to read it.</p>
      <Sheet open={!!open} onClose={() => setOpen(null)} title={open ? open.metric : ""}>
        {open && <ItemDetail it={open} />}
      </Sheet>
    </div>
  );
}

function Quote({ text, who, source, page, url }: { text: string; who?: string | null; source: string; page: number | null | undefined; url?: string | null }) {
  return (
    <figure className="m-0 border-l-2 border-accent pl-4">
      <blockquote className="m-0 font-serif text-[17px] leading-relaxed text-ink">{plain(text)}</blockquote>
      <figcaption className="mt-2 text-xs text-muted">
        {who && `${who}, `}
        {source} call{page ? `, page ${page}` : ""}
        {url && (
          <>
            {" · "}
            <ExtLink href={pdfAt(url, page)}>Open PDF</ExtLink>
          </>
        )}
      </figcaption>
    </figure>
  );
}

function ItemDetail({ it }: { it: LedgerItem }) {
  const a = it.assessment;
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <p className="tabular text-[17px] font-semibold">{target(it.target, it.unit)}</p>
        <StatusChip status={it.status} />
      </div>
      <p className="-mt-3 text-[13px] text-muted">
        {it.timeframe ? `Timeframe as said: "${it.timeframe}"` : "No timeframe given"}
        {it.due && `. Read as due ${monthYear(it.due)}.`}
      </p>

      <section>
        <h3 className="mb-3 text-[13px] text-muted">What they said</h3>
        <Quote text={it.quote} who={it.speaker} source={it.source} page={it.page} url={it.source_url} />
        {(it.repeated_in?.length ?? 0) > 0 && <p className="mt-2 text-xs text-muted">Repeated on the {it.repeated_in!.join(", ")} calls.</p>}
      </section>

      <section>
        <h3 className="mb-3 text-[13px] text-muted">What happened</h3>
        {it.check && (
          <div className="mb-3 rounded-[10px] bg-base p-3 text-[14px]">
            <p>
              <span className="text-muted">Reported numbers: </span>
              {it.check.basis}
              {it.judged_by === "numbers" && <span className="text-muted"> (this decides the status)</span>}
            </p>
            {it.metric_key === "operating_margin" && (
              <p className="mt-1 text-xs text-muted">
                Our margin excludes other income, and companies often guide on their own definition, so for margins the status rests on what
                management reported on later calls.
              </p>
            )}
          </div>
        )}
        <p className="text-[14px]">{a.note}</p>
        {a.evidence_quote && a.evidence_source ? (
          <div className="mt-3">
            <Quote text={a.evidence_quote} source={a.evidence_source} page={a.evidence_page} url={a.evidence_url} />
          </div>
        ) : (
          !it.check && <p className="mt-2 text-xs text-muted">No later call addressed this directly.</p>
        )}
      </section>

      <p className="text-xs text-muted">
        {JUDGED[it.judged_by] ?? it.judged_by}. Quotes are matched word for word against the PDF before they are shown.
      </p>
    </div>
  );
}

// ---------- building a ledger for a company that has none ----------

interface JobPoll {
  jobs: Record<string, string>;
  has_ledger: boolean;
  flash_left_today: number;
}

export function LedgerBuilder({ ticker, onBuilt }: { ticker: string; onBuilt: () => void }) {
  const [state, setState] = useState<"idle" | "running" | "failed">("idle");
  const [msg, setMsg] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [left, setLeft] = useState<number | null>(null);
  const started = useRef(0);

  useEffect(() => {
    api
      .get<JobPoll>(`/api/research/${ticker}/jobs`)
      .then((j) => {
        setLeft(j.flash_left_today);
        if (j.jobs.ledger === "running") {
          started.current = Date.now();
          setState("running");
        }
      })
      .catch(() => {});
  }, [ticker]);

  useEffect(() => {
    if (state !== "running") return;
    const t = setInterval(async () => {
      setElapsed(Math.round((Date.now() - started.current) / 1000));
      try {
        const j = await api.get<JobPoll>(`/api/research/${ticker}/jobs`);
        const job = j.jobs.ledger ?? "";
        if (j.has_ledger && job !== "running") {
          clearInterval(t);
          onBuilt();
        } else if (job.startsWith("failed")) {
          clearInterval(t);
          setState("failed");
          setMsg(
            /quota/i.test(job)
              ? "The model's free daily quota is used up. It resets at 12:30 IST."
              : "The build failed. The transcripts may be unreadable; try again later.",
          );
        }
      } catch {
        // keep polling through a network blip
      }
    }, 3000);
    return () => clearInterval(t);
  }, [state, ticker, onBuilt]);

  const start = async () => {
    setMsg(null);
    try {
      await api.post(`/api/research/${ticker}/ledger`);
      started.current = Date.now();
      setElapsed(0);
      setState("running");
    } catch (e) {
      setState("failed");
      setMsg((e as ApiError).message);
    }
  };

  return (
    <div className="mx-4 rounded-[12px] bg-card p-4">
      {state === "running" ? (
        <>
          <p className="font-semibold">Reading the last four earnings calls</p>
          <p className="mt-1 text-[13px] text-muted">
            Finding every target management set, then checking each against later calls and reported numbers. Most companies take 16 to
            63 seconds; when the model is busy it has taken up to 7 minutes. {elapsed > 0 && `${elapsed} s so far.`}
          </p>
          <div className="mt-3 h-[3px] overflow-hidden rounded-full bg-base">
            <div className="h-full rounded-full bg-accent transition-[width] duration-1000" style={{ width: `${Math.min(95, (elapsed / 60) * 100)}%` }} />
          </div>
        </>
      ) : (
        <>
          <p className="font-semibold">No promise ledger yet</p>
          <p className="mt-1 text-[13px] text-muted">
            FINN reads the last four earnings call transcripts, lists what management promised, and checks what happened. One model call per
            company.
            {left != null && ` ${left} builds left today on the free tier.`}
          </p>
          {msg && <p className="mt-2 text-[13px] text-down">{msg}</p>}
          <Button onClick={start} disabled={left === 0} className="mt-3 w-full">
            {state === "failed" ? "Try again" : "Build the ledger"}
          </Button>
        </>
      )}
    </div>
  );
}
