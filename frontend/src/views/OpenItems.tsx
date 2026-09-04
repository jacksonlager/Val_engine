import { useMemo, useState } from "react";
import type { ValuationRun } from "../types";
import { isoDate, KIND_LABEL, musd } from "../lib/format";

function monthsBetween(a: string, b: string): number {
  const da = new Date(a), db = new Date(b);
  return (db.getFullYear() - da.getFullYear()) * 12 + (db.getMonth() - da.getMonth());
}

export function OpenItemsView({ run, gotoCompany }: { run: ValuationRun; gotoCompany: (n: string) => void }) {
  const [kind, setKind] = useState("");
  const md = run.manifest.measurement_date;
  const items = useMemo(
    () =>
      run.open_items
        .filter((o) => !kind || o.kind === kind)
        .slice()
        .sort((a, b) => Number(b.escalated) - Number(a.escalated) || b.age_quarters - a.age_quarters || a.opened.localeCompare(b.opened)),
    [run, kind],
  );
  const kinds = [...new Set(run.open_items.map((o) => o.kind))];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All kinds</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k] ?? k}
            </option>
          ))}
        </select>
        <span className="text-[11px] text-muted ml-auto">
          {items.length} item{items.length === 1 ? "" : "s"} · carried across the quarter boundary (E-07); each ages and escalates on its own
        </span>
      </div>
      <div className="card overflow-x-auto">
        <table className="dtable text-[12px]">
          <thead>
            <tr>
              <th>Company</th>
              <th>Kind</th>
              <th>Opened</th>
              <th>Expected resolution</th>
              <th className="r">Amount</th>
              <th className="r">Age</th>
              <th>Escalated</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {items.map((o, i) => (
              <tr key={i} className={o.escalated ? "disp-REVIEW" : ""}>
                <td className={o.escalated ? "stripe" : ""}>
                  <button className="font-medium hover:underline" onClick={() => gotoCompany(o.company)}>
                    {o.company}
                  </button>
                </td>
                <td>{KIND_LABEL[o.kind] ?? o.kind}</td>
                <td className="mono">
                  {isoDate(o.opened)} <span className="text-muted">{o.opened_quarter}</span>
                </td>
                <td className="mono">
                  {o.expected_resolution ? (
                    <>
                      {isoDate(o.expected_resolution)}
                      <span className="text-muted"> ({monthsBetween(md, o.expected_resolution)} mo)</span>
                    </>
                  ) : (
                    <span className="text-muted">open-ended</span>
                  )}
                </td>
                <td className="r num">{o.amount_musd === null ? "—" : musd(o.amount_musd)}</td>
                <td className="r num">
                  {o.age_quarters} q<span className="text-muted"> · {monthsBetween(o.opened, md)} mo</span>
                </td>
                <td>{o.escalated ? <span className="chip disp-REVIEW">escalated</span> : <span className="text-muted">no</span>}</td>
                <td className="whitespace-normal min-w-[280px] text-ink2">{o.detail}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center text-muted py-8">
                  No open items.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
