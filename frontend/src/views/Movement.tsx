import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CompsMove, ValuationRun } from "../types";
import { musd, pct, signed, signClass } from "../lib/format";
import { useChartTheme } from "../lib/theme";
import { SectionTitle } from "../components/ui";
import { SensitivityView } from "./Sensitivity";

const TAIL_AFTER = 12;

/** "2026-09" -> "September 2026". Kept local: Market.tsx has its own copy. */
function monthLabel(ym: string): string {
  const t = Date.parse(`${ym}-01T00:00:00Z`);
  if (!Number.isFinite(t)) return ym;
  return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(t));
}

interface Bridge {
  name: string;
  kind: "total" | "up" | "down";
  base: number; // invisible offset
  size: number; // visible height
  value: number; // signed delta or total
  running: number;
  members?: string[];
}

function buildBridge(run: ValuationRun): Bridge[] {
  const t = run.totals;
  const movers = run.companies
    .map((c) => ({ name: c.company, d: c.proposed_mark - c.prior_mark }))
    .filter((m) => Math.abs(m.d) > 1e-6)
    .sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
  const head = movers.slice(0, TAIL_AFTER);
  const tail = movers.slice(TAIL_AFTER);
  const seq: { name: string; d: number; members?: string[] }[] = [...head];
  if (tail.length) {
    seq.push({ name: `Other (${tail.length})`, d: tail.reduce((s, m) => s + m.d, 0), members: tail.map((m) => `${m.name} ${signed(m.d)}`) });
  }
  const out: Bridge[] = [{ name: "Prior fair value", kind: "total", base: 0, size: t.prior_nav, value: t.prior_nav, running: t.prior_nav }];
  let running = t.prior_nav;
  for (const m of seq) {
    const next = running + m.d;
    out.push({
      name: m.name,
      kind: m.d >= 0 ? "up" : "down",
      base: Math.min(running, next),
      size: Math.abs(m.d),
      value: m.d,
      running: next,
      members: m.members,
    });
    running = next;
  }
  out.push({ name: "Proposed fair value", kind: "total", base: 0, size: t.proposed_nav, value: t.proposed_nav, running: t.proposed_nav });
  return out;
}

export function MovementView({ run, onGoto }: { run: ValuationRun; onGoto?: (name: string) => void }) {
  const th = useChartTheme();
  const data = useMemo(() => buildBridge(run), [run]);
  const [showTable, setShowTable] = useState(false);
  const [sensitivity, setSensitivity] = useState(false);

  // Truncate the axis so a $35M step is legible against a $1.1B total. Stated in the subtitle.
  const levels = data.map((d) => d.running);
  const lo = Math.min(...levels);
  const hi = Math.max(...levels);
  const pad = (hi - lo) * 0.08;
  const floor = Math.floor((lo - pad) / 50) * 50;
  const ceil = Math.ceil((hi + pad) / 50) * 50;
  // Totals are drawn from the floor so they read as columns, not as a gap.
  const plotted = data.map((d) => ({
    ...(d.kind === "total" ? { ...d, base: floor, size: d.value - floor } : d),
    // selective direct labels: totals always, single steps only when they are big enough to read
    label: d.kind === "total" ? musd(d.value, 1) : Math.abs(d.value) >= 5 ? signed(d.value, 1) : "",
  }));

  const colorOf = (k: Bridge["kind"]) => (k === "up" ? th.up : k === "down" ? th.down : th.neutral);

  const s = run.sensitivity;
  // one headline: the brief's "software multiples"; the wider scope is a secondary line and the slider's switch
  const soft = typeof s["nav_if_software_multiples_-20pct"] === "number";
  const loKey = soft ? "nav_if_software_multiples_-20pct" : "nav_if_multiples_-20pct";
  const hiKey = soft ? "nav_if_software_multiples_+20pct" : "nav_if_multiples_+20pct";
  const exposedNav = soft ? s.software_exposed_nav : s.multiple_exposed_nav;
  const sens = [
    { name: "Multiples −20%", value: s[loKey], key: "down" },
    { name: "Base (booked)", value: s.base_nav, key: "base" },
    { name: "Multiples +20%", value: s[hiKey], key: "up" },
  ].filter((x) => x.value !== undefined);
  const exposedShare = s.base_nav ? exposedNav / s.base_nav : null;
  const sensMin = Math.min(...sens.map((x) => x.value));
  const sensMax = Math.max(...sens.map((x) => x.value));
  const sFloor = Math.floor((sensMin - (sensMax - sensMin) * 0.4) / 100) * 100;
  const sCeil = Math.ceil((sensMax + (sensMax - sensMin) * 0.05) / 100) * 100;

  const switcher = (
    <div className="view-switch" role="tablist" aria-label="Movement views">
      <button role="tab" aria-selected={!sensitivity} className={`btn ${!sensitivity ? "btn-primary" : "btn-ghost"}`} onClick={() => setSensitivity(false)}>
        Bridge
      </button>
      <button role="tab" aria-selected={sensitivity} className={`btn ${sensitivity ? "btn-primary" : "btn-ghost"}`} onClick={() => setSensitivity(true)}>
        Sensitivity view
      </button>
    </div>
  );

  if (sensitivity) {
    return (
      <div className="space-y-3">
        {switcher}
        <SensitivityView run={run} onGoto={onGoto} />
      </div>
    );
  }

  return (
    <div className="space-y-3">
    {switcher}
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,3fr)_minmax(0,1fr)] gap-4">
      <div className="card p-4">
        <SectionTitle
          right={
            <button className="btn btn-ghost" onClick={() => setShowTable((v) => !v)}>
              {showTable ? "Chart" : "Table view"}
            </button>
          }
        >
          Quarter-over-quarter bridge · {run.manifest.prior_close} → {run.manifest.measurement_date}
        </SectionTitle>
        <p className="text-[11px] text-muted mb-2 num">
          Prior fair value {musd(run.totals.prior_nav, 1)} → proposed {musd(run.totals.proposed_nav, 1)} ({signed(run.totals.net_movement, 1)},{" "}
          {pct(run.totals.net_movement / run.totals.prior_nav, 1, true)}). The {TAIL_AFTER} largest moves, up or down; the rest fold into Other. Axis
          starts at{" "}
          {musd(floor, 0)} so single-company steps stay legible. $M.
        </p>
        {showTable ? (
          <BridgeTable data={data} />
        ) : (
          <div style={{ height: 420 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={plotted} margin={{ top: 24, right: 12, left: 0, bottom: 64 }} barCategoryGap="28%">
                <CartesianGrid vertical={false} stroke={th.grid} strokeWidth={1} />
                <XAxis
                  dataKey="name"
                  interval={0}
                  angle={-38}
                  textAnchor="end"
                  height={70}
                  tick={{ fill: th.ink2, fontSize: 11 }}
                  axisLine={{ stroke: th.axis }}
                  tickLine={false}
                />
                <YAxis
                  domain={[floor, ceil]}
                  allowDataOverflow
                  tick={{ fill: th.muted, fontSize: 11, fontFamily: "IBM Plex Mono, ui-monospace, monospace" }}
                  axisLine={false}
                  tickLine={false}
                  width={56}
                  tickFormatter={(v: number) => musd(v, 0)}
                />
                <ReferenceLine y={run.totals.prior_nav} stroke={th.axis} strokeWidth={1} />
                <Tooltip
                  cursor={{ fill: th.grid, opacity: 0.5 }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const d = payload[0].payload as Bridge;
                    const orig = data.find((x) => x.name === d.name)!;
                    return (
                      <div className="tooltip-box">
                        <div className="font-medium">{d.name}</div>
                        <div className="num">
                          {orig.kind === "total" ? (
                            <strong>{musd(orig.value)}</strong>
                          ) : (
                            <>
                              <strong className={signClass(orig.value)}>{signed(orig.value)}</strong>
                              <span className="text-muted"> · running {musd(orig.running)}</span>
                            </>
                          )}
                        </div>
                        {orig.members && (
                          <div className="text-[11px] text-muted mt-1 max-w-[260px] whitespace-normal">{orig.members.join(" · ")}</div>
                        )}
                      </div>
                    );
                  }}
                />
                <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
                <Bar dataKey="size" stackId="w" isAnimationActive={false} maxBarSize={24} radius={[3, 3, 0, 0]}>
                  {plotted.map((d, i) => (
                    <Cell key={i} fill={colorOf(d.kind)} />
                  ))}
                  <LabelList dataKey="label" position="top" fill={th.ink2} fontSize={11} fontFamily="IBM Plex Mono, ui-monospace, monospace" />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        <div className="flex gap-4 text-[11px] text-ink2 mt-1">
          <span className="flex items-center gap-1"><i className="inline-block w-3 h-3 rounded-sm" style={{ background: th.up }} /> mark up</span>
          <span className="flex items-center gap-1"><i className="inline-block w-3 h-3 rounded-sm" style={{ background: th.down }} /> mark down / realized / written off</span>
          <span className="flex items-center gap-1"><i className="inline-block w-3 h-3 rounded-sm" style={{ background: th.neutral }} /> Fair value total</span>
        </div>
      </div>

      <div className="card p-4">
        <SectionTitle
          right={
            <button className="btn btn-ghost" onClick={() => setSensitivity(true)} title="Slider from −20% to +20%, by sector, fund and position">
              Open slider →
            </button>
          }
        >
          Sensitivity · {soft ? "software" : "revenue"} multiples ±20%
        </SectionTitle>
        <p className="text-[11px] text-muted mb-2 num">
          Shock applied to {soft ? "software-sector " : ""}Level 3 positions with ARR above the screening floor: {musd(exposedNav, 1)} of{" "}
          {musd(s.base_nav, 1)} ({pct(exposedShare)}). Level 1, pre-revenue and terminal positions held flat. $M.
        </p>
        <div style={{ height: 150 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sens} layout="vertical" margin={{ top: 4, right: 64, left: 4, bottom: 4 }} barCategoryGap="30%">
              <XAxis type="number" domain={[sFloor, sCeil]} allowDataOverflow hide />
              <YAxis type="category" dataKey="name" width={112} tick={{ fill: th.ink2, fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                cursor={{ fill: th.grid, opacity: 0.5 }}
                content={({ active, payload }) =>
                  active && payload?.length ? (
                    <div className="tooltip-box num">
                      <strong>{musd(payload[0].value as number)}</strong> <span className="text-muted">{payload[0].payload.name}</span>
                    </div>
                  ) : null
                }
              />
              <Bar dataKey="value" isAnimationActive={false} maxBarSize={22} radius={[0, 3, 3, 0]}>
                {sens.map((x, i) => (
                  <Cell key={i} fill={x.key === "base" ? th.neutral : th.series1} />
                ))}
                <LabelList
                  dataKey="value"
                  position="right"
                  fill={th.ink2}
                  fontSize={11}
                  fontFamily="IBM Plex Mono, ui-monospace, monospace"
                  formatter={(v: number) => musd(v, 1)}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="text-[11px] text-ink2 mt-1 num">
          Range {signed(sens[0].value - s.base_nav, 1)} / {signed(sens[sens.length - 1].value - s.base_nav, 1)} around base. Axis starts at {musd(sFloor, 0)}.
          {soft && typeof s["nav_if_multiples_-20pct"] === "number" && (
            <>
              {" "}
              Every multiple-exposed position: {signed(s["nav_if_multiples_-20pct"] - s.base_nav, 1)} / {signed(s["nav_if_multiples_+20pct"] - s.base_nav, 1)}.
            </>
          )}
        </div>
        {run.comps_move && <CompsMoveCard m={run.comps_move} />}
      </div>
    </div>
    </div>
  );
}

/** The observed sensitivity: what the same multiple-exposed marks would have done had they moved
    with their sector's public comps over the quarter. Alternative arithmetic, like M-080 — it
    changes nothing; it says how far the carried book sits from the public market's quarter. */
function CompsMoveCard({ m }: { m: CompsMove }) {
  const share = m.exposed_nav ? m.covered_nav / m.exposed_nav : 0;
  return (
    <div className="mt-4 pt-3 border-t border-line">
      <SectionTitle
        right={
          m.all_live ? (
            <span className="chip disp-CLEAR no-dot" title="Multiples observed from the live market data provider">
              Live market data
            </span>
          ) : (
            <span
              className="chip disp-MONITOR no-dot"
              title="Stand-in multiples shipped with the app, shaped like the provider's. Connect a live market data provider for an observed history."
            >
              Sample market data
            </span>
          )
        }
      >
        Observed · public comparables, {monthLabel(m.prior_month)} → {monthLabel(m.now_month)}
      </SectionTitle>
      <p className="text-[11px] text-muted mb-2 num">
        Each sector's basket EV/revenue move this quarter applied to that sector's multiple-exposed marks. Had the book re-rated with its
        comps: <span className="text-ink2">{musd(m.nav_if_marked_with_comps, 1)}</span> (
        <span className={signClass(m.delta)}>{signed(m.delta, 1)}</span>, {pct(m.delta / m.base_nav, 2, true)}). Covers {pct(share)} of the
        exposed fair value. Nothing here moves a mark — it is the gap between the carried book and the public market's quarter.
      </p>
      <div className="overflow-x-auto">
        <table className="dtable text-[11.5px] w-full">
          <thead>
            <tr>
              <th>Sector</th>
              <th className="r" title="The sector basket's EV/revenue multiple this quarter against last">Multiple move</th>
              <th className="r" title="The marks in this sector that a multiple regime drives">Exposed marks</th>
              <th className="r" title="What those marks would have done had they moved with the basket">Change</th>
            </tr>
          </thead>
          <tbody>
            {m.sectors.map((x) => (
              <tr key={x.sector} title={`${x.sector}: ${x.multiple_prior.toFixed(1)}× → ${x.multiple_now.toFixed(1)}× · ${x.positions} positions · ${x.source}`}>
                <td className="whitespace-nowrap">
                  {x.sector} <span className="text-muted">· {x.positions}</span>
                </td>
                <td className={`r num ${signClass(x.qoq_pct)}`}>{pct(x.qoq_pct, 1, true)}</td>
                <td className="r num">{musd(x.exposed_nav, 1)}</td>
                <td className={`r num ${signClass(x.delta)}`}>{signed(x.delta, 1)}</td>
              </tr>
            ))}
            <tr className="font-semibold">
              <td>Total</td>
              <td className={`r num ${signClass(m.delta)}`}>{m.covered_nav ? pct(m.delta / m.covered_nav, 1, true) : "—"}</td>
              <td className="r num">{musd(m.covered_nav, 1)}</td>
              <td className={`r num ${signClass(m.delta)}`}>{signed(m.delta, 1)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-[10.5px] text-muted mt-1">Hover a row for the basket multiples then → now and the source.</p>
    </div>
  );
}

function BridgeTable({ data }: { data: Bridge[] }) {
  return (
    <table className="dtable text-[12px]">
      <thead>
        <tr>
          <th>Step</th>
          <th className="r">Change or total</th>
          <th className="r">Running total</th>
        </tr>
      </thead>
      <tbody>
        {data.map((d) => (
          <tr key={d.name}>
            <td>
              {d.name}
              {d.members && <div className="text-[11px] text-muted whitespace-normal">{d.members.join(" · ")}</div>}
            </td>
            <td className={`r num ${d.kind === "total" ? "font-medium" : signClass(d.value)}`}>{d.kind === "total" ? musd(d.value) : signed(d.value)}</td>
            <td className="r num">{musd(d.running)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
