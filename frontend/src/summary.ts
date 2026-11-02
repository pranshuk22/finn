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

/** The profit line worth quoting: PBT when tax explains the PAT change, EBITDA when other income or a cost below
 * it does (ETERNAL's "PBT rose 150.4%" leaned on other income at 109% of PBT), none when the figures look wrong. */
function profitYoy(c: BriefCard): { label: string; y: number } | null {
  if (!c.results?.has_year_ago || c.results.suspect?.length) return null;
  const label = c.results.below_ebitda ? "EBITDA" : c.results.tax_note ? "PBT" : "PAT";
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
      // The biggest rise and the biggest fall, so the line never reads only the good news (the 24-hour brief once
      // named RELIANCE's +33.8% and not DIXON's -44.9%). EBITDA is called EBITDA, never "profit".
      const what = (m: { label: string }) => (m.label === "PBT" ? "profit before tax" : m.label === "EBITDA" ? "EBITDA" : "profit");
      const say = (m: (typeof moves)[number]) => `${m.c.ticker}'s ${what(m)} ${m.y >= 0 ? "rose" : "fell"} ${Math.abs(m.y).toFixed(1)}%`;
      const up = moves.filter((m) => m.y >= 0).sort((a, b) => b.y - a.y)[0];
      const down = moves.filter((m) => m.y < 0).sort((a, b) => a.y - b.y)[0];
      s += `; ${[up, down].filter(Boolean).map((m) => say(m!)).join(" and ")} from a year ago`;
    }
    sentences.push(`${s}.`);
  }

  const people = open.filter((c) => c.category === "management_change");
  if (people.length) {
    // A CEO or chair leaving is the news; name it rather than fold it into a count.
    // Grouped per company: HDFCBANK once read "HDFCBANK's MD and CEO, HDFCBANK's MD".
    const exits = people.flatMap((c) => {
      const roles = [...new Set((c.people ?? []).filter((p) => p.level === "top" && p.change === "leaving").map((p) => shortRole(p.role)))];
      return roles.length ? [{ text: `${c.ticker}'s ${list(roles)}`, n: roles.length }] : [];
    });
    const leaving = exits.reduce((n, e) => n + e.n, 0);
    const exitClause = exits.length ? `; ${list(exits.map((e) => e.text))} ${leaving === 1 ? "is" : "are"} leaving` : "";
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
  if (md) return /deputy/.test(r) ? "Deputy MD" : /joint/.test(r) ? "Joint MD" : "MD";
  if (/chief financial/.test(r)) return "CFO";
  if (/chair(man|person)?\b/.test(r)) return "Chair";
  return role.split(/ and |,/)[0].trim();
}
