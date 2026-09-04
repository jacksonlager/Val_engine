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

export function shortSha(s: string, n = 8): string {
  return s ? s.slice(0, n) : "—";
}

export function isoDate(s: string | null | undefined): string {
  return s ? s.slice(0, 10) : "—";
}

export function isoDateTime(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace("T", " ").replace(/\+00:00$/, "Z").slice(0, 20);
}

export function signClass(v: number | null | undefined): string {
  if (v === null || v === undefined || Math.abs(v) < 0.005) return "";
  return v > 0 ? "up" : "down";
}

export const KIND_LABEL: Record<string, string> = {
  convertible_note: "Convertible note",
  pending_acquisition: "Pending acquisition",
  term_sheet: "Term sheet",
  ipo_lockup: "IPO lock-up",
};

export const ALT_LABEL: Record<string, string> = {
  at_secondary_price: "At secondary price",
  at_full_deal_value: "At full deal value",
  hold_prior: "Hold prior",
  at_ipo_print: "At IPO print",
  at_market_close: "At market close",
  calibrated_to_comps: "Calibrated to comps",
  with_lockup_discount: "With lock-up discount",
  probability_weighted: "Probability-weighted",
};

export function altLabel(k: string): string {
  return ALT_LABEL[k] ?? k.replace(/_/g, " ");
}
