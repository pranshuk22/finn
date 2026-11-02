import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ago, bps, inr, signedPct, tone } from "../format";
import type { ResultsCard } from "../types";

// ---------- layout ----------

export function Header({ eyebrow, title, sub, right }: { eyebrow?: string; title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <header className="px-4 pt-[calc(20px+env(safe-area-inset-top))] pb-4">
      {eyebrow && <p className="text-[13px] text-muted">{eyebrow}</p>}
      <div className="mt-0.5 flex items-end justify-between gap-3">
        <h1 className="font-display text-[32px] leading-tight font-semibold tracking-[-0.01em]">{title}</h1>
        {right}
      </div>
      {sub && <div className="mt-1.5 text-[14px] text-muted">{sub}</div>}
    </header>
  );
}

export function SectionTitle({ children, count, right, id }: { children: ReactNode; count?: number; right?: ReactNode; id?: string }) {
  return (
    <div id={id} className="mt-8 mb-3 flex scroll-mt-24 items-baseline gap-2 px-4">
      <h2 className="text-[17px] font-semibold">{children}</h2>
      {count != null && <span className="tabular text-[15px] text-muted">{count}</span>}
      <span className="flex-1" />
      {right}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-4 mb-2.5 rounded-[12px] bg-card p-4 ${className}`}>{children}</div>;
}

// ---------- controls ----------

/** iOS-style segmented control: one container, the selected segment raised. */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
  className = "mx-4 bg-card",
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={`grid rounded-[10px] p-[3px] ${className}`} style={{ gridTemplateColumns: `repeat(${options.length}, 1fr)` }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`h-9 rounded-[8px] text-[14px] transition-colors ${on ? "bg-sheet font-semibold text-ink shadow-[0_1px_2px_rgba(0,0,0,.25)]" : "text-muted"}`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Text tabs with an underline, for filters and section navigation. */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  className = "",
}: {
  items: { value: T; label: string; count?: number }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div role="tablist" aria-label={label} className={`no-scrollbar flex gap-5 overflow-x-auto border-b border-line px-4 ${className}`}>
      {items.map((t) => {
        const on = t.value === value;
        return (
          <button
            key={t.value}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.value)}
            className={`relative h-11 shrink-0 text-[14px] whitespace-nowrap ${on ? "font-semibold text-ink" : "text-muted"}`}
          >
            {t.label}
            {t.count != null && <span className="tabular ml-1.5 text-muted">{t.count}</span>}
            {on && <span className="absolute inset-x-0 -bottom-px h-[2px] rounded-full bg-accent-ink" />}
          </button>
        );
      })}
    </div>
  );
}

export function Button({
  children,
  onClick,
  kind = "primary",
  disabled,
  className = "",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  kind?: "primary" | "ghost";
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`h-11 rounded-[10px] px-4 text-[15px] font-semibold transition-opacity disabled:opacity-40 ${
        kind === "primary" ? "bg-accent text-on-accent" : "border border-line text-ink"
      } ${className}`}
    >
      {children}
    </button>
  );
}

/** A quiet action inside a card: icon and label, full 44 px tap height. */
export function TextAction({ children, onClick, icon, strong }: { children: ReactNode; onClick: () => void; icon?: ReactNode; strong?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={`flex h-11 items-center gap-1.5 text-[14px] ${strong ? "font-semibold text-accent-ink" : "text-muted"}`}>
      {icon}
      {children}
    </button>
  );
}

export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`relative h-[30px] w-[50px] shrink-0 rounded-full transition-colors ${on ? "bg-accent" : "bg-line"}`}
    >
      <span className={`absolute top-[3px] h-6 w-6 rounded-full bg-white shadow transition-[left] ${on ? "left-[23px]" : "left-[3px]"}`} />
    </button>
  );
}

// ---------- data ----------

export function Pct({ value, digits = 1, className = "" }: { value: number | null | undefined; digits?: number; className?: string }) {
  const t = tone(value);
  return (
    <span className={`tabular ${t === "up" ? "text-up" : t === "down" ? "text-down" : "text-muted"} ${className}`}>
      {signedPct(value, digits)}
    </span>
  );
}

export function Bps({ value }: { value: number | null | undefined }) {
  const t = tone(value);
  return <span className={`tabular text-[13px] ${t === "up" ? "text-up" : t === "down" ? "text-down" : "text-muted"}`}>{bps(value)}</span>;
}

export function Sparkline({ values, width = 72, height = 24 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <span style={{ width, height }} />;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pts = values
    .map((v, i) => `${((i * width) / (values.length - 1)).toFixed(1)},${(height - ((v - lo) / (hi - lo || 1)) * height).toFixed(1)}`)
    .join(" ");
  // Neutral on purpose: the day's move is coloured next to it; a 30-day trend in red beside "+5.2%" reads as a contradiction.
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} overflow="visible" aria-hidden>
      <polyline points={pts} fill="none" stroke="var(--text-muted)" strokeWidth="1.25" strokeLinejoin="round" />
      <circle cx={width} cy={pts.split(" ").pop()!.split(",")[1]} r="2" fill="var(--text)" />
    </svg>
  );
}

export function ResultsTable({ r }: { r: ResultsCard }) {
  return (
    <div>
      <ResultsGrid r={r} />
      <ResultsNotes r={r} />
    </div>
  );
}

export function ResultsGrid({ r }: { r: ResultsCard }) {
  return (
    <table className="w-full border-collapse text-[14px]">
      <thead>
        <tr className="text-[12px] text-muted">
          <th className="pb-1.5 text-left font-normal">{r.unit}</th>
          <th className="pb-1.5 text-right font-normal">{r.quarter}</th>
          <th className="pb-1.5 text-right font-normal">QoQ</th>
          <th className="pb-1.5 text-right font-normal">YoY</th>
        </tr>
      </thead>
      <tbody>
        {r.rows.map((row) => (
          <tr key={row.label} className="border-t border-line">
            <td className="py-[7px]">
              {row.label}
              {row.derived && <sup className="ml-0.5 text-muted">*</sup>}
            </td>
            <td className="tabular py-[7px] text-right">{inr(row.value)}</td>
            <td className="py-[7px] text-right">{r.has_prev ? <Pct value={row.qoq} /> : <span className="text-muted">n/a</span>}</td>
            <td className="py-[7px] text-right">{r.has_year_ago ? <Pct value={row.yoy} /> : <span className="text-muted">n/a</span>}</td>
          </tr>
        ))}
        {r.margins?.map((m, i) => (
          <tr key={m.label} className={i === 0 ? "border-t-2 border-line" : "border-t border-line"}>
            <td className="py-[7px] text-muted">{m.label}</td>
            <td className="tabular py-[7px] text-right">{m.now != null ? `${m.now.toFixed(1)}%` : "n/a"}</td>
            <td className="py-[7px] text-right">
              <Bps value={r.has_prev ? m.qoq_bps : null} />
            </td>
            <td className="py-[7px] text-right">
              <Bps value={r.has_year_ago ? m.yoy_bps : null} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** What FINN wants you to check about these numbers, and where they come from. */
export function ResultsNotes({ r }: { r: ResultsCard }) {
  return (
    <>
      {r.other_income_pct_of_pbt != null && (
        <p className={`mt-2 text-[12px] ${r.other_income_pct_of_pbt >= 25 ? "text-needs" : "text-muted"}`}>
          Other income is {r.other_income_pct_of_pbt.toFixed(0)}% of PBT
          {r.other_income_pct_of_pbt >= 25 && ": a large part of profit does not come from operations"}.
        </p>
      )}
      {r.tax_note && <p className="mt-2 text-[12px] text-needs">{r.tax_note}</p>}
      {r.below_ebitda && <p className="mt-2 text-[12px] text-needs">{r.below_ebitda}</p>}
      {r.suspect?.length > 0 && (
        <p className="mt-2 text-[12px] text-needs">
          Check the filing: {r.suspect.join(" and ")} {r.suspect.length > 1 ? "differ" : "differs"} from Screener by more than 10%, so
          FINN does not headline {r.suspect.length > 1 ? "them" : "it"}.
        </p>
      )}
      {r.derived && <p className="mt-2 text-[12px] text-muted">Quarter worked out from the filing: {r.derived}.</p>}
      {r.rows.some((x) => x.check) && (
        <p className="mt-2 text-[12px] text-muted">
          {r.rows
            .filter((x) => x.check)
            .map((x) => `${x.label} differs from Screener (${inr(x.check!.screener)}) by ${x.check!.diff_pct}%.`)
            .join(" ")}
        </p>
      )}
      <p className="mt-2 text-[12px] leading-relaxed text-muted">
        {r.consolidated ? "Consolidated" : "Standalone"}
        {r.rows.some((x) => x.derived) &&
          (r.is_bank ? ". *PPOP computed from the filed lines" : ". *Operating EBITDA = PBT + finance costs + depreciation - other income")}
        {r.source_url && (
          <>
            {". "}
            <ExtLink href={r.source_url}>NSE filing</ExtLink>
          </>
        )}
      </p>
    </>
  );
}

// ---------- overlays and states ----------

export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  // Callers pass a new onClose on every render. Keeping it in a ref means the focus and scroll lock below run
  // once when the sheet opens and once when it closes, not on every re-render (the Research section bar
  // re-renders on each scroll frame, and re-focusing during a scroll can stall it on iOS).
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    panel.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close.current();
    document.addEventListener("keydown", onKey);
    lockScroll(true);
    return () => {
      document.removeEventListener("keydown", onKey);
      lockScroll(false);
      prev?.focus({ preventScroll: true }); // focusing must not scroll: a jump started on close would be cancelled
    };
  }, [open]);
  if (!open) return null;
  // Rendered at the end of <body>: a sheet opened from inside the sticky section bar (backdrop-blur) or a swiped
  // card (transform) would otherwise be positioned against that element instead of the screen, which put the
  // Research section menu off screen while the page stayed locked behind it.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center" role="dialog" aria-modal="true" aria-label={title}>
      <button type="button" aria-label="Close" className="animate-fade absolute inset-0 bg-black/55" onClick={onClose} />
      <div
        ref={panel}
        tabIndex={-1}
        className="animate-sheet relative max-h-[88dvh] w-full max-w-[480px] overflow-y-auto rounded-t-[16px] bg-sheet px-4 pt-2 pb-[calc(24px+env(safe-area-inset-bottom))] outline-none"
      >
        <div className="mx-auto mb-2 h-1 w-9 rounded-full bg-line" />
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="font-display text-[20px] font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="-mr-2 h-11 px-2 text-[15px] text-accent-ink">
            Done
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function Toast({ message, action, onAction }: { message: string; action?: string; onAction?: () => void }) {
  return (
    <div
      role="status"
      className="animate-fade fixed inset-x-0 bottom-[calc(76px+env(safe-area-inset-bottom))] z-40 mx-auto flex max-w-[448px] items-center justify-between gap-3 rounded-[10px] bg-ink px-4 py-2 text-[14px] text-on-accent shadow-lg"
      style={{ width: "calc(100% - 32px)" }}
    >
      <span>{message}</span>
      {action && (
        <button type="button" onClick={onAction} className="h-9 font-semibold">
          {action}
        </button>
      )}
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2.5 px-4" aria-label="Loading" role="status">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton h-32 rounded-[12px]" />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="mx-4 rounded-[12px] border border-line p-5 text-center">
      <p className="text-ink">{message}</p>
      {onRetry && (
        <Button kind="ghost" onClick={onRetry} className="mt-4">
          Try again
        </Button>
      )}
    </div>
  );
}

export function StaleNote({ savedAt, offline, onRetry }: { savedAt: number | null; offline: boolean; onRetry: () => void }) {
  if (!savedAt) return null;
  return (
    <div className="mx-4 mb-3 flex items-center justify-between gap-3 border-b border-line pb-2 text-[13px] text-muted">
      <span>
        {offline ? "Offline." : "Could not refresh."} Showing the copy saved {ago(savedAt)}.
      </span>
      <button type="button" onClick={onRetry} className="h-9 shrink-0 font-semibold text-accent-ink">
        Retry
      </button>
    </div>
  );
}

export function ExtLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-accent-ink underline decoration-line underline-offset-[3px]">
      {children}
    </a>
  );
}

// ---------- icons (16 px, stroke) ----------

const ip = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const Icon = {
  check: () => (
    <svg {...ip}>
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  ),
  arrow: () => (
    <svg {...ip}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  ),
  doc: () => (
    <svg {...ip}>
      <path d="M7 3h7l5 5v13H7z" />
      <path d="M14 3v5h5" />
    </svg>
  ),
  bell: () => (
    <svg {...ip} width={13} height={13}>
      <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <path d="M10 20.5a2 2 0 0 0 4 0" />
    </svg>
  ),
  share: () => (
    <svg {...ip}>
      <path d="M12 4v11M8 8l4-4 4 4M5 13v6h14v-6" />
    </svg>
  ),
  chevron: () => (
    <svg {...ip}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  ),
};

/** Swipe right to finish a card, the gesture people know from mail. Touch events, not pointer events: the
 * browser cancels a pointer as soon as it might be a scroll, while touch events keep coming, and the page never
 * scrolls sideways. A vertical move is left to the page, and a swipe never counts as a tap on what is inside. */
export function Swipeable({ onSwipe, label, children }: { onSwipe: () => void; label: string; children: ReactNode }) {
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ x: number; y: number; axis: "x" | "y" | null } | null>(null);
  const swiped = useRef(false);
  const dxNow = useRef(0); // read on touchend: a fast flick can end before React re-renders with the new dx
  const THRESHOLD = 96;
  return (
    <div className="relative mx-4 mb-3">
      <div
        className="absolute inset-0 flex items-center rounded-[12px] px-5 text-[14px] font-semibold"
        style={{ background: "var(--viz-up)", color: "var(--bg)", opacity: Math.min(1, dx / THRESHOLD) }}
        aria-hidden
      >
        <Icon.check />
        <span className="ml-2">{label}</span>
      </div>
      <div
        style={{ transform: `translateX(${dx}px)`, transition: dragging ? "none" : "transform 200ms ease-out" }}
        onTouchStart={(e) => {
          const t = e.touches[0];
          start.current = { x: t.clientX, y: t.clientY, axis: null };
          swiped.current = false;
        }}
        onTouchMove={(e) => {
          const s = start.current;
          if (!s) return;
          const t = e.touches[0];
          const x = t.clientX - s.x;
          const y = t.clientY - s.y;
          if (!s.axis && Math.abs(x) + Math.abs(y) > 8) s.axis = Math.abs(x) > Math.abs(y) ? "x" : "y";
          if (s.axis !== "x") return;
          swiped.current = true;
          dxNow.current = Math.max(0, x);
          setDragging(true);
          setDx(dxNow.current);
        }}
        onTouchEnd={() => {
          const done = dxNow.current > THRESHOLD;
          dxNow.current = 0;
          start.current = null;
          setDragging(false);
          setDx(done ? 480 : 0);
          if (done) setTimeout(onSwipe, 180);
        }}
        onTouchCancel={() => {
          dxNow.current = 0;
          start.current = null;
          setDragging(false);
          setDx(0);
        }}
        onClickCapture={(e) => {
          if (swiped.current) {
            e.stopPropagation();
            e.preventDefault();
            swiped.current = false;
          }
        }}
      >
        {children}
      </div>
    </div>
  );
}

/** A number that counts up when it first appears; shown as is when the reader prefers less motion. */
export function useCountUp(target: number, ms = 500): number {
  const [n, setN] = useState(target);
  useEffect(() => {
    if (typeof matchMedia === "undefined" || matchMedia("(prefers-reduced-motion: reduce)").matches || target === 0) {
      setN(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      setN(Math.round(target * (1 - (1 - k) ** 3)));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return n;
}

/** The page stops scrolling behind an open sheet. Released before any jump, so a jump never meets a locked page. */
export function lockScroll(on: boolean): void {
  document.documentElement.style.overflow = on ? "hidden" : "";
  document.body.style.overflow = on ? "hidden" : "";
}

/** Scroll so a section's heading sits just under the sticky section bar (44px) on Research. Short jumps glide;
 * long ones are instant, because a long programmatic smooth scroll on iOS ignores the finger until it ends. */
export function jumpTo(id: string, offset = 52): void {
  const el = document.getElementById(id);
  if (!el) return;
  lockScroll(false);
  const delta = el.getBoundingClientRect().top - offset;
  window.scrollTo({ top: window.scrollY + delta, behavior: Math.abs(delta) < 1200 ? "smooth" : "auto" });
}
