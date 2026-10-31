import { useState } from "react";
import { dayMonthYear, inr, signedPct, when } from "../format";
import type { CashQuality, LedgerItem, PortfolioDay, PriceStory } from "../types";

// Charts beyond the one-series Bars. Same conventions: thin marks with a rounded data end on a zero baseline,
// hairline axes, labels only where the story is, and tap any mark to read it. Gains and losses use the validated
// --viz-up / --viz-down pair, and their direction is always carried by position too, never by colour alone.

/** Every portfolio stock's move on the latest session, sorted, as columns above and below zero. */
export function PortfolioStrip({ pd }: { pd: PortfolioDay }) {
  const [picked, setPicked] = useState<string | null>(null);
  const H = 56;
  const up = Math.max(0, ...pd.stocks.map((s) => s.move_pct));
  const down = Math.max(0, ...pd.stocks.map((s) => -s.move_pct));
  const span = up + down || 1;
  const zero = (up / span) * H;
  const sel = pd.stocks.find((s) => s.ticker === picked);
  return (
    <div className="mt-3">
      <div className="relative flex gap-[2px]" style={{ height: H }} role="group" aria-label="Each stock's move on the day, best to worst">
        <span className="absolute inset-x-0 h-px bg-line" style={{ top: zero }} aria-hidden />
        {pd.stocks.map((s) => {
          const h = Math.max(2, (Math.abs(s.move_pct) / span) * H);
          const pos = s.move_pct >= 0;
          const on = s.ticker === picked;
          return (
            <button
              key={s.ticker}
              type="button"
              onClick={() => setPicked(on ? null : s.ticker)}
              aria-label={`${s.ticker} ${signedPct(s.move_pct, 2)}`}
              aria-pressed={on}
              className="relative flex-1"
            >
              <span
                className="absolute inset-x-0 mx-auto max-w-[12px]"
                style={{
                  top: pos ? zero - h : zero,
                  height: h,
                  background: pos ? "var(--viz-up)" : "var(--viz-down)",
                  borderRadius: pos ? "4px 4px 0 0" : "0 0 4px 4px",
                  opacity: picked && !on ? 0.4 : 1,
                }}
              />
            </button>
          );
        })}
      </div>
      <p className="tabular mt-2 flex justify-between text-[12px] text-muted">
        {sel ? (
          <span className="text-ink">
            {sel.ticker} {signedPct(sel.move_pct, 2)}
          </span>
        ) : (
          <>
            <span>{pd.stocks[0].ticker}</span>
            <span>Tap a bar</span>
            <span>{pd.stocks[pd.stocks.length - 1].ticker}</span>
          </>
        )}
      </p>
    </div>
  );
}

// Markers must stand off the line, which wears the accent: amber for Needs you, ink for Worth knowing.
const MARK: Record<string, string> = { needs_you: "var(--needs-you)", worth_knowing: "var(--text)" };

/** Daily closes with the filings that mattered marked on the session they could first move the price. */
export function PriceChart({ price }: { price: PriceStory }) {
  const s = price.series;
  const [i, setI] = useState(s.length - 1);
  const W = 340;
  const H = 120;
  const PAD = 8;
  const lo = Math.min(...s.map((p) => p.close));
  const hi = Math.max(...s.map((p) => p.close));
  const x = (k: number) => 6 + (k / (s.length - 1)) * (W - 12); // inset so an end marker is not clipped
  const y = (v: number) => PAD + (1 - (v - lo) / (hi - lo || 1)) * (H - 2 * PAD);
  const line = s.map((p, k) => `${k ? "L" : "M"}${x(k).toFixed(1)},${y(p.close).toFixed(1)}`).join(" ");
  const at = new Map(price.events.map((e) => [e.date, e]));
  const index = new Map(s.map((p, k) => [p.date, k]));
  const cur = s[i];
  const change = 100 * (cur.close / s[0].close - 1);
  const event = at.get(cur.date);

  const pick = (clientX: number, el: SVGSVGElement) => {
    const r = el.getBoundingClientRect();
    const k = Math.round((((clientX - r.left) / r.width) * W - 6) / (W - 12) * (s.length - 1));
    const clamped = Math.max(0, Math.min(s.length - 1, k));
    // snap to a filing within two sessions, so a marker is easy to hit with a finger
    const near = price.events.map((e) => index.get(e.date)!).find((e) => Math.abs(e - clamped) <= 2);
    setI(near ?? clamped);
  };

  return (
    <figure className="mt-4">
      <figcaption>
        <p className="text-[24px] font-semibold">Rs {inr(cur.close, 2)}</p>
        <p className="tabular text-[13px] text-muted">
          <span className={change >= 0 ? "text-up" : "text-down"}>{signedPct(change)}</span> since {dayMonthYear(s[0].date)}
          {i < s.length - 1 ? `, close on ${dayMonthYear(cur.date)}` : `, last close ${dayMonthYear(cur.date)}`}
        </p>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H + 16}`}
        className="mt-2 block w-full touch-pan-y"
        role="img"
        aria-label={`Close from ${dayMonthYear(s[0].date)} to ${dayMonthYear(s[s.length - 1].date)}, ${price.events.length} days with filings marked`}
        onPointerMove={(e) => e.pointerType === "mouse" && pick(e.clientX, e.currentTarget)}
        onPointerDown={(e) => pick(e.clientX, e.currentTarget)}
      >
        <path d={`${line} L${x(s.length - 1)},${H} L${x(0)},${H} Z`} fill="var(--accent)" opacity="0.1" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <line x1={x(i)} x2={x(i)} y1="0" y2={H} stroke="var(--text-faint)" strokeWidth="1" />
        {price.events.map((e) => {
          const k = index.get(e.date)!;
          const top = e.filings.some((f) => f.priority === "needs_you") ? "needs_you" : "worth_knowing";
          return <circle key={e.date} cx={x(k)} cy={y(s[k].close)} r="4.5" fill={MARK[top]} stroke="var(--surface)" strokeWidth="2" />;
        })}
        {!event && <circle cx={x(i)} cy={y(cur.close)} r="4" fill="var(--text)" stroke="var(--surface)" strokeWidth="2" />}
        <text x="0" y={H + 13} fontSize="11" fill="var(--text-muted)">
          {dayMonthYear(s[0].date)}
        </text>
        <text x={W} y={H + 13} fontSize="11" fill="var(--text-muted)" textAnchor="end">
          {dayMonthYear(s[s.length - 1].date)}
        </text>
      </svg>
      {event ? (
        <ul className="mt-2 space-y-1.5 text-[13px]">
          {event.filings.map((f) => (
            <li key={f.at + f.summary} className="flex gap-2">
              <span className="mt-[7px] h-2 w-2 shrink-0 rounded-full" style={{ background: MARK[f.priority] }} />
              <span className="line-clamp-3">
                <span className="font-semibold">{f.category_label}</span>
                <span className="text-muted"> · filed {when(f.at)}. </span>
                {f.summary}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 flex items-center gap-4 text-[12px] text-muted">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: MARK.needs_you }} /> Needs you
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: MARK.worth_knowing }} /> Worth knowing
          </span>
          <span>Tap a dot to see the filing</span>
        </p>
      )}
    </figure>
  );
}

function unitFmt(v: number, unit: string): string {
  if (unit === "percent") return `${+v.toFixed(1)}%`;
  if (unit === "rs_crore") return `Rs ${inr(v)} cr`;
  if (unit === "bps") return `${v} bps`;
  return `${+v.toFixed(1)}`;
}

/** Guided range as a band, the reported figure as a dot: a near miss and a wide miss look different. */
export function GuidedVsActual({ it }: { it: LedgerItem }) {
  const lo = it.target_low;
  const hi = it.target_high ?? lo;
  const actual = it.check?.actual;
  if (lo == null || hi == null || actual == null) return null;
  const W = 300;
  const min = Math.min(lo, actual);
  const max = Math.max(hi, actual);
  const pad = (max - min || Math.abs(max) || 1) * 0.25;
  const sx = (v: number) => 12 + ((v - (min - pad)) / (max - min + 2 * pad)) * (W - 24);
  const ok = it.status === "delivered" || it.status === "on_track";
  const range = lo === hi ? unitFmt(lo, it.unit) : `${unitFmt(lo, it.unit)} to ${unitFmt(hi, it.unit)}`;
  return (
    <svg viewBox={`0 0 ${W} 40`} className="mt-2 block w-full" role="img" aria-label={`Guided ${range}, reported ${unitFmt(actual, it.unit)}`}>
      <line x1="0" x2={W} y1="20" y2="20" stroke="var(--line)" strokeWidth="1" />
      <rect x={sx(lo) - (lo === hi ? 2 : 0)} y="15" width={Math.max(4, sx(hi) - sx(lo))} height="10" rx="4" fill="var(--accent)" opacity="0.45" />
      <circle cx={sx(actual)} cy="20" r="5" fill={ok ? "var(--viz-up)" : "var(--viz-down)"} stroke="var(--surface)" strokeWidth="2" />
      <text x={sx(actual)} y="9" fontSize="11" textAnchor="middle" fill="var(--text)">
        {unitFmt(actual, it.unit)} reported
      </text>
      <text x={(sx(lo) + sx(hi)) / 2} y="38" fontSize="11" textAnchor="middle" fill="var(--text-muted)">
        guided {range}
      </text>
    </svg>
  );
}

/** Operating cash flow as columns, operating profit as a tick on each: a column short of its tick is profit not
 * yet turned into cash. One unit, one axis. */
export function CashVsProfit({ years }: { years: CashQuality["years"] }) {
  const data = years.filter((y) => y.cfo != null && y.operating_profit != null);
  const [picked, setPicked] = useState(data.length - 1);
  if (data.length === 0) return null;
  const W = 320;
  const H = 100;
  const max = Math.max(0, ...data.flatMap((d) => [d.cfo!, d.operating_profit!]));
  const min = Math.min(0, ...data.flatMap((d) => [d.cfo!, d.operating_profit!]));
  const span = max - min || 1;
  const yv = (v: number) => ((max - v) / span) * H;
  const zero = yv(0);
  const slot = W / data.length;
  const bar = Math.min(24, slot - 10);
  const sel = data[Math.min(picked, data.length - 1)];
  return (
    <figure>
      <figcaption className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="text-muted">Cash from operations vs operating profit, Rs crore</span>
      </figcaption>
      <p className="tabular mt-1 text-[13px]">
        <span className="text-muted">{sel.period}: </span>
        <span className="font-semibold text-ink">{inr(sel.cfo)}</span>
        <span className="text-muted"> cash vs </span>
        <span className="font-semibold text-ink">{inr(sel.operating_profit)}</span>
        <span className="text-muted"> profit ({sel.cfo_to_ebitda ?? "n/a"}%)</span>
      </p>
      <svg viewBox={`0 0 ${W} ${H + 18}`} className="mt-2 block w-full" role="img" aria-label={data.map((d) => `${d.period}: cash ${inr(d.cfo)}, profit ${inr(d.operating_profit)}`).join("; ")}>
        <line x1="0" x2={W} y1={zero} y2={zero} stroke="var(--line)" strokeWidth="1" />
        {data.map((d, k) => {
          const x = k * slot + (slot - bar) / 2;
          const top = yv(Math.max(0, d.cfo!));
          const h = Math.max(1, Math.abs(yv(d.cfo!) - zero));
          const r = Math.min(4, h / 2);
          const pos = d.cfo! >= 0;
          const path = pos
            ? `M${x},${zero} V${top + r} Q${x},${top} ${x + r},${top} H${x + bar - r} Q${x + bar},${top} ${x + bar},${top + r} V${zero} Z`
            : `M${x},${zero} V${zero + h - r} Q${x},${zero + h} ${x + r},${zero + h} H${x + bar - r} Q${x + bar},${zero + h} ${x + bar},${zero + h - r} V${zero} Z`;
          const on = k === Math.min(picked, data.length - 1);
          return (
            <g key={d.period} onClick={() => setPicked(k)} className="cursor-pointer">
              <rect x={k * slot} y="0" width={slot} height={H + 18} fill="transparent" />
              <path d={path} fill="var(--accent)" opacity={on ? 1 : 0.55} />
              <line x1={x - 4} x2={x + bar + 4} y1={yv(d.operating_profit!)} y2={yv(d.operating_profit!)} stroke="var(--text)" strokeWidth="2" strokeLinecap="round" />
              {(k === 0 || k === data.length - 1) && (
                <text x={k * slot + slot / 2} y={H + 14} textAnchor="middle" fontSize="11" fill="var(--text-muted)">
                  {d.period.replace(/^(\w{3}) 20(\d\d)$/, "$1 $2")}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <p className="mt-1 flex gap-4 text-[12px] text-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[2px] bg-accent" /> Cash from operations
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-[2px] w-3 rounded-full bg-ink" /> Operating profit
        </span>
      </p>
    </figure>
  );
}
