import { useEffect, useState } from "react";
import { api, useQuery, useStored } from "../api";
import { HelpButton } from "../components/Help";
import { Header, Icon, Pct, SectionTitle, Segmented, Sparkline } from "../components/ui";
import { inr, istDay } from "../format";
import { navigate } from "../router";
import type { Companies, Glance } from "../types";

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
      <Header eyebrow="Any NSE company" title="Research" right={<HelpButton topic="research" />} sub="Numbers from filings, promises from earnings calls, every claim with its source." />
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

      {!term && q.data && <Watchlist data={q.data} go={go} />}
    </>
  );
}

function Watchlist({ data, go }: { data: Companies; go: (t: string) => void }) {
  const [sort, setSort] = useStored<"sector" | "move">("watch-sort", "sector");
  const priced = data.portfolio.filter((c) => c.move_pct != null);
  const up = priced.filter((c) => c.move_pct! > 0).length;
  const down = priced.filter((c) => c.move_pct! < 0).length;
  const day = priced.find((c) => c.date)?.date;
  const sectors = [...new Set(data.portfolio.map((c) => c.sector))];
  const byMove = [...data.portfolio].sort((a, b) => (b.move_pct ?? -1e9) - (a.move_pct ?? -1e9));
  return (
    <>
      <div className="mt-6 flex items-center justify-between gap-3 px-4">
        <h2 className="text-[17px] font-semibold">
          Your portfolio <span className="tabular text-[15px] font-normal text-muted">{data.portfolio.length}</span>
        </h2>
        <Segmented
          label="Order"
          className="w-[190px] bg-card"
          options={[
            { value: "sector", label: "By sector" },
            { value: "move", label: "Day's move" },
          ]}
          value={sort}
          onChange={setSort}
        />
      </div>
      {day && (
        <div className="mt-3 px-4">
          <p className="text-[12px] text-muted">
            {up} up, {down} down on {istDay(`${day}T15:30:00`)}. Results are the latest quarter's growth.
          </p>
          <div className="mt-1.5 flex h-1 gap-[2px]" aria-hidden>
            <span className="rounded-full" style={{ flexGrow: up, background: "var(--viz-up)" }} />
            <span className="rounded-full" style={{ flexGrow: down, background: "var(--viz-down)" }} />
          </div>
        </div>
      )}
      <div className="mx-4 mt-3 overflow-hidden rounded-[12px] bg-card">
        {sort === "sector"
          ? sectors.map((sec) => {
              const rows = data.portfolio.filter((c) => c.sector === sec);
              return (
                <div key={sec}>
                  <p className="border-t border-line bg-base/40 px-4 py-1.5 text-[12px] font-semibold text-muted first:border-0">
                    {sec} <span className="tabular font-normal">{rows.length}</span>
                  </p>
                  {rows.map((c) => (
                    <WatchRow key={c.ticker} c={c} onClick={() => go(c.ticker)} />
                  ))}
                </div>
              );
            })
          : byMove.map((c) => <WatchRow key={c.ticker} c={c} onClick={() => go(c.ticker)} />)}
      </div>

      <SectionTitle count={data.adhoc.length}>Also prepared</SectionTitle>
      <p className="-mt-1 mb-2 px-4 text-[12px] text-muted">Outside the portfolio, built in full for this challenge. Any NSE company works through the search above.</p>
      <div className="mx-4 overflow-hidden rounded-[12px] bg-card">
        {data.adhoc.map((c) => (
          <WatchRow key={c.ticker} c={c} onClick={() => go(c.ticker)} />
        ))}
      </div>
      <div className="h-6" />
    </>
  );
}

/** One company: ticker and name, the latest quarter's growth, a 30-day line, the close and the day's move. */
function WatchRow({ c, onClick }: { c: Glance; onClick: () => void }) {
  const r = c.results;
  return (
    <button type="button" onClick={onClick} className="flex w-full items-center gap-3 border-t border-line px-4 py-3 text-left first:border-0">
      <div className="min-w-0 flex-1">
        <p className="flex items-baseline gap-2">
          <span className="font-semibold">{c.ticker}</span>
          <span className="truncate text-[12px] text-muted">{c.name}</span>
        </p>
        {r && (
          <p className="mt-0.5 truncate text-[12px] text-muted" title={`${r.quarter}, ${r.basis === "YOY" ? "on a year earlier" : "on the quarter before"}`}>
            Rev <Pct value={r.revenue} /> · {r.profit_label} <Pct value={r.profit} /> {r.basis === "YOY" ? "YoY" : "QoQ"}
          </p>
        )}
      </div>
      {c.spark.length > 1 && <Sparkline values={c.spark} width={52} height={22} />}
      <div className="w-[68px] shrink-0 text-right">
        {c.close != null ? (
          <>
            <p className="tabular text-[14px] font-medium">{inr(c.close, 2)}</p>
            <p className="text-[12px]">
              <Pct value={c.move_pct} digits={2} />
            </p>
          </>
        ) : (
          <span className="text-faint">
            <Icon.chevron />
          </span>
        )}
      </div>
    </button>
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
