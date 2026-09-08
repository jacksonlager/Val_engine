import { useMemo, useState } from "react";
import type { CompanyRow, ExecView } from "../types";
import { Section, Chip, Delta, DeltaPct, Empty } from "../components/ui";
import { money, num, plural, signed } from "../lib/format";

type Key = "company" | "event" | "prior" | "proposed" | "booked" | "delta" | "delta_pct" | "disposition";
const ORDER: Record<string, number> = { BLOCK: 0, REVIEW: 1, MONITOR: 2, CLEAR: 3 };

const COLS: { key: Key; label: string; right?: boolean }[] = [
  { key: "company", label: "Company" },
  { key: "event", label: "Event" },
  { key: "prior", label: "Prior", right: true },
  { key: "proposed", label: "Proposed", right: true },
  { key: "booked", label: "Booked", right: true },
  { key: "delta", label: "Δ", right: true },
  { key: "delta_pct", label: "Δ %", right: true },
  { key: "disposition", label: "Review status" },
];

export function Activity({ view }: { view: ExecView }) {
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: "delta", dir: -1 });
  const rows = useMemo(() => {
    const r = [...view.events];
    const { key, dir } = sort;
    r.sort((a, b) => {
      let x: number | string, y: number | string;
      if (key === "disposition") { x = ORDER[a.disposition] ?? 9; y = ORDER[b.disposition] ?? 9; }
      else if (key === "delta") { x = Math.abs(a.delta); y = Math.abs(b.delta); }
      else { x = (a[key] ?? "") as number | string; y = (b[key] ?? "") as number | string; }
      if (typeof x === "string" || typeof y === "string") return String(x).localeCompare(String(y)) * dir;
      return (x - y) * dir;
    });
    return r;
  }, [view.events, sort]);

  const click = (key: Key) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: key === "company" || key === "event" || key === "disposition" ? 1 : -1 }));

  const overridden = view.events.filter((e) => e.overridden).length;

  return (
    <Section
      id="activity"
      eyebrow="All activity"
      title={`${plural(view.events.length, "event")} marked this quarter`}
      aside={<>Every position with an event in the quarter. Proposed is the engine's number; booked is what stands after any override{overridden ? ` (${overridden} overridden)` : ""}. Click a column to sort.</>}
    >
      <div className="frame overflow-x-auto">
        {rows.length === 0 ? (
          <Empty>No events this quarter.</Empty>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                {COLS.map((c) => (
                  <th key={c.key} className={`sortable ${c.right ? "r" : ""}`} onClick={() => click(c.key)} aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                    {c.label}
                    {sort.key === c.key && <span className="ml-1 text-ink2">{sort.dir === 1 ? "↑" : "↓"}</span>}
                  </th>
                ))}
                <th>Rule</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e: CompanyRow) => (
                <tr key={e.company}>
                  <td>
                    <div className="text-ink font-medium whitespace-nowrap">{e.company}</div>
                    <div className="text-[11.5px] text-muted whitespace-nowrap">{e.fund} · {e.sector} · {e.stage}</div>
                  </td>
                  <td className="text-ink2">{e.event}</td>
                  <td className="r text-ink2">{num(e.prior)}</td>
                  <td className={`r ${e.overridden ? "text-muted line-through" : "text-ink2"}`}>{num(e.proposed)}</td>
                  <td className="r text-ink font-medium">{num(e.booked)}</td>
                  {e.driver_kind === "realized" ? (
                    <>
                      <td className="r"><span className="num font-medium realized">{signed(e.delta)}</span></td>
                      <td className="r"><span className="num realized whitespace-nowrap">{e.driver_label ?? `Realized ${money(e.realized_quarter, 1)}`}</span></td>
                    </>
                  ) : (
                    <>
                      <td className="r"><Delta v={e.delta} className="font-medium" /></td>
                      <td className="r"><DeltaPct v={e.delta_pct} /></td>
                    </>
                  )}
                  <td><Chip d={e.disposition} /></td>
                  <td className="num text-muted text-[12px]">{e.rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Section>
  );
}
