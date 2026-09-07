// Number formatting used everywhere so the committee reads one convention.
// Marks are $M. Tables: 2 decimals. Tiles: 1 decimal. Percentages: 1 decimal.

const nf = (d: number) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export function musd(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return nf(decimals).format(v);
}

export function musdTile(v: number | null | undefined): string {
  return musd(v, 1);
}

export function signed(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (Math.abs(v) < 0.5 * Math.pow(10, -decimals)) return nf(decimals).format(0);
  return (v > 0 ? "+" : "−") + nf(decimals).format(Math.abs(v));
}

export function pct(v: number | null | undefined, decimals = 1, sign = false): string {
  if (v === null || v === undefined || Number.isNaN(v) || !Number.isFinite(v)) return "—";
  const p = v * 100;
  if (sign) return signed(p, decimals) + "%";
  return nf(decimals).format(p) + "%";
}

export function mult(v: number | null | undefined, decimals = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return nf(decimals).format(v) + "×";
}

export function months(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return nf(1).format(v) + " mo";
}

export function deltaPct(prior: number, proposed: number): number | null {
  if (!prior) return null;
  return (proposed - prior) / prior;
}

export function isoDate(s: string | null | undefined): string {
  return s ? s.slice(0, 10) : "—";
}

/** "2 Oct 2026" from an ISO timestamp; falls back to the ISO date when it does not parse. */
export function shortDate(s: string | null | undefined): string {
  if (!s) return "—";
  const t = Date.parse(s);
  if (!Number.isFinite(t)) return isoDate(s);
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(new Date(t));
}

/**
 * Relative wording only when it is informative: "just now", "12m ago", "3h ago", "2d ago"
 * within the last 7 days. Anything older, or a timestamp in the future (a fixture dated
 * ahead of today), is shown as the absolute date so it never reads as "just now".
 */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return isoDate(iso);
  const s = (now - t) / 1000;
  if (s < 0 || s >= 7 * 86400) return shortDate(iso);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function isoDateTime(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace("T", " ").replace(/\+00:00$/, "Z").slice(0, 20);
}

export function signClass(v: number | null | undefined): string {
  if (v === null || v === undefined || Math.abs(v) < 0.005) return "";
  return v > 0 ? "up" : "down";
}

// Wording — every enum, key and label a reviewer reads — lives in ./labels.
