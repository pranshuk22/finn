import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useStored } from "../api";
import { PortfolioStrip } from "../components/Charts";
import { HelpButton } from "../components/Help";
import { CategoryIcon } from "../components/Identity";
import { ResultsTiles } from "../components/ResultsTiles";
import { ErrorState, ExtLink, Icon, Pct, SectionTitle, Segmented, Sheet, Skeleton, Sparkline, StaleNote, Swipeable, TextAction, Toast, useCountUp } from "../components/ui";
import { ago, dayMonthYear, filedDate, inr, istDay, scaleLine, when } from "../format";
import { shareCard } from "../share";
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

  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    if (!note) return;
    const t = setTimeout(() => setNote(null), 2500);
    return () => clearTimeout(t);
  }, [note]);

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
        <div className="mt-0.5 flex items-center justify-between gap-3">
          <h1 className="font-display text-[34px] leading-tight font-semibold tracking-[-0.01em]">Brief</h1>
          <HelpButton topic="brief" />
        </div>
      </header>

      <div className="mt-3">
        <Segmented label="Time window" options={WINDOWS} value={hours} onChange={setHours} />
        {b?.sessions && (
          <p className="mx-4 mt-1.5 text-[12px] text-muted">
            Filings since {when(b.since)}, price moves from the last {b.sessions === 1 ? "session" : `${b.sessions} sessions`}
          </p>
        )}
      </div>

      {b && <Hero b={b} done={doneSet} finished={finished.length} total={cards.length} />}

      <div className="mt-2">
        <StaleNote savedAt={q.savedAt} offline={q.error?.status === 0} onRetry={q.reload} />
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
                    ? "Nothing in this window needs your attention."
                    : "Everything in this window is marked done."}
                  {b.freshness.filings_refreshed_at && ` Last checked ${when(b.freshness.filings_refreshed_at)}.`}
                </p>
              </div>
            )}

            <Group id="needs" title="Needs you" cards={b.needs_you.filter((c) => !doneSet.has(c.id))} onOpen={setOpen} onDone={markDone} onNote={setNote} />
            <Group id="worth" title="Worth knowing" cards={b.worth_knowing.filter((c) => !doneSet.has(c.id))} onOpen={setOpen} onDone={markDone} onNote={setNote} />

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
                          {r.copies > 1 && ` · filed ${r.copies} times`}
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
      {!toast && note && <Toast message={note} />}
    </>
  );
}

function CountUp({ n }: { n: number }) {
  return <>{useCountUp(n)}</>;
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
      <p className="px-4 pt-4 font-display text-[15px] leading-relaxed">{summarize(b, done)}</p>

      <div className="mt-4 grid grid-cols-3 border-t border-line">
        {stats.map((s, i) => (
          <button
            key={s.id}
            type="button"
            onClick={() => jump(s.id)}
            disabled={s.n === 0}
            className={`px-4 py-3 text-left ${i ? "border-l border-line" : ""}`}
          >
            <span className={`block font-display text-[28px] leading-none font-semibold ${s.n ? s.tone : "text-muted"}`}>
              <CountUp n={s.n} />
            </span>
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
          {pd.stocks?.length > 1 && <PortfolioStrip pd={pd} />}
        </div>
      )}

      {total > 0 && finished === total && (
        <div className="flex items-center gap-3 border-t border-line px-4 py-3">
          <span className="animate-pop flex h-7 w-7 items-center justify-center rounded-full bg-viz-up text-base">
            <Icon.check />
          </span>
          <span className="text-[14px]">
            You are through this brief. {total} {total === 1 ? "item" : "items"} read.
          </span>
        </div>
      )}
      {total > 0 && finished < total && (
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
  onNote,
}: {
  id: string;
  title: string;
  cards: BriefCard[];
  onOpen: (c: BriefCard) => void;
  onDone: (id: string) => void;
  onNote: (m: string) => void;
}) {
  if (cards.length === 0) return null;
  return (
    <section id={id} className="scroll-mt-4">
      <SectionTitle count={cards.length}>{title}</SectionTitle>
      {cards.map((c) => (
        <BriefCardView key={c.id} card={c} onOpen={() => onOpen(c)} onDone={() => onDone(c.id)} onNote={onNote} />
      ))}
    </section>
  );
}

function BriefCardView({ card, onOpen, onDone, onNote }: { card: BriefCard; onOpen: () => void; onDone: () => void; onNote: (m: string) => void }) {
  const dig = `/research/${card.ticker}${card.results || card.moved ? "#ledger" : ""}`;
  const body = useRef<HTMLDivElement>(null);
  const share = async () => {
    try {
      const how = await shareCard(body.current!, `${card.ticker}-${card.category}`, card.results ? "NSE results filing" : "NSE filing");
      if (how === "saved") onNote("Image saved");
    } catch {
      onNote("Could not make the image");
    }
  };
  return (
    <Swipeable onSwipe={onDone} label="Done">
      <div ref={body} className="relative overflow-hidden rounded-[12px] bg-card p-4 pb-0">
        {card.priority === "needs_you" && <span className="absolute inset-y-0 left-0 w-[3px] bg-needs" aria-hidden />}
        <div className="flex items-center gap-1.5 text-[13px] text-muted">
          <span className="font-semibold text-ink">{card.ticker}</span>
          <span aria-hidden>·</span>
          <CategoryIcon category={card.category} />
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

        {card.results && <ResultsTiles r={card.results} />}
        {!card.results && card.people && <People people={card.people} named={card.people.length === 1} />}
        {card.scale && (
          <p className="mt-2 text-[14px] text-muted">
            {scaleLine(
              card.scale.amount_cr,
              card.scale.pct_of_revenue,
              ["fund_raise", "M&A"].includes(card.category) ? card.scale.pct_of_market_cap : null,
            )}
          </p>
        )}

        {card.moved && card.moved.length > 0 && (
          <ul className="space-y-1 text-[13px] text-muted">
            {card.moved.slice(0, 3).map((m) => (
              <li key={m.metric}>
                {m.metric}: {STATUS_WORD[m.from] ?? m.from} to <span className="font-medium text-ink">{STATUS_WORD[m.to] ?? m.to}</span>
              </li>
            ))}
          </ul>
        )}
        {card.note && <p className="mt-2 text-[12px] text-muted">{card.note}</p>}
        <Facts card={card} />

        {/* wraps whole actions, never mid-label: Large text once broke "2 filings" over two lines (review, 3 Nov) */}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 border-t border-line" data-noshare>
          {card.filings.length > 0 && (
            <TextAction onClick={onOpen} icon={<Icon.doc />}>
              {filingSpan(card)}
            </TextAction>
          )}
          <span className="flex-1" />
          {card.results && (
            <button type="button" onClick={share} aria-label="Share as an image" className="flex h-11 w-9 items-center justify-center text-muted">
              <Icon.share />
            </button>
          )}
          <TextAction onClick={onDone} icon={<Icon.check />}>
            Done
          </TextAction>
          <TextAction onClick={() => navigate(dig)} strong>
            Research
            <Icon.arrow />
          </TextAction>
        </div>
      </div>
    </Swipeable>
  );
}

function filingSpan(card: BriefCard): string {
  const n = card.filings.length;
  if (n === 1) return "1 filing";
  const first = istDay(card.first_at);
  return first === istDay(card.latest_at) ? `${n} filings` : `${n} filings since ${first}`;
}

const STATUS_WORD: Record<string, string> = {
  missed: "missed",
  off_track: "off track",
  revised: "revised",
  dropped: "not mentioned again",
  delivered: "delivered",
  on_track: "on track",
  pending: "pending",
  unclear: "unclear",
  awaiting: "due, not settled",
};

/** The context a professional checks next: how the stock took it, and whether management is keeping its word. */
function Facts({ card }: { card: BriefCard }) {
  const r = card.reaction;
  const led = card.results ? card.ledger : null;
  if (!r && !led) return null;
  return (
    <div className="mt-3 space-y-1.5 text-[13px]">
      {r && !r.pending && (
        <p className="text-muted">
          Stock {r.session === "same day" ? "that day" : "next session"}: <Pct value={r.move_pct} className="font-semibold" />
          {r.vol_mult != null && (
            <span className={r.vol_mult >= 2 ? "text-ink" : ""}>, {r.vol_mult.toFixed(1)}x usual volume</span>
          )}
        </p>
      )}
      {r?.pending && (
        <p className="text-muted">
          {r.state === "upcoming" ? `Stock reaction: first session after the filing is ${dayMonthYear(r.date)}.` : `Stock reaction: price for ${dayMonthYear(r.date)} not loaded yet.`}
        </p>
      )}
      {led && (
        <button type="button" onClick={() => navigate(`/research/${card.ticker}#ledger`)} className="flex min-h-9 items-center gap-1 text-left text-accent-ink">
          {/* the two most telling counts; the full ledger is one tap away */}
          Promises:{" "}
          {Object.entries(led.counts)
            .filter(([k]) => !["pending", "unclear"].includes(k))
            .sort((a, b) => ORDER.indexOf(a[0]) - ORDER.indexOf(b[0]))
            .slice(0, 2)
            .map(([k, n]) => `${n} ${STATUS_WORD[k] ?? k}`)
            .join(", ") || `${led.promises} tracked`}
          <Icon.chevron />
        </button>
      )}
    </div>
  );
}

const ORDER = ["missed", "off_track", "revised", "dropped", "delivered", "on_track", "awaiting", "pending", "unclear"];

const LEVEL: Record<string, string> = { top: "Top management", board: "Board", staff: "Senior staff" };

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
          ) : null}
          {p.relationship && <p className="mt-1 text-[13px] font-medium">{p.relationship}, as the filing states</p>}
          {(p.level || p.effective) && (
            <p className="mt-1.5 text-[12px] text-muted">
              {p.level && LEVEL[p.level]}
              {p.entity && `, at ${p.entity}`}
              {p.effective && `${p.level ? " · " : ""}effective ${filedDate(p.effective)}`}
            </p>
          )}
          {p.bio?.confident && p.bio.lines.length > 0 ? null : p.profile_from_filing ? (
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
                <span className={`block truncate text-[12px] ${m.filed.length ? "text-accent-ink" : "text-muted"}`}>
                  {m.filed.length ? `Filed: ${[...new Set(m.filed.map((f) => f.category_label))].join(", ")}` : "No filing explains it"}
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
