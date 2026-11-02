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

  it("shows a bank's asset quality from its filing instead of debt to equity", () => {
    // HDFCBANK Q2 FY27 standalone filing: gross NPA 1.11%, net NPA 0.37%
    const q = { quarter: "Q2 FY27", gnpa_pct: 1.11, nnpa_pct: 0.37 };
    const r = research({ snapshot: { is_financial: true, ratios: {} }, bank_kpis: { quarters: [q] } });
    expect(balanceTile(r)).toMatchObject({ label: "Asset quality", value: "0.37%", verdict: "Clean", tone: "good" });
    expect(balanceTile(r).detail).toBe("Net NPA, gross 1.11%, Q2 FY27");
  });

  it("does not call a merger year a growth trend", () => {
    // HDFCBANK: revenue 1,70,754 (FY23) to 2,83,649 (FY24, the HDFC Ltd merger), then +18.6% and +3.6%
    const pts = (vals: number[]) => vals.map((value, i) => ({ period: `Mar 20${23 + i}`, value }));
    const r = research({
      snapshot: { is_financial: true, ratios: { "Stock P/E": 13.5 } },
      trajectory: {
        annual: { Revenue: pts([170754, 283649, 336367, 348615]), "Net profit": pts([46149, 65446, 73440, 79219]) },
        growth: { Revenue: { cagr_3y: 26.9, last_year: 3.6 }, "Net profit": { cagr_3y: 19.7, last_year: 7.9 } },
        quarterly: {},
      },
    });
    expect(growthTile(r)).toMatchObject({ value: "3.6%", verdict: "Slow" });
    expect(growthTile(r).detail).toContain("one-off +66% in Mar 2024");
    expect(valuationTile(r)).toMatchObject({ verdict: "Fair" }); // 13.5 / 7.9 = 1.7x, not 0.7x "Cheap"
  });

  it("judges the track record only once enough promises have come due", () => {
    const ledger = (st: string[]) => ({ status: "ok", items: st.map(promise) });
    expect(trackTile(research({ ledger: ledger(["pending", "delivered"]) }))).toMatchObject({ verdict: "Too early", tone: "neutral" });
    // DIXON on 2 Nov: two revised targets once read "0 of 2, Often misses"
    expect(trackTile(research({ ledger: ledger(["pending", "revised", "revised"]) }))).toMatchObject({ value: "0 of 0", verdict: "Too early" });
    // RELIANCE: revised, not mentioned again and unclear are left out, not counted as misses
    const rel = ["delivered", "revised", "unclear", "dropped", "revised", "dropped", "pending"];
    expect(trackTile(research({ ledger: ledger(rel) })).detail).toContain("4 revised or not mentioned again, not counted");
    // HAL: 2 kept of 8 checked
    const hal = ["delivered", "on_track", "missed", "missed", "missed", "missed", "missed", "missed", "pending"];
    expect(trackTile(research({ ledger: ledger(hal) }))).toMatchObject({ value: "2 of 8", verdict: "Often misses", tone: "weak" });
  });

  it("does not call a stock cheap for growth that just reversed", () => {
    // DIXON: P/E 48.6 on 86% a year of profit growth, but Q2 FY27 PAT fell 44.9% YoY
    const r = research({
      snapshot: { is_financial: false, ratios: { "Stock P/E": 48.6 } },
      trajectory: { growth: { "Net profit": { cagr_3y: 86.1 } }, quarterly: {} },
      results: { quarter: "Q2 FY27", rows: [{ label: "PAT", yoy: -44.9 }] },
    });
    expect(valuationTile(r)).toMatchObject({ verdict: "Growth in doubt", tone: "mixed" });
    expect(valuationTile(r).detail).toContain("PAT fell 44.9% YoY in Q2 FY27");
  });

  it("shows a lender's credit cost instead of a margin", () => {
    const r = research({
      snapshot: { is_financial: true, ratios: {} },
      results: { quarter: "Q2 FY27", rows: [{ label: "Pre-provision profit", value: 32872 }, { label: "Provisions", value: 4209 }] },
    });
    expect(marginTile(r)).toMatchObject({ label: "Credit cost", value: "12.8%", verdict: "Low", tone: "good" });
  });

  it("says rich when profit shrank, whatever the P/E", () => {
    const r = research({ trajectory: { growth: { "Net profit": { cagr_3y: -4 } }, quarterly: {} } });
    expect(valuationTile(r)).toMatchObject({ verdict: "Rich", detail: "Profit shrank over the last 3 years" });
  });
});
