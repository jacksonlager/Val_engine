/**
 * One place where the engine's internal vocabulary becomes the reviewer's.
 *
 * The engine speaks in enums and snake_case keys because it has to: they are stable, they key
 * CSS classes, and they are what the ledger records. None of that belongs on a screen a CFO
 * reads. Every map here turns one of those values into words a valuation committee would use,
 * and `humanize()` is the backstop so a key nobody thought to map still arrives as prose rather
 * than as an identifier.
 *
 * Rule ids (X-101, M-080) are deliberately NOT laundered — they are the reviewer's reference
 * into the policy and the audit trail. They belong in evidence, chips and tooltips; they do not
 * belong in a headline, a button or a dialog title.
 */

/** "days_since_price" -> "Days since price". The last resort, never the first choice. */
export function humanize(k: string): string {
  const s = k.replace(/_/g, " ").trim();
  if (!s) return "—";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** BLOCK / REVIEW / MONITOR / CLEAR as a reader would say them. */
// Deliberately different words from readiness (Blocked / Needs Review / Ready): a disposition counts
// findings — "Decision required" is one or more findings that stop approval, "Confirm" is a judgment
// to ratify — while readiness says whether the engine had what it needed. The two are not the same axis.
export const DISPOSITION_LABEL: Record<string, string> = {
  BLOCK: "Decision required",
  REVIEW: "Confirm",
  MONITOR: "Noted",
  CLEAR: "Clear",
};

export function dispositionLabel(d: string): string {
  return DISPOSITION_LABEL[d] ?? humanize(d);
}

/** Completes "Why it …" in the finding dialog. */
export const SEVERITY_PHRASE: Record<string, string> = {
  BLOCK: "blocks approval",
  REVIEW: "needs a review",
  MONITOR: "is noted only",
  CLEAR: "is clear",
};

export function severityPhrase(s: string): string {
  return SEVERITY_PHRASE[s] ?? humanize(s).toLowerCase();
}

/** Same four values where the sentence wants an adjective: "· blocks approval · Cash runway is short". */
export const SEVERITY_SHORT: Record<string, string> = {
  BLOCK: "blocks approval",
  REVIEW: "needs review",
  MONITOR: "noted only",
  CLEAR: "clear",
};

export function severityShort(s: string): string {
  return SEVERITY_SHORT[s] ?? humanize(s).toLowerCase();
}

/**
 * What each family is about, in a reviewer's words — the fallback when the rule catalogue
 * (rules/rationale.yaml, served at /api/rationale) is not loaded.
 */
export const FAMILY_LABEL: Record<string, string> = {
  treatment: "How this event should be treated",
  staleness: "The price behind this mark is old",
  growth: "Revenue is going backwards",
  liquidity: "Cash runway is short",
  valuation: "The mark screens as an outlier",
  related_party: "The price came from an insider",
  notes: "The note's terms have to be read",
  data: "The workbook row needs fixing",
};

export function familyLabel(f: string): string {
  return FAMILY_LABEL[f] ?? humanize(f);
}

/** The same wording where it continues a sentence: "…needs a review: the price behind this mark is old." */
export function familyPhrase(f: string): string {
  const s = familyLabel(f);
  return s.charAt(0).toLowerCase() + s.slice(1);
}

/** Joins phrases the way a sentence would: "a", "a and b", "a, b and c". */
export function joinPhrases(xs: string[]): string {
  if (xs.length <= 1) return xs[0] ?? "";
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

/** Where the price behind a listed mark came from. */
export const PRICE_SOURCE_LABEL: Record<string, string> = {
  market_close: "Quarter-end market close",
  ipo_print: "Listing-day price",
  // the sample book carries synthetic tickers no feed can price; the note beside it says so
  "stub:seeded_to_ipo_print": "Listing-day price, seeded because no feed prices this ticker",
};

export function priceSourceLabel(s: string): string {
  return PRICE_SOURCE_LABEL[s] ?? humanize(s);
}

/** Evidence keys the engine attaches to a finding. Units are stated where a bare number misleads. */
export const EVIDENCE_LABEL: Record<string, string> = {
  months: "Months since the last priced round",
  anchor: "Priced from",
  implied_multiple: "Implied revenue multiple",
  threshold: "Threshold it crossed",
  basis: "Basis",
  screens: "Screens it failed",
  runway_months_aged: "Runway, months",
  financings_in_quarter: "Financings this quarter",
  arr: "ARR, $M",
  arr_growth: "ARR growth",
  arr_prior: "Prior-quarter ARR, $M",
  ownership_before: "Ownership before",
  ownership_after: "Ownership after",
  relative_change: "Change against the threshold",
  insider_led: "Insider-led round",
  post_money: "Post-money valuation, $M",
  prior_post_money: "Prior post-money valuation, $M",
  indicated_post_money: "Indicated post-money valuation, $M",
  indicated_mark: "Indicated mark, $M",
  valuation_cap: "Note's valuation cap, $M",
  cap_vs_last_round: "Cap against the last round",
  structure_haircut_pct: "Structure haircut",
  hc_funded_new_class: "HC funded a new share class",
  hc_investment: "HC's investment, $M",
  step_up: "Step-up on the last round",
  moic: "Multiple on invested capital",
  deal_value: "Announced deal value, $M",
  close_probability: "Probability the deal closes",
  ratio_to_last_round: "Against the last round",
  treatment: "Treatment applied",
  superseded_by: "Superseded by",
  rule: "Rule",
  price_source: "Price source",
  price_source_note: "Note on the price",
  lockup_end: "Lock-up ends",
  ipo_print_mark: "Mark at the listing-day price, $M",
  days_since_price: "Days since the last price",
  measurement_date: "Measured at",
};

export function evidenceLabel(k: string): string {
  return EVIDENCE_LABEL[k] ?? humanize(k);
}

/** What the engine did to the position this quarter, as a sentence ending. */
export const ACTION_PHRASE: Record<string, string> = {
  Carry: "carried at the prior mark",
  Revalue: "revalued this quarter",
  "Partial exit": "partially exited this quarter",
  "Full exit": "fully exited this quarter",
  "New investment": "new to the book this quarter",
  Exit: "exited this quarter",
  "Write-off": "written off this quarter",
  "Write-down": "written down this quarter",
};

export function actionPhrase(a: string): string {
  return ACTION_PHRASE[a] ?? `${a.toLowerCase()} this quarter`;
}

/** Open items carried across the quarter boundary. */
export const KIND_LABEL: Record<string, string> = {
  convertible_note: "Convertible note",
  pending_acquisition: "Pending acquisition",
  term_sheet: "Term sheet",
  ipo_lockup: "IPO lock-up",
  unconfirmed_exit: "Exit awaiting consideration",
  debt: "Loan by HC, at cost",
};

export function kindLabel(k: string): string {
  return KIND_LABEL[k] ?? humanize(k);
}

/** The alternative marks a rule can offer. */
export const ALT_LABEL: Record<string, string> = {
  at_secondary_price: "At the secondary price",
  at_full_deal_value: "At the full deal value",
  hold_prior: "Hold the prior mark",
  at_ipo_print: "At the listing-day price",
  at_market_close: "At the market close",
  calibrated_to_comps: "Calibrated to public comparables",
  with_lockup_discount: "With a lock-up discount",
  probability_weighted: "Probability-weighted",
  as_proposed: "As proposed",
  at_proceeds_price: "At the price the proceeds imply",
};

export function altLabel(k: string): string {
  return ALT_LABEL[k] ?? humanize(k);
}

/**
 * Readiness as the tail of a counted phrase: "7 positions to review", "3 positions blocked".
 * The bucket names themselves (Blocked / Needs Review / Ready) are titles, not sentence parts,
 * and lowercasing them is what produced "7 needs review".
 */
export const READINESS_PHRASE: Record<string, string> = {
  Blocked: "blocked",
  "Needs Review": "to review",
  Ready: "ready",
};

export function readinessPhrase(r: string): string {
  return READINESS_PHRASE[r] ?? humanize(r).toLowerCase();
}

/** How a quarter was released. Reads inside a sentence: "Published as final". */
export const PUBLISH_STATUS_LABEL: Record<string, string> = {
  final: "final",
  proposed: "proposed",
};

export function publishStatusLabel(s: string): string {
  return PUBLISH_STATUS_LABEL[s] ?? humanize(s).toLowerCase();
}

/** What a drafted treatment would become if a reviewer took it. */
export const PROPOSED_KIND_LABEL: Record<string, string> = {
  new_rule: "Needs a new rule",
  reuse: "Reuses an existing rule",
};

export function proposedKindLabel(k: string): string {
  return PROPOSED_KIND_LABEL[k] ?? humanize(k);
}

/** Where a drafted treatment stands. Reads after "Already …" on a spent button. */
export const PROPOSAL_STATUS_LABEL: Record<string, string> = {
  pending: "Awaiting a decision",
  accepted: "Accepted once",
  promoted: "Promoted to a rule",
  rejected: "Rejected",
};

export function proposalStatusLabel(s: string): string {
  return PROPOSAL_STATUS_LABEL[s] ?? humanize(s);
}

/** How a draft was produced — provenance a regulator reads, not a key=value dump. */
export const PROVENANCE_LABEL: Record<string, string> = {
  model: "Model",
  prompt_hash: "Prompt fingerprint",
  catalogue_version: "Rule catalogue version",
  ts: "Drafted",
};

export function provenanceLabel(k: string): string {
  return PROVENANCE_LABEL[k] ?? humanize(k);
}

/**
 * Where a drafted formula reads a parameter from. The path stays visible — an auditor checks it —
 * but the source it names is spelled out: "event.value" -> "The event row (value)".
 */
export const PARAM_SOURCE_ROOT: Record<string, string> = {
  event: "The event row",
  config: "A policy setting",
  policy: "A policy setting",
  position: "The position record",
  company: "The company record",
  market: "Market data",
  inputs: "The workbook row",
};

export function parameterSource(v: string): string {
  const [root, ...rest] = v.split(".");
  const head = PARAM_SOURCE_ROOT[root];
  if (!head) return humanize(v.replace(/\./g, " "));
  return rest.length ? `${head} (${rest.join(".")})` : head;
}

/**
 * The manifest's market-data source ("live:edgar+yahoo", "fixture:pitchbook@2026-09") as a
 * reader would say it. The raw string is a provider identifier, not a sentence.
 */
export function marketSourceLabel(s: string | null | undefined): string {
  if (!s) return "—";
  const [kind, rest = ""] = s.split(":", 2);
  const names = rest
    .split("@")[0]
    .split("+")
    .map((n) => ({ edgar: "EDGAR", yahoo: "Yahoo", stooq: "Stooq", pitchbook: "PitchBook" })[n] ?? humanize(n))
    .filter((n) => n && n !== "—");
  const from = names.length ? ` (${names.join(" + ")})` : "";
  if (kind === "live") return `Live${from}`;
  if (kind === "synthetic") return "Synthetic test data — invented, not observed";
  if (kind === "fixture" || kind === "stub") return `Illustrative — not live market data${from}`;
  return humanize(s);
}

/**
 * A run's identity, shortened for display. The full value stays available in the run details —
 * a reviewer needs it to tie a screenshot to a ledger entry, but never mid-sentence.
 */
export function shortRef(s: string | null | undefined, n = 8): string {
  return s ? s.slice(0, n) : "—";
}
