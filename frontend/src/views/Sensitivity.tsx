// The sensitivity view: "what the portfolio looks like if revenue multiples move 20 percent",
// with a slider so the reader can ask for any move between −20% and +20%. Every number here is
// arithmetic on the booked book — shock × the marks a multiple regime drives — and nothing is
// written back; the engine's ±20% points (run.sensitivity) are the two ends of the slider.
import { Fragment, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CompanyResult, ValuationRun } from "../types";
import { musd, pct, signed, signClass } from "../lib/format";
import { useChartTheme } from "../lib/theme";
import { SectionTitle } from "../components/ui";

const MONO = "IBM Plex Mono, ui-monospace, monospace";
const MIN = -20;
const MAX = 20;



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


/** The one definition of "moves with a multiple", mirroring engine/rollup.py::exposed_amount:
    the equity leg of a booked Level 3 mark whose revenue clears the screening floor. A note leg
    carried at cost is a receivable, not a multiple of revenue, so it is subtracted; a position the
    engine did not mark as exposed contributes nothing. Everything on this screen — the sector
    totals, the position rows and the portfolio sum — is this one function, so they cannot disagree. */
const movesWithMultiples = (c: CompanyResult) => (c.multiple_exposed ? c.booked_mark - (c.note_at_cost ?? 0) : 0);

/** Why a position does not move, in the reviewer's terms. Read from what the engine recorded, in
    the order the exposure test applies them. */
function heldFlatReason(c: CompanyResult, minArr: number): string {
  if (c.status_after !== "Active") return "no longer held";
  if (c.fv_level === 1) return "listed — carried at its market price";
  if (c.fv_level === 2) return "priced from an observable input, not a multiple";
  if (c.arr === null || c.arr === undefined) return "no revenue on file";
  if (c.arr < minArr) return `revenue below the ${musd(minArr, 1)}M screening floor`;
  return "priced by a transaction, not a multiple";
}

/** Sector by sector. A firm rarely believes every sector re-rates by the same amount — AI multiples
    and fintech multiples move for different reasons — so each sector carries its own shock and the
    portfolio effect is the sum. Open a sector to see the effect position by position. */
function SectorShocks({ run, base, portfolioShock }: { run: ValuationRun; base: number; portfolioShock: number }) {
  const sectors = run.sensitivity_sectors ?? [];
  const [shocks, setShocks] = useState<Record<string, number>>({});
  const [open, setOpen] = useState<string | null>(null);
  const minArr = run.sensitivity_meta?.min_arr ?? 0.5;
  const shockOf = (name: string) => shocks[name] ?? portfolioShock;
  const set = (name: string, v: number) => setShocks((p) => ({ ...p, [name]: Math.max(MIN, Math.min(MAX, v)) }));
  const touched = Object.keys(shocks).length > 0;

  const bySector = useMemo(() => {
    const m = new Map<string, CompanyResult[]>();
    for (const c of run.companies) m.set(c.sector, [...(m.get(c.sector) ?? []), c]);
    return m;
  }, [run]);

  const rows = sectors.map((x) => ({ ...x, shock: shockOf(x.sector), delta: x.exposed_nav * (shockOf(x.sector) / 100) }));
  const totalDelta = rows.reduce((a, r) => a + r.delta, 0);
  const totalExposed = rows.reduce((a, r) => a + r.exposed_nav, 0);

  if (sectors.length === 0) return null;
  return (
    <div className="card p-4">
      <SectionTitle
        right={
          <span className="flex items-center gap-2">
            {touched && (
              <button className="btn btn-ghost text-[11px]" onClick={() => setShocks({})}>
                Reset every sector to {signed(portfolioShock, 0)}%
              </button>
            )}
            <span className="num text-[12px]">
              {musd(base, 1)} → <b>{musd(base + totalDelta, 1)}</b>{" "}
              <span className={signClass(totalDelta)}>({signed(totalDelta, 1)})</span>
            </span>
          </span>
        }
      >
        Sector by sector
      </SectionTitle>
      <p className="text-[12px] text-ink2 leading-[1.55] max-w-[78ch] mt-1 mb-2">
        Every sector starts at the move set above. Change one and the rest hold, so you can ask what a re-rating in one
        part of the book does on its own. Open a sector to see every position in it and what the move does to each.
      </p>
      <div className="overflow-x-auto -mx-4 px-4">
        <table className="dtable text-[12px] w-full">
          <thead>
            <tr>
              <th style={{ width: 28 }}></th>
              <th>Sector</th>
              <th className="r">Value</th>
              <th className="r">Moves with multiples</th>
              <th className="r">Held flat</th>
              <th className="r">Move</th>
              <th className="r">Impact</th>
              <th className="r">Value after</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const held = r.nav - r.exposed_nav;
              const cs = (bySector.get(r.sector) ?? []).slice().sort((a, b) => movesWithMultiples(b) - movesWithMultiples(a));
              const isOpen = open === r.sector;
              return (
                <Fragment key={r.sector}>
                  <tr>
                    <td>
                      <button
                        className="btn btn-ghost px-1 py-0 text-[10px]"
                        onClick={() => setOpen(isOpen ? null : r.sector)}
                        aria-expanded={isOpen}
                        aria-label={`${isOpen ? "Hide" : "Show"} the positions in ${r.sector}`}
                      >
                        {isOpen ? "▾" : "▸"}
                      </button>
                    </td>
                    <td>
                      {r.sector}
                      <span className="text-muted text-[11px]"> · {r.exposed_positions} of {r.positions} move</span>
                    </td>
                    <td className="r num">{musd(r.nav, 1)}</td>
                    <td className="r num">
                      {musd(r.exposed_nav, 1)}
                      <span className="text-muted"> ({pct(r.nav ? r.exposed_nav / r.nav : 0, 0)})</span>
                    </td>
                    <td className="r num text-muted">{musd(held, 1)}</td>
                    <td className="r">
                      <span className="inline-flex items-center gap-1.5">
                        <input
                          type="range"
                          min={MIN}
                          max={MAX}
                          step={1}
                          value={r.shock}
                          onChange={(e) => set(r.sector, Number(e.target.value))}
                          aria-label={`Multiple move for ${r.sector}, percent`}
                          style={{ width: 92 }}
                        />
                        <span className="num w-[46px] text-right">{signed(r.shock, 0)}%</span>
                      </span>
                    </td>
                    <td className={`r num ${signClass(r.delta)}`}>{signed(r.delta, 1)}</td>
                    <td className="r num">{musd(r.nav + r.delta, 1)}</td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={8} style={{ padding: 0 }}>
                        <div className="sector-detail">
                          <table className="dtable text-[11.5px] w-full">
                            <thead>
                              <tr>
                                <th>Position</th>
                                <th className="r">Booked</th>
                                <th className="r">Moves with multiples</th>
                                <th className="r">Impact at {signed(r.shock, 0)}%</th>
                                <th className="r">Mark after</th>
                              </tr>
                            </thead>
                            <tbody>
                              {cs.map((c) => {
                                const exp = movesWithMultiples(c);
                                const d = exp * (r.shock / 100);
                                const note = (c.note_at_cost ?? 0) > 0.005;
                                return (
                                  <tr key={c.company}>
                                    <td>
                                      {c.company}
                                      {exp === 0 && (
                                        <span className="text-muted"> · held flat: {heldFlatReason(c, minArr)}</span>
                                      )}
                                      {exp > 0 && note && (
                                        <span className="text-muted"> · {musd(c.note_at_cost, 2)} note at cost held flat</span>
                                      )}
                                    </td>
                                    <td className="r num">{musd(c.booked_mark, 2)}</td>
                                    <td className={`r num ${exp === 0 ? "text-muted" : ""}`}>{musd(exp, 2)}</td>
                                    <td className={`r num ${exp === 0 ? "text-muted" : signClass(d)}`}>
                                      {exp === 0 ? "—" : signed(d, 2)}
                                    </td>
                                    <td className="r num">{musd(c.booked_mark + d, 2)}</td>
                                  </tr>
                                );
                              })}
                              <tr>
                                <td className="font-semibold">{r.sector} · {cs.length} positions</td>
                                <td className="r num font-semibold">{musd(r.nav, 2)}</td>
                                <td className="r num font-semibold">{musd(r.exposed_nav, 2)}</td>
                                <td className={`r num font-semibold ${signClass(r.delta)}`}>{signed(r.delta, 2)}</td>
                                <td className="r num font-semibold">{musd(r.nav + r.delta, 2)}</td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            <tr>
              <td></td>
              <td className="font-semibold">Portfolio</td>
              <td className="r num font-semibold">{musd(base, 1)}</td>
              <td className="r num font-semibold">{musd(totalExposed, 1)}</td>
              <td className="r num text-muted">{musd(base - totalExposed, 1)}</td>
              <td className="r text-muted text-[11px]">{touched ? "mixed" : `${signed(portfolioShock, 0)}% across`}</td>
              <td className={`r num font-semibold ${signClass(totalDelta)}`}>{signed(totalDelta, 1)}</td>
              <td className="r num font-semibold">{musd(base + totalDelta, 1)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted mt-2 mb-0 max-w-[82ch]">
        Arithmetic on the booked book, not a revaluation: nothing here is written back, and no mark changes until a
        decision is recorded against the position itself. A position moves only where the mark rests on a revenue
        multiple — the equity leg of a Level 3 mark whose revenue clears the {musd(minArr, 1)}M screening floor.
      </p>
    </div>
  );
}

export function SensitivityView({ run, onGoto }: { run: ValuationRun; onGoto?: (name: string) => void }) {
  const th = useChartTheme();
  const [shockPct, setShockPct] = useState(20);
  const s = shockPct / 100;
  const base = run.sensitivity.base_nav ?? run.totals.booked_nav;

  const exposed = useMemo(() => run.companies.filter((c) => movesWithMultiples(c) > 0), [run]);
  const exposedNav = exposed.reduce((a, c) => a + movesWithMultiples(c), 0);
  const delta = exposedNav * s;
  const navAt = base + delta;
  const unexposed = run.companies.length - exposed.length;

  const curve = useMemo(() => {
    const pts = [];
    for (let p = MIN; p <= MAX; p += 1) pts.push({ shock: p, nav: base + exposedNav * (p / 100) });
    return pts;
  }, [base, exposedNav]);

  const bySector = useMemo(() => groupSum(exposed, (c) => c.sector, movesWithMultiples), [exposed]);
  const byFund = useMemo(() => groupSum(exposed, (c) => c.fund, movesWithMultiples), [exposed]);
  const fundBase = useMemo(() => groupSum(run.companies, (c) => c.fund, (c) => c.booked_mark), [run]);
  const movers = useMemo(() => [...exposed].sort((a, b) => movesWithMultiples(b) - movesWithMultiples(a)).slice(0, 10), [exposed]);

  const lo = Math.min(curve[0].nav, curve[curve.length - 1].nav);
  const hi = Math.max(curve[0].nav, curve[curve.length - 1].nav);
  const yFloor = Math.floor((lo - (hi - lo) * 0.15) / 50) * 50;
  const yCeil = Math.ceil((hi + (hi - lo) * 0.15) / 50) * 50;

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <SectionTitle>Sensitivity · what the book looks like if multiples move</SectionTitle>
        <p className="text-[11px] text-muted num mb-3">
          The move is applied one-for-one to every position whose mark rests on a revenue multiple — the equity leg of a
          booked Level 3 mark with revenue at or above the ${run.sensitivity_meta?.min_arr ?? 0.5}M screening floor.
          That is {exposed.length} of {run.companies.length} positions, {musd(exposedNav, 1)} of {musd(base, 1)}{" "}
          ({pct(exposedNav / base)}) of the book. The other {unexposed} — listed, pre-revenue, no longer held, or priced
          by a transaction — and any note leg carried at cost are held flat. Nothing here changes a mark.
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
            <div className="k">Moves with multiples</div>
            <div className="v">{musd(exposedNav, 1)}</div>
            <div className="d text-muted">
              {exposed.length} positions · {pct(exposedNav / base)} of NAV
            </div>
          </div>
          <div className="sens-tile">
            <div className="k">Policy points · ±20%</div>
            <div className="v num">
              {musd(run.sensitivity["nav_if_multiples_-20pct"], 1)} · {musd(run.sensitivity["nav_if_multiples_+20pct"], 1)}
            </div>
            <div className="d text-muted">The two ends of the slider, as the engine computed them</div>
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
          A straight line by construction: the exposed marks move one-for-one with the multiple and everything else is held flat. The dashed line is
          the booked NAV; the dot is where the slider sits.
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
                <th className="r">Change</th>
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
                <th className="r">NAV at {signed(shockPct, 0)}%</th>
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
                <th className="r">Mark at {signed(shockPct, 0)}%</th>
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
                  <td className={`r num ${signClass(movesWithMultiples(c) * s)}`}>
                    {musd(c.booked_mark + movesWithMultiples(c) * s, 1)} <span className="text-muted">({signed(movesWithMultiples(c) * s, 1)})</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <SectorShocks run={run} base={base} portfolioShock={shockPct} />
    </div>
  );
}
