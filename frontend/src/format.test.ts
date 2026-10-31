import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ago, bps, dayMonthYear, filedDate, inr, plain, scaleLine, signedPct, target, tone, when } from "./format";

describe("inr", () => {
  it("groups digits the Indian way", () => {
    expect(inr(332861)).toBe("3,32,861");
    expect(inr(1199033)).toBe("11,99,033");
    expect(inr(414)).toBe("414");
  });
  it("says n/a instead of inventing a number", () => {
    expect(inr(null)).toBe("n/a");
    expect(inr(undefined)).toBe("n/a");
  });
});

describe("signedPct and tone", () => {
  it("always shows the sign of a change", () => {
    expect(signedPct(28.6)).toBe("+28.6%");
    expect(signedPct(-44.9)).toBe("-44.9%");
    expect(signedPct(0)).toBe("0.0%");
  });
  it("colours by direction, and leaves zero and missing neutral", () => {
    expect(tone(5.2)).toBe("up");
    expect(tone(-1.8)).toBe("down");
    expect(tone(0)).toBe("flat");
    expect(tone(null)).toBe("flat");
  });
});

describe("scaleLine", () => {
  it("never shows a tiny amount as 0.00%", () => {
    expect(scaleLine(56, 0.0047)).toBe("Rs 56 crore, under 0.01% of yearly revenue");
  });
  it("leads with market cap when it is known", () => {
    expect(scaleLine(4264.6, 25.38, 4.24)).toBe("Rs 4,265 crore, 4.2% of market cap, 25.4% of yearly revenue");
  });
  it("keeps small amounts exact, and uses two decimals below 1% and one above", () => {
    expect(scaleLine(2.79, 0.28)).toBe("Rs 2.79 crore, 0.28% of yearly revenue");
    expect(scaleLine(1143, 12.48)).toBe("Rs 1,143 crore, 12.5% of yearly revenue");
  });
});

describe("times are shown in IST", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-31T08:00:00Z")); // 13:30 IST
  });
  afterEach(() => vi.useRealTimers());

  it("reads exchange timestamps as IST wall time", () => {
    expect(when("2026-10-31T09:15:00")).toBe("Today 09:15");
    expect(when("2026-10-30T19:47:12")).toBe("Yesterday 19:47");
  });
  it("converts the server's UTC timestamps to IST", () => {
    expect(when("2026-10-30T20:33:55+00:00")).toBe("Today 02:03");
  });
  it("says how long ago", () => {
    expect(ago("2026-10-31T07:48:00+00:00")).toBe("12 min ago");
    expect(ago("2026-10-30T20:00:00+00:00")).toBe("12 h ago");
  });
  it("formats calendar dates", () => {
    expect(dayMonthYear("2026-06-30")).toBe("30 Jun 2026");
  });
});

describe("plain", () => {
  it("replaces PDF ligature glyphs in quotes", () => {
    expect(plain("we don't provide any speciﬁc revenue")).toBe("we don't provide any specific revenue");
    expect(plain("eﬀect")).toBe("effect");
  });
});

describe("bps", () => {
  it("signs a margin change in basis points", () => {
    expect(bps(-110)).toBe("-110 bps");
    expect(bps(40)).toBe("+40 bps");
    expect(bps(null)).toBe("n/a");
  });
});

describe("target", () => {
  it("gives a bare number its unit", () => {
    expect(target("100000", "rs_crore")).toBe("Rs 1,00,000 crore");
    expect(target("17,500", "rs_crore")).toBe("Rs 17,500 crore");
    expect(target("6,000", "other")).toBe("6,000");
  });
  it("leaves a target with words as said", () => {
    expect(target("INR 6,000 crores to INR 7,000 crores", "rs_crore")).toBe("INR 6,000 crores to INR 7,000 crores");
  });
});

describe("filedDate", () => {
  it("formats ISO and keeps a date written in words, instead of showing Invalid Date", () => {
    expect(filedDate("2027-01-01")).toBe("1 Jan 2027");
    expect(filedDate("12th November 2026")).toBe("12th November 2026");
  });
});
