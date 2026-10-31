import { describe, expect, it } from "vitest";
import { parse } from "./router";

describe("parse", () => {
  it("maps paths to screens", () => {
    expect(parse("/", "")).toEqual({ name: "brief" });
    expect(parse("/alerts", "")).toEqual({ name: "alerts" });
    expect(parse("/settings", "")).toEqual({ name: "settings" });
    expect(parse("/research", "")).toEqual({ name: "search" });
  });
  it("upper-cases tickers and keeps the section to open", () => {
    expect(parse("/research/hal", "#ledger")).toEqual({ name: "research", ticker: "HAL", section: "ledger" });
    expect(parse("/research/BAJAJ-AUTO", "")).toEqual({ name: "research", ticker: "BAJAJ-AUTO", section: null });
  });
  it("falls back to the brief for unknown paths", () => {
    expect(parse("/nope", "")).toEqual({ name: "brief" });
  });
});
