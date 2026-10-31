import { useState } from "react";
import { inr } from "../format";
import type { ResultsCard } from "../types";
import { Bps, Pct, ResultsGrid, ResultsNotes } from "./ui";

// A quarter at a glance: four figures, each with its year-on-year change and a five-quarter trend. The full
// table with QoQ, margins in bps and the EBITDA definition is one tap away.

function Trend({ values }: { values: (number | null)[] }) {
  const v = values.map((x) => x ?? 0);
  const max = Math.max(...v.map(Math.abs), 1);
  const neg = v.some((x) => x < 0);
  const H = 22;
  return (
    <span className="flex h-[22px] items-end gap-[2px]" aria-hidden>
      {v.map((x, i) => {
        const h = Math.max(2, (Math.abs(x) / max) * (neg ? H / 2 : H));
        const last = i === v.length - 1;
        return (
          <span
            key={i}
            className="w-[6px] rounded-t-[2px]"
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

export function ResultsTiles({ r }: { r: ResultsCard }) {
  const [table, setTable] = useState(false);
  const tiles = r.rows.filter((x) => x.label !== "Provisions").slice(0, 4);
  const yoy = r.has_year_ago;
  return (
    <div>
      <div className="grid grid-cols-2 gap-2">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-[10px] bg-base/60 px-3 py-2.5">
            <div className="flex items-start justify-between gap-2">
              <span className="text-[12px] text-muted">
                {t.label === "Pre-provision profit" ? "Pre-provision" : t.label}
                {t.derived && "*"}
              </span>
              {r.history.length > 1 && <Trend values={r.history.map((h) => (typeof h[t.label] === "number" ? (h[t.label] as number) : null))} />}
            </div>
            <p className="mt-1 text-[22px] leading-none font-semibold">
              {yoy ? <Pct value={t.yoy} /> : <Pct value={t.qoq} />}
              <span className="ml-1 text-[11px] font-normal text-muted">{yoy ? "YoY" : "QoQ"}</span>
            </p>
            <p className="tabular mt-1 text-[12px] text-muted">Rs {inr(t.value)} cr</p>
          </div>
        ))}
      </div>
      {r.margins?.length > 0 && (
        <p className="mt-2 flex flex-wrap gap-x-4 text-[13px] text-muted">
          {r.margins.map((m) => (
            <span key={m.label}>
              {m.label} <span className="tabular font-semibold text-ink">{m.now != null ? `${m.now.toFixed(1)}%` : "n/a"}</span>{" "}
              <Bps value={yoy ? m.yoy_bps : m.qoq_bps} />
            </span>
          ))}
        </p>
      )}
      {table && (
        <div className="mt-3 animate-fade">
          <ResultsGrid r={r} />
        </div>
      )}
      <ResultsNotes r={r} />
      <button type="button" onClick={() => setTable(!table)} className="mt-1 h-9 text-[13px] font-semibold text-accent-ink" aria-expanded={table}>
        {table ? "Hide full table" : "Full table with QoQ"}
      </button>
    </div>
  );
}
