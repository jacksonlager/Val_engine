import { useMemo, useState } from "react";
import type { CompanyRow, ExecView } from "../types";
import { Section, Chip, Empty } from "../components/ui";
import { money, num, plural, signed, signedPct } from "../lib/format";

type SortKey = "company" | "fund" | "sector" | "stage" | "status" | "fv_level" | "prior" | "proposed" | "booked" | "delta" | "delta_pct" | "disposition";

const DISP_ORDER: Record<string, number> = { BLOCK: 0, REVIEW: 1, MONITOR: 2, CLEAR: 3 };

const COLUMNS: { key: SortKey; label: string; numeric?: boolean; defaultDesc?: boolean }[] = [
  { key: "company", label: "Company" },
  { key: "fund", label: "Fund" },
  { key: "sector", label: "Sector" },
  { key: "stage", label: "Stage" },
  { key: "status", label: "Status" },
  { key: "fv_level", label: "Level", numeric: true },
  { key: "prior", label: "Prior", numeric: true, defaultDesc: true },
  { key: "proposed", label: "Proposed", numeric: true, defaultDesc: true },
  { key: "booked", label: "Booked", numeric: true, defaultDesc: true },
  { key: "delta", label: "Δ", numeric: true, defaultDesc: true },
  { key: "delta_pct", label: "Δ %", numeric: true, defaultDesc: true },
  { key: "disposition", label: "Review status" },
];

function sortValue(r: CompanyRow, k: SortKey): string | number {
  switch (k) {
    case "delta":
      return Math.abs(r.delta);
    case "delta_pct":
      return r.delta_pct == null ? -1 : Math.abs(r.delta_pct);
    case "fv_level":
      return r.fv_level ?? 0;
    case "disposition":
      return DISP_ORDER[r.disposition] ?? 9;
    default:
      return r[k] as string | number;
  }
}

function compare(a: CompanyRow, b: CompanyRow, k: SortKey, desc: boolean): number {
  const va = sortValue(a, k), vb = sortValue(b, k);
  let c = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
  if (desc) c = -c;
  // Stable secondary order: fund, then size of movement, then name (the payload's default).
  if (c === 0 && k !== "fund") c = a.fund.localeCompare(b.fund);
  if (c === 0) c = Math.abs(b.delta) - Math.abs(a.delta);
  if (c === 0) c = a.company.localeCompare(b.company);
  return c;
}

function deltaClass(r: CompanyRow): string {
  if (r.driver_kind === "realized") return "realized";
  if (r.delta > 0.0005) return "up";
  if (r.delta < -0.0005) return "down";
  return "flat";
}

export function Marks({ view }: { view: ExecView }) {
  const rows = view.marks ?? [];
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "fund", desc: false });
  const proposed = view.meta.status !== "final";

  const sorted = useMemo(() => [...rows].sort((a, b) => compare(a, b, sort.key, sort.desc)), [rows, sort]);

  // From the unrounded sums when the payload carries them: adding 100 two-decimal rows drifts a
  // cent or two from the headline tile, and the two must agree on the same page.
  const totals = useMemo(() => {
    if (view.marks_totals) return view.marks_totals;
    const t = { prior: 0, proposed: 0, booked: 0 };
    for (const r of rows) {
      t.prior += r.prior;
      t.proposed += r.proposed;
      t.booked += r.booked;
    }
    return t;
  }, [rows, view.marks_totals]);

  function clickHeader(col: (typeof COLUMNS)[number]) {
    setSort((s) => (s.key === col.key ? { key: col.key, desc: !s.desc } : { key: col.key, desc: !!col.defaultDesc }));
  }

  return (
    <Section
      id="marks"
      eyebrow="Full schedule"
      title={`${proposed ? "Proposed" : "Booked"} marks — all positions`}
    >
      {rows.length === 0 ? (
        <Empty>The published snapshot carries no per-position schedule.</Empty>
      ) : (
        <div className="frame overflow-x-auto">
          <table className="tbl tbl-compact">
            <thead>
              <tr>
                {COLUMNS.map((c) => {
                  const active = sort.key === c.key;
                  return (
                    <th
                      key={c.key}
                      className={`sortable ${active ? "sorted" : ""} ${c.numeric ? "r" : ""}`}
                      onClick={() => clickHeader(c)}
                      aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
                      title={c.key === "delta" || c.key === "delta_pct" ? "Sorts by size of movement" : undefined}
                    >
                      {c.label}
                      {active && <span className="ml-1 text-ink2">{sort.desc ? "↓" : "↑"}</span>}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const cls = deltaClass(r);
                return (
                  <tr key={r.company}>
                    <td className="text-ink font-medium">{r.company}{r.overridden ? <span className="text-muted" title="Overridden by a reviewer"> *</span> : null}</td>
                    <td className="text-ink2">{r.fund}</td>
                    <td className="text-ink2">{r.sector}</td>
                    <td className="text-ink2">{r.stage}</td>
                    <td className="text-ink2">{r.status}</td>
                    <td className="r text-ink2">{r.fv_level ?? "—"}</td>
                    <td className="r text-ink2">{num(r.prior)}</td>
                    <td className="r text-ink2">{num(r.proposed)}</td>
                    <td className="r text-ink">{num(r.booked)}</td>
                    <td className={`r font-medium ${cls}`} title={r.driver_label}>{signed(r.delta)}</td>
                    <td className={`r ${cls}`} title={r.driver_label}>
                      {r.driver_kind === "realized" ? (r.driver_label ?? `Realized ${money(r.realized_quarter, 1)}`) : signedPct(r.delta_pct)}
                    </td>
                    <td><Chip d={r.disposition} /></td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td className="text-ink font-semibold" colSpan={6} style={{ borderTop: "1px solid var(--border)" }}>
                  Total · {plural(rows.length, "position")}
                  {rows.some((r) => r.overridden) && <span className="text-muted font-normal"> · * overridden by a reviewer</span>}
                </td>
                <td className="r text-ink2 font-semibold" style={{ borderTop: "1px solid var(--border)" }}>{num(totals.prior)}</td>
                <td className="r text-ink2 font-semibold" style={{ borderTop: "1px solid var(--border)" }}>{num(totals.proposed)}</td>
                <td className="r text-ink font-semibold" style={{ borderTop: "1px solid var(--border)" }}>{num(totals.booked)}</td>
                <td className={`r font-semibold ${totals.booked - totals.prior >= 0 ? "up" : "down"}`} style={{ borderTop: "1px solid var(--border)" }}>
                  {signed(totals.booked - totals.prior)}
                </td>
                <td className={`r ${totals.booked - totals.prior >= 0 ? "up" : "down"}`} style={{ borderTop: "1px solid var(--border)" }}>
                  {signedPct(totals.prior ? (totals.booked - totals.prior) / totals.prior : null)}
                </td>
                <td style={{ borderTop: "1px solid var(--border)" }}></td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </Section>
  );
}
