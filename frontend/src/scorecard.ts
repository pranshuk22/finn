import type { Research } from "./types";

// The six tiles at the top of a company page. Each verdict is a fixed rule on numbers FINN already shows below,
// so a reader can check it; the thresholds are listed in Help. No model is involved.

export type Tone = "good" | "mixed" | "weak" | "neutral";

export interface Tile {
  key: string;
  label: string;
  value: string;
  verdict: string;
  detail: string;
  tone: Tone;
  section: string; // the section the tile opens
}

const n1 = (x: number) => `${+x.toFixed(1)}`;

/** A single year in the 3-year window that grew 40% or more while last year grew less than half the 3-year rate:
 * a merger or a one-off, not a trend. HDFCBANK's revenue rose 66% in FY24 (the HDFC Ltd merger) and 3.6% in FY26,
 * so "26.9% a year, Strong" overstated it (review, 3 Nov). */
export function oneOffJump(r: Research, item: string): { period: string; pct: number; lastYear: number } | null {
  const pts = (r.trajectory?.annual?.[item] ?? []).filter((p) => p.value != null && p.value > 0).slice(-4);
  const g = r.trajectory?.growth[item];
  if (pts.length < 4 || g?.cagr_3y == null || g.last_year == null || g.last_year >= g.cagr_3y / 2) return null;
  let best: { period: string; pct: number } | null = null;
  for (let i = 1; i < pts.length; i++) {
    const pct = (100 * (pts[i].value! - pts[i - 1].value!)) / pts[i - 1].value!;
    if (pct >= 40 && (!best || pct > best.pct)) best = { period: pts[i].period, pct };
  }
  return best && { ...best, lastYear: g.last_year };
}

export function growthTile(r: Research): Tile {
  const g = r.trajectory?.growth["Revenue"]?.cagr_3y;
  const base = { key: "growth", label: "Growth", section: "trajectory" };
  if (g == null) return { ...base, value: "n/a", verdict: "No history", detail: "Not enough years of revenue", tone: "neutral" };
  const jump = oneOffJump(r, "Revenue");
  if (jump) {
    const y = jump.lastYear;
    const [verdict, tone]: [string, Tone] = y >= 15 ? ["Strong", "good"] : y >= 8 ? ["Steady", "good"] : y >= 0 ? ["Slow", "mixed"] : ["Shrinking", "weak"];
    return { ...base, value: `${n1(y)}%`, verdict, detail: `Revenue last year. The 3-year ${n1(g)}% a year includes a one-off +${Math.round(jump.pct)}% in ${jump.period}`, tone };
  }
  const [verdict, tone]: [string, Tone] = g >= 15 ? ["Strong", "good"] : g >= 8 ? ["Steady", "good"] : g >= 0 ? ["Slow", "mixed"] : ["Shrinking", "weak"];
  return { ...base, value: `${n1(g)}%`, verdict, detail: "Revenue a year, last 3 years", tone };
}

const row = (r: Research, label: string) => r.results?.rows.find((x) => x.label === label);

export function marginTile(r: Research): Tile {
  if (r.snapshot.is_financial) return creditCostTile(r);
  const q = (r.trajectory?.quarterly["Margin %"] ?? []).filter((p) => p.value != null);
  const base = { key: "margins", label: "Margins", section: "trajectory" };
  if (q.length < 5) return { ...base, value: "n/a", verdict: "No history", detail: "Fewer than five quarters", tone: "neutral" };
  const now = q[q.length - 1].value!;
  const change = now - q[q.length - 5].value!;
  const [verdict, tone]: [string, Tone] = change >= 1 ? ["Expanding", "good"] : change <= -1 ? ["Slipping", "weak"] : ["Stable", "neutral"];
  return { ...base, value: `${n1(now)}%`, verdict, detail: `${change >= 0 ? "+" : ""}${n1(change)} pts vs a year ago`, tone };
}

// A lender has no operating margin worth the name (Screener's "financing margin" for HDFCBANK ran -2% to -17%).
// What eats a lender's profit is bad loans, so the tile shows provisions against pre-provision profit.
export function creditCostTile(r: Research): Tile {
  const base = { key: "margins", label: "Credit cost", section: "results" };
  const prov = row(r, "Provisions");
  const ppop = row(r, "Pre-provision profit");
  if (!prov?.value || !ppop?.value) return { ...base, value: "n/a", verdict: "No data", detail: "Provisions against pre-provision profit", tone: "neutral" };
  const share = (100 * prov.value) / ppop.value;
  const [verdict, tone]: [string, Tone] = share <= 15 ? ["Low", "good"] : share <= 30 ? ["Moderate", "mixed"] : ["High", "weak"];
  return { ...base, value: `${n1(share)}%`, verdict, detail: `Of pre-provision profit went to provisions, ${r.results!.quarter}`, tone };
}

export function cashTile(r: Research): Tile {
  if (r.snapshot.is_financial) {
    const roe = r.snapshot.ratios["ROE"] as number | undefined;
    const base = { key: "cash", label: "Returns", section: "cash" };
    if (roe == null) return { ...base, value: "n/a", verdict: "No data", detail: "Return on equity", tone: "neutral" };
    const [verdict, tone]: [string, Tone] = roe >= 15 ? ["Strong", "good"] : roe >= 10 ? ["Fair", "mixed"] : ["Weak", "weak"];
    return { ...base, value: `${n1(roe)}%`, verdict, detail: "Return on equity (cash flow does not apply to lenders)", tone };
  }
  const c = r.cash_quality?.cfo_to_ebitda_3y;
  const base = { key: "cash", label: "Cash", section: "cash" };
  if (c == null) return { ...base, value: "n/a", verdict: "No data", detail: "Cash conversion", tone: "neutral" };
  const [verdict, tone]: [string, Tone] = c >= 90 ? ["Strong", "good"] : c >= 70 ? ["Fair", "mixed"] : ["Weak", "weak"];
  return { ...base, value: `${Math.round(c)}%`, verdict, detail: "Of operating profit came in as cash, 3 years", tone };
}

// For a lender the balance sheet question is how many of its loans have gone bad, as filed.
export function assetQualityTile(r: Research): Tile {
  const base = { key: "balance", label: "Asset quality", section: "lending" };
  const q = r.bank_kpis?.quarters.at(-1);
  if (q?.nnpa_pct == null) return { ...base, value: "n/a", verdict: "No data", detail: "Net NPA from the bank's filing", tone: "neutral" };
  const [verdict, tone]: [string, Tone] = q.nnpa_pct <= 0.5 ? ["Clean", "good"] : q.nnpa_pct <= 1.5 ? ["Watch", "mixed"] : ["Stressed", "weak"];
  const gross = q.gnpa_pct != null ? `, gross ${q.gnpa_pct}%` : "";
  return { ...base, value: `${q.nnpa_pct}%`, verdict, detail: `Net NPA${gross}, ${q.quarter}`, tone };
}

export function balanceTile(r: Research): Tile {
  if (r.bank_kpis?.quarters.length) return assetQualityTile(r);
  const bs = r.balance_sheet;
  const y = bs?.years[bs.years.length - 1];
  const base = { key: "balance", label: "Balance sheet", section: "balance" };
  if (!y) return { ...base, value: "n/a", verdict: "No data", detail: "", tone: "neutral" };
  if (bs!.is_financial) {
    const eq = y.mix.equity;
    return { ...base, value: eq != null ? `${n1(eq)}%` : "n/a", verdict: "Lender", detail: "Equity's share of funding; see deposits and borrowings", tone: "neutral" };
  }
  const de = y.debt_to_equity;
  if (de == null) return { ...base, value: "n/a", verdict: "No data", detail: "", tone: "neutral" };
  const [verdict, tone]: [string, Tone] = de <= 0.3 ? ["Light debt", "good"] : de <= 1 ? ["Moderate debt", "mixed"] : ["Heavy debt", "weak"];
  const cover = bs!.interest_coverage ? `, interest covered ${bs!.interest_coverage.value}x` : "";
  return { ...base, value: `${de}`, verdict, detail: `Debt to equity${cover}`, tone };
}

/** One count for the scorecard tile and the Narrative vs numbers section, so they never disagree (HDFCBANK once
 * read "2 of 2" on the tile and "2 of 5" in the section). Settled means delivered, missed, on or off track. */
export function trackCounts(items: { status: string }[]) {
  const judged = items.filter((i) => ["delivered", "on_track", "missed", "off_track"].includes(i.status));
  const kept = judged.filter((i) => i.status === "delivered" || i.status === "on_track").length;
  const aside = items.filter((i) => i.status === "revised" || i.status === "dropped").length;
  const open = items.filter((i) => ["unclear", "awaiting"].includes(i.status)).length;
  return { judged, kept, aside, open };
}

export function trackTile(r: Research): Tile {
  const base = { key: "track", label: "Track record", section: "ledger" };
  const l = r.ledger;
  if (!l || l.status !== "ok") return { ...base, value: "n/a", verdict: "Not built", detail: "Build the promise ledger below", tone: "neutral" };
  // Only promises a later result settled count. Revised, not mentioned again and unclear are not misses: DIXON
  // once read "0 of 2, Often misses" from two revised targets.
  const { judged, kept, aside } = trackCounts(l.items);
  const note = aside ? `; ${aside} revised or not mentioned again, not counted` : "";
  if (judged.length < 3) return { ...base, value: `${kept} of ${judged.length}`, verdict: "Too early", detail: `Fewer than 3 promises checked so far${note}`, tone: "neutral" };
  const share = kept / judged.length;
  const [verdict, tone]: [string, Tone] = share >= 0.6 ? ["Reliable", "good"] : share >= 0.4 ? ["Mixed", "mixed"] : ["Often misses", "weak"];
  return { ...base, value: `${kept} of ${judged.length}`, verdict, detail: `Promises kept, of those checked against results${note}`, tone };
}

export function valuationTile(r: Research): Tile {
  const pe = r.snapshot.ratios["Stock P/E"] as number | undefined;
  const jump = oneOffJump(r, "Net profit");
  const g = jump ? jump.lastYear : r.trajectory?.growth["Net profit"]?.cagr_3y;
  const basis = jump ? `last year's profit growth (the 3 years include a one-off +${Math.round(jump.pct)}% in ${jump.period})` : "its 3-year profit growth";
  const base = { key: "valuation", label: "Valuation", section: "trajectory" };
  if (pe == null) return { ...base, value: "n/a", verdict: "No P/E", detail: "", tone: "neutral" };
  if (g == null) return { ...base, value: `P/E ${n1(pe)}`, verdict: "No history", detail: "No profit growth to compare with", tone: "neutral" };
  if (g <= 0) return { ...base, value: `P/E ${n1(pe)}`, verdict: "Rich", detail: jump ? "Profit shrank last year" : "Profit shrank over the last 3 years", tone: "weak" };
  const peg = pe / g;
  // Past growth only justifies a P/E while it lasts: DIXON read "Cheap for its growth" the week its PAT fell 45%.
  const pat = row(r, "PAT");
  if (peg <= 2 && pat?.yoy != null && pat.yoy <= -20)
    return { ...base, value: `P/E ${n1(pe)}`, verdict: "Growth in doubt", detail: `${n1(peg)}x ${basis}, but PAT fell ${n1(-pat.yoy)}% YoY in ${r.results!.quarter}`, tone: "mixed" };
  const [verdict, tone]: [string, Tone] = peg <= 1 ? ["Cheap for its growth", "good"] : peg <= 2 ? ["Fair", "mixed"] : ["Rich", "weak"];
  return { ...base, value: `P/E ${n1(pe)}`, verdict, detail: `${n1(peg)}x ${basis}`, tone };
}

export function scorecard(r: Research): Tile[] {
  return [growthTile(r), marginTile(r), cashTile(r), balanceTile(r), trackTile(r), valuationTile(r)];
}
