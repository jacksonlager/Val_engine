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

/** "days_since_price" -> "Days since price"; "netRevenueRetention" -> "Net revenue retention".
    The last resort, never the first choice — but a vendor key nobody mapped still has to arrive
    as words rather than as an identifier. */
export function humanize(k: string): string {
  const s = k
    .replace(/_/g, " ")
    // camelCase and ALLCAPSWord boundaries, so a feed's own key names read as prose
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (!s) return "—";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** BLOCK / REVIEW / MONITOR / CLEAR as a reader would say them. */
// Deliberately different words from readiness (Blocked / Needs Review / Ready): a disposition counts
// findings — "Decision required" is one or more findings that stop approval, "Confirm" is a judgment
// to ratify — while readiness says whether the engine had what it needed. The two are not the same axis.
// Used only on individual findings now: a position carries a readiness word instead.
export const DISPOSITION_LABEL: Record<string, string> = {
  BLOCK: "Decision required",
  REVIEW: "Check to confirm",
  MONITOR: "Noted",
  CLEAR: "Clear",
};

/** "Needs Review" -> "rd-NeedsReview": the readiness CSS class. */
export function readinessClass(r: string): string {
  return `rd-${r.replace(/\s+/g, "")}`;
}

export function dispositionLabel(d: string): string {
  return DISPOSITION_LABEL[d] ?? humanize(d);
}

/** Completes "Why it …" in the finding dialog. */
export const SEVERITY_PHRASE: Record<string, string> = {
  BLOCK: "requires a decision",
  REVIEW: "needs a check to confirm",
  MONITOR: "is noted only",
  CLEAR: "is clear",
};

export function severityPhrase(s: string): string {
  return SEVERITY_PHRASE[s] ?? humanize(s).toLowerCase();
}

/** Same four values where the sentence wants an adjective: "· decision required · Cash runway is short". */
export const SEVERITY_SHORT: Record<string, string> = {
  BLOCK: "decision required",
  REVIEW: "check to confirm",
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
  // the workbook row a rule read, and the reader's own outcome on it
  row_index: "Workbook row",
  rows: "Workbook rows",
  sheet: "Workbook tab",
  event_type: "Event on the row",
  date: "Date on the row",
  detail: "Detail on the row",
  reason: "Why it could not run",
  reader_unavailable: "The note reader could not run",
  // the comparables working behind a calibrated figure (M-080)
  comps_source: "Comparables feed",
  comp_multiple_at_round: "Comparable multiple at the round",
  comp_multiple_now: "Comparable multiple now",
  comp_month_used: "Comparables priced as of",
  n_constituents_at_round: "Comparable companies at the round",
  n_constituents_now: "Comparable companies now",
  factor_raw: "Adjustment before the policy cap",
  factor_bounded: "Adjustment after the policy cap",
  bound_hit: "Held at the policy cap",
  age_months: "Age of the price, months",
  round_month: "Round priced in",
  sector: "Sector basket",
  // the figures a rule derived on the way to a mark
  prior_mark: "Prior mark, $M",
  latest_post_money: "Latest post-money valuation, $M",
  last_round_post_money: "Last round's post-money valuation, $M",
  implied_post_money: "Implied post-money valuation, $M",
  implied_from_ownership: "Implied from the ownership sold, $M",
  implied_from_deal_value: "Implied from the deal value, $M",
  implied_post_from_hc_cheque: "Implied from HC's cheque, $M",
  implied_price_source: "Where the implied price came from",
  at_last_round: "At the last round's price, $M",
  at_secondary_price: "At the secondary price, $M",
  at_implied_price: "At the implied price, $M",
  at_full_deal_value: "At the full deal value, $M",
  hold_prior: "Holding the prior mark, $M",
  probability_weighted: "Probability-weighted, $M",
  structure_adjusted: "After the structure haircut, $M",
  standalone_if_deal_breaks: "If the deal breaks, $M",
  ipo_market_cap: "Market capitalisation at listing, $M",
  measurement_date_market_cap: "Market capitalisation at the measurement date, $M",
  lockup_discount_pct: "Lock-up discount",
  new_money_basis: "New money carried at",
  remainder_basis: "Remaining stake carried at",
  non_binding: "Non-binding",
  ownership: "Ownership",
  ownership_sold: "Ownership sold",
  proceeds: "Proceeds to HC, $M",
  realized: "Realized this quarter, $M",
  status: "Status",
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
  adopt_proposed: "Adopt the revised proposal",
  structure_adjusted: "After the structure haircut",
  term_sheet_indicated: "At the term sheet's indicated value",
  at_last_round: "At the last round's price",
  at_implied_price: "At the implied price",
  at_cost: "At invested cost",
  to_cost: "Down to invested cost",
  write_to_zero: "Written to zero",
  calibrate: "Calibrated to public comparables",
  full_value: "At the full deal value",
  impair_note: "Note impaired",
};

export function altLabel(k: string): string {
  return ALT_LABEL[k] ?? humanize(k);
}

/**
 * The *value* side of an evidence or input row. The keys were always laundered; the values were
 * not, so a rule that recorded `treatment: probability_weighted` printed the identifier straight
 * onto the card. Numbers, dates and free text pass through untouched — only a machine token
 * becomes words, and the raw token stays available in the row's tooltip.
 */
const EVIDENCE_VALUE_LABEL: Record<string, string> = {
  cost: "Invested cost",
  last_round: "The last round's price",
  market_close: "The quarter-end market close",
};

export function evidenceValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v !== "string") return String(v);
  const t = v.trim();
  if (!t) return "—";
  const known = PRICE_SOURCE_LABEL[t] ?? EVIDENCE_VALUE_LABEL[t] ?? ALT_LABEL[t];
  if (known) return known;
  // a provider identifier ("live:edgar+yahoo@2026-09") is not a sentence
  if (/^(live|fixture|stub|synthetic):/.test(t)) return marketSourceLabel(t);
  // an identifier is a bare token: no spaces, machine-shaped, and not a rule id or a date
  const isToken = !/\s/.test(t) && /_|[a-z][A-Z]/.test(t) && !/^\d/.test(t);
  return isToken ? humanize(t) : plainSystemPhrase(t);
}

/**
 * Engine prose that names a machine, not a fact about the book. The note reader's failure reason
 * is the live case: "ANTHROPIC_API_KEY not set" is exactly right on a server log and exactly
 * wrong on a card a CFO reads. The finding, the severity and the row it names are untouched —
 * only the word for the missing thing changes.
 */
const SYSTEM_PHRASE: [RegExp, string][] = [
  [/ANTHROPIC_API_KEY not set/g, "no Claude API key is set on this machine"],
];

export function plainSystemPhrase(text: string): string {
  return SYSTEM_PHRASE.reduce((acc, [re, to]) => acc.replace(re, to), text);
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
