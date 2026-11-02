import { oneOffJump, trackCounts, type Tile } from "./scorecard";
import type { ResultsCard, Research } from "./types";

// Plain-English readings for someone new to investing, turned on in Settings ("Explain the numbers"). Each line
// says what a number means and how to read this company's value, written in code from the same figures the
// scorecard uses. No model writes these, so they can never disagree with the number above them.

const r1 = (x: number) => `${+x.toFixed(1)}`;
const rs = (x: number) => (x > 0 && x < 1 ? `${Math.round(x * 100)} paise` : `Rs ${+x.toFixed(x < 10 ? 1 : 0)}`);

/** Years for something growing g% a year to double (exact, not the rule of 72). */
function doubling(g: number): string | null {
  if (g <= 0) return null;
  const years = Math.log(2) / Math.log(1 + g / 100);
  return years <= 30 ? `At that pace it doubles in about ${Math.round(years)} years.` : null;
}

export function explainTile(t: Tile, r: Research): string | null {
  const num = (s: string) => parseFloat(s.replace(/[^\d.-]/g, ""));
  const v = num(t.value);
  if (Number.isNaN(v)) return null;
  switch (t.label) {
    case "Growth": {
      const jump = oneOffJump(r, "Revenue");
      const what = jump ? "last year" : "each year, on average, over the last 3 years";
      return `Revenue is the money the company takes in from sales. It grew ${r1(v)}% ${what}. ${doubling(v) ?? "It is not growing."}`;
    }
    case "Margins":
      return `Of every Rs 100 of sales, about ${rs(v)} is left after running the business, before interest, depreciation and tax. A margin that rises means each sale earns more.`;
    case "Credit cost":
      return `Of every Rs 100 the bank earned before setting money aside for bad loans, ${rs(v)} went to that buffer this quarter. Lower means fewer loans are going wrong.`;
    case "Cash":
      return `Of every Rs 100 of operating profit over 3 years, about ${rs(v)} actually came in as cash. Profit that does not turn into cash can mean customers pay late or stock is piling up.`;
    case "Returns":
      return `For every Rs 100 of shareholders' money in the bank, it earned ${rs(v)} of profit in a year (return on equity). Banks are judged on this more than on cash flow.`;
    case "Asset quality":
      return `Of every Rs 100 lent, about ${rs(v)} is in loans that have stopped paying, after the money already set aside for them (net NPA). FINN reads Rs 0.5 or less as clean and above Rs 1.5 as stressed.`;
    case "Balance sheet":
      if (r.snapshot.is_financial) return "A lender borrows to lend, so its debt says little on its own; see the Lending and Balance sheet sections.";
      return `For every Rs 100 of shareholders' money, the company has borrowed ${rs(100 * v)}. Less debt means less risk when business slows, because interest must be paid either way.`;
    case "Track record": {
      const l = r.ledger;
      if (!l || l.status !== "ok") return "Build the promise ledger below to see whether management delivers what it promises on earnings calls.";
      const { judged, kept } = trackCounts(l.items);
      if (judged.length === 0) return "None of management's promises from recent earnings calls has been settled yet.";
      return `Management made promises on earnings calls; of the ${judged.length} that results have settled, ${kept} were kept. A management that keeps its word makes its next forecast easier to believe.`;
    }
    case "Valuation": {
      const pe = r.snapshot.ratios["Stock P/E"] as number | undefined;
      if (pe == null) return null;
      return `P/E ${r1(pe)}: buyers pay Rs ${r1(pe)} for every Rs 1 of the company's yearly profit. A high P/E only makes sense if profit keeps growing fast; the line above compares the two.`;
    }
  }
  return null;
}

const RESULT_MEANS: Record<string, string> = {
  Revenue: "money from sales",
  EBITDA: "profit from running the business, before interest, depreciation and tax, leaving out other income",
  "Pre-provision profit": "profit before setting money aside for bad loans",
  PBT: "profit before tax",
  PAT: "profit after tax: what is left for shareholders",
};

/** One line per headline figure, in the order of the card. */
export function explainResults(rc: ResultsCard): string[] {
  const out: string[] = [];
  const yoy = rc.has_year_ago;
  for (const row of rc.rows) {
    const means = RESULT_MEANS[row.label];
    const ch = yoy ? row.yoy : row.qoq;
    if (!means || row.value == null) continue;
    const dir = ch == null ? "" : `, ${ch >= 0 ? "up" : "down"} ${r1(Math.abs(ch))}% on ${yoy ? "the same quarter last year" : "the quarter before"}`;
    out.push(`${row.label}: ${means}. Rs ${Math.round(row.value).toLocaleString("en-IN")} crore this quarter${dir}.`);
  }
  if (yoy) out.push("Comparing with the same quarter a year earlier avoids seasonal swings, like festive-season sales.");
  return out;
}
