import { scorecard, type Tone } from "../scorecard";
import type { Research } from "../types";

// Six tiles that give a company's shape in a glance, each opening the section that backs it. The verdict word
// always sits beside its colour, so the colour is never the only signal.

export const TONE: Record<Tone, string> = {
  good: "var(--viz-up)",
  mixed: "var(--needs-you)",
  weak: "var(--viz-down)",
  neutral: "var(--text-faint)",
};

export function Scorecard({ r }: { r: Research }) {
  const tiles = scorecard(r);
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  return (
    <section aria-label="Scorecard" className="mt-4">
      <div className="grid grid-cols-2 gap-2">
        {tiles.map((t, i) => (
          <button
            key={t.key}
            type="button"
            onClick={() => go(t.section)}
            className="animate-rise relative overflow-hidden rounded-[12px] bg-card px-3.5 pt-3 pb-3 text-left"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            <span className="absolute inset-x-0 top-0 h-[3px]" style={{ background: TONE[t.tone] }} aria-hidden />
            <span className="block text-[12px] text-muted">{t.label}</span>
            <span className="mt-1 block text-[22px] leading-tight font-semibold">{t.value}</span>
            <span className="mt-1 flex items-center gap-1.5 text-[13px] font-semibold">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: TONE[t.tone] }} aria-hidden />
              {t.verdict}
            </span>
            <span className="mt-0.5 block text-[12px] leading-snug text-muted">{t.detail}</span>
          </button>
        ))}
      </div>
      <p className="mt-2 text-[12px] text-muted">Each verdict is a fixed rule on the numbers below. Tap a tile for the detail; the rules are in Help.</p>
    </section>
  );
}
