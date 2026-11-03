import { useState } from "react";
import { explainResults } from "../explain";
import { inr } from "../format";
import { useSettings } from "../settings";
import type { ResultsCard } from "../types";
import { Icon, keyNote, Pct, ResultsGrid, ResultsNotes } from "./ui";

// A quarter at a glance: four figures in one row, each with its year-on-year change and a five-quarter trend.
// The full table with QoQ, margins in bps and the EBITDA definition is one tap away.

function Trend({ values }: { values: (number | null)[] }) {
  const v = values.map((x) => x ?? 0);
  const max = Math.max(...v.map(Math.abs), 1);
  const neg = v.some((x) => x < 0);
  const H = 16;
  return (
    <span className="flex h-4 items-end gap-[2px]" aria-hidden>
      {v.map((x, i) => {
        const h = Math.max(2, (Math.abs(x) / max) * (neg ? H / 2 : H));
        const last = i === v.length - 1;
        return (
          <span
            key={i}
            className="w-[5px] rounded-t-[1px]"
            style={{
              height: h,
              marginBottom: neg ? (x < 0 ? H / 2 - h : H / 2) : 0,
              background: last ? "var(--accent-text)" : "var(--accent)",
              opacity: last ? 1 : 0.45,
            }}
          />
        );
      })}
    </span>
  );
}

const SHORT: Record<string, string> = { "Pre-provision profit": "PPOP" };

export function ResultsTiles({ r }: { r: ResultsCard }) {
  const [open, setOpen] = useState(false);
  const key = keyNote(r);
  const tiles = r.rows.filter((x) => x.label !== "Provisions").slice(0, 4);
  const yoy = r.has_year_ago;
  const { explain } = useSettings();
  return (
    <div>
      <p className="mb-1 flex justify-between text-[11px] text-muted">
        <span>{yoy ? "Change on a year earlier" : "Change on the quarter before"}</span>
        <span>Rs crore, last {r.history.length} quarters</span>
      </p>
      <div className="grid grid-cols-4 border-y border-line">
        {tiles.map((t, i) => (
          <div key={t.label} className={`min-w-0 py-2.5 ${i ? "border-l border-line pl-2.5" : "pr-1"}`}>
            <span className="block truncate text-[11px] text-muted">
              {SHORT[t.label] ?? t.label}
              {t.derived && "*"}
            </span>
            <span className="mt-0.5 block text-[16px] leading-tight font-semibold">
              <Pct value={yoy ? t.yoy : t.qoq} />
            </span>
            <span className="tabular block truncate text-[11px] text-muted">{inr(t.value)}</span>
            {r.history.length > 1 && (
              <span className="mt-1.5 block">
                <Trend values={r.history.map((h) => (typeof h[t.label] === "number" ? (h[t.label] as number) : null))} />
              </span>
            )}
          </div>
        ))}
      </div>
      {explain && (
        <ul className="mt-2 space-y-1 text-[12px] leading-snug">
          {explainResults(r).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {/* Up front: the one note that changes the reading most. Margins, the QoQ table, other notes and the source wait
          behind Details, so the card reads at a glance. */}
      <ResultsNotes r={r} only={key} />
      {/* Details is a row of its own with a chevron, and opens into an inset box, so it is clear what it holds and
          where the card carries on (owner, 3 Nov: the expanded part blended into the card). */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="mt-3 flex h-10 w-full items-center justify-between rounded-[10px] bg-base px-3 text-[13px] font-semibold text-accent-ink"
      >
        <span>{open ? "Hide details" : "Details"}</span>
        <span className="flex items-center gap-2 font-normal text-muted">
          {!open && "QoQ table, margins, source"}
          <span className={`transition-transform ${open ? "-rotate-90" : "rotate-90"}`}>
            <Icon.chevron />
          </span>
        </span>
      </button>
      {open && (
        <div className="mt-2 animate-fade rounded-[10px] border border-line px-3 pt-1 pb-3">
          <ResultsGrid r={r} />
          <ResultsNotes r={r} skip={key} />
        </div>
      )}
    </div>
  );
}
