import { describe, expect, it } from "vitest";
import { balanceTile, cashTile, growthTile, marginTile, trackTile, valuationTile } from "./scorecard";
import type { LedgerItem, Research } from "./types";

// Only the fields each rule reads; the rest of a Research payload does not matter here.
function research(over: Partial<Record<string, unknown>> = {}): Research {
  return {
    snapshot: { is_financial: false, ratios: { "Stock P/E": 19.2, ROE: 18.9 } },
    trajectory: {
      growth: { Revenue: { cagr_3y: 6.4 }, "Net profit": { cagr_3y: 8.9 } },
      quarterly: { "Margin %": [17, 16, 16, 15, 15, 16, 17].map((v, i) => ({ period: `Q${i}`, value: v })) },
    },
    cash_quality: { cfo_to_ebitda_3y: 104 },
    balance_sheet: { is_financial: false, years: [{ debt_to_equity: 0.43, mix: { equity: 41.5 } }], interest_coverage: { period: "Mar 2026", value: 5.6 } },
    ledger: null,
    ...over,
  } as unknown as Research;
}

const promise = (status: string) => ({ status }) as LedgerItem;

describe("scorecard rules", () => {
  it("reads RELIANCE's numbers as the rules say", () => {
    const r = research();
    expect(growthTile(r)).toMatchObject({ value: "6.4%", verdict: "Slow", tone: "mixed" });
    expect(marginTile(r)).toMatchObject({ value: "17%", verdict: "Expanding", tone: "good" }); // 15% to 17%
    expect(cashTile(r)).toMatchObject({ value: "104%", verdict: "Strong" });
    expect(balanceTile(r)).toMatchObject({ value: "0.43", verdict: "Moderate debt", tone: "mixed" });
    expect(balanceTile(r).detail).toContain("interest covered 5.6x");
    expect(valuationTile(r)).toMatchObject({ value: "P/E 19.2", verdict: "Rich", tone: "weak" }); // 19.2 / 8.9 = 2.2x
  });

  it("uses return on equity for a lender, where cash flow says little", () => {
    const r = research({ snapshot: { is_financial: true, ratios: { ROE: 14.2 } } });
    expect(cashTile(r)).toMatchObject({ label: "Returns", value: "14.2%", verdict: "Fair" });
  });

  it("judges the track record only once enough promises have come due", () => {
    const ledger = (st: string[]) => ({ status: "ok", items: st.map(promise) });
    expect(trackTile(research({ ledger: ledger(["pending", "delivered"]) }))).toMatchObject({ verdict: "Too early", tone: "neutral" });
    // HAL: 2 kept of 8 checked
    const hal = ["delivered", "on_track", "missed", "missed", "missed", "missed", "missed", "missed", "pending"];
    expect(trackTile(research({ ledger: ledger(hal) }))).toMatchObject({ value: "2 of 8", verdict: "Often misses", tone: "weak" });
  });

  it("says rich when profit shrank, whatever the P/E", () => {
    const r = research({ trajectory: { growth: { "Net profit": { cagr_3y: -4 } }, quarterly: {} } });
    expect(valuationTile(r)).toMatchObject({ verdict: "Rich", detail: "Profit shrank over the last 3 years" });
  });
});
