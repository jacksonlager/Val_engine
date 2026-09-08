// A company's booked mark, quarter over quarter — the archive api/history.py assembles from
// the backfill file, the publish ledger and the current run. One solid line (the mark) and
// one dashed line (cumulative invested, the cost basis) on a single $M axis anchored at
// zero, so "above or below cost" is read at a glance. Every point carries where it came
// from; nothing on this chart is interpolated or invented.
import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MarkHistoryPoint, MarkHistorySource } from "../types";
import { isoDate, musd, mult, signClass } from "../lib/format";
import { dispositionLabel } from "../lib/labels";
import { useHistory } from "../lib/history";
import { useChartTheme } from "../lib/theme";
import { Label } from "./ui";

const MONO = "IBM Plex Mono, ui-monospace, monospace";

const SOURCE_LABEL: Record<MarkHistorySource, string> = {
  backfill: "HC records",
  published: "published",
  prior: "workbook prior mark",
  live: "this run · unpublished",
};

const SOURCE_TITLE: Record<MarkHistorySource, string> = {
  backfill: "From data/mark_history.yaml — HC's own record for a quarter before the engine's first run",
  published: "The booked mark released to executives for this quarter (data/published/)",
  prior: "The previous quarter's close as the workbook's Prior Mark column carried it into this run",
  live: "This run's booked mark; not yet published, or changed since the last publish",
};

function SourceChip({ s }: { s: MarkHistorySource }) {
  const cls = s === "published" ? "disp-CLEAR" : s === "live" ? "disp-MONITOR" : "disp-NONE";
  return (
    <span className={`chip ${cls}`} title={SOURCE_TITLE[s]}>
      {SOURCE_LABEL[s]}
    </span>
  );
}

interface Row {
  quarter: string;
  mark: number;
  invested: number | null;
  p: MarkHistoryPoint;
}

/** A 1-2-5 step giving four to six gridlines from zero to just above the tallest value. */
function yScale(maxValue: number): { ceil: number; ticks: number[]; decimals: number } {
  const top = Math.max(maxValue, 0.5) * 1.12;
  const step = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500].find((st) => top / st <= 6) ?? 1000;
  const ceil = Math.ceil(top / step) * step;
  const ticks: number[] = [];
  for (let y = 0; y <= ceil + 1e-9; y += step) ticks.push(Number(y.toFixed(2)));
  return { ceil, ticks, decimals: step < 1 ? 1 : 0 };
}

export function MarkHistoryCard({ company }: { company: string }) {
  const { data, error } = useHistory();
  const th = useChartTheme();
  const points = data?.companies[company] ?? [];
  const rows = useMemo<Row[]>(() => points.map((p) => ({ quarter: p.quarter, mark: p.mark, invested: p.invested, p })), [points]);
  const n = rows.length;
  const maxV = Math.max(0, ...rows.map((r) => Math.max(r.mark, r.invested ?? 0)));
  const { ceil, ticks, decimals } = yScale(maxV);
  const hasCost = rows.some((r) => r.invested !== null);
  const first = rows[0];
  const last = rows[n - 1];
  const change = n >= 2 ? last.mark - first.mark : null;
  const notes = rows.filter((r) => r.p.note);
  // ~8 quarter labels at most, the latest always among them
  const every = Math.max(1, Math.ceil(n / 8));
  const xTicks = rows.filter((_, i) => (n - 1 - i) % every === 0).map((r) => r.quarter);

  return (
    <div className="card p-3">
      <div className="flex items-baseline justify-between gap-2">
        <Label>Mark history</Label>
        {n > 0 && (
          <span className="text-[11px] text-muted whitespace-nowrap">
            {n} quarter{n === 1 ? "" : "s"} · {first.quarter}
            {n > 1 ? ` → ${last.quarter}` : ""}
          </span>
        )}
      </div>

      {!data && !error && <p className="text-[12px] text-muted">Loading the archive…</p>}
      {error && <p className="text-[12px] text-muted leading-snug">{error}</p>}
      {data && n === 0 && <p className="text-[12px] text-muted">No archived marks for this company.</p>}

      {n > 0 && (
        <>
          <div style={{ height: 190 }} className="mt-1">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 10, right: 16, left: 0, bottom: 2 }}>
                <CartesianGrid vertical={false} stroke={th.grid} strokeWidth={1} />
                <XAxis
                  dataKey="quarter"
                  ticks={xTicks}
                  interval={0}
                  tick={{ fill: th.muted, fontSize: 11, fontFamily: MONO }}
                  axisLine={{ stroke: th.axis }}
                  tickLine={false}
                  tickMargin={6}
                  padding={{ left: 12, right: 12 }}
                />
                <YAxis
                  domain={[0, ceil]}
                  ticks={ticks}
                  allowDataOverflow
                  tick={{ fill: th.muted, fontSize: 11, fontFamily: MONO }}
                  axisLine={false}
                  tickLine={false}
                  width={44}
                  tickFormatter={(v: number) => musd(v, decimals)}
                />
                <Tooltip
                  cursor={{ stroke: th.axis, strokeWidth: 1 }}
                  isAnimationActive={false}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const p = (payload[0].payload as Row).p;
                    return (
                      <div className="tooltip-box" style={{ maxWidth: 280 }}>
                        <div className="flex items-center justify-between gap-3">
                          <span className="mono text-[11px] text-muted">{p.quarter}</span>
                          <SourceChip s={p.source} />
                        </div>
                        <div className="num mt-1">
                          <strong>{musd(p.mark)}</strong> <span className="text-muted">$M booked mark</span>
                          {p.overridden && <span className="chip disp-REVIEW ml-1">committee decision</span>}
                        </div>
                        <div className="text-[11.5px] text-ink2 num">
                          {p.invested !== null && <>invested {musd(p.invested)} · </>}
                          {p.moic !== null && <>{mult(p.moic, 2)} MOIC · </>}
                          {p.status ?? "—"}
                          {p.disposition ? ` · ${dispositionLabel(p.disposition)}` : ""}
                        </div>
                        {p.published_at && <div className="text-[11px] text-muted mono">published {isoDate(p.published_at)}</div>}
                        {p.note && <div className="text-[11px] text-muted mt-1 leading-snug whitespace-normal">{p.note}</div>}
                      </div>
                    );
                  }}
                />
                {hasCost && (
                  <Line
                    type="linear"
                    dataKey="invested"
                    name="Invested"
                    stroke={th.muted}
                    strokeWidth={1.5}
                    strokeDasharray="4 3"
                    dot={false}
                    activeDot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                )}
                <Line
                  type="linear"
                  dataKey="mark"
                  name="Booked mark"
                  stroke={th.series1}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  isAnimationActive={false}
                  dot={(d: { cx?: number; cy?: number; index?: number; payload?: Row }) => {
                    if (d.cx === undefined || d.cy === undefined) return <g key={d.index} />;
                    const live = d.payload?.p.source === "live";
                    // a hollow dot is a point the ledger does not (yet) hold; filled means published or on file
                    return (
                      <circle
                        key={d.index}
                        cx={d.cx}
                        cy={d.cy}
                        r={4}
                        fill={live ? th.surface : th.series1}
                        stroke={th.series1}
                        strokeWidth={2}
                      />
                    );
                  }}
                  activeDot={{ r: 5, fill: th.series1, stroke: th.surface, strokeWidth: 2 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-[11px] text-muted">
            <span className="flex items-center gap-1.5">
              <span aria-hidden style={{ width: 14, height: 0, borderTop: `2px solid ${th.series1}` }} />
              Booked mark
            </span>
            {hasCost && (
              <span className="flex items-center gap-1.5">
                <span aria-hidden style={{ width: 14, height: 0, borderTop: `2px dashed ${th.muted}` }} />
                Invested (cost)
              </span>
            )}
            <span className="flex items-center gap-1.5">
              <span aria-hidden style={{ width: 8, height: 8, borderRadius: 4, border: `2px solid ${th.series1}`, background: th.surface }} />
              not yet published
            </span>
            {change !== null && (
              <span className="ml-auto num text-ink2">
                {musd(first.mark)} → {musd(last.mark)}
                <span className={`ml-1 ${signClass(change)}`}>
                  ({change >= 0 ? "+" : "−"}
                  {musd(Math.abs(change))})
                </span>
              </span>
            )}
          </div>

          <div className="flex flex-wrap gap-1 mt-2">
            {rows.map((r) => (
              <span key={r.quarter} className="flex items-center gap-1 text-[10.5px] text-muted">
                <span className="mono">{r.quarter}</span>
                <SourceChip s={r.p.source} />
              </span>
            ))}
          </div>

          {notes.length > 0 && (
            <ul className="mt-2 space-y-1">
              {notes.map((r) => (
                <li key={r.quarter} className="text-[11px] text-muted leading-snug whitespace-normal">
                  <span className="mono text-ink2">{r.quarter}</span> — {r.p.note}
                </li>
              ))}
            </ul>
          )}

          <span className="sr-only">
            {company} booked mark by quarter:{" "}
            {rows.map((r) => `${r.quarter} ${musd(r.mark)} $M (${SOURCE_LABEL[r.p.source]})`).join("; ")}.
          </span>
        </>
      )}

      {data && data.errors.length > 0 && (
        <p className="text-[11px] text-muted mt-2 leading-snug whitespace-normal">
          Archive problems: {data.errors.join(" · ")}
        </p>
      )}
    </div>
  );
}
