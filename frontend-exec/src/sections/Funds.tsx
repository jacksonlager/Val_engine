import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ExecView, Fund } from "../types";
import { Section, Delta, DeltaPct } from "../components/ui";
import { multiple, num, pct } from "../lib/format";

function FundTip({ active, payload }: { active?: boolean; payload?: { payload: Fund }[] }) {
  if (!active || !payload?.length) return null;
  const f = payload[0].payload;
  return (
    <div className="tip">
      <div className="font-medium text-ink mb-1">{f.fund}</div>
      <div className="flex justify-between gap-6"><span className="text-ink2 flex items-center gap-2"><i className="inline-block w-3 h-[2px]" style={{ background: "var(--series-2)" }} />DPI</span><span className="num text-ink font-semibold">{multiple(f.dpi)}</span></div>
      <div className="flex justify-between gap-6"><span className="text-ink2 flex items-center gap-2"><i className="inline-block w-3 h-[2px]" style={{ background: "var(--series-1)" }} />RVPI</span><span className="num text-ink font-semibold">{multiple(f.rvpi)}</span></div>
      <div className="flex justify-between gap-6 border-t border-hair mt-1 pt-1"><span className="text-ink2">TVPI</span><span className="num text-ink font-semibold">{multiple(f.tvpi)}</span></div>
    </div>
  );
}

export function Funds({ view }: { view: ExecView }) {
  const funds = view.funds;
  const word = view.meta.status === "final" ? "booked" : "proposed";
  const Word = word[0].toUpperCase() + word.slice(1);
  const maxT = Math.max(1, ...funds.map((f) => f.tvpi));
  const xMax = Math.ceil(maxT * 2) / 2 + 0.5;
  const ticks: number[] = [];
  for (let t = 0; t <= xMax + 1e-9; t += 0.5) ticks.push(t);

  return (
    <Section id="funds" eyebrow="Funds" title={`Fund performance on ${word} marks`} aside={<>TVPI = ({word} NAV + cumulative distributions) ÷ invested. DPI is the realized part, RVPI the residual.</>}>
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-8 max-[1180px]:col-span-12 frame overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Fund</th>
                <th className="r">Invested</th>
                <th className="r">Prior NAV</th>
                <th className="r">{Word} NAV</th>
                <th className="r">Δ</th>
                <th className="r">Δ %</th>
                <th className="r">Realized Q</th>
                <th className="r">Cumulative</th>
                <th className="r">TVPI</th>
                <th className="r">DPI</th>
                <th className="r">RVPI</th>
              </tr>
            </thead>
            <tbody>
              {funds.map((f) => (
                <tr key={f.fund}>
                  <td>
                    <div className="text-ink font-medium whitespace-nowrap">{f.fund}</div>
                    <div className="text-[11.5px] text-muted whitespace-nowrap">{f.active} active of {f.companies}</div>
                  </td>
                  <td className="r text-ink2">{num(f.invested)}</td>
                  <td className="r text-ink2">{num(f.prior_nav)}</td>
                  <td className="r text-ink font-medium">{num(f.booked_nav)}</td>
                  <td className="r"><Delta v={f.delta} /></td>
                  <td className="r"><DeltaPct v={f.delta_pct} /></td>
                  <td className="r text-ink2">{num(f.realized_quarter)}</td>
                  <td className="r text-ink2">{num(f.realized_cumulative)}</td>
                  <td className="r text-ink font-medium">{multiple(f.tvpi)}</td>
                  <td className="r text-ink2">{multiple(f.dpi)}</td>
                  <td className="r text-ink2">{multiple(f.rvpi)}</td>
                </tr>
              ))}
              <tr>
                <td className="text-ink font-medium">Portfolio</td>
                <td className="r text-ink2">{num(view.headline.invested)}</td>
                <td className="r text-ink2">{num(view.headline.prior_nav)}</td>
                <td className="r text-ink font-medium">{num(view.headline.booked_nav)}</td>
                <td className="r"><Delta v={view.headline.net_movement} /></td>
                <td className="r"><DeltaPct v={view.headline.net_movement_pct} /></td>
                <td className="r text-ink2">{num(view.headline.realized_quarter)}</td>
                <td className="r text-ink2">{num(view.headline.realized_cumulative)}</td>
                <td className="r text-ink font-medium">{multiple(view.headline.tvpi)}</td>
                <td className="r text-ink2">{multiple(view.headline.dpi)}</td>
                <td className="r text-ink2">{multiple(view.headline.tvpi - view.headline.dpi)}</td>
              </tr>
            </tbody>
          </table>
          <div className="px-3 py-2.5 border-t border-hair flex flex-col gap-1">
            {funds.map((f) => (
              <div key={f.fund} className="text-[12px] text-ink2">
                <span className="text-muted">Top of {f.fund}</span>{" "}
                {f.top_positions.slice(0, 5).map((p, i) => (
                  <span key={p.company}>{i > 0 ? " · " : ""}{p.company} <span className="num">{pct(p.share, 0)}</span></span>
                ))}
              </div>
            ))}
            <div className="text-[11px] text-muted mt-1">$M except multiples. Top positions as a share of the fund's {word} NAV.</div>
          </div>
        </div>
        <div className="col-span-4 max-[1180px]:col-span-12 frame px-4 pt-3.5 pb-3 flex flex-col">
          <div className="flex items-baseline justify-between">
            <div className="text-[13px] font-medium text-ink">TVPI by fund</div>
            <div className="flex items-center gap-4 text-[11px] text-muted">
              <span className="flex items-center gap-1.5"><i className="inline-block w-2.5 h-2.5 rounded-[2px]" style={{ background: "var(--series-2)" }} />DPI</span>
              <span className="flex items-center gap-1.5"><i className="inline-block w-2.5 h-2.5 rounded-[2px]" style={{ background: "var(--series-1)" }} />RVPI</span>
            </div>
          </div>
          <div className="flex-1 min-h-[150px] mt-2">
            <ResponsiveContainer width="100%" height={Math.max(160, funds.length * 52 + 40)}>
              <BarChart data={funds} layout="vertical" margin={{ top: 4, right: 44, bottom: 0, left: 0 }} barCategoryGap={12}>
                <CartesianGrid horizontal={false} stroke="var(--grid)" />
                <XAxis type="number" domain={[0, xMax]} ticks={ticks} tickFormatter={(v: number) => `${v.toFixed(1)}x`} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="fund" width={64} axisLine={false} tickLine={false} tick={{ className: "cat", fill: "var(--ink-2)", fontSize: 12 }} />
                <Tooltip content={<FundTip />} cursor={{ fill: "var(--accent-wash)" }} />
                <Bar dataKey="dpi" stackId="t" fill="var(--series-2)" barSize={18} stroke="var(--surface)" strokeWidth={1} isAnimationActive={false} />
                <Bar dataKey="rvpi" stackId="t" fill="var(--series-1)" barSize={18} radius={[0, 4, 4, 0]} stroke="var(--surface)" strokeWidth={1} isAnimationActive={false}>
                  <LabelList
                    dataKey="tvpi"
                    position="right"
                    offset={8}
                    className="num"
                    fill="var(--ink)"
                    fontSize={12}
                    fontWeight={600}
                    formatter={(v: number) => multiple(v)}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="text-[11px] text-muted mt-1">Each bar is the fund's TVPI, split into cash returned (DPI) and value still held (RVPI).</div>
        </div>
      </div>
    </Section>
  );
}
