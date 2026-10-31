import { useSyncExternalStore } from "react";

// Appearance lives on the device. index.html applies it before the first paint; this store keeps every screen
// and the <html> attributes in sync after that.

export type Theme = "slate" | "paper" | "system";
export type Accent = "taupe" | "sage" | "steel" | "ochre";
export type Typeface = "editorial" | "modern" | "classic";
export type TextSize = "standard" | "large";

export interface Settings {
  theme: Theme;
  accent: Accent;
  type: Typeface;
  size: TextSize;
}

export const DEFAULTS: Settings = { theme: "slate", accent: "taupe", type: "editorial", size: "standard" };

// Swatch colours shown in Settings, per resolved theme (same values as tokens.css).
export const ACCENTS: { value: Accent; label: string; slate: string; paper: string }[] = [
  { value: "taupe", label: "Taupe", slate: "#9e9189", paper: "#6b5d54" },
  { value: "sage", label: "Sage", slate: "#8faa9b", paper: "#46695a" },
  { value: "steel", label: "Steel", slate: "#8fa5bb", paper: "#3f5f7f" },
  { value: "ochre", label: "Ochre", slate: "#c2a46c", paper: "#7a5a1c" },
];

const KEY = "finn:settings";
const THEME_COLOR = { slate: "#2e3736", paper: "#f3f1ec" };
const mq = matchMedia("(prefers-color-scheme: light)");

function load(): Settings {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return DEFAULTS;
  }
}

let current = load();
const listeners = new Set<() => void>();

export function resolved(theme: Theme = current.theme): "slate" | "paper" {
  if (theme !== "system") return theme;
  return mq.matches ? "paper" : "slate";
}

function apply(): void {
  const d = document.documentElement;
  const t = resolved();
  d.dataset.theme = t;
  d.dataset.accent = current.accent;
  d.dataset.type = current.type;
  d.dataset.size = current.size;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[t]);
}

mq.addEventListener("change", () => {
  if (current.theme === "system") {
    apply();
    listeners.forEach((l) => l());
  }
});

export function updateSettings(patch: Partial<Settings>): void {
  current = { ...current, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    // the choice still applies for this visit
  }
  apply();
  listeners.forEach((l) => l());
}

export function useSettings(): Settings {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}
