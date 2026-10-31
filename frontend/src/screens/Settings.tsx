import type { ReactNode } from "react";
import { useQuery, useStored } from "../api";
import { Header, SectionTitle, Segmented } from "../components/ui";
import { when } from "../format";
import { ACCENTS, resolved, updateSettings, useSettings, type Accent, type TextSize, type Theme, type Typeface } from "../settings";

interface Meta {
  freshness: { refreshed_at: string | null; filings_refreshed_at: string | null; last_eod_date: string | null };
  budget: Record<string, { used_today: number; per_day: number; exhausted: boolean } | string>;
}

const TYPEFACES: { value: Typeface; label: string; title: string; body: string }[] = [
  { value: "editorial", label: "Editorial", title: "var(--font-serif)", body: '"IBM Plex Sans", sans-serif' },
  { value: "modern", label: "Modern", title: '"IBM Plex Sans", sans-serif', body: '"IBM Plex Sans", sans-serif' },
  { value: "classic", label: "Classic", title: "var(--font-serif)", body: "var(--font-serif)" },
];

const WINDOWS = [
  { value: 24, label: "24 hours" },
  { value: 72, label: "3 days" },
  { value: 168, label: "7 days" },
  { value: 720, label: "30 days" },
];

export function SettingsScreen() {
  const s = useSettings();
  const theme = resolved(s.theme);
  const [window, setWindow] = useStored("window", 24);
  const [done, setDone] = useStored<string[]>("done", []);
  const meta = useQuery<Meta>("/api/meta");

  return (
    <>
      <Header eyebrow="On this device" title="Settings" />

      <SectionTitle>Appearance</SectionTitle>
      <Group>
        <Row label="Theme" stacked>
          <Segmented<Theme>
            label="Theme"
            value={s.theme}
            onChange={(theme) => updateSettings({ theme })}
            options={[
              { value: "slate", label: "Slate" },
              { value: "paper", label: "Paper" },
              { value: "system", label: "System" },
            ]}
            className="bg-base"
          />
        </Row>
        <Row label="Accent" stacked>
          <div role="radiogroup" aria-label="Accent colour" className="flex gap-3">
            {ACCENTS.map((a) => {
              const on = s.accent === a.value;
              return (
                <button
                  key={a.value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => updateSettings({ accent: a.value as Accent })}
                  className="flex flex-1 flex-col items-center gap-1.5"
                >
                  <span
                    className={`grid h-11 w-11 place-items-center rounded-full ring-offset-2 ring-offset-card transition ${on ? "ring-2 ring-ink" : ""}`}
                    style={{ background: theme === "paper" ? a.paper : a.slate }}
                  />
                  <span className={`text-[13px] ${on ? "font-semibold text-ink" : "text-muted"}`}>{a.label}</span>
                </button>
              );
            })}
          </div>
        </Row>
        <Row label="Typeface" stacked>
          <div role="radiogroup" aria-label="Typeface" className="grid grid-cols-3 gap-2">
            {TYPEFACES.map((t) => {
              const on = s.type === t.value;
              return (
                <button
                  key={t.value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => updateSettings({ type: t.value })}
                  className={`rounded-[10px] border px-2 py-2.5 text-left transition-colors ${on ? "border-accent-ink bg-base" : "border-line"}`}
                >
                  <span className="block text-[22px] leading-none font-semibold" style={{ fontFamily: t.title }}>
                    Aa
                  </span>
                  <span className="mt-1.5 block text-[12px] text-muted" style={{ fontFamily: t.body }}>
                    {t.label}
                  </span>
                </button>
              );
            })}
          </div>
        </Row>
        <Row label="Text size" stacked>
          <Segmented<TextSize>
            label="Text size"
            value={s.size}
            onChange={(size) => updateSettings({ size })}
            options={[
              { value: "standard", label: "Standard" },
              { value: "large", label: "Large" },
            ]}
            className="bg-base"
          />
        </Row>
      </Group>
      <p className="mx-4 mt-2 text-[13px] text-muted">Every combination keeps text at WCAG AA contrast or better.</p>

      <SectionTitle>Brief</SectionTitle>
      <Group>
        <Row label="Opens on" stacked>
          <Segmented label="Default window" value={window} onChange={setWindow} options={WINDOWS} className="bg-base" />
        </Row>
        <Row label="Items marked done">
          <button
            type="button"
            disabled={done.length === 0}
            onClick={() => setDone([])}
            className="h-11 text-[15px] text-accent-ink disabled:text-muted"
          >
            {done.length === 0 ? "None" : `Clear ${done.length}`}
          </button>
        </Row>
      </Group>

      <SectionTitle>Data</SectionTitle>
      <Group>
        <Row label="Filings checked">
          <Value>{meta.data?.freshness.filings_refreshed_at ? when(meta.data.freshness.filings_refreshed_at) : "..."}</Value>
        </Row>
        <Row label="Prices up to">
          <Value>{meta.data?.freshness.last_eod_date ? when(`${meta.data.freshness.last_eod_date}T15:30:00`).replace(/ 15:30$/, "") : "..."}</Value>
        </Row>
        <Row label="Ledger builds left today">
          <Value>{meta.data ? flashLeft(meta.data) : "..."}</Value>
        </Row>
        <Row label="Sources">
          <Value>NSE, Screener, earnings calls</Value>
        </Row>
      </Group>
      <p className="mx-4 mt-2 text-[13px] text-muted">
        Filings refresh every 30 minutes from 08:00 to 22:30 IST, prices after the close. The model's free daily quota resets at 12:30 IST.
      </p>

      <SectionTitle>About</SectionTitle>
      <Group>
        <Row label="FINN">
          <Value>ENAM challenge build, 2026</Value>
        </Row>
      </Group>
      <div className="h-8" />
    </>
  );
}

function flashLeft(m: Meta): string {
  let left = 0;
  for (const [k, v] of Object.entries(m.budget)) {
    if (typeof v === "string" || !k.endsWith("flash")) continue;
    left += Math.max(0, v.per_day - v.used_today);
  }
  return String(left);
}

function Group({ children }: { children: ReactNode }) {
  return <div className="mx-4 overflow-hidden rounded-[12px] bg-card">{children}</div>;
}

function Row({ label, children, stacked }: { label: string; children: ReactNode; stacked?: boolean }) {
  return (
    <div className={`border-t border-line px-4 first:border-0 ${stacked ? "py-3.5" : "flex min-h-12 items-center justify-between gap-4"}`}>
      <span className={`text-[15px] ${stacked ? "mb-3 block" : ""}`}>{label}</span>
      {children}
    </div>
  );
}

function Value({ children }: { children: ReactNode }) {
  return <span className="tabular text-right text-[15px] text-muted">{children}</span>;
}
