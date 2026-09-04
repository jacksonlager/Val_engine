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
    at_full_deal_value: "full deal value",
    hold_prior: "hold prior",
    probability_weighted: "probability-weighted",
    at_ipo_print: "at IPO print",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
