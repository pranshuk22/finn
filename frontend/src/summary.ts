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

/** The profit line worth quoting: PBT when tax explains the PAT change, none when the figures look wrong. */
function profitYoy(c: BriefCard): { label: string; y: number } | null {
  if (!c.results?.has_year_ago || c.results.suspect?.length) return null;
  const label = c.results.tax_note ? "PBT" : "PAT";
  const y = c.results.rows.find((r) => r.label === label)?.yoy;
  return y == null ? null : { label, y };
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
    const moves = results.flatMap((c) => {
      const p = profitYoy(c);
      return p ? [{ c, ...p }] : [];
    });
    if (moves.length) {
      const big = moves.reduce((a, x) => (Math.abs(x.y) > Math.abs(a.y) ? x : a));
      const what = big.label === "PBT" ? "profit before tax" : "profit";
      s += `; ${big.c.ticker}'s ${what} ${big.y >= 0 ? "rose" : "fell"} ${Math.abs(big.y).toFixed(1)}% from a year ago`;
    }
    sentences.push(`${s}.`);
  }

  const people = open.filter((c) => c.category === "management_change");
  if (people.length) {
    // A CEO or chair leaving is the news; name it rather than fold it into a count.
    const exits = people.flatMap((c) => (c.people ?? []).filter((p) => p.level === "top" && p.change === "leaving").map((p) => `${c.ticker}'s ${shortRole(p.role)}`));
    const exitClause = exits.length ? `; ${list([...new Set(exits)])} ${exits.length === 1 ? "is" : "are"} leaving` : "";
    sentences.push(`${count(people.length, "leadership change", "leadership changes")}, at ${list([...new Set(people.map((c) => c.ticker))])}${exitClause}.`);
  }

  const other = open.length - results.length - people.length;
  if (other > 0 && sentences.length > 1) sentences.push(`${count(other, "other filing", "other filings")}.`);
  return sentences.join(" ");
}

/** "Managing Director and Chief Executive Officer" reads "MD and CEO" in a sentence. */
export function shortRole(role: string): string {
  const r = role.toLowerCase();
  const md = /managing director/.test(r);
  if (/chief executive/.test(r)) return md ? "MD and CEO" : "CEO";
  if (md) return "MD";
  if (/chief financial/.test(r)) return "CFO";
  if (/chair(man|person)?\b/.test(r)) return "Chair";
  return role.split(/ and |,/)[0].trim();
}
