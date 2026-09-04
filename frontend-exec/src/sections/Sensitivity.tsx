import type { ExecView } from "../types";
import { Section, Empty } from "../components/ui";
import { humanKind, longDate, money, pct, signedMoney, signedPct } from "../lib/format";

export function Sensitivity({ view }: { view: ExecView }) {
  const s = view.sensitivity;
  const base = s.base_nav ?? view.headline.booked_nav;
  const lo = s["nav_if_multiples_-20pct"];
  const hi = s["nav_if_multiples_+20pct"];
  const exposed = s.multiple_exposed_nav;
  const has = typeof lo === "number" && typeof hi === "number";
  const span = has ? hi - lo : 1;
  const basePos = has ? ((base - lo) / span) * 100 : 50;

  return (
    <Section
      id="sensitivity"
      eyebrow="Sensitivity and open items"
      title="What could move these numbers"
      aside={<>Sensitivity re-marks every position that rests on a revenue multiple. Open items are events that have started but not yet resolved into a mark.</>}
    >
      <div className="grid grid-cols-12 gap-3 items-start">
        <div className="col-span-4 max-[1180px]:col-span-12 frame px-5 pt-4 pb-5">
          <div className="text-[13px] font-medium text-ink">Booked NAV if revenue multiples move</div>
          {typeof exposed === "number" && (
            <div className="text-[12px] text-muted mt-0.5">
              <span className="num text-ink2">{money(exposed, 1)}</span> ({pct(exposed / base)}) of NAV is multiple-exposed
            </div>
          )}
          {has ? (
            <>
              <div className="grid grid-cols-3 gap-2 mt-5">
                {[
                  { k: "−20%", v: lo },
                  { k: "Base", v: base },
                  { k: "+20%", v: hi },
                ].map((x, i) => (
                  <div key={x.k} className={i === 1 ? "text-center" : i === 0 ? "text-left" : "text-right"}>
                    <div className="eyebrow">{x.k}</div>
                    <div className={`display font-semibold leading-none mt-1 ${i === 1 ? "text-[26px] text-ink" : "text-[22px] text-ink2"}`}>{money(x.v, 1)}</div>
                    {i !== 1 && (
                      <div className={`num text-[12px] mt-1 ${i === 0 ? "down" : "up"}`}>
                        {signedMoney(x.v - base, 1)} · {signedPct((x.v - base) / base)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="relative h-2 mt-4 rounded-[3px]" style={{ background: "var(--raised-2)" }} aria-hidden>
                <div className="absolute inset-y-0 left-0 rounded-l-[3px]" style={{ width: `${basePos}%`, background: "var(--down-mark)", opacity: 0.55 }} />
                <div className="absolute inset-y-0 rounded-r-[3px]" style={{ left: `${basePos}%`, right: 0, background: "var(--up-mark)", opacity: 0.55 }} />
                <div className="absolute -top-1 w-[2px] h-4 rounded" style={{ left: `calc(${basePos}% - 1px)`, background: "var(--ink)" }} />
              </div>
            </>
          ) : (
            <Empty>No sensitivity was computed for this run.</Empty>
          )}
        </div>
        <div className="col-span-8 max-[1180px]:col-span-12 frame overflow-x-auto">
          <div className="px-4 pt-3.5 pb-2 flex items-baseline justify-between">
            <div className="text-[13px] font-medium text-ink">Open items</div>
            <div className="text-[11px] text-muted">{view.open_items.length} carried into next quarter</div>
          </div>
          {view.open_items.length === 0 ? (
            <Empty>No open items.</Empty>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Kind</th>
                  <th>Opened</th>
                  <th>Expected</th>
                  <th className="r">Amount</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {view.open_items.map((o, i) => (
                  <tr key={i}>
                    <td className="text-ink font-medium whitespace-nowrap">
                      {o.company}
                      {o.escalated && <span className="chip chip-BLOCK ml-2">Escalated</span>}
                    </td>
                    <td className="text-ink2 whitespace-nowrap">{humanKind(o.kind)}</td>
                    <td className="text-ink2 whitespace-nowrap num">{longDate(o.opened)}</td>
                    <td className="text-ink2 whitespace-nowrap num">{o.expected_resolution ? longDate(o.expected_resolution) : <span className="text-muted">not set</span>}</td>
                    <td className="r text-ink2">{o.amount != null ? money(o.amount, 1) : "—"}</td>
                    <td className="text-ink2">{o.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </Section>
  );
}
