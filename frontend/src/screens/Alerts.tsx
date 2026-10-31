import { useEffect, useState } from "react";
import { api, ApiError, useQuery } from "../api";
import { Button, Card, ErrorState, Header, Pct, SectionTitle, Skeleton, Switch } from "../components/ui";
import { when } from "../format";
import type { AlertRules, Scan } from "../types";

const CATEGORIES: [string, string][] = [
  ["results", "Results"],
  ["management_change", "Management"],
  ["litigation", "Litigation"],
  ["credit_rating", "Credit rating"],
  ["pledging", "Pledge"],
  ["M&A", "M&A"],
  ["fund_raise", "Fund raise"],
  ["capex", "Capex"],
  ["insider_trading", "Insider trade"],
  ["dividend", "Dividend"],
];

export function Alerts() {
  const saved = useQuery<AlertRules>("/api/alerts/rules");
  const [rules, setRules] = useState<AlertRules | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [scanErr, setScanErr] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    if (saved.data && !rules) setRules(saved.data);
  }, [saved.data, rules]);

  // Replay the thresholds over the stored price history as the sliders move.
  useEffect(() => {
    if (!rules) return;
    const t = setTimeout(() => {
      api
        .get<Scan>(`/api/alerts/scan?price_pct=${rules.price_pct}&vol_mult=${rules.vol_mult}&days=60`)
        .then((s) => {
          setScan(s);
          setScanErr(null);
        })
        .catch((e: ApiError) => setScanErr(e.message));
    }, 200);
    return () => clearTimeout(t);
  }, [rules?.price_pct, rules?.vol_mult]); // categories do not change the replay

  const update = (patch: Partial<AlertRules>) => {
    setRules((r) => (r ? { ...r, ...patch } : r));
    setStatus("idle");
  };

  const save = async () => {
    if (!rules) return;
    setStatus("saving");
    try {
      await api.put("/api/alerts/rules", rules);
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  };

  const dirty = rules && saved.data && JSON.stringify(rules) !== JSON.stringify(saved.data);
  const top = scan ? Object.entries(scan.per_ticker).sort((a, b) => b[1] - a[1]).slice(0, 5) : [];

  return (
    <>
      <Header eyebrow="What counts as unusual" title="Alerts" sub="Tune it on real data: FINN replays your thresholds over the last 60 trading sessions." />
      {!rules && saved.loading && <Skeleton lines={2} />}
      {!rules && saved.error && <ErrorState message={saved.error.message} onRetry={saved.reload} />}

      {rules && (
        <>
          <Card>
            <div className="text-center">
              <p className="tabular font-display text-[48px] leading-none font-semibold" aria-live="polite">
                {scan ? scan.count : "..."}
              </p>
              <p className="mt-2 text-[13px] text-muted">
                {scan
                  ? `alerts across your 18 stocks in the last ${scan.days} sessions, about ${(scan.count / Math.max(1, scan.days)).toFixed(1)} a day`
                  : "replaying..."}
              </p>
              {scanErr && <p className="mt-1 text-[13px] text-down">{scanErr}</p>}
            </div>

            <Slider
              label="Price move in a day"
              value={rules.price_pct}
              min={1}
              max={10}
              step={0.5}
              show={(v) => `±${v}%`}
              onChange={(v) => update({ price_pct: v })}
            />
            <Slider
              label="Volume against its 20-day average"
              value={rules.vol_mult}
              min={1.5}
              max={6}
              step={0.25}
              show={(v) => `${v}x`}
              onChange={(v) => update({ vol_mult: v })}
            />
          </Card>

          {top.length > 0 && (
            <>
              <SectionTitle>Who would fire most</SectionTitle>
              <ul className="mx-4">
                {top.map(([t, n]) => (
                  <li key={t} className="flex min-h-11 items-center gap-3 border-b border-line py-2">
                    <span className="w-28 font-semibold">{t}</span>
                    <span className="h-1 flex-1 overflow-hidden rounded-full bg-card">
                      <span className="block h-full rounded-full bg-accent-ink" style={{ width: `${(n / top[0][1]) * 100}%` }} />
                    </span>
                    <span className="tabular w-8 text-right text-[14px]">{n}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {scan && scan.hits.length > 0 && (
            <>
              <SectionTitle>Most recent</SectionTitle>
              <ul className="mx-4">
                {scan.hits.slice(0, 8).map((h) => (
                  <li key={`${h.ticker}-${h.date}`} className="flex min-h-11 items-center justify-between gap-3 border-b border-line py-2 text-[14px]">
                    <span>
                      <span className="font-semibold">{h.ticker}</span>
                      <span className="text-muted"> · {when(`${h.date}T15:30:00`).replace(/ 15:30$/, "")}</span>
                    </span>
                    <span className="tabular text-right">
                      <Pct value={h.move_pct} /> <span className={h.reasons.includes("volume") ? "text-ink" : "text-muted"}>{h.vol_mult.toFixed(1)}x</span>
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          <SectionTitle>Always flag these filings</SectionTitle>
          <ul className="mx-4 overflow-hidden rounded-[12px] bg-card">
            {CATEGORIES.map(([k, label]) => {
              const on = rules.categories.includes(k);
              return (
                <li key={k} className="flex min-h-12 items-center justify-between gap-3 border-t border-line px-4 first:border-0">
                  <span className="text-[15px]">{label}</span>
                  <Switch
                    label={label}
                    on={on}
                    onChange={(v) => update({ categories: v ? [...rules.categories, k] : rules.categories.filter((c) => c !== k) })}
                  />
                </li>
              );
            })}
          </ul>
          <p className="mx-4 mt-2 text-[13px] text-muted">Filings in these categories are marked in your brief even when FINN ranks them below Needs you.</p>

          <div className="mx-4 mt-6 mb-4">
            <Button onClick={save} disabled={!dirty || status === "saving"} className="w-full">
              {status === "saving" ? "Saving" : status === "saved" && !dirty ? "Saved" : "Save"}
            </Button>
            {status === "error" && <p className="mt-2 text-center text-[13px] text-down">Could not save. Check your connection.</p>}
          </div>
        </>
      )}
    </>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  show,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  show: (v: number) => string;
  onChange: (v: number) => void;
}) {
  const id = label.replace(/\W+/g, "-").toLowerCase();
  return (
    <div className="mt-6">
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-[14px] text-muted">
          {label}
        </label>
        <span className="tabular text-[17px] font-semibold">{show(value)}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 h-11 w-full accent-[var(--accent)]"
      />
    </div>
  );
}
