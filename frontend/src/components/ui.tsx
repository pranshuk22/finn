import { useEffect, useRef, type ReactNode } from "react";
import { ago, inr, signedPct, tone } from "../format";
import type { ResultsCard } from "../types";

export function Header({ eyebrow, title, sub, right }: { eyebrow?: string; title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <header className="px-4 pt-[calc(16px+env(safe-area-inset-top))] pb-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {eyebrow && <p className="text-xs font-semibold tracking-[0.12em] text-muted uppercase">{eyebrow}</p>}
          <h1 className="mt-1 text-[30px] leading-tight font-semibold tracking-[-0.02em]">{title}</h1>
        </div>
        {right}
      </div>
      {sub && <div className="mt-1 text-[13px] text-muted">{sub}</div>}
    </header>
  );
}

export function SectionTitle({ children, dot, right, id }: { children: ReactNode; dot?: "needs" | "worth"; right?: ReactNode; id?: string }) {
  return (
    <h2 id={id} className="mt-6 mb-3 flex scroll-mt-20 items-center gap-2 px-4 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">
      {dot && <span className={`h-2 w-2 rounded-full ${dot === "needs" ? "bg-needs" : "bg-worth"}`} />}
      <span className="flex-1">{children}</span>
      {right}
    </h2>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-4 mb-3 rounded-card bg-card p-4 ${className}`}>{children}</div>;
}

export function Chip({ on, onClick, children, label }: { on?: boolean; onClick?: () => void; children: ReactNode; label?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-label={label}
      className={`h-9 shrink-0 rounded-full border px-3.5 text-[13px] transition-colors ${
        on ? "border-accent bg-accent font-semibold text-on-accent" : "border-line text-muted"
      }`}
    >
      {children}
    </button>
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
      className={`h-11 rounded-[14px] px-4 font-semibold transition-opacity disabled:opacity-50 ${
        kind === "primary" ? "bg-accent text-on-accent" : "border border-line text-ink"
      } ${className}`}
    >
      {children}
    </button>
  );
}

export function Pct({ value, digits = 1, className = "" }: { value: number | null | undefined; digits?: number; className?: string }) {
  const t = tone(value);
  return (
    <span className={`tabular ${t === "up" ? "text-up" : t === "down" ? "text-down" : "text-muted"} ${className}`}>
      {signedPct(value, digits)}
    </span>
  );
}

export function Sparkline({ values, width = 72, height = 24 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <span style={{ width, height }} />;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pts = values
    .map((v, i) => `${((i * width) / (values.length - 1)).toFixed(1)},${(height - ((v - lo) / (hi - lo || 1)) * height).toFixed(1)}`)
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline points={pts} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export function ResultsTable({ r }: { r: ResultsCard }) {
  return (
    <div>
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-muted">
            <th className="border-b border-line py-1.5 text-left font-medium">{r.unit}</th>
            <th className="border-b border-line py-1.5 text-right font-medium">{r.quarter}</th>
            <th className="border-b border-line py-1.5 text-right font-medium">QoQ</th>
            <th className="border-b border-line py-1.5 text-right font-medium">YoY</th>
          </tr>
        </thead>
        <tbody>
          {r.rows.map((row) => (
            <tr key={row.label} className="border-b border-line last:border-0">
              <td className="py-2">
                {row.label}
                {row.derived && <span className="ml-1 text-muted" title="Computed from the filed lines">*</span>}
              </td>
              <td className="tabular py-2 text-right">{inr(row.value)}</td>
              <td className="py-2 text-right">{r.has_prev ? <Pct value={row.qoq} /> : <span className="text-muted">n/a</span>}</td>
              <td className="py-2 text-right">{r.has_year_ago ? <Pct value={row.yoy} /> : <span className="text-muted">n/a</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {r.rows.some((x) => x.check) && (
        <p className="mt-2 text-xs text-muted">
          {r.rows
            .filter((x) => x.check)
            .map((x) => `${x.label} differs from Screener (${inr(x.check!.screener)}) by ${x.check!.diff_pct}%.`)
            .join(" ")}
        </p>
      )}
      <p className="mt-2 text-xs text-muted">
        {r.consolidated ? "Consolidated" : "Standalone"}
        {r.rows.some((x) => x.derived) && (r.is_bank ? ". * PPOP computed from the filed lines" : ". * EBITDA = PBT + finance costs + depreciation - other income")}
        {r.source_url && (
          <>
            {". "}
            <a href={r.source_url} target="_blank" rel="noreferrer" className="text-accent-ink underline underline-offset-2">
              NSE filing
            </a>
          </>
        )}
      </p>
    </div>
  );
}

export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      prev?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center" role="dialog" aria-modal="true" aria-label={title}>
      <button type="button" aria-label="Close" className="animate-fade absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        ref={panel}
        tabIndex={-1}
        className="animate-sheet relative max-h-[88dvh] w-full max-w-[480px] overflow-y-auto rounded-t-[24px] bg-sheet px-4 pt-3 pb-[calc(24px+env(safe-area-inset-bottom))] outline-none"
      >
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line" />
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="-mr-2 h-11 px-2 text-[13px] text-muted">
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-3 px-4" aria-label="Loading" role="status">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton h-28 rounded-card" />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="mx-4 rounded-card border border-line p-5 text-center">
      <p className="text-ink">{message}</p>
      {onRetry && (
        <Button kind="ghost" onClick={onRetry} className="mt-4">
          Try again
        </Button>
      )}
    </div>
  );
}

export function StaleNote({ savedAt, onRetry }: { savedAt: number | null; onRetry: () => void }) {
  if (!savedAt) return null;
  return (
    <div className="mx-4 mb-3 flex items-center justify-between gap-3 rounded-[14px] border border-line px-3 py-2 text-[13px] text-muted">
      <span>Offline. Showing the copy saved {ago(savedAt)}.</span>
      <button type="button" onClick={onRetry} className="h-9 shrink-0 font-semibold text-accent-ink">
        Retry
      </button>
    </div>
  );
}

export function ExtLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-accent-ink underline decoration-line underline-offset-2">
      {children}
    </a>
  );
}
