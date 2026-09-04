// Hand-written mirror of src/hc_valuation/engine/models.py as serialised by
// ValuationRun.model_dump_json(). Dates are ISO strings; tuples become arrays.
// Keep field names and optionality identical to the pydantic models.

export type Severity = "BLOCK" | "REVIEW" | "MONITOR";
export type Disposition = "BLOCK" | "REVIEW" | "MONITOR" | "CLEAR";
export const DISPOSITIONS: Disposition[] = ["BLOCK", "REVIEW", "MONITOR", "CLEAR"];

// engine/inputs.py Status enum — values as they appear in the workbook.
export type Status = "Active" | "Acquired" | "Shut Down" | string;

export type OpenItemKind = "convertible_note" | "pending_acquisition" | "term_sheet" | "ipo_lockup";

export interface EventRef {
  sheet: string;
  row_index: number;
  event_type: string;
  date: string; // ISO date
}

export interface MarkStep {
  rule_id: string;
  rule_version: string;
  sequence: number;
  inputs: Record<string, unknown>;
  prior_value: number;
  new_value: number;
  rationale: string;
  evidence: EventRef | null;
}

export interface Flag {
  rule_id: string;
  family: string;
  severity: Severity;
  /** Why the engine cannot decide this alone. Two or three plain sentences. */
  message: string;
  /** The imperative: exactly what the reviewer must decide or check. Always "" on MONITOR. */
  action: string;
  evidence: Record<string, unknown>;
}

export interface ValidationIssue {
  rule_id: string;
  severity: Severity;
  message: string;
  sheet: string | null;
  row_index: number | null;
  company: string | null;
  blocking: boolean;
}

export interface OverrideRecord {
  company: string;
  quarter: string;
  proposed: number;
  booked: number;
  reason: string;
  approver: string;
  created_at: string; // ISO date
  rule_ids_addressed: string[];
  source_proposal: string | null;
}

export interface OpenItem {
  company: string;
  kind: OpenItemKind;
  opened: string; // ISO date
  opened_quarter: string;
  expected_resolution: string | null;
  amount_musd: number | null;
  detail: string;
  age_quarters: number;
  escalated: boolean;
}

export interface CompanyResult {
  company: string;
  fund: string;
  sector: string;
  stage: string;
  status_before: Status;
  status_after: Status;
  listed: boolean;

  prior_mark: number;
  equity_mark: number;
  note_at_cost: number;
  proposed_mark: number; // engine output, never modified
  booked_mark: number; // after E-01 override, if any
  override: OverrideRecord | null;

  ownership_before: number;
  ownership_after: number;
  invested_before: number;
  invested_after: number;
  realized_quarter: number;
  realized_cumulative: number;
  latest_post_money: number;
  staleness_anchor: string; // ISO date
  fv_level: number | null; // 1 | 2 | 3 | null for zero positions

  arr: number | null;
  arr_growth: number | null;
  runway_months_aged: number | null;
  implied_multiple: number | null;
  moic_after: number | null;

  steps: MarkStep[]; // the audit chain; proposed_mark == steps[-1].new_value
  flags: Flag[];
  disposition: Disposition;
  open_items: OpenItem[];
  alternative_marks: Record<string, number>; // e.g. at_secondary_price, hold_prior, at_ipo_print
}

export interface FundRollup {
  fund: string;
  companies: number;
  active: number;
  invested: number;
  prior_nav: number;
  proposed_nav: number;
  booked_nav: number;
  realized_quarter: number;
  realized_cumulative: number;
  tvpi: number;
  dpi: number;
  rvpi: number;
  top_positions: [string, number][]; // (company, share of booked nav)
}

export interface PortfolioTotals {
  positions: number;
  active_after: number;
  prior_nav: number;
  proposed_nav: number;
  booked_nav: number;
  net_movement: number;
  realized_quarter: number;
  realized_cumulative: number;
  written_off: number;
  exited_at_prior_mark: number;
  dispositions: Record<Disposition, number>;
  level1_positions: number;
  top10_concentration: number;
}

export interface RunManifest {
  run_id: string;
  input_sha256: string;
  input_file: string;
  policy_version: string;
  engine_version: string;
  quarter_label: string;
  measurement_date: string; // ISO date
  prior_close: string; // ISO date
  generated_at: string; // ISO datetime
  adjudication_enabled: boolean;
  market_data_source: string;
}

export interface ValuationRun {
  manifest: RunManifest;
  companies: CompanyResult[];
  rollups: FundRollup[];
  validation: ValidationIssue[];
  totals: PortfolioTotals;
  open_items: OpenItem[];
  // keys: base_nav, multiple_exposed_nav, nav_if_multiples_-20pct, nav_if_multiples_+20pct
  sensitivity: Record<string, number>;
}

// ---------------------------------------------------------------- E-09 proposals (GET /api/proposals)
// Shape follows TreatmentProposal in the build spec; `id` is the API's handle for
// POST /api/proposals/{id}/decision. Fields the API may omit are optional.

export interface Provenance {
  model?: string;
  prompt_hash?: string;
  catalogue_version?: string;
  ts?: string;
  [k: string]: unknown;
}

export interface TreatmentProposal {
  proposal_id?: string; // adjudication/schema.py handle; POST /api/proposals/{proposal_id}/decision
  id?: string; // tolerated alias
  company?: string;
  event_type?: string;
  event_signature: string;
  analogue_rule_id: string;
  proposed_kind: "reuse" | "new_rule" | string;
  formula: string;
  parameter_map: Record<string, string>;
  suggested_severity: Severity;
  rationale: string;
  missing_facts: string[];
  confidence: number; // displayed only; gates nothing
  provenance?: Provenance;
  status?: string; // pending | accepted | promoted | rejected
  decision?: Record<string, unknown> | null;
  repeat_count?: number;
}

// Body of POST /api/proposals/{id}/decision — approver and reason on every decision.
export type ProposalDecision =
  | { decision: "accept_once"; booked: number; approver: string; reason: string }
  | { decision: "promote"; approver: string; reason: string; effective_from: string }
  | { decision: "reject"; approver: string; reason: string };

export interface OverrideRequest {
  company: string;
  booked: number;
  approver: string;
  reason: string;
}

// ---------------------------------------------------------------- publish gate (api/publish.py)
// POST /api/publish freezes the current booked marks as the executive snapshot for the
// quarter; GET /api/published lists every release, newest first. `run_id` lets the review
// bar say whether the live run has moved on since executives last saw it.
export interface PublishRecord {
  quarter: string;
  slug: string;
  published_at: string; // ISO datetime
  published_by: string;
  note?: string;
  status: "proposed" | "final";
  open_blocks?: string[];
  run_id?: string;
  booked_nav: number;
}

// ---------------------------------------------------------------- provenance (GET /api/sources)
// api/sources.py — the workbook, its sheets and column letters, plus the row each company
// and event was read from, so the detail panel can cite `'Q3 2026 Activity'!E18`.
// Always optional: the UI drops references and keeps working when it is absent.

export type SheetKey = "portfolio" | "activity";

export interface SourceEvent {
  row: number;
  event_type: string;
  date: string; // ISO date
}

export interface SourceCompany {
  portfolio_row: number | null;
  events: SourceEvent[];
}

export interface SourceInputColumn {
  sheet: SheetKey | string;
  column: string;
}

export interface Sources {
  workbook: { name: string; path: string; sha256: string };
  /** sheet key -> the sheet's name in the workbook */
  sheets: Record<string, string>;
  /** sheet key -> column header -> spreadsheet letter */
  columns: Record<string, Record<string, string>>;
  /** step/flag input name -> the column it was read from; absent = computed by the engine */
  input_columns: Record<string, SourceInputColumn>;
  companies: Record<string, SourceCompany>;
}

// ---------------------------------------------------------------- market feed (GET /api/market)
// docs/market-feed.md §3 — the sector comps behind X-401/X-402 and M-080, with where they
// came from. `provider` is what was asked for; `source` is what actually answered. In the
// stub case `fetched_at` and `cache` are null and every constituent is a `fixture` with
// numeric fields null.

export type MarketProvider = "live" | "stub" | string;
export type ConstituentStatus = "ok" | "error" | "fixture";

export interface MarketConstituent {
  ticker: string;
  name: string | null;
  cik: string | null;
  status: ConstituentStatus;
  price: number | null;
  price_month: string | null; // "YYYY-MM"
  shares_m: number | null;
  market_cap_musd: number | null;
  net_cash_musd: number | null;
  ttm_revenue_musd: number | null;
  revenue_through: string | null; // ISO date
  ev_to_revenue: number | null;
  error: string | null;
}

export interface MarketSector {
  sector: string;
  positions: number; // portfolio companies in this sector
  ev_to_revenue: number; // the value in force at as_of
  as_of_month: string; // "YYYY-MM"
  source: string; // "live:edgar+yahoo@2026-09" (live:edgar+<price source>) | "fixture:pitchbook@2026-09"
  live: boolean;
  prior_quarter: number | null; // three months earlier
  qoq_pct: number | null; // fraction, e.g. 0.076
  history: Record<string, number>; // ≤ 36 months, ascending "YYYY-MM" keys
  constituents: MarketConstituent[];
}

export interface MarketCacheInfo {
  dir: string;
  hit: boolean;
  refreshable: boolean;
}

export interface MarketReport {
  provider: MarketProvider;
  source: string; // manifest label, e.g. "live:edgar+yahoo" (live:edgar+<price source>) or "stub"
  reached_live: boolean;
  as_of: string; // ISO date
  fetched_at: string | null; // ISO datetime; null when the fixture answered
  cache: MarketCacheInfo | null;
  used_by: { multiple_mode: string; calibration_enabled: boolean; note: string };
  baskets_file: string;
  errors: string[];
  sectors: MarketSector[];
}

// ---------------------------------------------------------------- mark history (api/history.py)

/** Where a point in a company's quarter-over-quarter archive came from.
    backfill  — data/mark_history.yaml, HC's own records for quarters before the engine
    published — the publish ledger (data/published/<slug>.json): the mark executives were shown
    prior     — this run's workbook Prior Mark, i.e. the previous quarter's close as carried in
    live      — this run's booked mark, not (or no longer) matching a published snapshot */
export type MarkHistorySource = "backfill" | "published" | "prior" | "live";

export interface MarkHistoryPoint {
  quarter: string; // "Q3 2026"
  slug: string; // "2026Q3"
  mark: number; // booked mark, $M (after any override)
  invested: number | null; // cumulative invested, $M
  realized: number | null; // cumulative realized, $M
  moic: number | null; // (mark + realized) / invested
  status: string | null;
  disposition: Disposition | null;
  source: MarkHistorySource;
  overridden: boolean;
  run_id: string | null;
  published_at: string | null; // ISO datetime
  note: string | null; // a disagreement between sources, or the backfill entry's own note
}

export interface MarkHistory {
  as_of_quarter: string;
  quarters: string[]; // every quarter any company has a point for, ascending
  counts: Record<MarkHistorySource, number>;
  backfill_file: string | null; // set only when the backfill file contributed points
  errors: string[];
  companies: Record<string, MarkHistoryPoint[]>; // ascending by quarter
}

declare global {
  interface Window {
    __HC_RUN__?: ValuationRun;
    __HC_PROPOSALS__?: TreatmentProposal[];
    __HC_SOURCES__?: Sources;
    __HC_MARKET__?: MarketReport;
    __HC_HISTORY__?: MarkHistory;
  }
}
