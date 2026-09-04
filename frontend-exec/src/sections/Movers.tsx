import type { CompanyRow, DriverKind, ExecView } from "../types";
import { Section, Bar, Delta, DeltaPct, Empty } from "../components/ui";
import { money, num } from "../lib/format";

/** How a movement is coloured: realized exits are cash back, never a mark-down. */
export function toneFor(kind: DriverKind | undefined, delta: number): "up" | "down" | "realized" | "neutral" {
  if (kind === "realized") return "realized";
  if (delta > 0.0005) return "up";
  if (delta < -0.0005) return "down";
  return "neutral";
}

function MoverList({ title, rows, tone, scale, markLabel }: { title: string; rows: CompanyRow[]; tone: "up" | "down"; scale: number; markLabel: string }) {
  return (
    <div className="frame">
      <div className="px-4 pt-3.5 pb-2 flex items-baseline justify-between">
        <div className="text-[13px] font-medium text-ink">{title}</div>
        <div className="text-[11px] text-muted">{markLabel.toLowerCase()} vs prior, $M</div>
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
              <th className="r">{markLabel}</th>
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
                <td className="text-ink2 text-[12px] leading-snug">
                  {r.event}
                  {r.driver_label && <div className="text-[11px] text-muted">{r.driver_label}</div>}
                </td>
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

/** Closed acquisitions paid in cash. The mark goes to zero because the proceeds arrived, so the
    row leads with what came back rather than with a −100% figure. */
function RealizedList({ rows, scale }: { rows: CompanyRow[]; scale: number }) {
  return (
    <div className="frame">
      <div className="px-4 pt-3.5 pb-2 flex items-baseline justify-between">
        <div className="text-[13px] font-medium text-ink">Realized exits</div>
        <div className="text-[11px] text-muted">cash returned this quarter · mark released, $M</div>
      </div>
      {rows.length === 0 ? (
        <Empty>No positions were realized this quarter.</Empty>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Company</th>
              <th>Event</th>
              <th className="r">Prior mark</th>
              <th className="r">Proceeds</th>
              <th className="r">vs prior</th>
              <th className="r">Mark released</th>
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
                <td className="text-ink2 text-[12px] leading-snug">
                  {r.event}
                  <div className="text-[11px] realized font-medium">{r.driver_label ?? `Realized ${money(r.realized_quarter, 1)}`}</div>
                </td>
                <td className="r text-ink2">{num(r.prior)}</td>
                <td className="r text-ink font-medium realized">{num(r.realized_quarter)}</td>
                <td className="r">
                  <span className={`num ${r.prior > 0 ? (r.realized_quarter >= r.prior ? "up" : "down") : "flat"}`}>
                    {r.prior > 0 ? `${(r.realized_quarter / r.prior).toFixed(2)}x` : "—"}
                  </span>
                </td>
                <td className="r text-ink2">{num(r.delta)}</td>
                <td className="align-middle">
                  <Bar share={r.realized_quarter / scale} tone="realized" align="left" />
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
  const realized = view.movers.realized ?? [];
  const markLabel = view.meta.status === "final" ? "Booked" : "Proposed";
  const scale = Math.max(
    1,
    ...up.map((r) => Math.abs(r.delta)),
    ...down.map((r) => Math.abs(r.delta)),
    ...realized.map((r) => r.realized_quarter),
  );
  return (
    <Section
      id="movers"
      eyebrow="Top movers"
      title="Largest mark-ups, mark-downs and realizations"
      aside={
        <>
          Bars share one scale across all lists, so magnitude reads without the digits. Realized exits are shown apart: the
          mark is released because cash came back, not because value was lost.
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3 max-[1180px]:grid-cols-1">
        <MoverList title="Mark-ups" rows={up} tone="up" scale={scale} markLabel={markLabel} />
        <MoverList title="Mark-downs and write-offs" rows={down} tone="down" scale={scale} markLabel={markLabel} />
      </div>
      {realized.length > 0 && (
        <div className="mt-3">
          <RealizedList rows={realized} scale={scale} />
        </div>
      )}
    </Section>
  );
}
