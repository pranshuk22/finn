import { describe, expect, it } from "vitest";
import { explainResults, explainTile } from "./explain";
import type { Tile } from "./scorecard";
import type { ResultsCard, Research } from "./types";

const tile = (label: string, value: string) => ({ key: label, label, value, verdict: "", detail: "", tone: "neutral", section: "" }) as Tile;
const research = (over: Partial<Research> = {}) =>
  ({ snapshot: { is_financial: false, ratios: { "Stock P/E": 19.2 } }, trajectory: null, ledger: null, ...over }) as unknown as Research;

describe("plain-English readings", () => {
  it("reads each tile from its own number", () => {
    // 15% a year: 1.15^5 = 2.01, so about 5 years to double
    expect(explainTile(tile("Growth", "15%"), research())).toContain("doubles in about 5 years");
    expect(explainTile(tile("Margins", "17%"), research())).toContain("Of every Rs 100 of sales, about Rs 17 is left");
    expect(explainTile(tile("Balance sheet", "0.43"), research())).toContain("has borrowed Rs 43");
    // HDFCBANK Q2 FY27 net NPA 0.37%
    expect(explainTile(tile("Asset quality", "0.37%"), research())).toContain("about 37 paise is in loans that have stopped paying");
    expect(explainTile(tile("Valuation", "P/E 19.2"), research())).toContain("Rs 19.2 for every Rs 1");
    expect(explainTile(tile("Growth", "n/a"), research())).toBeNull();
  });

  it("explains a results card line by line", () => {
    const rc = {
      has_year_ago: true,
      rows: [
        { label: "Revenue", value: 21793.64, yoy: 46.7, qoq: 40.2 },
        { label: "PAT", value: 410.87, yoy: -44.9, qoq: -60 },
      ],
    } as unknown as ResultsCard;
    const lines = explainResults(rc);
    expect(lines[0]).toBe("Revenue: money from sales. Rs 21,794 crore this quarter, up 46.7% on the same quarter last year.");
    expect(lines[1]).toContain("down 44.9% on the same quarter last year");
  });
});
