import type { Brief, BriefCard } from "./types";

// The brief's opening sentence, written from the data in code. No model: it has to be right every time.

const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];

export function count(n: number, one: string, many: string): string {
  const w = n <= 10 ? WORDS[n] : String(n);
  return `${w} ${n === 1 ? one : many}`;
}

export function list(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function patYoy(c: BriefCard): number | null {
  if (!c.results?.has_year_ago) return null;
  const pat = c.results.rows.find((r) => r.label === "PAT");
  return pat?.yoy ?? null;
}

export function summarize(b: Brief, done: Set<string>): string {
  const open = b.needs_you.filter((c) => !done.has(c.id));
  if (open.length === 0) {
    const worth = b.worth_knowing.filter((c) => !done.has(c.id)).length;
    return worth ? `Nothing urgent. ${count(worth, "item is", "items are")} worth a look.` : "Nothing needs you. You're caught up.";
  }

  const sentences = [`${count(open.length, "filing needs", "filings need")} you.`];

  const results = open.filter((c) => c.category === "results" && c.results);
  if (results.length) {
    const quarter = results[0].results!.quarter;
    let s = `${list(results.map((c) => c.ticker))} reported ${quarter}`;
    const moves = results.map((c) => ({ c, y: patYoy(c) })).filter((x): x is { c: BriefCard; y: number } => x.y != null);
    if (moves.length) {
      const big = moves.reduce((a, x) => (Math.abs(x.y) > Math.abs(a.y) ? x : a));
      s += `; ${big.c.ticker}'s profit ${big.y >= 0 ? "rose" : "fell"} ${Math.abs(big.y).toFixed(1)}% from a year ago`;
    }
    sentences.push(`${s}.`);
  }

  const people = open.filter((c) => c.category === "management_change");
  if (people.length) {
    sentences.push(`${count(people.length, "leadership change", "leadership changes")}, at ${list([...new Set(people.map((c) => c.ticker))])}.`);
  }

  const other = open.length - results.length - people.length;
  if (other > 0 && sentences.length > 1) sentences.push(`${count(other, "other filing", "other filings")}.`);
  return sentences.join(" ");
}
