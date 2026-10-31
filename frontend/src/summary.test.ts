import { describe, expect, it } from "vitest";
import { count, list, summarize } from "./summary";
import type { Brief, BriefCard, ResultsCard } from "./types";

function results(ticker: string, patYoy: number | null): ResultsCard {
  return {
    ticker,
    period_end: "2026-09-30",
    quarter: "Q2 FY27",
    consolidated: true,
    is_bank: false,
    unit: "Rs crore",
    rows: [{ label: "PAT", value: 100, prev: 90, year_ago: 80, qoq: 11.1, yoy: patYoy, derived: false, check: null }],
    ebitda_margin: null,
    source_url: null,
    broadcast_at: null,
    has_prev: true,
    has_year_ago: patYoy !== null,
  };
}

function card(id: string, ticker: string, category: string, r: ResultsCard | null = null): BriefCard {
  return {
    id,
    ticker,
    name: ticker,
    category,
    category_label: category,
    priority: "needs_you",
    latest_at: "2026-10-30T19:47:12",
    headline: "",
    alert: false,
    filings: [],
    results: r,
    people: null,
    scale: null,
  };
}

function brief(needs: BriefCard[], worth: BriefCard[] = []): Brief {
  return {
    window_hours: 24,
    since: "",
    needs_you: needs,
    worth_knowing: worth,
    moves: [],
    routine: { count: 0, by_category: {}, items: [] },
    total_filings: needs.length + worth.length,
    portfolio_day: null,
    freshness: { refreshed_at: null, filings_refreshed_at: null, last_eod_date: null },
  };
}

describe("count and list", () => {
  it("writes small numbers as words and agrees in number", () => {
    expect(count(1, "filing needs", "filings need")).toBe("One filing needs");
    expect(count(5, "filing needs", "filings need")).toBe("Five filings need");
    expect(count(14, "filing needs", "filings need")).toBe("14 filings need");
  });
  it("joins names the way a person would", () => {
    expect(list(["TCS"])).toBe("TCS");
    expect(list(["TCS", "INFY"])).toBe("TCS and INFY");
    expect(list(["RELIANCE", "DIXON", "MAXHEALTH"])).toBe("RELIANCE, DIXON and MAXHEALTH");
  });
});

describe("summarize", () => {
  it("leads with the count and the largest profit move among results", () => {
    const b = brief([
      card("a", "RELIANCE", "results", results("RELIANCE", 33.8)),
      card("b", "DIXON", "results", results("DIXON", -44.9)),
      card("c", "DIXON", "management_change"),
    ]);
    expect(summarize(b, new Set())).toBe(
      "Three filings need you. RELIANCE and DIXON reported Q2 FY27; DIXON's profit fell 44.9% from a year ago. One leadership change, at DIXON.",
    );
  });

  it("skips the profit clause when there is no year-ago quarter to compare", () => {
    const b = brief([card("a", "ETERNAL", "results", results("ETERNAL", null))]);
    expect(summarize(b, new Set())).toBe("One filing needs you. ETERNAL reported Q2 FY27.");
  });

  it("drops what is done and says so when nothing urgent is left", () => {
    const b = brief([card("a", "TCS", "litigation")], [card("w", "INFY", "capex")]);
    expect(summarize(b, new Set(["a"]))).toBe("Nothing urgent. One item is worth a look.");
    expect(summarize(b, new Set(["a", "w"]))).toBe("Nothing needs you. You're caught up.");
  });

  it("counts filings outside results and people", () => {
    const b = brief([card("a", "TCS", "results", results("TCS", 14.9)), card("b", "POLYCAB", "litigation")]);
    expect(summarize(b, new Set())).toBe(
      "Two filings need you. TCS reported Q2 FY27; TCS's profit rose 14.9% from a year ago. One other filing.",
    );
  });
});
