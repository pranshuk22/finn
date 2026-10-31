import { useState } from "react";
import type { Point } from "../types";

// One series per chart, so the title names it and no legend is needed. Thin bars with rounded data ends on a
// zero baseline, a recessive axis, labels only on the first and last bar, and tap any bar to read its value.

export function Bars({
  title,
  points,
  format,
  footnote,
}: {
  title: string;
  points: Point[];
  format: (v: number) => string;
  footnote?: string;
}) {
  const data = points.filter((p): p is { period: string; value: number } => p.value != null);
  const [picked, setPicked] = useState<number | null>(null);
  if (data.length === 0) return null;

  const W = 320;
  const H = 96;
  const max = Math.max(0, ...data.map((d) => d.value));
  const min = Math.min(0, ...data.map((d) => d.value));
  const span = max - min || 1;
  const zero = (max / span) * H;
  const slot = W / data.length;
  const bar = Math.min(28, slot - 6);
  const sel = picked ?? data.length - 1;

  return (
    <figure className="m-0">
      <figcaption className="flex items-baseline justify-between gap-3">
        <span className="text-[13px] text-muted">{title}</span>
        <span className="tabular text-[13px]">
          <span className="text-muted">{data[sel].period} </span>
          <span className="font-semibold text-ink">{format(data[sel].value)}</span>
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H + 18}`} className="mt-2 block w-full" role="img" aria-label={`${title}: ${data.map((d) => `${d.period} ${format(d.value)}`).join(", ")}`}>
        <line x1="0" x2={W} y1={zero} y2={zero} stroke="var(--line)" strokeWidth="1" />
        {data.map((d, i) => {
          const h = Math.max(1, (Math.abs(d.value) / span) * H);
          const x = i * slot + (slot - bar) / 2;
          const y = d.value >= 0 ? zero - h : zero;
          const r = Math.min(4, h / 2, bar / 2);
          // round only the data end, keep the baseline end square
          const path =
            d.value >= 0
              ? `M${x},${zero} V${y + r} Q${x},${y} ${x + r},${y} H${x + bar - r} Q${x + bar},${y} ${x + bar},${y + r} V${zero} Z`
              : `M${x},${zero} V${y + h - r} Q${x},${y + h} ${x + r},${y + h} H${x + bar - r} Q${x + bar},${y + h} ${x + bar},${y + h - r} V${zero} Z`;
          return (
            <g key={d.period} onClick={() => setPicked(i)} className="cursor-pointer">
              <rect x={i * slot} y="0" width={slot} height={H + 18} fill="transparent" />
              <path d={path} fill={i === sel ? "var(--accent-text)" : "var(--accent)"} opacity={i === sel ? 1 : 0.55} />
              {(i === 0 || i === data.length - 1) && (
                <text x={i * slot + slot / 2} y={H + 14} textAnchor="middle" fontSize="11" fill="var(--text-muted)">
                  {d.period.replace(/^(\w{3}) 20(\d\d)$/, "$1 $2")}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {footnote && <p className="mt-1 text-xs text-muted">{footnote}</p>}
    </figure>
  );
}
