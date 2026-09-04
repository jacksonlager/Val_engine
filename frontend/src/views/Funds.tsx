import type { ValuationRun } from "../types";
import { musd, pct, signClass, signed } from "../lib/format";
import { SectionTitle } from "../components/ui";

export function FundsView({ run, gotoCompany }: { run: ValuationRun; gotoCompany: (n: string) => void }) {
  const maxNav = Math.max(...run.rollups.map((r) => r.booked_nav), 1);
  return (
    <div className="space-y-4">
      <div className="card overflow-x-auto">
        <table className="dtable text-[12px]">
          <thead>
            <tr>
              <th>Fund</th>
              <th className="r">Companies</th>
              <th className="r">Active</th>
              <th className="r">Invested</th>
              <th className="r">Prior NAV</th>
              <th className="r">Proposed NAV</th>
              <th className="r">Booked NAV</th>
              <th className="r">Δ</th>
              <th className="r">Realized Q</th>
              <th className="r">Realized cum.</th>
              <th className="r">TVPI</th>
              <th className="r">DPI</th>
              <th className="r">RVPI</th>
              <th>Top positions · share of booked NAV</th>
            </tr>
          </thead>
          <tbody>
            {run.rollups.map((r) => {
              const d = r.proposed_nav - r.prior_nav;
              return (
                <tr key={r.fund}>
                  <td className="font-medium">{r.fund}</td>
                  <td className="r num">{r.companies}</td>
                  <td className="r num">{r.active}</td>
                  <td className="r num">{musd(r.invested)}</td>
                  <td className="r num">{musd(r.prior_nav)}</td>
                  <td className="r num">{musd(r.proposed_nav)}</td>
                  <td className={`r num ${Math.abs(r.booked_nav - r.proposed_nav) > 1e-6 ? "font-semibold" : "text-ink2"}`}>{musd(r.booked_nav)}</td>
                  <td className={`r num ${signClass(d)}`}>{signed(d)}</td>
                  <td className="r num">{musd(r.realized_quarter)}</td>
                  <td className="r num">{musd(r.realized_cumulative)}</td>
                  <td className="r num">{musd(r.tvpi)}×</td>
                  <td className="r num">{musd(r.dpi)}×</td>
                  <td className="r num">{musd(r.rvpi)}×</td>
                  <td>
                    <span className="flex flex-wrap gap-x-3 gap-y-0.5">
                      {r.top_positions.map(([name, share]) => (
                        <button key={name} className="hover:underline" onClick={() => gotoCompany(name)}>
                          {name} <span className="num text-muted">{pct(share)}</span>
                        </button>
                      ))}
                    </span>
                  </td>
                </tr>
              );
            })}
            <tr>
              <td className="font-medium">Portfolio</td>
              <td className="r num">{run.totals.positions}</td>
              <td className="r num">{run.totals.active_after}</td>
              <td className="r num">{musd(run.rollups.reduce((s, r) => s + r.invested, 0))}</td>
              <td className="r num">{musd(run.totals.prior_nav)}</td>
              <td className="r num">{musd(run.totals.proposed_nav)}</td>
              <td className="r num">{musd(run.totals.booked_nav)}</td>
              <td className={`r num ${signClass(run.totals.net_movement)}`}>{signed(run.totals.net_movement)}</td>
              <td className="r num">{musd(run.totals.realized_quarter)}</td>
              <td className="r num">{musd(run.totals.realized_cumulative)}</td>
              <td className="r num text-muted" colSpan={3}>
                top-10 concentration {pct(run.totals.top10_concentration)}
              </td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>

      <div className="card p-4">
        <SectionTitle right="$M · booked NAV">Booked NAV by fund</SectionTitle>
        <div className="space-y-2 max-w-[720px]">
          {run.rollups.map((r) => (
            <div key={r.fund} className="grid grid-cols-[72px_1fr_84px] items-center gap-3">
              <span className="text-[12px]">{r.fund}</span>
              <div className="h-[14px] rounded-r-[4px] overflow-hidden bg-hair" role="img" aria-label={`${r.fund} booked NAV ${musd(r.booked_nav, 1)}`}>
                <div className="h-full rounded-r-[4px]" style={{ width: `${(r.booked_nav / maxNav) * 100}%`, background: "var(--series-1)" }} />
              </div>
              <span className="mono text-[12px] text-right">{musd(r.booked_nav, 1)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
