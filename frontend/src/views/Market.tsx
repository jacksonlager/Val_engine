import { useEffect, useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CompanyResult, ConstituentStatus, MarketConstituent, MarketReport, MarketSector, ValuationRun } from "../types";
import { loadMarket, type Mode } from "../lib/api";
import { isoDateTime, mult, musd, pct, shortDate, signClass } from "../lib/format";
import { useChartTheme } from "../lib/theme";
import { SectionTitle, useAsync } from "../components/ui";

const MONO = "IBM Plex Mono, ui-monospace, monospace";

// ---------------------------------------------------------------- chips

/** "live:edgar+yahoo" (or "live:edgar+yahoo@2026-09") -> ["EDGAR", "Yahoo"]: the parts of a live label, for display. */
function liveParts(source: string | undefined): string[] {
  const body = (source ?? "").replace(/^live:/, "").replace(/@.*$/, "");
  const parts = body ? body.split("+") : [];
  return parts.map((p) => (p.toLowerCase() === "edgar" ? "EDGAR" : p.charAt(0).toUpperCase() + p.slice(1).toLowerCase()));
}

/** Where a number came from. Green only when a live source actually answered; the label names the sources in `source`. */
function SourceChip({ live, long = false, source }: { live: boolean; long?: boolean; source?: string }) {
  const parts = liveParts(source);
  const names = parts.length ? parts.join(" + ") : "EDGAR + prices";
  const prices = parts.length > 1 ? parts.slice(1).join(" + ") : "the price source";
  return live ? (
    <span className="chip disp-CLEAR" title={`Priced from SEC EDGAR XBRL frames and ${prices} month-end closes`}>
      {long ? `LIVE · ${names}` : "LIVE"}
    </span>
  ) : (
    <span className="chip disp-NONE" title="Fixture: the PitchBook-shaped stub shipped with the engine (data/market_multiples.json)">
      {long ? "FIXTURE · PitchBook-shaped stub" : "FIXTURE"}
    </span>
  );
}

/** `ok` priced; `error` is shown as "unpriced" in the watch hue — a constituent the feed could not
    price is left out of the median, which is a gap to know about, not a fault in the book. */
function StatusChip({ s }: { s: ConstituentStatus }) {
  const cls = s === "ok" ? "disp-CLEAR" : s === "error" ? "disp-MONITOR" : "disp-NONE";
  return <span className={`chip ${cls}`}>{s === "error" ? "unpriced" : s}</span>;
}

// ---------------------------------------------------------------- header strip

function Meta({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <span className="text-[11px] text-muted whitespace-nowrap">
      {k} <span className="mono text-ink2">{children}</span>
    </span>
  );
}

function HeaderStrip({ rep }: { rep: MarketReport }) {
  const [showErrors, setShowErrors] = useState(false);
  const n = rep.errors.length;
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <SourceChip live={rep.reached_live} long source={rep.source} />
        <Meta k="asked">{rep.provider}</Meta>
        <Meta k="answered">{rep.source}</Meta>
        <span className="border-l border-line h-4" aria-hidden />
        <Meta k="as-of">{rep.as_of}</Meta>
        {rep.reached_live ? (
          <>
            <Meta k="fetched">{rep.fetched_at ? isoDateTime(rep.fetched_at) : "—"}</Meta>
            <Meta k="cache">
              {rep.cache ? (
                <>
                  {rep.cache.dir} <span className={rep.cache.hit ? "text-[var(--clear-text)]" : "text-[var(--review-text)]"}>{rep.cache.hit ? "hit" : "miss"}</span>
                </>
              ) : (
                "—"
              )}
            </Meta>
          </>
        ) : (
          /* the fixture answered: nothing was fetched and nothing was cached, said in words rather than dashes */
          <Meta k="status">Fixture · not fetched · no cache</Meta>
        )}
        <Meta k="baskets">{rep.baskets_file}</Meta>
      </div>
      <p className="text-[11px] text-muted mt-2">
        {rep.used_by.note}{" "}
        <span className="mono">
          multiple.mode={rep.used_by.multiple_mode} · calibration={rep.used_by.calibration_enabled ? "on" : "off"}
        </span>
      </p>
      {n > 0 && (
        <div className="mt-2 text-[12px]">
          <button
            className="inline-flex items-center gap-1.5 text-[var(--review-text)] hover:underline"
            onClick={() => setShowErrors((v) => !v)}
            aria-expanded={showErrors}
          >
            <span className="chip disp-REVIEW no-dot">{n}</span>
            {n === 1 ? "constituent could not be priced" : "constituents could not be priced"}
            <span className="text-muted text-[11px]">{showErrors ? "hide" : "show"}</span>
          </button>
          {showErrors && (
            <ul className="mt-1.5 ml-1 space-y-0.5 text-[11px] text-ink2 mono">
              {rep.errors.map((e, i) => (
                <li key={i} className="pl-2 border-l-2 border-[var(--review)]">
                  {e}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- data quality

/** One caveat that applies to this run: a short title and one or two sentences. */
interface Caveat {
  key: string;
  title: string;
  text: string;
  /** a check that passed, listed for the record; not counted as a caveat */
  ok?: boolean;
}

/** Whole days from `a` to `b` (positive when `b` is later); null when either does not parse. */
function daysBetween(a: string | null | undefined, b: string | null | undefined): number | null {
  if (!a || !b) return null;
  const ta = Date.parse(a), tb = Date.parse(b);
  if (!Number.isFinite(ta) || !Number.isFinite(tb)) return null;
  return Math.round((tb - ta) / 86400000);
}

/** "2026-09" -> "September 2026". */
function monthLabel(ym: string): string {
  const t = Date.parse(`${ym}-01T00:00:00Z`);
  if (!Number.isFinite(t)) return ym;
  return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(t));
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** A share count from a diluted weighted average is an approximation of the count outstanding, and labelled as one. */
function isDilutedBasis(c: MarketConstituent): boolean {
  const b = (c.shares_basis ?? "").toLowerCase();
  return b.includes("diluted") || b.includes("average");
}

/** Each ticker once, whichever sectors it sits in — the run-level counts are per name, not per seat. */
function distinctPriced(rep: MarketReport): MarketConstituent[] {
  const seen = new Map<string, MarketConstituent>();
  for (const s of rep.sectors) for (const c of s.constituents) if (c.status === "ok" && !seen.has(c.ticker)) seen.set(c.ticker, c);
  return [...seen.values()];
}

/** The caveats that apply to this run, computed from the report. Only the ones that apply are returned. */
function qualityCaveats(rep: MarketReport): Caveat[] {
  const out: Caveat[] = [];
  if (!rep.reached_live) return out;
  const priced = distinctPriced(rep);
  const live = rep.sectors.filter((s) => s.live);
  const obsMonth = live[0]?.as_of_month ?? rep.as_of.slice(0, 7);

  // 1 — the close was retrieved before the valuation date: it is the last close on file, not an as-of print
  const lag = daysBetween(rep.fetched_at, `${rep.as_of}T00:00:00Z`);
  if (lag !== null && lag > 0)
    out.push({
      key: "asof",
      title: "Close not dated to the valuation date",
      text: `The ${monthLabel(obsMonth)} close was retrieved ${lag} day${lag === 1 ? "" : "s"} before ${shortDate(rep.as_of)} (on ${shortDate(
        rep.fetched_at,
      )}). It is the last close on file at retrieval, not a ${shortDate(rep.as_of)} print.`,
    });

  // 2 — share-count provenance
  const rejected = priced.filter((c) => (c.shares_rejected?.length ?? 0) > 0);
  const diluted = priced.filter(isDilutedBasis);
  const ages = priced.map((c) => c.shares_age_days).filter((n): n is number => typeof n === "number");
  const medAge = median(ages);
  if (rejected.length || diluted.length || medAge !== null)
    out.push({
      key: "shares",
      title: "Share counts",
      text: `${rejected.length} of ${priced.length} priced names passed over a concept the filer had abandoned or left at zero; ${
        diluted.length
      } ${diluted.length === 1 ? "is" : "are"} priced on a diluted weighted average rather than a count outstanding. Median count age ${
        medAge === null ? "—" : `${Math.round(medAge)} days`
      }; no count older than 450 days is used at all.`,
    });

  // 3 — negative enterprise value: the inputs stand, the month leaves the median
  const negMonths = priced.reduce((a, c) => a + (c.months_negative_ev ?? 0), 0);
  const negNow = priced.filter((c) => (c.ev_to_revenue ?? 1) < 0);
  if (negMonths > 0 || negNow.length)
    out.push({
      key: "negev",
      title: "Negative enterprise value",
      text: `${negMonths} constituent-month${negMonths === 1 ? "" : "s"} with net cash above market cap${
        negNow.length ? ` (${negNow.map((c) => c.ticker).join(", ")} at ${obsMonth})` : ""
      }. Such a month is excluded from the median because a negative multiple is not a comparable; the inputs are kept and counted, not deleted.`,
    });

  // 4 — split basis: closes come back split-adjusted, EDGAR counts are as filed
  if (priced.length) {
    const unverifiedNames = priced.filter((c) => c.splits_known !== true);
    const withheld = priced.reduce((a, c) => a + (c.months_unverified_splits ?? 0), 0);
    out.push(
      unverifiedNames.length === 0
        ? {
            key: "splits",
            title: "Split basis verified",
            text: "Split events are on file for every priced name, so each month's close and share count sit on one basis.",
            ok: true,
          }
        : {
            key: "splits",
            title: "Split basis unverified",
            text: `${unverifiedNames.length} of ${priced.length} priced names have no split history on file, so ${withheld.toLocaleString()} constituent-month${
              withheld === 1 ? " was" : "s were"
            } withheld rather than priced on two bases (closes are split-adjusted; EDGAR counts are as filed).`,
          },
    );
  }

  // 5 — basket depth: a five-name median is one name
  const depths = live.map((s) => s.counts?.[s.as_of_month] ?? s.constituents.filter((c) => c.status === "ok").length);
  if (depths.length) {
    const minDepth = Math.min(...depths);
    const thinnest = live.filter((_, i) => depths[i] === minDepth).map((s) => s.sector);
    out.push({
      key: "depth",
      title: "Basket depth",
      text: `Thinnest live basket at ${obsMonth}: ${minDepth} name${minDepth === 1 ? "" : "s"} (${
        thinnest.length === live.length ? "every sector" : thinnest.join(", ")
      }). A five-name median is set by its third name — read a sector multiple as one company's multiple, not a market's.`,
    });
  }

  return out;
}

/** The caveats behind one priced constituent, as short lines for a tooltip. */
function constituentCaveats(c: MarketConstituent): string[] {
  const out: string[] = [];
  if (c.status !== "ok") return out;
  for (const r of c.shares_rejected ?? []) out.push(`shares: passed over ${r}`);
  if (isDilutedBasis(c)) out.push(`shares: ${c.shares_basis} used as the count outstanding`);
  if ((c.ev_to_revenue ?? 1) < 0) out.push("negative EV at as-of: net cash above market cap, not in the median");
  const neg = c.months_negative_ev ?? 0;
  if (neg > 0) out.push(`${neg} month${neg === 1 ? "" : "s"} excluded: negative EV`);
  if (c.splits_known === false) {
    const w = c.months_unverified_splits ?? 0;
    out.push(w > 0 ? `splits unverified: ${w} month${w === 1 ? "" : "s"} withheld` : "splits unverified");
  }
  return out;
}

function DataQuality({ rep }: { rep: MarketReport }) {
  const caveats = useMemo(() => qualityCaveats(rep), [rep]);
  if (!caveats.length) return null;
  const n = caveats.filter((c) => !c.ok).length;
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="eyebrow text-muted">Data quality</span>
        <span className={`chip ${n ? "disp-REVIEW" : "disp-CLEAR"} no-dot`}>{n}</span>
        <span className="text-[11px] text-muted">
          {n === 1 ? "caveat" : "caveats"} on this run · per-name detail in the constituents table
        </span>
      </div>
      <dl className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-2 m-0">
        {caveats.map((c) => (
          <div key={c.key} className="text-[11.5px] leading-snug">
            <dt className={`font-semibold ${c.ok ? "text-[var(--clear-text)]" : "text-ink2"}`}>{c.title}</dt>
            <dd className="m-0 text-muted">{c.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// ---------------------------------------------------------------- sector table

const scol = createColumnHelper<MarketSector>();

function okCount(s: MarketSector): { ok: number; total: number; sampled: boolean } {
  const total = s.constituents.length;
  const ok = s.constituents.filter((c) => c.status === "ok").length;
  return { ok, total, sampled: total > 0 && s.constituents.every((c) => c.status === "fixture") };
}

function SectorTable({ sectors, selected, onSelect }: { sectors: MarketSector[]; selected: string | null; onSelect: (s: string) => void }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "positions", desc: true }]);
  const columns = useMemo<ColumnDef<MarketSector, any>[]>(
    () => [
      scol.accessor("sector", { header: "Sector", cell: (i) => <span className="font-medium">{i.getValue()}</span> }),
      scol.accessor("positions", { header: "Positions", meta: { r: true }, cell: (i) => <span className="num">{i.getValue()}</span> }),
      scol.accessor("ev_to_revenue", { header: "EV/Revenue", meta: { r: true }, cell: (i) => <span className="mono">{mult(i.getValue(), 1)}</span> }),
      scol.accessor("qoq_pct", {
        header: "QoQ",
        meta: { r: true },
        sortUndefined: "last",
        cell: (i) => <span className={`num ${signClass(i.getValue())}`}>{pct(i.getValue(), 1, true)}</span>,
      }),
      scol.accessor("as_of_month", { header: "As-of", cell: (i) => <span className="mono">{i.getValue()}</span> }),
      scol.accessor("live", { header: "Source", cell: (i) => <SourceChip live={i.getValue()} source={i.row.original.source} /> }),
      scol.accessor((s) => okCount(s).ok, {
        id: "ok",
        header: "Constituents",
        meta: { r: true },
        cell: (i) => {
          const { ok, total, sampled } = okCount(i.row.original);
          return sampled ? (
            <span className="num text-muted" title="Sample constituents named by the fixture; not priced">
              {total} sample
            </span>
          ) : (
            <span className="num" title={`${ok} of ${total} constituents priced`}>
              {ok}/{total}
            </span>
          );
        },
      }),
    ],
    [],
  );
  const table = useReactTable({
    data: sectors,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (r) => r.sector,
  });
  return (
    <div className="card overflow-x-auto">
      <table className="dtable text-[12px]">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const r = (h.column.columnDef.meta as { r?: boolean } | undefined)?.r;
                const sorted = h.column.getIsSorted();
                return (
                  <th
                    key={h.id}
                    className={`sortable ${r ? "r" : ""}`}
                    onClick={h.column.getToggleSortingHandler()}
                    aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {sorted && <span className="ml-1 text-accent">{sorted === "asc" ? "↑" : "↓"}</span>}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => {
            const s = row.original;
            const isSel = selected === s.sector;
            return (
              <tr
                key={row.id}
                className={`row ${isSel ? "expanded" : ""}`}
                onClick={() => onSelect(s.sector)}
                aria-selected={isSel}
                style={isSel ? { boxShadow: "inset 3px 0 0 var(--accent)" } : undefined}
              >
                {row.getVisibleCells().map((cell) => {
                  const r = (cell.column.columnDef.meta as { r?: boolean } | undefined)?.r;
                  return (
                    <td key={cell.id} className={r ? "r" : ""}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- history chart

interface Point {
  month: string;
  v: number;
}

function HistoryChart({ sector }: { sector: MarketSector }) {
  const th = useChartTheme();
  const data = useMemo<Point[]>(
    () =>
      Object.entries(sector.history)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([month, v]) => ({ month, v })),
    [sector],
  );
  const n = data.length;
  const values = data.map((d) => d.v);
  const lo = Math.min(...values, sector.ev_to_revenue);
  const hi = Math.max(...values, sector.ev_to_revenue);
  // nice y ticks: a step from the 1-2-5 series giving four to six gridlines, padded 12% each side
  const span = Math.max(hi - lo, 0.4);
  const step = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20].find((st) => (span * 1.24) / st <= 6) ?? 50;
  const floor = Math.max(0, Math.floor((lo - span * 0.12) / step) * step);
  const ceil = Math.ceil((hi + span * 0.12) / step) * step;
  const yTicks: number[] = [];
  for (let y = floor; y <= ceil + 1e-9; y += step) yTicks.push(Number(y.toFixed(2)));
  const yd = step < 1 ? 1 : 0;
  // about eight labels whatever the span (36 or 96 months), the latest month always among them
  const every = Math.max(1, Math.ceil(n / 8));
  const ticks = data.filter((_, i) => (n - 1 - i) % every === 0).map((d) => d.month);
  const last = data[n - 1];

  if (n === 0) return <div className="text-[12px] text-muted p-6 text-center">No history for this sector.</div>;

  return (
    <div style={{ height: 240 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 32, left: 0, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke={th.grid} strokeWidth={1} />
          <XAxis
            dataKey="month"
            ticks={ticks}
            interval={0}
            tick={{ fill: th.muted, fontSize: 11, fontFamily: MONO }}
            axisLine={{ stroke: th.axis }}
            tickLine={false}
            tickMargin={6}
          />
          <YAxis
            domain={[floor, ceil]}
            ticks={yTicks}
            allowDataOverflow
            tick={{ fill: th.muted, fontSize: 11, fontFamily: MONO }}
            axisLine={false}
            tickLine={false}
            width={48}
            tickFormatter={(v: number) => mult(v, yd)}
          />
          <ReferenceLine y={sector.ev_to_revenue} stroke={th.axis} strokeWidth={1} />
          <Tooltip
            cursor={{ stroke: th.axis, strokeWidth: 1 }}
            isAnimationActive={false}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0].payload as Point;
              return (
                <div className="tooltip-box">
                  <div className="mono text-muted text-[11px]">{p.month}</div>
                  <div className="num">
                    <strong>{mult(p.v, 2)}</strong> <span className="text-muted">EV/Revenue</span>
                  </div>
                </div>
              );
            }}
          />
          <Line
            type="monotone"
            dataKey="v"
            stroke={th.series1}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            isAnimationActive={false}
            dot={(p: { cx?: number; cy?: number; index?: number }) =>
              p.index === n - 1 && p.cx !== undefined && p.cy !== undefined ? (
                <circle key="end" cx={p.cx} cy={p.cy} r={4} fill={th.series1} stroke={th.surface} strokeWidth={2} />
              ) : (
                <g key={p.index} />
              )
            }
            activeDot={{ r: 4, fill: th.series1, stroke: th.surface, strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
      <span className="sr-only">
        {sector.sector} EV/Revenue, {data[0].month} to {last.month}, currently {mult(sector.ev_to_revenue, 1)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------- constituents

const ccol = createColumnHelper<MarketConstituent>();

function Num({ v, d = 1, x = false }: { v: number | null; d?: number; x?: boolean }) {
  return <span className={x ? "mono" : "num"}>{x ? mult(v, d) : musd(v, d)}</span>;
}

function ConstituentsTable({ sector }: { sector: MarketSector }) {
  const columns = useMemo<ColumnDef<MarketConstituent, any>[]>(
    () => [
      ccol.accessor("ticker", { header: "Ticker", cell: (i) => <span className="mono font-medium">{i.getValue()}</span> }),
      ccol.accessor("name", {
        header: "Name",
        cell: (i) => {
          const c = i.row.original;
          return (
            <span className="block max-w-[420px]">
              <span className="block truncate max-w-[260px]" title={c.name ?? undefined}>
                {c.name ?? <span className="text-muted">—</span>}
              </span>
              {c.error && <span className="block text-[11px] text-muted whitespace-normal">{c.error}</span>}
            </span>
          );
        },
      }),
      ccol.accessor("status", { header: "Status", cell: (i) => <StatusChip s={i.getValue()} /> }),
      ccol.accessor("price", { header: "Price", meta: { r: true }, cell: (i) => <Num v={i.getValue()} d={2} /> }),
      ccol.accessor("shares_m", {
        header: "Shares (M)",
        meta: { r: true },
        cell: (i) => {
          const c = i.row.original;
          const basis = c.shares_basis ?? null;
          const tip = basis
            ? `${basis}${c.shares_as_of ? ` as of ${c.shares_as_of}` : ""}${typeof c.shares_age_days === "number" ? ` (${c.shares_age_days} days before the valuation date)` : ""}`
            : undefined;
          return (
            <span className="block" title={tip}>
              <Num v={i.getValue()} d={1} />
              {basis && (
                <span className={`block text-[10.5px] whitespace-nowrap ${isDilutedBasis(c) ? "text-[var(--review-text)]" : "text-muted"}`}>
                  {basis.replace("outstanding, ", "")}
                  {c.shares_as_of && <span className="mono"> · {c.shares_as_of}</span>}
                </span>
              )}
            </span>
          );
        },
      }),
      ccol.accessor("market_cap_musd", { header: "Market cap ($M)", meta: { r: true }, cell: (i) => <Num v={i.getValue()} d={0} /> }),
      ccol.accessor("net_cash_musd", { header: "Net cash ($M)", meta: { r: true }, cell: (i) => <Num v={i.getValue()} d={0} /> }),
      ccol.accessor("ttm_revenue_musd", { header: "TTM revenue ($M)", meta: { r: true }, cell: (i) => <Num v={i.getValue()} d={0} /> }),
      ccol.accessor("revenue_through", { header: "Revenue through", cell: (i) => <span className="mono">{i.getValue() ?? "—"}</span> }),
      ccol.accessor("ev_to_revenue", { header: "EV/Rev", meta: { r: true }, cell: (i) => <Num v={i.getValue()} d={1} x /> }),
      ccol.accessor((c) => constituentCaveats(c).length, {
        id: "quality",
        header: "Quality",
        cell: (i) => {
          const c = i.row.original;
          if (c.status !== "ok") return <span className="text-muted">—</span>;
          const lines = constituentCaveats(c);
          return lines.length ? (
            <span className="chip disp-REVIEW no-dot" title={lines.join("\n")}>
              {lines.length} caveat{lines.length === 1 ? "" : "s"}
            </span>
          ) : (
            <span className="chip disp-CLEAR no-dot" title="Share count current and outstanding; split basis verified; no month excluded">
              clean
            </span>
          );
        },
      }),
    ],
    [],
  );
  const table = useReactTable({
    data: sector.constituents,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r, i) => `${r.ticker}-${i}`,
  });
  return (
    <div className="overflow-x-auto -mx-4 px-4">
      <table className="dtable text-[12px]">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const r = (h.column.columnDef.meta as { r?: boolean } | undefined)?.r;
                return (
                  <th key={h.id} className={r ? "r" : ""}>
                    {flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="text-muted text-center py-4">
                No constituents listed for this sector.
              </td>
            </tr>
          )}
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => {
                const r = (cell.column.columnDef.meta as { r?: boolean } | undefined)?.r;
                return (
                  <td key={cell.id} className={`${r ? "r" : ""} ${row.original.status === "error" ? "text-ink2" : ""}`} style={{ verticalAlign: "top" }}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- view

// ---------------------------------------------------------------- M-080 calibration

type CalRow = {
  c: CompanyResult;
  age: number;
  then: number;
  now: number;
  monthUsed: string;
  roundMonth: string;
  raw: number;
  factor: number;
  bounded: boolean;
  equity: number;
  calibrated: number;
};

function calibrationRows(run: ValuationRun): { rows: CalRow[]; stale: number } {
  const rows: CalRow[] = [];
  let stale = 0;
  for (const c of run.companies) {
    const step = c.steps.find((s) => s.rule_id === "M-080");
    const alt = c.alternative_marks?.calibrated_to_comps;
    if (!step || alt === undefined) {
      const md = new Date(run.manifest.measurement_date), an = new Date(c.staleness_anchor);
      const months = (md.getFullYear() - an.getFullYear()) * 12 + (md.getMonth() - an.getMonth());
      if (months >= 24 && !c.listed && c.arr !== null && c.fv_level === 3) stale += 1;
      continue;
    }
    const i = step.inputs as Record<string, any>;
    const factor = Number(i.factor_bounded);
    rows.push({
      c,
      age: Number(i.age_months),
      then: Number(i.comp_multiple_at_round),
      now: Number(i.comp_multiple_now),
      monthUsed: String(i.comp_month_used ?? ""),
      roundMonth: String(i.round_month ?? ""),
      raw: Number(i.factor_raw ?? factor),
      factor,
      bounded: Boolean(i.bound_hit),
      equity: c.equity_mark,
      calibrated: alt,
    });
  }
  rows.sort((a, b) => Math.abs(b.calibrated - b.equity) - Math.abs(a.calibrated - a.equity));
  return { rows, stale };
}

/** The stretch item from the brief: a defensible adjustment for stale rounds, calibrated to the
    movement in public comparable multiples since the round closed. Alternatives only. */
function CalibrationCard({ run, rep, onGoto }: { run: ValuationRun; rep: MarketReport; onGoto?: (name: string) => void }) {
  const { rows, stale } = useMemo(() => calibrationRows(run), [run]);
  const total = rows.reduce((a, r) => a + (r.calibrated - r.equity), 0);
  const base = rows.reduce((a, r) => a + r.equity, 0);
  const pinned = rows.filter((r) => r.bounded).length;
  return (
    <div className="card p-4 xl:col-span-2 min-w-0">
      <SectionTitle
        right={
          rows.length ? (
            <span className="num">
              {rows.length} calibrated · {pinned} at the ±35% bound · net{" "}
              <span className={signClass(total)}>
                {total >= 0 ? "+" : ""}
                {musd(total, 1)}
              </span>{" "}
              on {musd(base, 1)}
            </span>
          ) : (
            <span className="num">{stale} stale positions · none calibrated</span>
          )
        }
      >
        Stale-round calibration · M-080
      </SectionTitle>
      <p className="text-[11px] text-muted mb-2">
        For a Level 3 position whose price anchor is 24+ months old: calibrated = equity mark × (sector comps now ÷ sector comps in the round
        month), bounded ±35%. Written as the <span className="mono">calibrated_to_comps</span> alternative — the base mark never moves; a
        reviewer books it through the "Calibrate to public comps" resolution on X-202 / X-106 / X-405.
        {!rep.reached_live && (
          <>
            {" "}
            <span className="chip disp-MONITOR no-dot">gated</span> Only an observed comps history calibrates; the fixture never does. Run with{" "}
            <span className="mono">--provider live</span>.
          </>
        )}
      </p>
      {rows.length > 0 && (
        <div className="overflow-x-auto -mx-4 px-4">
          <table className="dtable text-[12px]">
            <thead>
              <tr>
                <th>Company</th>
                <th>Sector</th>
                <th className="r">Round</th>
                <th className="r">Age</th>
                <th className="r">Comps then → now</th>
                <th className="r">Factor</th>
                <th className="r">Equity mark</th>
                <th className="r">Calibrated</th>
                <th className="r">Δ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const d = r.calibrated - r.equity;
                return (
                  <tr key={r.c.company}>
                    <td>
                      {onGoto ? (
                        <button className="btn btn-ghost font-medium" style={{ padding: "0 4px" }} onClick={() => onGoto(r.c.company)}>
                          {r.c.company}
                        </button>
                      ) : (
                        <span className="font-medium">{r.c.company}</span>
                      )}{" "}
                      <span className={`chip disp-${r.c.disposition} no-dot`} style={{ fontSize: 9 }}>
                        {r.c.disposition}
                      </span>
                    </td>
                    <td className="text-ink2">{r.c.sector}</td>
                    <td className="r mono" title={r.monthUsed !== r.roundMonth ? `no basket value in ${r.roundMonth}; read at ${r.monthUsed}` : undefined}>
                      {r.roundMonth}
                      {r.monthUsed !== r.roundMonth && <span className="text-muted"> ≈{r.monthUsed}</span>}
                    </td>
                    <td className="r num">{r.age} mo</td>
                    <td className="r num">
                      {r.then.toFixed(1)}× → {r.now.toFixed(1)}×
                    </td>
                    <td className="r num" title={r.bounded ? `raw ${r.raw.toFixed(3)}, pinned at the bound` : undefined}>
                      {r.factor.toFixed(3)}
                      {r.bounded && <span className="text-muted"> ⌐</span>}
                    </td>
                    <td className="r num">{musd(r.equity, 2)}</td>
                    <td className="r num font-medium">{musd(r.calibrated, 2)}</td>
                    <td className={`r num ${signClass(d)}`}>
                      {d >= 0 ? "+" : ""}
                      {musd(d, 2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {pinned > 0 && (
            <p className="text-[11px] text-muted mt-1">⌐ factor pinned at the ±35% bound (the raw ratio is in the tooltip).</p>
          )}
        </div>
      )}
    </div>
  );
}

export function MarketView({ mode, run, onGoto }: { mode: Mode; run?: ValuationRun; onGoto?: (name: string) => void }) {
  const { data: rep, error, loading } = useAsync(() => loadMarket(mode), [mode]);
  const [selected, setSelected] = useState<string | null>(null);

  // default to the sector with the most portfolio positions (the API's first row)
  useEffect(() => {
    if (rep && (selected === null || !rep.sectors.some((s) => s.sector === selected))) setSelected(rep.sectors[0]?.sector ?? null);
  }, [rep, selected]);

  if (error)
    return (
      <div className="p-8 max-w-[640px] mx-auto">
        <h1 className="font-semibold text-[16px] mb-2">Could not load the market feed</h1>
        <p className="text-ink2 mono text-[12px] mb-4">{error}</p>
        <p className="text-[12px] text-muted">
          {mode === "static" ? (
            <>
              This export predates the market feed. Rebuild it with <span className="mono">hc-valuation build</span> on an engine that inlines{" "}
              <span className="mono">window.__HC_MARKET__</span>, or serve the dashboard with <span className="mono">hc-valuation run</span>.
            </>
          ) : (
            <>
              The server did not answer <span className="mono">GET /api/market</span>. It may predate the market feed; restart it with{" "}
              <span className="mono">hc-valuation run --provider live</span> (or <span className="mono">stub</span>) to expose the sector comps.
            </>
          )}
        </p>
      </div>
    );
  if (loading || !rep) return <div className="p-8 text-muted">Loading market feed…</div>;

  const sector = rep.sectors.find((s) => s.sector === selected) ?? rep.sectors[0];
  const liveCount = rep.sectors.filter((s) => s.live).length;

  return (
    <div className="space-y-4">
      <HeaderStrip rep={rep} />
      <DataQuality rep={rep} />

      {rep.sectors.length === 0 ? (
        <div className="card p-6 text-center text-muted text-[12px]">No sectors in the market report.</div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
          <div>
            <SectionTitle
              right={
                <>
                  {liveCount}/{rep.sectors.length} sectors live · EV / TTM revenue at {rep.as_of}
                </>
              }
            >
              Sector comps
            </SectionTitle>
            <SectorTable sectors={rep.sectors} selected={sector?.sector ?? null} onSelect={setSelected} />
          </div>

          {sector && (
            <div className="min-w-0">
              <div className="card p-4">
                <SectionTitle
                  right={
                    <span className="num">
                      now <span className="mono text-ink2">{mult(sector.ev_to_revenue, 1)}</span> · prior quarter{" "}
                      <span className="mono text-ink2">{mult(sector.prior_quarter, 1)}</span> ·{" "}
                      <span className={signClass(sector.qoq_pct)}>{pct(sector.qoq_pct, 1, true)}</span>
                    </span>
                  }
                >
                  <span className="flex items-center gap-2">
                    {sector.sector} · EV/Revenue history
                    <SourceChip live={sector.live} source={sector.source} />
                  </span>
                </SectionTitle>
                <p className="text-[11px] text-muted mb-1 num">
                  {Object.keys(sector.history).length} months through {sector.as_of_month} · source <span className="mono">{sector.source}</span>.
                  Hairline marks the value in force at as-of.
                </p>
                <HistoryChart sector={sector} />
              </div>
            </div>
          )}

          {sector && (
            <div className="card p-4 xl:col-span-2 min-w-0">
              <SectionTitle right={<>{okCount(sector).sampled ? "sample basket · not priced" : `${okCount(sector).ok}/${okCount(sector).total} priced`}</>}>
                Constituents · {sector.sector}
              </SectionTitle>
              {(okCount(sector).sampled || !rep.reached_live) && (
                <p className="text-[12px] text-ink2 mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="chip disp-NONE">FIXTURE</span>
                  <span>
                    Sample basket — not priced (fixture data). Run with <span className="mono">--provider live</span> to price constituents.
                  </span>
                </p>
              )}
              <ConstituentsTable sector={sector} />
              <p className="text-[11px] text-muted mt-2">
                EV = price × shares − net cash; EV/Revenue = EV / trailing-twelve-month revenue, built from each filer's own reported
                periods (SEC XBRL companyfacts) so a January or April fiscal year reads like a calendar one.
              </p>
            </div>
          )}

          {run && <CalibrationCard run={run} rep={rep} onGoto={onGoto} />}
        </div>
      )}
    </div>
  );
}
