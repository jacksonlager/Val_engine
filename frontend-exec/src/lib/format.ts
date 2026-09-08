// Number formatting. Real minus signs (U+2212), $M with one decimal in tiles and two in tables.

const MINUS = "−";

function fixed(x: number, d: number): string {
  return Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** $1,183.9M — unsigned money with a unit. */
export function money(x: number, d = 1): string {
  const s = `$${fixed(x, d)}M`;
  return x < 0 ? `${MINUS}${s}` : s;
}

/** Bare number for table columns whose header carries the unit. */
export function num(x: number, d = 2): string {
  return (x < 0 ? MINUS : "") + fixed(x, d);
}

/** +44.6 / −18.2 / 0.0 */
export function signed(x: number, d = 2): string {
  if (Math.abs(x) < 0.0005) return fixed(0, d);
  return (x < 0 ? MINUS : "+") + fixed(x, d);
}

/** +$44.6M */
export function signedMoney(x: number, d = 1): string {
  if (Math.abs(x) < 0.0005) return `$${fixed(0, d)}M`;
  return (x < 0 ? MINUS : "+") + `$${fixed(x, d)}M`;
}

/** +3.9% (signed); null when there is no base. */
export function signedPct(x: number | null | undefined, d = 1): string {
  if (x == null || !isFinite(x)) return "—";
  if (Math.abs(x) < 0.00005) return `${fixed(0, d)}%`;
  return (x < 0 ? MINUS : "+") + `${fixed(x * 100, d)}%`;
}

/** 44.6% (unsigned share). */
export function pct(x: number, d = 1): string {
  return `${fixed(x * 100, d)}%`;
}

/** 1.99x */
export function multiple(x: number, d = 2): string {
  return `${fixed(x, d)}x`;
}

export function dirClass(x: number): "up" | "down" | "flat" {
  if (x > 0.0005) return "up";
  if (x < -0.0005) return "down";
  return "flat";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 2026-09-30 -> 30 Sep 2026 */
export function longDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${parseInt(m[3], 10)} ${MONTHS[parseInt(m[2], 10) - 1]} ${m[1]}`;
}

/** 2026-09-30 -> 30 Sep */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${parseInt(m[3], 10)} ${MONTHS[parseInt(m[2], 10) - 1]}`;
}

/** ISO timestamp -> 4 Sep 2026, 02:13 UTC */
export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

/** convertible_note -> Convertible note */
export function humanKind(kind: string): string {
  const map: Record<string, string> = {
    convertible_note: "Convertible note",
    pending_acquisition: "Pending acquisition",
    term_sheet: "Term sheet",
    ipo_lockup: "IPO lock-up",
    secondary: "Secondary",
  };
  if (map[kind]) return map[kind];
  const s = kind.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function humanAltMark(key: string): string {
  const map: Record<string, string> = {
    at_full_deal_value: "at the full deal value",
    hold_prior: "holding the prior mark",
    probability_weighted: "probability-weighted",
    at_ipo_print: "at the listing-day price",
    at_market_close: "at the market close",
    at_secondary_price: "at the secondary price",
    at_proceeds_price: "at the price the proceeds imply",
    at_last_round: "at the last round's price",
    at_cost: "at invested cost",
    calibrated_to_comps: "calibrated to public comparables",
    structure_adjusted: "after the structure haircut",
    term_sheet_indicated: "at the term sheet's indicated value",
    with_lockup_discount: "with a lock-up discount",
    as_proposed: "as proposed",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

/**
 * The engine's four severities as an executive reads them. The *value* still drives the
 * `chip-BLOCK` / `chip-REVIEW` classes and the sort order — only the word on screen changes.
 */
const DISPOSITION_LABEL: Record<string, string> = {
  BLOCK: "Decision needed",
  REVIEW: "To review",
  MONITOR: "Monitored",
  CLEAR: "Clear",
};

export function dispositionLabel(d: string): string {
  return DISPOSITION_LABEL[d] ?? d.charAt(0) + d.slice(1).toLowerCase();
}

/**
 * "live:edgar+yahoo" is a provider identifier, not a sentence. The footer says where the numbers
 * came from in words; the raw string stays on the element's tooltip.
 */
export function marketSourceLabel(s: string | null | undefined): string {
  if (!s) return "—";
  const [kind, rest = ""] = s.split(":", 2);
  const names = rest
    .split("@")[0]
    .split("+")
    .map((n) => ({ edgar: "EDGAR", yahoo: "Yahoo", stooq: "Stooq", pitchbook: "PitchBook" })[n] ?? n)
    .filter(Boolean);
  const from = names.length ? ` (${names.join(" + ")})` : "";
  if (kind === "live") return `Live${from}`;
  if (kind === "synthetic") return "Synthetic test data — invented, not observed";
  if (kind === "fixture" || kind === "stub") return `Illustrative — not live market data${from}`;
  return s;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
