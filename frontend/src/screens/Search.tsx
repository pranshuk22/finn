import { useEffect, useState } from "react";
import { api, useQuery } from "../api";
import { HelpButton } from "../components/Help";
import { Header, SectionTitle } from "../components/ui";
import { navigate } from "../router";
import type { Companies } from "../types";

export function Search() {
  const q = useQuery<Companies>("/api/companies");
  const [text, setText] = useState("");
  const term = text.trim().toUpperCase();

  const all = q.data ? [...q.data.portfolio.map((c) => ({ ...c, group: "portfolio" })), ...q.data.adhoc.map((c) => ({ ...c, group: "adhoc" }))] : [];
  const known = term ? all.filter((c) => c.ticker.includes(term) || c.name.toUpperCase().includes(term)) : [];
  const alias = term && q.data?.aliases[term];

  // Any listed company by symbol or name, from NSE's own list (not cached on the device: searches are one-off).
  const [listed, setListed] = useState<{ term: string; matches: { ticker: string; name: string }[] }>({ term: "", matches: [] });
  useEffect(() => {
    if (term.length < 2) return;
    const t = setTimeout(() => {
      api
        .get<{ matches: { ticker: string; name: string }[] }>(`/api/search?q=${encodeURIComponent(term)}`)
        .then((r) => setListed({ term, matches: r.matches }))
        .catch(() => setListed({ term, matches: [] }));
    }, 250);
    return () => clearTimeout(t);
  }, [term]);
  const fromNse = listed.term === term ? listed.matches.filter((m) => !known.some((k) => k.ticker === m.ticker)) : [];
  const matches = [...known, ...fromNse];

  const go = (t: string) => navigate(`/research/${encodeURIComponent(t.trim().toUpperCase())}`);

  return (
    <>
      <Header eyebrow="Any NSE company" title="Research" right={<HelpButton />} sub="Numbers from filings, promises from earnings calls, every claim with its source." />
      <form
        className="px-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (term) go(matches[0]?.ticker ?? term);
        }}
      >
        <label htmlFor="q" className="sr-only">
          NSE symbol or company name
        </label>
        <input
          id="q"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="NSE symbol or name, e.g. TITAN"
          autoCapitalize="characters"
          autoComplete="off"
          enterKeyHint="search"
          className="h-12 w-full rounded-[10px] border border-line bg-card px-4 text-[16px] text-ink placeholder:text-muted focus:border-accent focus:outline-none"
        />
      </form>

      {term && (
        <ul className="mx-4 mt-2">
          {alias && (
            <Row ticker={alias} name={`${term} now trades as ${alias}`} onClick={() => go(alias)} />
          )}
          {matches.slice(0, 8).map((c) => (
            <Row key={c.ticker} ticker={c.ticker} name={fromNse.includes(c) ? `${c.name} · first look takes a few seconds` : c.name} onClick={() => go(c.ticker)} />
          ))}
          {matches.length === 0 && !alias && listed.term === term && (
            <Row ticker={term} name="No listed company matches. Try the NSE symbol." onClick={() => go(term)} />
          )}
        </ul>
      )}

      {!term && q.data && (
        <>
          <SectionTitle>Your portfolio</SectionTitle>
          <ul className="mx-4">
            {q.data.portfolio.map((c) => (
              <Row key={c.ticker} ticker={c.ticker} name={`${c.name} · ${c.sector}`} onClick={() => go(c.ticker)} />
            ))}
          </ul>
          <SectionTitle>Also prepared</SectionTitle>
          <ul className="mx-4">
            {q.data.adhoc.map((c) => (
              <Row key={c.ticker} ticker={c.ticker} name={c.name} onClick={() => go(c.ticker)} />
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function Row({ ticker, name, onClick }: { ticker: string; name: string; onClick: () => void }) {
  return (
    <li>
      <button type="button" onClick={onClick} className="flex min-h-12 w-full items-center gap-3 border-b border-line py-2 text-left">
        <span className="w-28 shrink-0 font-semibold">{ticker}</span>
        <span className="min-w-0 truncate text-[14px] text-muted">{name}</span>
      </button>
    </li>
  );
}
