import { useEffect, useMemo, useState } from "react";
import { useQuery, useStored } from "../api";
import { Card, ErrorState, ExtLink, Icon, Pct, ResultsTable, SectionTitle, Segmented, Sheet, Skeleton, Sparkline, StaleNote, TextAction, Toast } from "../components/ui";
import { ago, inr, istDay, scaleLine, when } from "../format";
import { summarize } from "../summary";
import { navigate } from "../router";
import type { Brief, BriefCard, Move, Person } from "../types";

const WINDOWS = [
  { value: 24, label: "24 hours" },
  { value: 72, label: "3 days" },
  { value: 168, label: "7 days" },
  { value: 720, label: "30 days" },
];

const SORTED_BY: Record<string, string> = {
  label: "Sorted by the exchange's own label",
  rule: "Sorted by a text rule",
  model: "Sorted by Flash-Lite",
};

function today(): string {
  return new Date().toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "long", day: "numeric", month: "long" });
}

export function BriefScreen() {
  const [hours, setHours] = useStored("window", 24);
  const [done, setDone] = useStored<string[]>("done", []);
  const q = useQuery<Brief>(`/api/brief?hours=${hours}`);
  const [open, setOpen] = useState<BriefCard | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [showRoutine, setShowRoutine] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const doneSet = useMemo(() => new Set(done), [done]);
  const b = q.data;
  const cards = b ? [...b.needs_you, ...b.worth_knowing] : [];
  const left = cards.filter((c) => !doneSet.has(c.id));
  const finished = cards.filter((c) => doneSet.has(c.id));

  const markDone = (id: string) => {
    setDone([...done.filter((x) => x !== id), id].slice(-500));
    setToast(id);
  };
  const undo = (id: string) => {
    setDone(done.filter((x) => x !== id));
    setToast(null);
  };

  return (
    <>
      <header className="px-4 pt-[calc(20px+env(safe-area-inset-top))]">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-[13px] text-muted">{today()}</p>
          {b?.freshness.filings_refreshed_at && <p className="text-[12px] text-muted">Updated {ago(b.freshness.filings_refreshed_at)}</p>}
        </div>
        <h1 className="mt-0.5 font-display text-[34px] leading-tight font-semibold tracking-[-0.01em]">Brief</h1>
      </header>

      <div className="mt-3">
        <Segmented label="Time window" options={WINDOWS} value={hours} onChange={setHours} />
      </div>

      {b && <Hero b={b} done={doneSet} finished={finished.length} total={cards.length} />}

      <div className="mt-2">
        <StaleNote savedAt={q.savedAt} onRetry={q.reload} />
        {!b && q.loading && (
          <div className="mt-4">
            <Skeleton lines={4} />
          </div>
        )}
        {!b && q.error && (
          <div className="mt-4">
            <ErrorState message={q.error.message} onRetry={q.reload} />
          </div>
        )}

        {b && (
          <>
            {left.length === 0 && (
              <div className="mx-4 mt-10 text-center">
                <p className="font-display text-[22px] font-semibold">You're caught up</p>
                <p className="mx-auto mt-2 max-w-[300px] text-[14px] text-muted">
                  {cards.length === 0
                    ? `Nothing in the last ${WINDOWS.find((w) => w.value === hours)?.label ?? `${hours} hours`} needs your attention.`
                    : "Everything in this window is marked done."}
                  {b.freshness.filings_refreshed_at && ` Last checked ${when(b.freshness.filings_refreshed_at)}.`}
                </p>
              </div>
            )}

            <Group id="needs" title="Needs you" cards={b.needs_you.filter((c) => !doneSet.has(c.id))} onOpen={setOpen} onDone={markDone} />
            <Group id="worth" title="Worth knowing" cards={b.worth_knowing.filter((c) => !doneSet.has(c.id))} onOpen={setOpen} onDone={markDone} />

            <Moves moves={b.moves} />

            {b.routine.count > 0 && (
              <section>
                <SectionTitle
                  count={b.routine.count}
                  right={
                    <button type="button" className="h-9 text-[14px] text-accent-ink" onClick={() => setShowRoutine(!showRoutine)} aria-expanded={showRoutine}>
                      {showRoutine ? "Hide" : "Show"}
                    </button>
                  }
                >
                  Routine
                </SectionTitle>
                <p className="-mt-2 px-4 text-[13px] text-muted">
                  {Object.entries(b.routine.by_category)
                    .sort((x, y) => y[1] - x[1])
                    .map(([k, n]) => `${n} ${k.toLowerCase()}`)
                    .join(", ")}
                </p>
                {showRoutine && (
                  <ul className="animate-fade mx-4 mt-2">
                    {b.routine.items.map((r) => (
                      <li key={r.id} className="border-t border-line py-3">
                        <p className="text-[12px] text-muted">
                          <span className="font-semibold text-ink">{r.ticker}</span> · {r.category_label} · {when(r.at)}
                        </p>
                        <p className="mt-0.5 text-[14px]">{r.summary}</p>
                        {r.pdf_url && (
                          <p className="mt-1 text-[13px]">
                            <ExtLink href={r.pdf_url}>Filing</ExtLink>
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {finished.length > 0 && (
              <section>
                <SectionTitle
                  count={finished.length}
                  right={
                    <button type="button" className="h-9 text-[14px] text-accent-ink" onClick={() => setShowDone(!showDone)} aria-expanded={showDone}>
                      {showDone ? "Hide" : "Show"}
                    </button>
                  }
                >
                  Done
                </SectionTitle>
                {showDone && (
                  <ul className="mx-4">
                    {finished.map((c) => (
                      <li key={c.id} className="flex items-center justify-between gap-3 border-t border-line py-2.5">
                        <div className="min-w-0">
                          <p className="text-[12px] text-muted">
                            <span className="font-semibold text-ink">{c.ticker}</span> · {c.category_label}
                          </p>
                          <p className="truncate text-[14px] text-muted">{c.headline}</p>
                        </div>
                        <button type="button" onClick={() => undo(c.id)} className="h-11 shrink-0 text-[14px] text-accent-ink">
                          Restore
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
            <div className="h-6" />
          </>
        )}
      </div>

      <Sheet open={!!open} onClose={() => setOpen(null)} title={open ? `${open.ticker}, ${open.category_label.toLowerCase()}` : ""}>
        {open && <Sources card={open} />}
      </Sheet>

      {toast && <Toast message="Marked done" action="Undo" onAction={() => undo(toast)} />}
    </>
  );
}

function Hero({ b, done, finished, total }: { b: Brief; done: Set<string>; finished: number; total: number }) {
  const needs = b.needs_you.filter((c) => !done.has(c.id)).length;
  const worth = b.worth_knowing.filter((c) => !done.has(c.id)).length;
  const pd = b.portfolio_day;
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const stats = [
    { id: "needs", label: "Need you", n: needs, tone: "text-needs" },
    { id: "worth", label: "Worth knowing", n: worth, tone: "text-ink" },
    { id: "moves", label: "Price moves", n: b.moves.length, tone: "text-ink" },
  ];
  return (
    <section className="mx-4 mt-3 overflow-hidden rounded-[14px] bg-hero" aria-label="Summary">
      <p className="px-4 pt-4 font-display text-[19px] leading-snug">{summarize(b, done)}</p>

      <div className="mt-4 grid grid-cols-3 border-t border-line">
        {stats.map((s, i) => (
          <button
            key={s.id}
            type="button"
            onClick={() => jump(s.id)}
            disabled={s.n === 0}
            className={`px-4 py-3 text-left ${i ? "border-l border-line" : ""}`}
          >
            <span className={`tabular block font-display text-[28px] leading-none font-semibold ${s.n ? s.tone : "text-muted"}`}>{s.n}</span>
            <span className="mt-1 block text-[12px] text-muted">{s.label}</span>
          </button>
        ))}
      </div>

      {pd && (
        <div className="border-t border-line px-4 py-3 text-[13px] text-muted">
          <span className="text-ink">
            Your {pd.of} stocks on {istDay(`${pd.date}T15:30:00`)}:
          </span>{" "}
          {pd.up} up, {pd.down} down
          {pd.count < pd.of && `, ${pd.of - pd.count} not priced yet`}, median <Pct value={pd.median_pct} digits={2} />. Best {pd.best.ticker}{" "}
          <Pct value={pd.best.move_pct} />, worst {pd.worst.ticker} <Pct value={pd.worst.move_pct} />.
        </div>
      )}

      {total > 0 && (
        <div className="flex items-center gap-3 border-t border-line px-4 py-3" aria-label={`${finished} of ${total} done`}>
          <div className="h-[3px] flex-1 overflow-hidden rounded-full bg-base">
            <div className="h-full rounded-full bg-accent-ink transition-[width] duration-300" style={{ width: `${(finished / total) * 100}%` }} />
          </div>
          <span className="tabular text-[12px] text-muted">
            {finished} of {total} done
          </span>
        </div>
      )}
    </section>
  );
}

function Group({
  id,
  title,
  cards,
  onOpen,
  onDone,
}: {
  id: string;
  title: string;
  cards: BriefCard[];
  onOpen: (c: BriefCard) => void;
  onDone: (id: string) => void;
}) {
  if (cards.length === 0) return null;
  return (
    <section id={id} className="scroll-mt-4">
      <SectionTitle count={cards.length}>{title}</SectionTitle>
      {cards.map((c) => (
        <BriefCardView key={c.id} card={c} onOpen={() => onOpen(c)} onDone={() => onDone(c.id)} />
      ))}
    </section>
  );
}

function BriefCardView({ card, onOpen, onDone }: { card: BriefCard; onOpen: () => void; onDone: () => void }) {
  const dig = `/research/${card.ticker}${card.results ? "#ledger" : ""}`;
  return (
    <Card className="pb-0">
      <div className="flex items-center gap-1.5 text-[13px] text-muted">
        <span className="font-semibold text-ink">{card.ticker}</span>
        <span>·</span>
        <span>{card.category_label}</span>
        {card.alert && card.priority !== "needs_you" && (
          <span className="ml-1 inline-flex items-center gap-1 text-needs" title="A category you asked to be alerted about">
            <Icon.bell />
            Alert
          </span>
        )}
        <span className="tabular ml-auto whitespace-nowrap">{when(card.latest_at)}</span>
      </div>
      <h3 className="mt-1.5 mb-3 text-[17px] leading-snug font-semibold">{card.headline}</h3>

      {card.results && <ResultsTable r={card.results} />}
      {!card.results && card.people && <People people={card.people} named={card.people.length === 1} />}
      {card.scale && <p className="mt-2 text-[14px] text-muted">{scaleLine(card.scale.amount_cr, card.scale.pct_of_revenue)}</p>}

      <div className="mt-3 flex items-center border-t border-line">
        <TextAction onClick={onOpen} icon={<Icon.doc />}>
          {card.filings.length === 1 ? "1 filing" : `${card.filings.length} filings`}
        </TextAction>
        <span className="flex-1" />
        <TextAction onClick={onDone} icon={<Icon.check />}>
          Done
        </TextAction>
        <span className="w-5" />
        <TextAction onClick={() => navigate(dig)} strong>
          Research
          <Icon.arrow />
        </TextAction>
      </div>
    </Card>
  );
}

function People({ people, named }: { people: Person[]; named: boolean }) {
  return (
    <ul className="space-y-3">
      {people.slice(0, 3).map((p) => (
        <li key={`${p.name}-${p.change}`}>
          <p className={`text-[15px] ${named ? "sr-only" : ""}`}>
            <span className="font-semibold">{p.name}</span>
            <span className="text-muted">
              {" "}
              {p.change === "joining" ? "joins as" : p.change === "leaving" ? "leaves as" : `${p.change},`} {p.role}
              {p.entity && ` at ${p.entity}`}
            </span>
          </p>
          {p.bio?.confident && p.bio.lines.length > 0 ? (
            <div className={`border-l-2 border-line pl-3 text-[14px] text-muted ${named ? "" : "mt-1.5"}`}>
              {p.bio.lines.slice(0, 3).map((l) => (
                <p key={l} className="mt-0.5">
                  {l}
                </p>
              ))}
              {p.bio.sources.length > 0 && (
                <p className="mt-1 text-[12px]">
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
            <p className="mt-1.5 border-l-2 border-line pl-3 text-[14px] text-muted">{p.profile_from_filing}</p>
          ) : (
            p.senior && <p className="mt-1 text-[13px] text-muted">No profile we could verify against this company.</p>
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
        <li key={f.id} className="border-t border-line py-3 first:border-0 first:pt-0">
          <p className="text-[12px] text-muted">{when(f.at)}</p>
          <p className="mt-1 text-[15px]">{f.summary}</p>
          <p className="mt-1 text-[12px] text-muted">
            NSE label: {f.label || "none"}. {SORTED_BY[f.classified_by] ?? f.classified_by}.
          </p>
          {f.pdf_url && (
            <p className="mt-1.5 text-[14px]">
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
    <section id="moves" className="scroll-mt-4">
      <SectionTitle count={moves.length}>Price and volume</SectionTitle>
      <ul className="mx-4 overflow-hidden rounded-[12px] bg-card">
        {moves.map((m) => (
          <li key={`${m.ticker}-${m.date}`} className="border-t border-line first:border-0">
            <button type="button" onClick={() => navigate(`/research/${m.ticker}`)} className="grid min-h-14 w-full grid-cols-[1fr_72px_92px] items-center gap-3 px-4 py-2.5 text-left">
              <span className="min-w-0">
                <span className="block text-[15px] font-semibold">{m.ticker}</span>
                <span className="tabular block truncate text-[12px] text-muted">
                  Rs {inr(m.close, 0)} · {when(`${m.date}T15:30:00`).replace(/ 15:30$/, "")}
                </span>
              </span>
              <Sparkline values={m.spark} />
              <span className="text-right">
                <Pct value={m.move_pct} className="block text-[15px] font-semibold" />
                <span className={`tabular block text-[12px] ${m.reasons.includes("volume") ? "text-ink" : "text-muted"}`}>{m.vol_mult.toFixed(1)}x volume</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
