// Hand-written mirror of src/hc_valuation/engine/models.py as serialised by
// ValuationRun.model_dump_json(). Dates are ISO strings; tuples become arrays.
// Keep field names and optionality identical to the pydantic models.

export type Severity = "BLOCK" | "REVIEW" | "MONITOR";
export type Disposition = "BLOCK" | "REVIEW" | "MONITOR" | "CLEAR";
export const DISPOSITIONS: Disposition[] = ["BLOCK", "REVIEW", "MONITOR", "CLEAR"];

/** What each disposition asks of the reader. One wording, used by the queue tiles and the
    disposition filter, so the four words mean the same thing everywhere in the tool. */
export const DISPOSITION_HINT: Record<Disposition, string> = {
  BLOCK: "Decision required before booking",
  REVIEW: "Check required to confirm the mark",
  MONITOR: "Watch item; may escalate next quarter",
  CLEAR: "Nothing outstanding; book as proposed",
};

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

/** One way a reviewer could resolve a flag, with the mark it would book ($M). Accepting it
    records an E-01 override addressed to the flag's rule id; the proposal itself never moves. */
export interface Suggestion {
  key: string;
  label: string; // one sentence, imperative
  reasons: string[]; // exactly two short lines
  booked: number;
}

/** The one resolution put forward first, chosen among `suggestions` (recommend.py). `key`
    names the chosen suggestion, so `booked` is always a number the engine computed; `source`
    says who chose — the rule's policy default, or Claude (with `model`, `rationale`,
    `confidence`). `note` explains a fallback when Claude was asked for but unavailable. */
export interface Recommendation {
  key: string;
  label: string;
  reasons: string[];
  booked: number;
  source: "policy" | "claude";
  model: string | null;
  rationale: string | null;
  confidence: number | null;
  note: string | null;
}

export interface Flag {
  rule_id: string;
  family: string;
  severity: Severity;
  /** Why the engine cannot decide this alone, in full. Shown on demand, not on the card. */
  message: string;
  /** The imperative: exactly what the reviewer must decide or check. Always "" on MONITOR. */
  action: string;
  /** Two or three scannable lines, `**bold**` on the words that carry the decision.
      Always present on BLOCK and REVIEW, always empty on MONITOR (the engine enforces both).
      Empty from a server or export that predates them — the card falls back to `message`. */
  points: string[];
  /** One to three priced resolutions; empty on MONITOR and on a server that predates them. */
  suggestions: Suggestion[];
  /** The one shown first; null on MONITOR, and on a server that predates it (then the first suggestion stands in). */
  recommendation?: Recommendation | null;
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
  /** "<rule_id>/<suggestion key>" when the decision was an accepted engine suggestion. */
  source_suggestion?: string | null;
  evidence?: Record<string, unknown> | null;
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

/** Can this be booked? One per position — distinct from a Disposition, which counts findings. */
export type Readiness = "Blocked" | "Needs Review" | "Ready";
/** What happened to the position this quarter — the accounting shape, not the review state. */
export type ValuationAction =
  | "Carry" | "Revalue" | "New investment" | "Partial exit" | "Full exit" | "Write-off";
/** Has a person signed it? Nothing is booked before the quarter is published. */
export type Approval = "Not approved" | "Decision recorded" | "Approved and published";

export const READINESS: Readiness[] = ["Blocked", "Needs Review", "Ready"];

export const READINESS_HINT: Record<Readiness, string> = {
  Blocked: "Missing information — no supported final mark yet",
  "Needs Review": "A proposal exists; judgment or verification is needed",
  Ready: "Checks complete — ready for approval",
};

/** The one next step for a position, chosen across all its findings (recommend.py). `rule_id`
    names the finding it leads with and `key` the priced suggestion on it, so `booked` is always
    a number the engine computed. `covers` is which findings the chooser reads this step as
    settling — shown to the reviewer as an editable list before anything is recorded. */
export interface PositionRecommendation {
  rule_id: string;
  key: string;
  label: string;
  reasons: string[];
  booked: number;
  covers: string[];
  source: "policy" | "claude";
  model: string | null;
  rationale: string | null;
  confidence: number | null;
  note: string | null;
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
  multiple_exposed: boolean; // Level 3 with ARR at or above the screening floor: the marks a multiple regime drives

  arr: number | null;
  arr_growth: number | null;
  runway_months_aged: number | null;
  implied_multiple: number | null;
  moic_after: number | null;
  /** Readiness bucket, what happened to the position, and whether a person has signed. */
  readiness: Readiness;
  action: ValuationAction;
  approval: Approval;
  monitor: boolean;
  /** The quarter's movement split, so capital activity is never read as performance:
      closing = prior + new_investment_quarter + valuation_change_quarter − realized_quarter */
  new_investment_quarter: number;
  valuation_change_quarter: number;
  /** The single next step for this position, across its findings. Null when nothing is actionable. */
  recommendation: PositionRecommendation | null;
  /** A proposal built on a stand-in input, and the sentence saying which. */
  provisional: boolean;
  provisional_reason: string | null;

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
  /** Companies per readiness bucket — distinct from `dispositions`, which counts findings. */
  readiness: Record<string, number>;
  monitor_positions: number;
  new_investment: number;
  valuation_change: number;
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
  /** who chose each flag's recommendation: "policy" or "claude:<model>" */
  recommender?: string;
  note_reader?: string;                   // "off: <reason>" | "claude:<model>"
  note_reader_report?: {
    status: string; provider: string; model: string; reason: string;
    rows_with_text: number; rows_read: number; rows_failed: number; rows_from_cache: number; calls: number; unverified_quotes: number;
  };
}

export interface ValuationRun {
  manifest: RunManifest;
  companies: CompanyResult[];
  rollups: FundRollup[];
  validation: ValidationIssue[];
  totals: PortfolioTotals;
  open_items: OpenItem[];
  // keys: base_nav, multiple_exposed_nav, software_exposed_nav, nav_if_multiples_±20pct, nav_if_software_multiples_±20pct
  sensitivity: Record<string, number>;
  sensitivity_meta: { shock_pct: number[]; min_arr: number; software_sectors: string[] };
  /** the observed counterpart of the shock: each sector's public-comps move this quarter applied to the marks it drives */
  comps_move: CompsMove | null;
}

export interface SectorMove {
  sector: string;
  multiple_prior: number;
  multiple_now: number;
  qoq_pct: number;
  exposed_nav: number;
  delta: number;
  positions: number;
  live: boolean;
  source: string;
}

export interface CompsMove {
  prior_month: string;
  now_month: string;
  base_nav: number;
  exposed_nav: number;
  covered_nav: number;
  delta: number;
  nav_if_marked_with_comps: number;
  sectors: SectorMove[];
  all_live: boolean;
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
  briefing?: Record<string, string>; // what_happened, why_no_rule, what_it_means, suggested_course, what_to_check — prose for the reviewer
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
  /** Which flags this decision resolves. Omitted = every flag on the position. */
  rule_ids_addressed?: string[];
  source_suggestion?: string;
  /** The input a decision supplied, when it supplied one — a quarter-end price and its source. */
  evidence?: Record<string, unknown>;
}

// ---------------------------------------------------------------- publish gate (api/publish.py)
// POST /api/publish freezes the current booked marks as the executive snapshot for the
// quarter; GET /api/published lists every release, newest first. `run_id` lets the review
// bar say whether the live run has moved on since executives last saw it.
/** One workbook the served dashboard can switch to (GET /api/workbooks). A profile bundles the
    file with the policy for its quarter, the ledger its decisions land in and the market
    provider that can price its measurement date; `synthetic` marks invented test data. */
export interface WorkbookProfile {
  id: string;
  workbook: string;
  quarter: string | null;
  policy: string | null;
  ledger_dir: string;
  provider: string | null;
  synthetic: boolean;
  usable: boolean;
  reason: string;
  current: boolean;
}

/** An upload in progress (POST /api/upload, then GET /api/upload/{id}). */
export interface UploadJob {
  id: string;
  file: string;
  stage: number;
  total: number;
  stages: string[];
  message: string;
  done: boolean;
  error: string | null;
  policy_created: string | null;
  result: {
    run_id: string;
    quarter: string;
    positions: number;
    readiness: Record<string, number>;
    proposed_nav: number;
    events: number;
    blocking_issues: number;
    market_data_source: string;
    synthetic: boolean;
    ledger: string;
  } | null;
}

/** What POST /api/reset removed. */
export interface ResetResult {
  status: "empty";
  removed: string[];
  files: number;
  ledger: string;
  kept: string[];
}

export interface PublishRecord {
  quarter: string;
  slug: string;
  published_at: string; // ISO datetime
  published_by: string;
  note?: string;
  status: "proposed" | "final";
  open_blocks?: string[];
  run_id?: string;
  /** sha256 of the workbook the snapshot was made from; a different one than the loaded book is said so in the header */
  input_sha256?: string;
  booked_nav: number;
  /** a FINAL publish emits next quarter's input workbook beside the one just closed */
  next_quarter_input?: string;
  next_quarter_input_error?: string;
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
  /** inputs the engine derives rather than reads: name -> what it is arithmetic on (cited cells or policy) */
  derived_inputs?: Record<string, string>;
  companies: Record<string, SourceCompany>;
}

// ---------------------------------------------------------------- market feed (GET /api/market)
// docs/market-feed.md §3 — the sector comps behind X-401/X-402 and M-080, with where they
// came from. `provider` is what was asked for; `source` is what actually answered. In the
// stub case `fetched_at` and `cache` are null and every constituent is a `fixture` with
// numeric fields null.

export type MarketProvider = "live" | "stub" | "synthetic" | string;
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
  /** Where the share count came from and how far back — a count is evidence about *today's*
      market cap, and a concept the filer abandoned years ago is not. All optional: a report
      written before these existed simply has no provenance to show. */
  shares_basis?: string | null; // "outstanding, cover page" | "outstanding, balance sheet" | "diluted weighted average"
  shares_as_of?: string | null; // the filing date the count is taken from (ISO date)
  shares_age_days?: number | null; // measurement date minus that date
  shares_rejected?: string[] | null; // concepts passed over, each with its reason
  months_negative_ev?: number | null; // months out of the median: net cash above market cap
  months_unverified_splits?: number | null; // months out of the median: no split history, so two bases
  splits_known?: boolean | null; // split events are on file for this constituent
}

export interface MarketSector {
  sector: string;
  positions: number; // portfolio companies in this sector
  ev_to_revenue: number; // the value in force at as_of
  as_of_month: string; // "YYYY-MM"
  source: string; // "live:edgar+yahoo@2026-09" (live:edgar+<price source>) | "fixture:pitchbook@2026-09" | "synthetic:invented-test-data@2027-03"
  live: boolean;
  /** invented for a test quarter (connectors/synthetic.py); never an observation */
  synthetic?: boolean;
  prior_quarter: number | null; // three months earlier
  qoq_pct: number | null; // fraction, e.g. 0.076
  history: Record<string, number>; // ≤ 36 months, ascending "YYYY-MM" keys
  /** How many constituents sit behind each month's median — a five-name median is set by its
      third name. Empty for a fixture sector; absent from a report that predates it. */
  counts?: Record<string, number>;
  constituents: MarketConstituent[];
}

export interface MarketCacheInfo {
  dir: string;
  hit: boolean;
  refreshable: boolean;
}

/** GET /api/health `market` and POST /api/market/refresh `market`: where the comps came from and when. */
export interface MarketStatus {
  source: string | null;        // "live:edgar+yahoo" | "stub" | "synthetic:…"
  reached_live: boolean;
  fetched_at: string | null;    // ISO datetime of the fetch that filled the cache
  as_of: string | null;         // the measurement date the data is priced for
  refreshable: boolean;
  errors: number;
}

export interface MarketReport {
  provider: MarketProvider;
  source: string; // manifest label, e.g. "live:edgar+yahoo" (live:edgar+<price source>), "stub" or "synthetic:invented-test-data"
  reached_live: boolean;
  /** the numbers were invented for a test quarter; `notice` is the sentence the page must print above them */
  synthetic?: boolean;
  notice?: string;
  synthetic_file?: string;
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
  /** The flags the position carried that quarter (slim), and where they came from:
      published = a released snapshot; backfill = HC's own records; reconstructed = the
      prior-close book re-screened by the current policy; live = this run. */
  flags: { rule_id: string; severity: Severity | null; family: string | null }[];
  flags_source: "published" | "backfill" | "reconstructed" | "live" | null;
}

export interface MarkHistory {
  as_of_quarter: string;
  quarters: string[]; // every quarter any company has a point for, ascending
  counts: Record<MarkHistorySource, number>;
  backfill_file: string | null; // set only when the backfill file contributed points
  errors: string[];
  companies: Record<string, MarkHistoryPoint[]>; // ascending by quarter
}

// ---------------------------------------------------------------- vendor signals (api/signals.py)

export interface SignalMetricRow {
  key: string;
  label: string;
  vendor: number | string | null;
  workbook: number | string | null;
  delta_pct: number | null;
  material: boolean; // vendor/workbook gap beyond 10% — shown, never acted on
}

export interface CompanySignals {
  metrics: {
    reporting_period: string | null;
    source_document: string | null;
    confidence: string | null;
    rows: SignalMetricRow[];
    extra: Record<string, unknown>;
  } | null;
  news: {
    published_at: string | null;
    source_type: string | null;
    source: string | null;
    sentiment: number | null;
    relevance: number | null;
    title: string | null;
    snippet: string | null;
    topics: string[];
  }[];
}

export interface Signals {
  as_of: string;
  since: string;
  providers: Record<"metrics" | "news", { name: string; live: boolean; source: string; protocol: string }>;
  note: string;
  companies: Record<string, CompanySignals>;
}

/** Why a rule exists and why it carries its severity — rules/rationale.yaml, served at
    /api/rationale. `source` says whether the brief named the exception or we added it. */
export interface RuleRationale {
  id: string;
  name: string;
  family: string;
  severity: Severity[];
  source: "brief" | "policy";
  brief_text?: string | null;
  reads: string;
  why_flag: string;
  why_severity: string;
}

export interface RationaleGroup {
  key: string;
  title: string;
  brief_text: string | null;
}

export interface Rationale {
  version: string | null;
  groups: RationaleGroup[];
  rules: RuleRationale[];
}

declare global {
  interface Window {
    __HC_RUN__?: ValuationRun;
    __HC_RATIONALE__?: Rationale;
    __HC_PROPOSALS__?: TreatmentProposal[];
    __HC_SOURCES__?: Sources;
    __HC_MARKET__?: MarketReport;
    __HC_HISTORY__?: MarkHistory;
    __HC_SIGNALS__?: Signals;
  }
}
