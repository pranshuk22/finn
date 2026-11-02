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
  margins: { label: string; now: number | null; prev: number | null; year_ago: number | null; qoq_bps: number | null; yoy_bps: number | null }[];
  other_income_pct_of_pbt: number | null;
  derived: string | null; // the filing gave only six, nine or twelve months; the quarter was worked out
  suspect: string[]; // lines more than 10% away from Screener: not headlined
  tax_note: string | null; // tax, not the business, explains most of the PAT change
  below_ebitda?: string | null; // other income, interest or depreciation, not the business, explains the PBT change
  history: ({ quarter: string } & Record<string, number | null | string>)[]; // up to five quarters, oldest first
  source_url: string | null;
  broadcast_at: string | null;
  has_prev: boolean;
  has_year_ago: boolean;
  stale?: boolean; // the quarter is over about 140 days old: a newer one should exist
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
  level?: "top" | "board" | "staff";
  profile_from_filing?: string | null;
  relationship?: string | null; // to an existing director or promoter, as the filing states it
  bio?: { lines: string[]; confident: boolean; sources: Source[] } | null;
}

export interface Scale {
  amount_cr: number;
  annual_revenue_cr: number | null;
  pct_of_revenue: number | null;
  market_cap_cr: number | null;
  pct_of_market_cap: number | null;
}

export type Reaction =
  | { pending: true; state: "upcoming" | "not_loaded"; date: string }
  | { pending: false; date: string; session: string; move_pct: number; vol_mult: number | null };

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
  first_at: string;
  reaction: Reaction | null;
  ledger: { counts: Record<string, number>; promises: number } | null;
  note?: string; // e.g. a press release whose figures are on another basis than the filed results
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
  filed: { category_label: string; summary: string; at: string }[];
}

export interface Freshness {
  refreshed_at: string | null;
  filings_refreshed_at: string | null;
  last_eod_date: string | null;
}

export interface Brief {
  window_hours: number;
  since: string; // the close of the session before the window's first one, when that is earlier than the hours
  sessions?: number; // trading sessions of price moves in the window
  needs_you: BriefCard[];
  worth_knowing: BriefCard[];
  moves: Move[];
  routine: {
    count: number;
    by_category: Record<string, number>;
    // copies: NSE sometimes publishes the same filing more than once in the same second; shown once
    items: { id: number; ticker: string; at: string; summary: string; category_label: string; pdf_url: string | null; copies: number }[];
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
  stocks: { ticker: string; move_pct: number }[];
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
  years: {
    period: string;
    cfo: number | null;
    operating_profit: number | null;
    fcf: number | null;
    cfo_to_ebitda: number | null;
    cfo_to_pat: number | null;
  }[];
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
  target_low: number | null;
  target_high: number | null;
  unit: string; // percent | rs_crore | bps | other
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
  check: { status: string; actual: number | null; basis: string; definition?: string } | null; // definition: ebit, ebitda, pbdit, segment, revenue
  repeated_in?: string[]; // missing on ledgers built before 31 Oct for metrics marked "other"
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

export interface PriceStory {
  series: { date: string; close: number }[];
  events: { date: string; filings: { category_label: string; priority: string; summary: string; at: string }[] }[];
}

export interface Segment {
  name: string;
  revenue: number | null;
  result: number | null;
  share_pct: number | null;
  margin_pct: number | null;
  yoy: number | null;
  share_change_pts: number | null;
}

export interface Segments {
  quarter: string;
  period_end: string;
  source_url: string | null;
  single: string | null;
  items: Segment[];
}

export interface BalanceSheet {
  years: {
    period: string;
    debt: number | null;
    equity: number | null;
    other_liabilities: number | null;
    total: number | null;
    debt_to_equity: number | null;
    interest_coverage: number | null;
    mix: Partial<Record<"deposits" | "debt" | "equity" | "other", number | null>>;
    cwip: number | null;
  }[];
  interest_coverage: { period: string; value: number } | null;
  is_financial: boolean;
}

export interface BankQuarter {
  quarter: string;
  period_end: string;
  nii: number | null;
  nii_yoy: number | null;
  nii_to_assets: number | null; // FINN's ratio: NII x 4 over total assets
  credit_cost: number | null; // FINN's ratio: provisions x 4 over advances
  gnpa_pct: number | null;
  nnpa_pct: number | null;
  cet1_pct: number | null;
  advances: number | null;
}

export interface BankKpis {
  quarters: BankQuarter[];
  basis: string;
  source_url: string | null;
}

export interface Research {
  ticker: string;
  resolved_from: string | null;
  in_portfolio: boolean;
  snapshot: Snapshot;
  results: ResultsCard | null;
  trajectory: Trajectory | null;
  price: PriceStory | null;
  segments: Segments | null;
  cash_quality: CashQuality | null;
  balance_sheet: BalanceSheet | null;
  bank_kpis?: BankKpis | null;
  documents: { kind: string; period: string; url: string; loaded: number }[];
  ledger: Ledger | null;
  bull_bear: BullBear | null;
  jobs: Record<string, string>;
}

export interface Answer {
  covered: boolean;
  unverified?: boolean; // the model said it could answer, but nothing it said traced to a figure or a quote
  answer: string;
  figures?: { id: string; text: string; source: string; url: string | null }[]; // from the filed results
  citations: { source: string; page: number; quote: string; url: string }[];
  unverified_dropped?: number;
  removed_sentences?: number; // sentences whose number was in no source
  unmatched_numbers?: string[];
}

/** What a watchlist row shows. Prices are kept for the portfolio only, so ad-hoc companies have none. */
export interface Glance {
  ticker: string;
  name: string;
  close: number | null;
  move_pct: number | null;
  date: string | null;
  spark: number[];
  results: { quarter: string; basis: "YOY" | "QOQ"; revenue: number | null; profit_label: string; profit: number | null } | null;
}

export interface Companies {
  portfolio: (Glance & { sector: string; size: string })[];
  adhoc: Glance[];
  aliases: Record<string, string>;
}
