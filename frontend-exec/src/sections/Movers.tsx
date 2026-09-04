import type { CompanyRow, ExecView } from "../types";
import { Section, Bar, Delta, DeltaPct, Empty } from "../components/ui";
import { num } from "../lib/format";

function MoverList({ title, rows, tone, scale }: { title: string; rows: CompanyRow[]; tone: "up" | "down"; scale: number }) {
  return (
    <div className="frame">
      <div className="px-4 pt-3.5 pb-2 flex items-baseline justify-between">
        <div className="text-[13px] font-medium text-ink">{title}</div>
        <div className="text-[11px] text-muted">booked vs prior, $M</div>
      </div>
      {rows.length === 0 ? (
        <Empty>No positions moved this way.</Empty>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Company</th>
              <th>Event</th>
              <th className="r">Prior</th>
              <th className="r">Booked</th>
              <th className="r">Δ</th>
              <th className="r">Δ %</th>
              <th style={{ width: 96 }}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.company}>
                <td>
                  <div className="text-ink font-medium whitespace-nowrap">{r.company}</div>
                  <div className="text-[11.5px] text-muted whitespace-nowrap">{r.fund} · {r.sector}</div>
                </td>
                <td className="text-ink2 text-[12px] leading-snug">{r.event}</td>
                <td className="r text-ink2">{num(r.prior)}</td>
                <td className="r text-ink">{num(r.booked)}</td>
                <td className="r"><Delta v={r.delta} className="font-medium" /></td>
                <td className="r"><DeltaPct v={r.delta_pct} /></td>
                <td className="align-middle">
                  <Bar share={Math.abs(r.delta) / scale} tone={tone} align={tone === "down" ? "right" : "left"} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function Movers({ view }: { view: ExecView }) {
  const { up, down } = view.movers;
  const scale = Math.max(1, ...up.map((r) => Math.abs(r.delta)), ...down.map((r) => Math.abs(r.delta)));
  return (
    <Section
      id="movers"
      eyebrow="Top movers"
      title="Largest mark-ups and mark-downs"
      aside={<>Bars share one scale across both lists, so magnitude reads without the digits.</>}
    >
      <div className="grid grid-cols-2 gap-3 max-[1180px]:grid-cols-1">
        <MoverList title="Mark-ups" rows={up} tone="up" scale={scale} />
        <MoverList title="Mark-downs, exits and write-offs" rows={down} tone="down" scale={scale} />
      </div>
    </Section>
  );
}
