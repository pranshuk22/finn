import { scorecard, type Tone } from "../scorecard";
import type { Research } from "../types";
import { jumpTo } from "./ui";

// The company at a glance: six verdicts, each a fixed rule on the numbers further down (rules in Help), then the
// key figures. One surface with hairline dividers; colour only on the small dot beside each verdict word.

export const TONE: Record<Tone, string> = {
  good: "var(--viz-up)",
  mixed: "var(--needs-you)",
  weak: "var(--viz-down)",
  neutral: "var(--text-faint)",
};

export function Scorecard({ r, figures }: { r: Research; figures: [string, string][] }) {
  const tiles = scorecard(r);
  return (
    <section aria-label="Scorecard" className="mt-4 overflow-hidden rounded-[12px] bg-card">
      <div className="grid grid-cols-2">
        {tiles.map((t, i) => (
          <button
            key={t.key}
            type="button"
            onClick={() => jumpTo(t.section)}
            className={`px-4 py-3 text-left ${i % 2 ? "border-l border-line" : ""} ${i > 1 ? "border-t border-line" : ""}`}
          >
            <span className="block text-[12px] text-muted">{t.label}</span>
            <span className="tabular mt-0.5 block text-[19px] leading-tight font-semibold">{t.value}</span>
            <span className="mt-1 flex items-center gap-1.5 text-[12px] font-medium">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: TONE[t.tone] }} aria-hidden />
              {t.verdict}
            </span>
            <span className="mt-0.5 block text-[11px] leading-snug text-muted">{t.detail}</span>
          </button>
        ))}
      </div>
      <dl className="grid grid-cols-3 gap-y-2.5 border-t border-line px-4 py-3">
        {figures.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="truncate text-[11px] text-muted">{k}</dt>
            <dd className="tabular m-0 truncate text-[13px] font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
