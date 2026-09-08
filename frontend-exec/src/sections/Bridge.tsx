import type { ExecView } from "../types";
import { Section, Delta } from "../components/ui";
import { Waterfall } from "../components/Waterfall";
import { money, shortDate, signedMoney, signedPct } from "../lib/format";

export function Bridge({ view }: { view: ExecView }) {
  const h = view.headline;
  const m = view.meta;
  const rows = view.bridge;
  const engine = rows.filter((b) => b.key !== "overrides").reduce((s, b) => s + b.delta, 0);
  const markLabel = m.status === "final" ? "Booked" : "Proposed";

  return (
    <Section
      id="bridge"
      eyebrow="Quarter over quarter"
      title={`How NAV moved from ${money(h.prior_nav, 1)} to ${money(h.booked_nav, 1)}`}
      aside={
        <>
          Net {signedMoney(h.net_movement, 1)} ({signedPct(h.net_movement_pct)}). Engine drivers {signedMoney(engine, 1)}
          {Math.abs(h.override_adjustment) > 0.005 ? <>, reviewer overrides {signedMoney(h.override_adjustment, 1)}</> : ", no reviewer overrides"}.
        </>
      }
    >
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-8 max-[1180px]:col-span-12 frame px-4 pt-4 pb-3 flex flex-col">
          <Waterfall
            prior={h.prior_nav}
            booked={h.booked_nav}
            bridge={rows}
            priorLabel={`Prior ${shortDate(m.prior_close)}`}
            bookedLabel={`${markLabel} ${shortDate(m.measurement_date)}`}
          />
          <div className="text-[11.5px] text-muted mt-2 px-1 shrink-0">
            $M. The vertical scale starts near the floor of the bridge rather than at zero so each step is legible; the
            two grey bars are totals; blue bars are cash realized, not value lost. Hover a bar for the positions behind it.
          </div>
        </div>
        <div className="col-span-4 max-[1180px]:col-span-12 frame">
          <div className="px-4 pt-3.5 pb-2 flex items-baseline justify-between">
            <div className="text-[13px] font-medium text-ink">What moved</div>
            <div className="text-[11px] text-muted">by driver, in bridge order</div>
          </div>
          <table className="tbl">
            <thead>
              <tr>
                <th>Driver</th>
                <th className="r">Positions</th>
                <th className="r">Δ $M</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.key}>
                  <td>
                    <div className="text-ink">{b.label}</div>
                    <div className="text-[11.5px] text-muted leading-snug">{b.companies.slice(0, 3).map((c) => c.company).join(", ")}{b.companies.length > 3 ? ` +${b.companies.length - 3}` : ""}</div>
                  </td>
                  <td className="r text-ink2">{b.count}</td>
                  <td className="r"><Delta v={b.delta} d={1} className="font-medium" /></td>
                </tr>
              ))}
              <tr>
                <td className="font-medium text-ink">Net movement</td>
                <td className="r text-ink2">{rows.reduce((s, b) => s + b.count, 0)}</td>
                <td className="r"><Delta v={h.net_movement} d={1} className="font-semibold" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </Section>
  );
}
