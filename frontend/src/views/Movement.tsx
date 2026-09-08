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
import type { ValuationRun } from "../types";
import { musd, pct, signed, signClass } from "../lib/format";
import { useChartTheme } from "../lib/theme";
import { SectionTitle } from "../components/ui";
import { SensitivityView } from "./Sensitivity";

const TAIL_AFTER = 12;

/** "2026-09" -> "September 2026". Kept local: Market.tsx has its own copy. */
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
  const out: Bridge[] = [{ name: "Prior NAV", kind: "total", base: 0, size: t.prior_nav, value: t.prior_nav, running: t.prior_nav }];
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
  out.push({ name: "Updated NAV", kind: "total", base: 0, size: t.proposed_nav, value: t.proposed_nav, running: t.proposed_nav });
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
    <div className="grid grid-cols-1 gap-4">
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
        <p className="text-[13px] text-ink2 mb-2 num">
          Prior NAV {musd(run.totals.prior_nav, 1)} → updated NAV {musd(run.totals.proposed_nav, 1)} ({signed(run.totals.net_movement, 1)},{" "}
          {pct(run.totals.net_movement / run.totals.prior_nav, 1, true)}). The {TAIL_AFTER} largest moves; the rest fold into Other. $M.
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
          <span className="flex items-center gap-1"><i className="inline-block w-3 h-3 rounded-sm" style={{ background: th.neutral }} /> NAV total</span>
        </div>
      </div>

    </div>
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
