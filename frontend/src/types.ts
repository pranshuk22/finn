// Shapes returned by the FastAPI backend (backend/main.py, backend/analytics.py, backend/pull.py).

export type Priority = "needs_you" | "worth_knowing" | "routine";

export interface ResultRow {
  label: string;
  value: number | null;
  prev: number | null;
  year_ago: number | null;
  qoq: number | null;
  yoy: number | null;
  derived: boolean;
  check: { screener: number; diff_pct: number } | null;
}

export interface ResultsCard {
  ticker: string;
  period_end: string;
  quarter: string;
  consolidated: boolean;
  is_bank: boolean;
  unit: string;
  rows: ResultRow[];
  ebitda_margin: number | null;
  source_url: string | null;
  broadcast_at: string | null;
  has_prev: boolean;
  has_year_ago: boolean;
}

export interface Source {
  title: string;
  url: string;
}

export interface Person {
  name: string;
  role: string;
  change: string;
  senior: boolean;
  effective?: string | null;
  entity?: string | null;
  profile_from_filing?: string | null;
  bio?: { lines: string[]; confident: boolean; sources: Source[] } | null;
}

export interface Scale {
  amount_cr: number;
  annual_revenue_cr: number;
  pct_of_revenue: number;
}

export interface FilingRef {
  id: number;
  at: string;
  summary: string;
  pdf_url: string | null;
  label: string;
  classified_by: string;
}

export interface BriefCard {
  id: string;
  ticker: string;
  name: string;
  category: string;
  category_label: string;
  priority: Priority;
  latest_at: string;
  headline: string;
  alert: boolean;
  filings: FilingRef[];
  results: ResultsCard | null;
  people: Person[] | null;
  scale: Scale | null;
}

export interface Move {
  ticker: string;
  name: string;
  date: string;
  close: number;
  move_pct: number;
  vol_mult: number;
  reasons: string[];
  spark: number[];
}

export interface Freshness {
  refreshed_at: string | null;
  filings_refreshed_at: string | null;
  last_eod_date: string | null;
}

export interface Brief {
  window_hours: number;
  since: string;
  needs_you: BriefCard[];
  worth_knowing: BriefCard[];
  moves: Move[];
  routine: {
    count: number;
    by_category: Record<string, number>;
    items: { id: number; ticker: string; at: string; summary: string; category_label: string; pdf_url: string | null }[];
  };
  total_filings: number;
  portfolio_day: PortfolioDay | null;
  freshness: Freshness;
}

export interface PortfolioDay {
  date: string;
  count: number;
  of: number;
  up: number;
  down: number;
  median_pct: number;
  best: { ticker: string; move_pct: number };
  worst: { ticker: string; move_pct: number };
}

export interface AlertRules {
  price_pct: number;
  vol_mult: number;
  categories: string[];
}

export interface ScanHit {
  ticker: string;
  date: string;
  close: number;
  move_pct: number;
  vol_mult: number;
  reasons: string[];
}

export interface Scan {
  count: number;
  days: number;
  per_ticker: Record<string, number>;
  hits: ScanHit[];
}

export interface Point {
  period: string;
  value: number | null;
}

export interface Snapshot {
  ticker: string;
  name: string;
  about: string | null;
  statement_mode: string;
  is_financial: boolean;
  ratios: Record<string, number | number[] | null>;
  ttm: { revenue: number | null; net_profit: number | null; margin_label: string; margin_pct: number | null };
  source: string;
}

export interface Trajectory {
  annual: Record<string, Point[]>;
  quarterly: Record<string, Point[]>;
  growth: Record<string, Record<string, number | null>>;
}

export interface CashQuality {
  years: { period: string; cfo: number | null; fcf: number | null; cfo_to_ebitda: number | null; cfo_to_pat: number | null }[];
  cfo_to_ebitda_3y: number | null;
  working_capital: Record<string, Point[]>;
  leverage: { period: string; debt: number | null; equity: number | null; debt_to_equity: number | null }[];
  is_financial: boolean;
}

export interface LedgerItem {
  id: string;
  source: string;
  metric: string;
  metric_key: string;
  target: string;
  timeframe: string | null;
  due: string | null;
  quote: string;
  page: number;
  speaker: string | null;
  kind: string;
  source_url: string;
  assessment: {
    status: string;
    note: string;
    evidence_quote: string | null;
    evidence_source: string | null;
    evidence_page: number | null;
    evidence_url?: string | null;
  };
  check: { status: string; actual: number | null; basis: string } | null;
  repeated_in: string[];
  status: string;
  judged_by: "numbers" | "model" | "later guidance";
}

export interface Ledger {
  status: string;
  transcripts: { period: string; url: string; pages: number }[];
  items: LedgerItem[];
  counts: Record<string, number>;
  unverified_dropped: number;
  build_seconds: number;
  model: string;
  built_at: string;
  note?: string;
}

export interface BullBear {
  bull: { text: string; refs: { id: string; fact: string }[] }[];
  bear: { text: string; refs: { id: string; fact: string }[] }[];
  built_at: string;
}

export interface Research {
  ticker: string;
  resolved_from: string | null;
  in_portfolio: boolean;
  snapshot: Snapshot;
  results: ResultsCard | null;
  trajectory: Trajectory | null;
  cash_quality: CashQuality | null;
  documents: { kind: string; period: string; url: string; loaded: number }[];
  ledger: Ledger | null;
  bull_bear: BullBear | null;
  jobs: Record<string, string>;
}

export interface Answer {
  covered: boolean;
  answer: string;
  citations: { source: string; page: number; quote: string; url: string }[];
  unverified_dropped?: number;
}

export interface Companies {
  portfolio: { ticker: string; name: string; sector: string; size: string }[];
  adhoc: { ticker: string; name: string }[];
  aliases: Record<string, string>;
}
