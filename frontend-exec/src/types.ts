// Mirrors the view-model built by src/hc_valuation/api/exec_view.py. All money is USD millions.

export type Disposition = "BLOCK" | "REVIEW" | "MONITOR" | "CLEAR";
export type Severity = "BLOCK" | "REVIEW" | "MONITOR";

export interface Meta {
  firm: string;
  quarter: string;
  measurement_date: string;
  prior_close: string;
  status: "proposed" | "final";
  published_at: string | null;
  published_by: string | null;
  note: string;
  run_id: string;
  policy_version: string;
  engine_version: string;
  input_file: string;
  input_sha256: string;
  market_data_source: string;
  generated_at: string;
}

export interface Headline {
  prior_nav: number;
  proposed_nav: number;
  booked_nav: number;
  net_movement: number;
  net_movement_pct: number | null;
  override_adjustment: number;
  realized_quarter: number;
  realized_cumulative: number;
  written_off: number;
  exited_at_prior_mark: number;
  exit_proceeds: number;
  positions: number;
  active: number;
  events: number;
  level1_positions: number;
  top10_concentration: number;
  dispositions: Partial<Record<Disposition, number>>;
  invested: number;
  tvpi: number;
  dpi: number;
}

export interface BridgeBar {
  key: string;
  label: string;
  note: string;
  delta: number;
  count: number;
  running_total: number;
  companies: { company: string; delta: number }[];
}

export interface CompanyRow {
  company: string;
  fund: string;
  sector: string;
  stage: string;
  status: string;
  fv_level: number | null;
  event: string;
  rule: string;
  prior: number;
  proposed: number;
  booked: number;
  delta: number;
  delta_pct: number | null;
  realized_quarter: number;
  ownership: number;
  disposition: Disposition;
  overridden: boolean;
}

export interface Action {
  rule_id: string;
  severity: Severity;
  action: string;
  message: string;
}

export interface Decision extends CompanyRow {
  actions: Action[];
  alternative_marks: Record<string, number>;
}

export interface Review extends CompanyRow {
  actions: Action[];
}

export interface Fund {
  fund: string;
  companies: number;
  active: number;
  invested: number;
  prior_nav: number;
  booked_nav: number;
  delta: number;
  delta_pct: number | null;
  realized_quarter: number;
  realized_cumulative: number;
  tvpi: number;
  dpi: number;
  rvpi: number;
  top_positions: { company: string; share: number }[];
}

export interface CompositionSlice {
  name: string;
  nav: number;
  share: number;
  count: number;
}

export interface RiskRow {
  company: string;
  fund: string;
  booked: number;
  detail: string;
  evidence: Record<string, number | string | null>;
  severity: Severity;
}

export interface OpenItem {
  company: string;
  kind: string;
  opened: string;
  expected_resolution: string | null;
  amount: number | null;
  detail: string;
  escalated: boolean;
}

export interface ExecView {
  meta: Meta;
  headline: Headline;
  bridge: BridgeBar[];
  movers: { up: CompanyRow[]; down: CompanyRow[] };
  funds: Fund[];
  composition: { by_sector: CompositionSlice[]; by_stage: CompositionSlice[]; by_fund: CompositionSlice[] };
  hierarchy: Record<string, { count: number; nav: number }>;
  decisions: Decision[];
  reviews: Review[];
  risk_watch: { short_runway: RiskRow[]; arr_contraction: RiskRow[]; stale_marks: RiskRow[] };
  sensitivity: Record<string, number>;
  open_items: OpenItem[];
  events: CompanyRow[];
  validation_issues: number;
  history?: unknown[];
}

declare global {
  interface Window {
    __HC_EXEC__?: ExecView;
  }
}
