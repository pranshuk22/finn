import { useMemo, useState } from "react";
import { useQuery, useStored } from "../api";
import { Button, Card, Chip, ErrorState, ExtLink, Header, Pct, ResultsTable, SectionTitle, Sheet, Skeleton, Sparkline, StaleNote } from "../components/ui";
import { ago, inr, scaleLine, when } from "../format";
import { navigate } from "../router";
import type { Brief, BriefCard, Move, Person } from "../types";

const WINDOWS = [
  { hours: 24, label: "24h" },
  { hours: 72, label: "3d" },
  { hours: 168, label: "7d" },
  { hours: 720, label: "30d" },
];

const SORTED_BY: Record<string, string> = {
  label: "Sorted by the exchange's own label",
  rules: "Sorted by a text rule",
  model: "Sorted by Flash-Lite",
};

export function BriefScreen() {
  const [hours, setHours] = useStored("window", 24);
  const [done, setDone] = useStored<string[]>("done", []);
  const q = useQuery<Brief>(`/api/brief?hours=${hours}`);
  const [open, setOpen] = useState<BriefCard | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [showRoutine, setShowRoutine] = useState(false);

  const doneSet = useMemo(() => new Set(done), [done]);
  const b = q.data;
  const cards = b ? [...b.needs_you, ...b.worth_knowing] : [];
  const left = cards.filter((c) => !doneSet.has(c.id));
  const finished = cards.filter((c) => doneSet.has(c.id));

  const markDone = (id: string) => setDone([...done.filter((x) => x !== id), id].slice(-500));
  const undo = (id: string) => setDone(done.filter((x) => x !== id));

  return (
    <>
      <Header
        eyebrow="FINN"
        title="Your brief"
        sub={
          b ? (
            <span>
              {left.length === 0 ? "Nothing left to read" : `${left.length} to read`}
              {finished.length > 0 && `, ${finished.length} done`}
              {b.freshness.filings_refreshed_at && ` · Filings checked ${ago(b.freshness.filings_refreshed_at)}`}
            </span>
          ) : null
        }
      />

      <div className="no-scrollbar flex gap-2 overflow-x-auto px-4 pb-1" role="group" aria-label="Time window">
        {WINDOWS.map((w) => (
          <Chip key={w.hours} on={hours === w.hours} onClick={() => setHours(w.hours)}>
            {w.label}
          </Chip>
        ))}
      </div>

      {cards.length > 0 && (
        <div className="mx-4 mt-4 h-1 overflow-hidden rounded-full bg-card" aria-hidden>
          <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${(finished.length / cards.length) * 100}%` }} />
        </div>
      )}

      <div className="mt-4">
        <StaleNote savedAt={q.savedAt} onRetry={q.reload} />
        {!b && q.loading && <Skeleton lines={4} />}
        {!b && q.error && <ErrorState message={q.error.message} onRetry={q.reload} />}

        {b && (
          <>
            {left.length === 0 && (
              <Card className="py-8 text-center">
                <p className="text-lg font-semibold">You're caught up</p>
                <p className="mt-1 text-[13px] text-muted">
                  {cards.length === 0
                    ? `No filings that need you in the last ${WINDOWS.find((w) => w.hours === hours)?.label ?? `${hours}h`}.`
                    : "Everything in this window is marked done."}{" "}
                  {b.freshness.filings_refreshed_at && `Last checked ${when(b.freshness.filings_refreshed_at)}.`}
                </p>
              </Card>
            )}

            <Group title="Needs you" dot="needs" cards={b.needs_you.filter((c) => !doneSet.has(c.id))} onOpen={setOpen} onDone={markDone} />
            <Group title="Worth knowing" dot="worth" cards={b.worth_knowing.filter((c) => !doneSet.has(c.id))} onOpen={setOpen} onDone={markDone} />

            <Moves moves={b.moves} />

            {finished.length > 0 && (
              <>
                <SectionTitle
                  right={
                    <button type="button" className="h-9 text-[13px] font-semibold tracking-normal text-accent-ink normal-case" onClick={() => setShowDone(!showDone)}>
                      {showDone ? "Hide" : "Show"}
                    </button>
                  }
                >
                  Done ({finished.length})
                </SectionTitle>
                {showDone &&
                  finished.map((c) => (
                    <div key={c.id} className="mx-4 flex items-center justify-between gap-3 border-b border-line py-3">
                      <div className="min-w-0">
                        <p className="text-xs text-muted">
                          {c.ticker} · {c.category_label}
                        </p>
                        <p className="truncate text-[14px]">{c.headline}</p>
                      </div>
                      <button type="button" onClick={() => undo(c.id)} className="h-11 shrink-0 text-[13px] font-semibold text-accent-ink">
                        Undo
                      </button>
                    </div>
                  ))}
              </>
            )}

            {b.routine.count > 0 && (
              <div className="mt-6 px-4">
                <button
                  type="button"
                  onClick={() => setShowRoutine(!showRoutine)}
                  aria-expanded={showRoutine}
                  className="flex min-h-11 w-full flex-col items-center justify-center py-2 text-[13px] text-muted"
                >
                  <span>
                    {b.routine.count} routine filings <span className="text-accent-ink">{showRoutine ? "Hide" : "Show"}</span>
                  </span>
                  <span className="text-xs">
                    {Object.entries(b.routine.by_category)
                      .sort((x, y) => y[1] - x[1])
                      .slice(0, 3)
                      .map(([k, n]) => `${n} ${k.toLowerCase()}`)
                      .join(", ")}
                  </span>
                </button>
                {showRoutine && (
                  <ul className="animate-fade">
                    {b.routine.items.map((r) => (
                      <li key={r.id} className="border-b border-line py-3 last:border-0">
                        <p className="text-xs text-muted">
                          {r.ticker} · {r.category_label} · {when(r.at)}
                        </p>
                        <p className="mt-0.5 text-[14px]">{r.summary}</p>
                        {r.pdf_url && (
                          <p className="mt-1 text-xs">
                            <ExtLink href={r.pdf_url}>Filing</ExtLink>
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <Sheet open={!!open} onClose={() => setOpen(null)} title={open ? `${open.ticker} · ${open.category_label}` : ""}>
        {open && <Sources card={open} />}
      </Sheet>
    </>
  );
}

function Group({
  title,
  dot,
  cards,
  onOpen,
  onDone,
}: {
  title: string;
  dot: "needs" | "worth";
  cards: BriefCard[];
  onOpen: (c: BriefCard) => void;
  onDone: (id: string) => void;
}) {
  if (cards.length === 0) return null;
  return (
    <section>
      <SectionTitle dot={dot}>
        {title} ({cards.length})
      </SectionTitle>
      {cards.map((c) => (
        <BriefCardView key={c.id} card={c} onOpen={() => onOpen(c)} onDone={() => onDone(c.id)} />
      ))}
    </section>
  );
}

function BriefCardView({ card, onOpen, onDone }: { card: BriefCard; onOpen: () => void; onDone: () => void }) {
  const dig = `/research/${card.ticker}${card.results ? "#ledger" : ""}`;
  return (
    <article className="mx-4 mb-3 rounded-card bg-card p-4">
      <div className="flex items-center gap-2 text-xs text-muted">
        <span className="font-bold tracking-[0.02em] text-ink">{card.ticker}</span>
        <span className="h-[3px] w-[3px] rounded-full bg-muted" />
        <span>{card.category_label}</span>
        {card.alert && (
          <span className="rounded-full border border-needs/60 px-1.5 text-[11px] font-semibold text-needs" title="A category you asked to be alerted about">
            Alert
          </span>
        )}
        <span className="tabular ml-auto">{when(card.latest_at)}</span>
      </div>
      <h3 className="mt-2 mb-3 text-[17px] leading-snug font-semibold tracking-[-0.01em]">{card.headline}</h3>

      {card.results && <ResultsTable r={card.results} />}
      {!card.results && card.people && <People people={card.people} />}
      {card.scale && <p className="mt-2 text-[13px] text-muted">{scaleLine(card.scale.amount_cr, card.scale.pct_of_revenue)}</p>}

      <button type="button" onClick={onOpen} className="mt-2 h-9 text-[13px] text-accent-ink">
        {card.filings.length === 1 ? "1 filing" : `${card.filings.length} filings`}, see sources
      </button>

      <div className="mt-2 flex gap-2">
        <Button kind="ghost" onClick={onDone} className="flex-1">
          Done
        </Button>
        <Button onClick={() => navigate(dig)} className="flex-1">
          Dig in
        </Button>
      </div>
    </article>
  );
}

function People({ people }: { people: Person[] }) {
  return (
    <ul className="space-y-3">
      {people.slice(0, 3).map((p) => (
        <li key={`${p.name}-${p.change}`}>
          <p>
            <span className="font-semibold">{p.name}</span>
            <span className="text-muted">
              {" "}
              {p.change === "joining" ? "joins" : p.change === "leaving" ? "leaves" : p.change}
            </span>
          </p>
          <p className="text-[13px] text-accent-ink">
            {p.role}
            {p.entity && <span className="text-muted"> at {p.entity}</span>}
          </p>
          {p.bio?.confident && p.bio.lines.length > 0 ? (
            <div className="mt-1 text-[13px] text-muted">
              {p.bio.lines.slice(0, 3).map((l) => (
                <p key={l}>{l}</p>
              ))}
              {p.bio.sources.length > 0 && (
                <p className="mt-1 text-xs">
                  {p.bio.sources.slice(0, 2).map((s, i) => (
                    <span key={s.url}>
                      {i > 0 && " · "}
                      <ExtLink href={s.url}>{new URL(s.url).hostname.replace(/^www\./, "")}</ExtLink>
                    </span>
                  ))}
                </p>
              )}
            </div>
          ) : p.profile_from_filing ? (
            <p className="mt-1 text-[13px] text-muted">{p.profile_from_filing}</p>
          ) : (
            p.senior && <p className="mt-1 text-xs text-muted">No profile we could verify against this company.</p>
          )}
        </li>
      ))}
    </ul>
  );
}

function Sources({ card }: { card: BriefCard }) {
  return (
    <ul>
      {card.filings.map((f) => (
        <li key={f.id} className="border-b border-line py-3 last:border-0">
          <p className="text-xs text-muted">{when(f.at)}</p>
          <p className="mt-1 text-[14px]">{f.summary}</p>
          <p className="mt-1 text-xs text-muted">
            NSE label: {f.label || "none"}. {SORTED_BY[f.classified_by] ?? f.classified_by}.
          </p>
          {f.pdf_url && (
            <p className="mt-1 text-[13px]">
              <ExtLink href={f.pdf_url}>Open the filing</ExtLink>
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function Moves({ moves }: { moves: Move[] }) {
  if (moves.length === 0) return null;
  return (
    <section>
      <SectionTitle>Price and volume ({moves.length})</SectionTitle>
      <ul className="mx-4">
        {moves.map((m) => (
          <li key={`${m.ticker}-${m.date}`}>
            <button
              type="button"
              onClick={() => navigate(`/research/${m.ticker}`)}
              className="grid min-h-14 w-full grid-cols-[1fr_72px_92px] items-center gap-3 border-b border-line py-2.5 text-left"
            >
              <span className="min-w-0">
                <span className="block font-bold">{m.ticker}</span>
                <span className="tabular block truncate text-xs text-muted">
                  Rs {inr(m.close, 0)} · {when(`${m.date}T15:30:00`).replace(/ 15:30$/, "")}
                </span>
              </span>
              <Sparkline values={m.spark} />
              <span className="text-right">
                <Pct value={m.move_pct} className="block font-semibold" />
                <span className={`tabular block text-xs ${m.reasons.includes("volume") ? "text-ink" : "text-muted"}`}>
                  {m.vol_mult.toFixed(1)}x volume
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
