// The sensitivity view: "what the portfolio looks like if software multiples move 20 percent",
// with a slider so the reader can ask for any move between −20% and +20%. Every number here is
// arithmetic on the booked book — shock × the marks a multiple regime drives — and nothing is
// written back; the engine's ±20% points (run.sensitivity) are the two ends of the slider.
import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CompanyResult, ValuationRun } from "../types";
import { musd, pct, signed, signClass } from "../lib/format";
import { useChartTheme } from "../lib/theme";
import { SectionTitle } from "../components/ui";

const MONO = "IBM Plex Mono, ui-monospace, monospace";
const MIN = -20;
const MAX = 20;

type Scope = "software" | "all";

function exposedUnder(run: ValuationRun, scope: Scope): CompanyResult[] {
  const soft = new Set(run.sensitivity_meta?.software_sectors ?? []);
  return run.companies.filter((c) => c.multiple_exposed && (scope === "all" || soft.has(c.sector)));
}

/** the part of a booked mark a multiple regime drives — the equity leg; a note carried at cost is a receivable */
const exposedOf = (c: CompanyResult) => c.booked_mark - (c.note_at_cost ?? 0);

function groupSum<T>(rows: T[], key: (r: T) => string, val: (r: T) => number): { name: string; value: number; n: number }[] {
  const m = new Map<string, { value: number; n: number }>();
  for (const r of rows) {
    const k = key(r);
    const cur = m.get(k) ?? { value: 0, n: 0 };
    cur.value += val(r);
    cur.n += 1;
    m.set(k, cur);
  }
  return [...m.entries()].map(([name, v]) => ({ name, ...v })).sort((a, b) => b.value - a.value);
}

export function SensitivityView({ run, onGoto }: { run: ValuationRun; onGoto?: (name: string) => void }) {
  const th = useChartTheme();
  const [shockPct, setShockPct] = useState(20);
  const [scope, setScope] = useState<Scope>(run.sensitivity_meta?.software_sectors?.length ? "software" : "all");
  const s = shockPct / 100;
  const base = run.sensitivity.base_nav ?? run.totals.booked_nav;

  const exposed = useMemo(() => exposedUnder(run, scope), [run, scope]);
  const exposedNav = exposed.reduce((a, c) => a + exposedOf(c), 0);
  const delta = exposedNav * s;
  const navAt = base + delta;
  const unexposed = run.companies.length - exposed.length;

  const curve = useMemo(() => {
    const pts = [];
    for (let p = MIN; p <= MAX; p += 1) pts.push({ shock: p, nav: base + exposedNav * (p / 100) });
    return pts;
  }, [base, exposedNav]);

  const bySector = useMemo(() => groupSum(exposed, (c) => c.sector, exposedOf), [exposed]);
  const byFund = useMemo(() => groupSum(exposed, (c) => c.fund, exposedOf), [exposed]);
  const fundBase = useMemo(() => groupSum(run.companies, (c) => c.fund, (c) => c.booked_mark), [run]);
  const movers = useMemo(() => [...exposed].sort((a, b) => exposedOf(b) - exposedOf(a)).slice(0, 10), [exposed]);

  const lo = Math.min(curve[0].nav, curve[curve.length - 1].nav);
  const hi = Math.max(curve[0].nav, curve[curve.length - 1].nav);
  const yFloor = Math.floor((lo - (hi - lo) * 0.15) / 50) * 50;
  const yCeil = Math.ceil((hi + (hi - lo) * 0.15) / 50) * 50;
  const scopeLabel = scope === "software" ? "software sectors" : "all multiple-exposed positions";

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <SectionTitle
          right={
            <div className="flex items-center gap-1 text-[11px]">
              <span className="text-muted mr-1">Scope</span>
              <button className={`btn ${scope === "software" ? "btn-primary" : "btn-ghost"}`} onClick={() => setScope("software")}>
                Software sectors
              </button>
              <button className={`btn ${scope === "all" ? "btn-primary" : "btn-ghost"}`} onClick={() => setScope("all")}>
                All multiple-exposed
              </button>
            </div>
          }
        >
          Sensitivity · what the book looks like if multiples move
        </SectionTitle>
        <p className="text-[11px] text-muted num mb-3">
          The shock is applied one-for-one to the equity leg of booked Level 3 marks with ARR at or above the ${run.sensitivity_meta?.min_arr ?? 0.5}M
          screening floor — {exposed.length} positions, {musd(exposedNav, 1)} of {musd(base, 1)} ({pct(exposedNav / base)}) under {scopeLabel}. The other{" "}
          {unexposed} (Level 1, pre-revenue, terminal, deal-priced{scope === "software" ? ", non-software" : ""}) and any note leg at cost are held flat.
          Nothing here changes a mark.
        </p>

        <div className="sens-slider">
          <button className="btn btn-ghost mono" onClick={() => setShockPct(MIN)} aria-label="−20%">
            −20%
          </button>
          <input
            type="range"
            min={MIN}
            max={MAX}
            step={1}
            value={shockPct}
            onChange={(e) => setShockPct(Number(e.target.value))}
            aria-label="Multiple shock, percent"
            list="sens-ticks"
          />
          <datalist id="sens-ticks">
            {[-20, -10, 0, 10, 20].map((v) => (
              <option key={v} value={v} />
            ))}
          </datalist>
          <button className="btn btn-ghost mono" onClick={() => setShockPct(MAX)} aria-label="+20%">
            +20%
          </button>
          <span className={`sens-readout ${signClass(s)}`}>{signed(shockPct, 0)}%</span>
          <div className="flex gap-1">
            {[-20, -10, 0, 10, 20].map((v) => (
              <button key={v} className={`btn ${v === shockPct ? "btn-primary" : "btn-ghost"} mono`} style={{ padding: "1px 6px" }} onClick={() => setShockPct(v)}>
                {v > 0 ? "+" : ""}
                {v}
              </button>
            ))}
          </div>
        </div>

        <div className="sens-tiles">
          <div className="sens-tile">
            <div className="k">NAV if multiples {signed(shockPct, 0)}%</div>
            <div className="v">{musd(navAt, 1)}</div>
            <div className={`d ${signClass(delta)}`}>
              {signed(delta, 1)} · {pct(delta / base, 2, true)}
            </div>
          </div>
          <div className="sens-tile">
            <div className="k">Booked NAV</div>
            <div className="v">{musd(base, 1)}</div>
            <div className="d text-muted">as of {run.manifest.measurement_date}</div>
          </div>
          <div className="sens-tile">
            <div className="k">Exposed · {scopeLabel}</div>
            <div className="v">{musd(exposedNav, 1)}</div>
            <div className="d text-muted">
              {exposed.length} positions · {pct(exposedNav / base)} of NAV
            </div>
          </div>
          <div className="sens-tile">
            <div className="k">Policy points (engine)</div>
            <div className="v num">
              {musd(run.sensitivity[scope === "software" ? "nav_if_software_multiples_-20pct" : "nav_if_multiples_-20pct"], 1)} ·{" "}
              {musd(run.sensitivity[scope === "software" ? "nav_if_software_multiples_+20pct" : "nav_if_multiples_+20pct"], 1)}
            </div>
            <div className="d text-muted">−20% · +20%, from run.sensitivity</div>
          </div>
        </div>

        <div style={{ height: 220 }} className="mt-3">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={curve} margin={{ top: 12, right: 24, left: 0, bottom: 4 }}>
              <CartesianGrid vertical={false} stroke={th.grid} strokeWidth={1} />
              <XAxis
                dataKey="shock"
                type="number"
                domain={[MIN, MAX]}
                ticks={[-20, -15, -10, -5, 0, 5, 10, 15, 20]}
                tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}%`}
                tick={{ fill: th.muted, fontSize: 11, fontFamily: MONO }}
                axisLine={{ stroke: th.axis }}
                tickLine={false}
              />
              <YAxis
                domain={[yFloor, yCeil]}
                tick={{ fill: th.muted, fontSize: 11, fontFamily: MONO }}
                axisLine={false}
                tickLine={false}
                width={56}
                tickFormatter={(v: number) => musd(v, 0)}
              />
              <ReferenceLine y={base} stroke={th.axis} strokeDasharray="3 3" />
              <ReferenceLine x={0} stroke={th.axis} />
              <Tooltip
                cursor={{ stroke: th.axis }}
                content={({ active, payload }) =>
                  active && payload?.length ? (
                    <div className="tooltip-box num">
                      <strong>{musd(payload[0].value as number, 1)}</strong>{" "}
                      <span className="text-muted">
                        at {signed(payload[0].payload.shock, 0)}% · {signed((payload[0].value as number) - base, 1)}
                      </span>
                    </div>
                  ) : null
                }
              />
              <Line type="linear" dataKey="nav" stroke={th.series1} strokeWidth={2} dot={false} isAnimationActive={false} />
              <ReferenceDot x={shockPct} y={navAt} r={5} fill={th.series1} stroke={th.surface} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="text-[11px] text-muted num">
          Straight line by construction: NAV(s) = booked + exposed × s. Dashed line is the booked NAV; the dot is the slider.
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 items-start">
        <div className="card p-4">
          <SectionTitle>By sector · at {signed(shockPct, 0)}%</SectionTitle>
          <table className="dtable text-[12px] w-full">
            <thead>
              <tr>
                <th>Sector</th>
                <th className="r">Exposed</th>
                <th className="r">Δ</th>
              </tr>
            </thead>
            <tbody>
              {bySector.map((r) => (
                <tr key={r.name}>
                  <td>
                    {r.name} <span className="text-muted">· {r.n}</span>
                  </td>
                  <td className="r num">{musd(r.value, 1)}</td>
                  <td className={`r num ${signClass(r.value * s)}`}>{signed(r.value * s, 1)}</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td>Total</td>
                <td className="r num">{musd(exposedNav, 1)}</td>
                <td className={`r num ${signClass(delta)}`}>{signed(delta, 1)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="card p-4">
          <SectionTitle>By fund · at {signed(shockPct, 0)}%</SectionTitle>
          <table className="dtable text-[12px] w-full">
            <thead>
              <tr>
                <th>Fund</th>
                <th className="r">NAV</th>
                <th className="r">Exposed</th>
                <th className="r">NAV at shock</th>
              </tr>
            </thead>
            <tbody>
              {fundBase.map((f) => {
                const ex = byFund.find((x) => x.name === f.name)?.value ?? 0;
                return (
                  <tr key={f.name}>
                    <td>{f.name}</td>
                    <td className="r num">{musd(f.value, 1)}</td>
                    <td className="r num">{musd(ex, 1)}</td>
                    <td className={`r num ${signClass(ex * s)}`}>
                      {musd(f.value + ex * s, 1)} <span className="text-muted">({pct(f.value ? (ex * s) / f.value : 0, 1, true)})</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="card p-4">
          <SectionTitle>Largest exposures · at {signed(shockPct, 0)}%</SectionTitle>
          <table className="dtable text-[12px] w-full">
            <thead>
              <tr>
                <th>Company</th>
                <th className="r">Booked</th>
                <th className="r">At shock</th>
              </tr>
            </thead>
            <tbody>
              {movers.map((c) => (
                <tr key={c.company}>
                  <td>
                    {onGoto ? (
                      <button className="btn btn-ghost" style={{ padding: "0 4px" }} onClick={() => onGoto(c.company)}>
                        {c.company}
                      </button>
                    ) : (
                      c.company
                    )}{" "}
                    <span className="text-muted text-[11px]">{c.sector}</span>
                  </td>
                  <td className="r num">{musd(c.booked_mark, 1)}</td>
                  <td className={`r num ${signClass(exposedOf(c) * s)}`}>
                    {musd(c.booked_mark + exposedOf(c) * s, 1)} <span className="text-muted">({signed(exposedOf(c) * s, 1)})</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
