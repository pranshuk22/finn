// Formatting only. Every number arrives computed by the backend; nothing here does finance arithmetic.

const IST = "Asia/Kolkata";

/** Indian digit grouping: 332861 -> 3,32,861 */
export function inr(x: number | null | undefined, digits = 0): string {
  if (x == null || Number.isNaN(x)) return "n/a";
  return x.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function signedPct(x: number | null | undefined, digits = 1): string {
  if (x == null) return "n/a";
  return `${x > 0 ? "+" : ""}${x.toFixed(digits)}%`;
}

export function tone(x: number | null | undefined): "up" | "down" | "flat" {
  if (x == null || x === 0) return "flat";
  return x > 0 ? "up" : "down";
}

function share(pct: number): string {
  return pct < 0.01 ? "under 0.01%" : pct < 1 ? `${pct.toFixed(2)}%` : `${pct.toFixed(1)}%`;
}

/** "Rs 56 crore, under 0.01% of yearly revenue"; with market cap first for raises and deals. */
export function scaleLine(amountCr: number, pctRevenue: number | null, pctMarketCap: number | null = null): string {
  const parts = [];
  if (pctMarketCap != null) parts.push(`${share(pctMarketCap)} of market cap`);
  if (pctRevenue != null) parts.push(`${share(pctRevenue)} of yearly revenue`);
  return `Rs ${inr(amountCr, amountCr < 10 ? 2 : 0)} crore${parts.length ? `, ${parts.join(", ")}` : ""}`;
}

/** Basis points with a sign: 140 -> "+140 bps" */
export function bps(x: number | null | undefined): string {
  if (x == null) return "n/a";
  return `${x > 0 ? "+" : ""}${x} bps`;
}

// The backend stores exchange timestamps as IST wall time without an offset ("2026-10-30T19:47:12"),
// and its own refresh times in UTC with "+00:00". Both are shown in IST.
function parse(ts: string): Date {
  return /[zZ]|[+-]\d\d:\d\d$/.test(ts) ? new Date(ts) : new Date(`${ts}+05:30`);
}

export function istTime(ts: string): string {
  return parse(ts).toLocaleTimeString("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false });
}

export function istDay(ts: string): string {
  return parse(ts).toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short" });
}

/** "Today 19:47", "Yesterday 08:55", "27 Oct 14:36" */
export function when(ts: string): string {
  const d = parse(ts);
  const key = (x: Date) => x.toLocaleDateString("en-CA", { timeZone: IST });
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  const t = istTime(ts);
  if (key(d) === key(today)) return `Today ${t}`;
  if (key(d) === key(yesterday)) return `Yesterday ${t}`;
  return `${istDay(ts)} ${t}`;
}

/** "12 min ago", "3 h ago", "2 days ago" */
export function ago(ts: string | number): string {
  const ms = Date.now() - (typeof ts === "number" ? ts : parse(ts).getTime());
  const min = Math.round(ms / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

/** ISO date "2026-06-30" -> "Jun 2026" */
export function monthYear(iso: string | null): string {
  if (!iso) return "open-ended";
  const d = new Date(`${iso}T00:00:00+05:30`);
  return d.toLocaleDateString("en-IN", { timeZone: IST, month: "short", year: "numeric" });
}

export function crore(x: number | null | undefined): string {
  if (x == null) return "n/a";
  if (Math.abs(x) >= 100_000) return `${(x / 100_000).toLocaleString("en-IN", { maximumFractionDigits: 2 })} lakh cr`;
  return `${inr(x)} cr`;
}

// PDF text keeps typographic ligatures ("speciﬁc"); quotes are shown with plain letters.
const LIGATURES: Record<string, string> = { "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\u01af": "ff" };
export function plain(text: string): string {
  return text.replace(/[\ufb00-\ufb04\u01af]/g, (c) => LIGATURES[c] ?? c);
}

/** ISO date "2026-06-30" -> "30 Jun 2026" */
export function dayMonthYear(iso: string): string {
  return new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" });
}
