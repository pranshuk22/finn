import type { ReactNode } from "react";

// An icon per filing kind, beside its label, so a scan down the brief picks out results, people and legal.

const ip = {
  width: 14,
  height: 14,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

const ICONS: Record<string, ReactNode> = {
  results: <path d="M5 20V11M12 20V5M19 20v-7" />,
  management_change: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5" />
    </>
  ),
  litigation: (
    <>
      <path d="M12 4v16M7 20h10M5 8h14" />
      <path d="M5 8 3 13h4zM19 8l-2 5h4z" />
    </>
  ),
  "M&A": <path d="M4 7h7l3 5-3 5H4M20 7h-3M20 17h-3" />,
  fund_raise: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M9 8.5h6M9 11h6M12 11c2 0 3 1.2 3 2.3S13.6 15.8 9.5 15.8L14 19" />
    </>
  ),
  capex: <path d="M3 20V10l5 3V10l5 3V7l8 4v9z" />,
  credit_rating: <path d="m12 4 2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.4l-4.8 2.5.9-5.4-3.9-3.8 5.4-.8z" />,
  dividend: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 7v10M9.5 9.5c0-1.2 1.1-2 2.5-2s2.5.8 2.5 2-1.1 1.8-2.5 2.2-2.5 1-2.5 2.2 1.1 2 2.5 2 2.5-.8 2.5-2" />
    </>
  ),
  press_release: <path d="M4 10v4h3l6 4V6L7 10zM17 9a4 4 0 0 1 0 6" />,
  pledging: <path d="M7 11V8a5 5 0 0 1 10 0v3M5 11h14v9H5z" />,
  insider_trading: <path d="M4 17 9 12l3 3 8-8M15 7h5v5" />,
};

export function CategoryIcon({ category }: { category: string }) {
  return <svg {...ip}>{ICONS[category] ?? <path d="M7 4h7l4 4v12H7zM14 4v4h4" />}</svg>;
}
