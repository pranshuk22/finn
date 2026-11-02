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

export function growthTile(r: Research): Tile {
  const g = r.trajectory?.growth["Revenue"]?.cagr_3y;
  const base = { key: "growth", label: "Growth", section: "trajectory" };
  if (g == null) return { ...base, value: "n/a", verdict: "No history", detail: "Not enough years of revenue", tone: "neutral" };
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

export function balanceTile(r: Research): Tile {
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

export function trackTile(r: Research): Tile {
  const base = { key: "track", label: "Track record", section: "ledger" };
  const l = r.ledger;
  if (!l || l.status !== "ok") return { ...base, value: "n/a", verdict: "Not built", detail: "Build the promise ledger below", tone: "neutral" };
  // Only promises a later result settled count. Revised, not mentioned again and unclear are not misses: DIXON
  // once read "0 of 2, Often misses" from two revised targets.
  const judged = l.items.filter((i) => ["delivered", "on_track", "missed", "off_track"].includes(i.status));
  const kept = judged.filter((i) => i.status === "delivered" || i.status === "on_track").length;
  const aside = l.items.filter((i) => i.status === "revised" || i.status === "dropped").length;
  const note = aside ? `; ${aside} revised or not mentioned again, not counted` : "";
  if (judged.length < 3) return { ...base, value: `${kept} of ${judged.length}`, verdict: "Too early", detail: `Fewer than 3 promises checked so far${note}`, tone: "neutral" };
  const share = kept / judged.length;
  const [verdict, tone]: [string, Tone] = share >= 0.6 ? ["Reliable", "good"] : share >= 0.4 ? ["Mixed", "mixed"] : ["Often misses", "weak"];
  return { ...base, value: `${kept} of ${judged.length}`, verdict, detail: `Promises kept, of those checked against results${note}`, tone };
}

export function valuationTile(r: Research): Tile {
  const pe = r.snapshot.ratios["Stock P/E"] as number | undefined;
  const g = r.trajectory?.growth["Net profit"]?.cagr_3y;
  const base = { key: "valuation", label: "Valuation", section: "trajectory" };
  if (pe == null) return { ...base, value: "n/a", verdict: "No P/E", detail: "", tone: "neutral" };
  if (g == null) return { ...base, value: `P/E ${n1(pe)}`, verdict: "No history", detail: "No profit growth to compare with", tone: "neutral" };
  if (g <= 0) return { ...base, value: `P/E ${n1(pe)}`, verdict: "Rich", detail: "Profit shrank over the last 3 years", tone: "weak" };
  const peg = pe / g;
  // Past growth only justifies a P/E while it lasts: DIXON read "Cheap for its growth" the week its PAT fell 45%.
  const pat = row(r, "PAT");
  if (peg <= 2 && pat?.yoy != null && pat.yoy <= -20)
    return { ...base, value: `P/E ${n1(pe)}`, verdict: "Growth in doubt", detail: `${n1(peg)}x its 3-year profit growth, but PAT fell ${n1(-pat.yoy)}% YoY in ${r.results!.quarter}`, tone: "mixed" };
  const [verdict, tone]: [string, Tone] = peg <= 1 ? ["Cheap for its growth", "good"] : peg <= 2 ? ["Fair", "mixed"] : ["Rich", "weak"];
  return { ...base, value: `P/E ${n1(pe)}`, verdict, detail: `${n1(peg)}x its 3-year profit growth`, tone };
}

export function scorecard(r: Research): Tile[] {
  return [growthTile(r), marginTile(r), cashTile(r), balanceTile(r), trackTile(r), valuationTile(r)];
}
