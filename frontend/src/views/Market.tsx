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
import type { CompanyResult, MarketConstituent, MarketReport, MarketSector, ValuationRun } from "../types";
import { loadMarket, type Mode } from "../lib/api";
import { isoDateTime, mmddyy, mult, musd, pct, shortDate, signClass } from "../lib/format";
import { altLabel, humanize } from "../lib/labels";
import { useChartTheme } from "../lib/theme";
import { MarketStatusButton } from "../components/MarketStatus";
import { ReadinessChip, SectionTitle, useAsync } from "../components/ui";

const MONO = "IBM Plex Mono, ui-monospace, monospace";

// ---------------------------------------------------------------- chips

/** "live:edgar+yahoo" (or "live:edgar+yahoo@2026-09") -> ["EDGAR", "Yahoo"]: the parts of a live label, for display. */
function liveParts(source: string | undefined): string[] {
  const body = (source ?? "").replace(/^live:/, "").replace(/@.*$/, "");
  const parts = body ? body.split("+") : [];
  return parts.map((p) => (p.toLowerCase() === "edgar" ? "EDGAR" : p.charAt(0).toUpperCase() + p.slice(1).toLowerCase()));
}

/** Where the numbers came from, said in a sentence rather than as a provider id. */
function sourceWords(source: string | undefined, live: boolean): string {
  if ((source ?? "").startsWith("synthetic:")) return "synthetic test data invented for this quarter — not an observation of any market";
  if (!live) return "an illustrative set of multiples shipped with the engine, not from live market data";
  const parts = liveParts(source);
  if (parts.length < 2) return "SEC filings and month-end closing prices";
  return `${parts[0]} filings and ${parts.slice(1).join(" and ")} month-end closing prices`;
}

const ILLUSTRATIVE_TIP =
  "Illustrative sector multiples shipped with the engine, in the shape a market-data vendor would supply. They stand in for live market data, and no booked mark depends on them.";

/** Where a number came from. Green only when a live source actually answered; the label names the sources in `source`. */
const SYNTHETIC_TIP = "Invented for a test quarter by a script. Not market data, never fetched, never cached; no mark calibrates to it.";

function SourceChip({ live, long = false, source }: { live: boolean; long?: boolean; source?: string }) {
  const parts = liveParts(source);
  if ((source ?? "").startsWith("synthetic:"))
    return (
      <span className="chip disp-BLOCK" title={SYNTHETIC_TIP}>
        {long ? "Synthetic test data · invented" : "Synthetic"}
      </span>
    );
  const names = parts.length ? parts.join(" + ") : "EDGAR + prices";
  const prices = parts.length > 1 ? parts.slice(1).join(" + ") : "the price source";
  return live ? (
    <span className="chip disp-CLEAR" title={`Priced from SEC EDGAR company filings and ${prices} month-end closes`}>
      {long ? `Live market data · ${names}` : "Live market data"}
    </span>
  ) : (
    <span className="chip disp-NONE" title={ILLUSTRATIVE_TIP}>
      {long ? "Illustrative · not live market data" : "Illustrative"}
    </span>
  );
}

// ---------------------------------------------------------------- header strip

/** What this policy does with the sector multiples, in the reviewer's words rather than as a
    config dump. The engine's own wording stays verbatim under Technical details. */
function policySentences(rep: MarketReport): string {
  const screens =
    rep.used_by.multiple_mode === "relative_to_comps"
      ? "Screens X-401 and X-402 compare each mark's implied multiple against these sector multiples."
      : "Screens X-401 and X-402 use absolute thresholds under this policy, so these multiples do not currently bite on a mark.";
  const cal = rep.used_by.calibration_enabled
    ? "Stale-round calibration (M-080) reads the monthly history to write the calibrated alternative mark."
    : "Stale-round calibration is switched off for this run, so no alternative mark is written from this history.";
  return `${screens} ${cal}`;
}

/** One number a reviewer can act on, with the words that make it one. */
function Kpi({ label, value, tone, sub }: { label: string; value: React.ReactNode; tone?: "up" | "down" | "warn" | "ok"; sub: React.ReactNode }) {
  const color =
    tone === "up" ? "text-[var(--clear-text)]" : tone === "down" ? "text-[var(--block-text)]" : tone === "warn" ? "text-[var(--review-text)]" : "text-ink";
  return (
    <div className="card p-3.5 min-w-0">
      <div className="eyebrow-sm">{label}</div>
      <div className={`num text-[24px] font-semibold leading-tight mt-0.5 ${color}`}>{value}</div>
      <div className="text-[11px] text-muted mt-1 leading-snug">{sub}</div>
    </div>
  );
}

/** The top of the page: three numbers, then the notices that change how the page is read. Every
    sentence of provenance and every data caveat is kept, one click away under "Data notes". */
function HeaderStrip({ rep, served }: { rep: MarketReport; served: boolean }) {
  const [showErrors, setShowErrors] = useState(false);
  const n = rep.errors.length;
  const askedLive = rep.provider === "live";
  // the requested source and the one that answered are worth a reviewer's attention only when they differ
  const mismatch = askedLive !== rep.reached_live;
  const synthetic = rep.synthetic === true || rep.provider === "synthetic" || rep.source.startsWith("synthetic:");
  const caveats = useMemo(() => qualityCaveats(rep), [rep]);
  const nCaveats = caveats.filter((c) => !c.ok).length;

  // what the multiples did this quarter, weighted by the positions that sit under each sector
  const moved = rep.sectors.filter((s) => s.qoq_pct !== null && s.positions > 0);
  const wsum = moved.reduce((t, s) => t + s.positions, 0);
  const wavg = wsum ? moved.reduce((t, s) => t + (s.qoq_pct as number) * s.positions, 0) / wsum : null;
  const up = moved.filter((s) => (s.qoq_pct as number) > 0).length;
  const down = moved.filter((s) => (s.qoq_pct as number) < 0).length;
  const byMove = [...moved].sort((x, y) => (y.qoq_pct as number) - (x.qoq_pct as number));
  const top = byMove[0];
  const bottom = byMove[byMove.length - 1];

  return (
    <div className="space-y-3">
      {synthetic && (
        <div className="card disp-BLOCK stripe p-3 pl-4" role="alert">
          <div className="flex items-center gap-2">
            <span className="chip disp-BLOCK no-dot">Synthetic test data</span>
            <span className="font-semibold text-[13px]">These multiples were invented for a test quarter. They are not market data.</span>
          </div>
          <p className="text-[12px] text-ink2 mt-1 mb-0">{rep.notice ?? SYNTHETIC_TIP}</p>
        </div>
      )}
      {mismatch && (
        <p className="text-[11.5px] m-0 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="chip disp-REVIEW no-dot">Substituted source</span>
          <span className="text-ink2">
            {askedLive
              ? "Live market data was requested, but the illustrative set answered. Read every multiple on this page as illustrative."
              : "The illustrative set was requested, but live market data answered."}
          </span>
        </p>
      )}
      {/* Market movement and portfolio exposure: what moved, and how much of the book sits in it.
          Every figure is read from the run's comps_move block, never typed in. */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Kpi
          label="Sector multiple movement"
          value={wavg === null ? "—" : `${pct(wavg, 1, true)} this quarter`}
          tone={wavg === null ? undefined : wavg > 0 ? "up" : wavg < 0 ? "down" : undefined}
          sub={
            wavg === null
              ? "No prior quarter on file to compare against"
              : `Average change across ${moved.length} sectors, weighted by portfolio positions · ${up} up, ${down} down`
          }
        />
        <Kpi
          label="Largest sector decline"
          value={
            bottom && (bottom.qoq_pct as number) < 0 ? (
              <span className="inline-flex flex-wrap items-baseline gap-x-2">
                <span className="text-[15px]">{bottom.sector}</span>
                <span>{pct(bottom.qoq_pct, 1, true)}</span>
              </span>
            ) : (
              "—"
            )
          }
          tone={bottom && (bottom.qoq_pct as number) < 0 ? "down" : undefined}
          sub={
            bottom && (bottom.qoq_pct as number) < 0
              ? `${bottom.positions} portfolio ${bottom.positions === 1 ? "position" : "positions"} in this sector`
              : "No sector fell this quarter"
          }
        />
        <Kpi
          label="Largest sector increase"
          value={
            top && (top.qoq_pct as number) > 0 ? (
              <span className="inline-flex flex-wrap items-baseline gap-x-2">
                <span className="text-[15px]">{top.sector}</span>
                <span>{pct(top.qoq_pct, 1, true)}</span>
              </span>
            ) : (
              "—"
            )
          }
          tone={top && (top.qoq_pct as number) > 0 ? "up" : undefined}
          sub={
            top && (top.qoq_pct as number) > 0
              ? `${top.positions} portfolio ${top.positions === 1 ? "position" : "positions"} in this sector`
              : "No sector rose this quarter"
          }
        />
      </div>

      {!rep.reached_live && (
        <p className="text-[11px] text-[var(--review-text)] mt-2 mb-0 leading-snug">
          Illustrative multiples only · {rep.sectors.length} sectors · no live feed answered
        </p>
      )}
      {n > 0 && (
        <div className="text-[12px]">
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
      {/* everything that used to be two panels of text: the caveats, the provenance and the
          operator's half of it. Kept whole, one click away from the numbers. */}
      <details className="px-1">
        <summary className="text-[11px] text-muted cursor-pointer select-none">
          Data notes{nCaveats ? ` · ${nCaveats} ${nCaveats === 1 ? "caveat" : "caveats"}` : ""} · where these multiples come from
        </summary>
        <div className="card p-4 mt-2 space-y-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <SourceChip live={rep.reached_live} long source={rep.source} />
            <span className="text-[11px] text-muted">Sector multiples priced from {sourceWords(rep.source, rep.reached_live)}.</span>
            {served && <MarketStatusButton refreshKey={rep.fetched_at ? rep.fetched_at.length : 0} />}
          </div>
          <p className="text-[11px] text-muted m-0">{policySentences(rep)}</p>
          {caveats.length > 0 && (
            <dl className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-2 m-0">
              {caveats.map((c) => (
                <div key={c.key} className="text-[11.5px] leading-snug">
                  <dt className={`font-semibold ${c.ok ? "text-[var(--clear-text)]" : "text-ink2"}`}>{c.title}</dt>
                  <dd className="m-0 text-muted">{c.text}</dd>
                </div>
              ))}
            </dl>
          )}
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px] m-0">
            <dt className="text-muted">Requested source</dt>
            <dd className="m-0 mono text-ink2">{rep.provider}</dd>
            <dt className="text-muted">Source that answered</dt>
            <dd className="m-0 mono text-ink2">{rep.source}</dd>
            <dt className="text-muted">Fetched at</dt>
            <dd className="m-0 mono text-ink2">{rep.fetched_at ? isoDateTime(rep.fetched_at) : "nothing was fetched"}</dd>
            <dt className="text-muted">Data on file</dt>
            <dd className="m-0 text-ink2">
              {rep.cache ? (rep.cache.hit ? "Read from the saved feed for this quarter" : "Fetched fresh on this run and saved") : "Nothing saved for this run"}
            </dd>
            {rep.synthetic_file && (
              <>
                <dt className="text-muted">Synthetic data file</dt>
                <dd className="m-0 mono text-ink2">{rep.synthetic_file}</dd>
              </>
            )}
            <dt className="text-muted">Policy settings</dt>
            <dd className="m-0 mono text-ink2">
              multiple.mode={rep.used_by.multiple_mode} · calibration={rep.used_by.calibration_enabled ? "on" : "off"}
            </dd>
            <dt className="text-muted">Engine note</dt>
            <dd className="m-0 text-ink2">{rep.used_by.note}</dd>
          </dl>
        </div>
      </details>
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

  // 1 — the multiples are priced as of the fetch day, not the valuation date: say so when the two differ
  const valuation = rep.valuation_date ?? rep.as_of;
  const pricedDay = rep.priced_as_of ?? rep.as_of;
  if (valuation !== pricedDay)
    out.push({
      key: "asof",
      title: "Priced as of the fetch day",
      text: `The ${monthLabel(obsMonth)} multiples are the last close on file at the fetch on ${shortDate(pricedDay)}; the book is valued as of ${shortDate(
        valuation,
      )}. Refresh to price them as of today.`,
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

// ---------------------------------------------------------------- sector table

const scol = createColumnHelper<MarketSector>();

function okCount(s: MarketSector): { ok: number; total: number; sampled: boolean } {
  const total = s.constituents.length;
  const ok = s.constituents.filter((c) => c.status === "ok").length;
  return { ok, total, sampled: total > 0 && s.constituents.every((c) => c.status === "fixture") };
}

function SectorTable({
  sectors,
  selected,
  onSelect,
  pricedAsOf,
}: {
  sectors: MarketSector[];
  selected: string | null;
  onSelect: (s: string) => void;
  pricedAsOf: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "positions", desc: true }]);
  const columns = useMemo<ColumnDef<MarketSector, any>[]>(
    () => [
      scol.accessor("sector", { header: "Sector", cell: (i) => <span className="font-medium">{i.getValue()}</span> }),
      scol.accessor("positions", { header: "Positions", meta: { r: true }, cell: (i) => <span className="num">{i.getValue()}</span> }),
      scol.accessor("ev_to_revenue", { header: "EV/Revenue", meta: { r: true }, cell: (i) => <span className="mono">{mult(i.getValue(), 1)}</span> }),
      scol.accessor("qoq_pct", {
        header: "Change on the quarter",
        meta: { r: true },
        sortUndefined: "last",
        cell: (i) => <span className={`num ${signClass(i.getValue())}`}>{pct(i.getValue(), 1, true)}</span>,
      }),
      // The day the multiples are priced as of, not the month they fall in. It is the same day for
      // every sector in one report, so it is passed in rather than read off the row.
      scol.accessor("as_of_month", {
        header: "Multiple as of",
        cell: () => <span className="num">{mmddyy(pricedAsOf)}</span>,
      }),
    ],
    [pricedAsOf],
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
      ccol.accessor("ticker", {
        header: "Ticker",
        // The filer's own EDGAR page: every figure on this row is derived from facts filed there,
        // so a reviewer can open the filing and see the number exists as of the date shown.
        cell: (i) => {
          const c = i.row.original;
          return c.cik ? (
            <a
              className="mono font-medium srclink"
              href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${c.cik}&type=10-&dateb=&owner=include&count=40`}
              target="_blank"
              rel="noreferrer noopener"
              title={`Open CIK ${c.cik} on EDGAR — the filings every figure on this row is built from`}
            >
              {i.getValue()}
            </a>
          ) : (
            <span className="mono font-medium">{i.getValue()}</span>
          );
        },
      }),
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
      ccol.accessor("price", {
        header: "Price",
        meta: { r: true },
        cell: (i) => {
          const c = i.row.original;
          return (
            <span title={c.price_month ? `Month-end close, ${monthLabel(c.price_month)}, from ${sector.source.split(":").pop()}` : undefined}>
              <Num v={i.getValue()} d={2} />
            </span>
          );
        },
      }),
      ccol.accessor("shares_m", {
        header: "Shares (M)",
        meta: { r: true },
        cell: (i) => {
          const c = i.row.original;
          const basis = c.shares_basis ?? null;
          const tip = basis
            ? `${humanize(basis)}${c.shares_as_of ? `, as filed on ${mmddyy(c.shares_as_of)}` : ""}${
                typeof c.shares_age_days === "number" ? ` (${c.shares_age_days} days before the valuation date)` : ""
              }`
            : undefined;
          return (
            <span className="block" title={tip}>
              <Num v={i.getValue()} d={1} />
              {basis && (
                /* the whole basis, not a fragment of it: "cover page" on its own names nothing */
                <span className={`block text-[10.5px] whitespace-nowrap ${isDilutedBasis(c) ? "text-[var(--review-text)]" : "text-muted"}`}>
                  {humanize(basis)}
                  {c.shares_as_of && <span> · {mmddyy(c.shares_as_of)}</span>}
                </span>
              )}
            </span>
          );
        },
      }),
      ccol.accessor("market_cap_musd", { header: "Market cap ($M)", meta: { r: true }, cell: (i) => <Num v={i.getValue()} d={0} /> }),
      ccol.accessor("net_cash_musd", { header: "Net cash ($M)", meta: { r: true }, cell: (i) => <Num v={i.getValue()} d={0} /> }),
      ccol.accessor("ttm_revenue_musd", {
        header: "TTM revenue ($M)",
        meta: { r: true },
        cell: (i) => {
          const c = i.row.original;
          return (
            <span
              title={
                c.revenue_through
                  ? `Trailing twelve months to ${mmddyy(c.revenue_through)}, summed from the filer's own reported periods (SEC XBRL companyfacts)`
                  : undefined
              }
            >
              <Num v={i.getValue()} d={0} />
            </span>
          );
        },
      }),
      ccol.accessor("revenue_through", {
        header: "Revenue through",
        cell: (i) => <span className="num" title="The last reported period end included in the trailing-twelve-month figure">{mmddyy(i.getValue())}</span>,
      }),
      ccol.accessor("ev_to_revenue", { header: "EV/Revenue", meta: { r: true }, cell: (i) => <Num v={i.getValue()} d={1} x /> }),
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
  nThen: number | null;   // constituents behind the round-month median
  nNow: number | null;    // constituents behind the measurement-month median
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
      nThen: typeof i.n_constituents_at_round === "number" ? i.n_constituents_at_round : null,
      nNow: typeof i.n_constituents_now === "number" ? i.n_constituents_now : null,
    });
  }
  rows.sort((a, b) => Math.abs(b.calibrated - b.equity) - Math.abs(a.calibrated - a.equity));
  return { rows, stale };
}

/** The stretch item from the brief: a defensible adjustment for stale rounds, calibrated to the
    movement in public comparable multiples since the round closed. Alternatives only. */
function CalibrationCard({ run, rep, onGoto }: { run: ValuationRun; rep: MarketReport; onGoto?: (name: string) => void }) {
  const { rows, stale } = useMemo(() => calibrationRows(run), [run]);
  // How many names the sector's basket holds, so "4 of 5" can be shown against the median's depth.
  const basketSize = useMemo(() => new Map(rep.sectors.map((x) => [x.sector, x.constituents.length])), [rep]);
  // A median taken over fewer names than the basket holds is a different statistic from the one it
  // is divided by, so the rows where that happens are called out rather than left to be assumed.
  const thin = rows.filter((r) => {
    const n = basketSize.get(r.c.sector);
    return n !== undefined && ((r.nThen !== null && r.nThen < n) || (r.nNow !== null && r.nNow < n));
  }).length;
  const total = rows.reduce((a, r) => a + (r.calibrated - r.equity), 0);
  const base = rows.reduce((a, r) => a + r.equity, 0);
  const pinned = rows.filter((r) => r.bounded).length;
  return (
    <div className="card p-4 xl:col-span-2 min-w-0">
      <SectionTitle
        right={
          rows.length ? (
            <span className="num">
              {rows.length} calibrated · {pinned} capped at ±35% · net{" "}
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
        <span className="flex items-center gap-2">
          Stale-round calibration
          <span className="chip disp-NONE no-dot mono" style={{ fontSize: 10 }} title="The policy rule behind this table">
            M-080
          </span>
        </span>
      </SectionTitle>
      <p className="text-[11px] text-muted mb-2">
        For a Level 3 position whose price anchor is 24+ months old: calibrated = equity mark × (sector comps now ÷ sector comps in the round
        month), capped at ±35%. It is written as the “{altLabel("calibrated_to_comps")}” alternative — the base mark never moves; a reviewer
        books it through the "Calibrate to public comps" resolution offered on the finding that raised it.
        {!rep.reached_live && (
          <>
            {" "}
            <span className="chip disp-MONITOR no-dot">Nothing calibrated</span> Calibration needs an observed history of comparable multiples
            to measure the movement since each round closed. This run is on illustrative multiples, which carry no such history, so no position
            was calibrated.
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
                <th className="r">Adjustment factor</th>
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
                      <ReadinessChip r={r.c.readiness} className="no-dot" />
                    </td>
                    <td className="text-ink2">{r.c.sector}</td>
                    <td
                      className="r mono"
                      title={
                        r.monthUsed !== r.roundMonth
                          ? `No basket value in ${monthLabel(r.roundMonth)}; the nearest month on file, ${monthLabel(r.monthUsed)}, was used instead.`
                          : undefined
                      }
                    >
                      {r.roundMonth}
                      {r.monthUsed !== r.roundMonth && <span className="text-muted"> ≈{r.monthUsed}</span>}
                    </td>
                    <td className="r num">{r.age} mo</td>
                    <td className="r num">
                      {r.then.toFixed(1)}× → {r.now.toFixed(1)}×
                      {(() => {
                        const n = basketSize.get(r.c.sector);
                        if (n === undefined || r.nThen === null || r.nNow === null) return null;
                        const short = r.nThen < n || r.nNow < n;
                        return (
                          <span
                            className={`block text-[10.5px] ${short ? "text-[var(--review-text)]" : "text-muted"}`}
                            title={
                              short
                                ? `The two medians are taken over different baskets: ${r.nThen} of ${n} names had data in ${monthLabel(
                                    r.monthUsed,
                                  )}, ${r.nNow} of ${n} now. Part of the measured movement is a change in which companies are being measured.`
                                : `Both medians are taken over all ${n} names in the basket.`
                            }
                          >
                            {r.nThen}/{n} → {r.nNow}/{n} names
                          </span>
                        );
                      })()}
                    </td>
                    <td className="r num" title={r.bounded ? `Uncapped ratio ${r.raw.toFixed(3)}, held at the ±35% limit.` : undefined}>
                      {r.factor.toFixed(3)}
                      {r.bounded && <span className="text-muted"> capped</span>}
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
            <p className="text-[11px] text-muted mt-1">
              A capped factor moved further than the ±35% limit allows and was held at it. Hover the factor to see the uncapped ratio.
            </p>
          )}
          {thin > 0 && (
            <p className="text-[11px] mt-1" style={{ color: "var(--review-text)" }}>
              {thin} of {rows.length} rows divide medians taken over different numbers of names — a company that had not yet listed cannot
              be in its sector&rsquo;s older months. Part of the movement those rows measure is a change in the basket rather than in the
              market. Hover the depth under each pair to see which.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function useMarket(mode: Mode, runId: string | undefined) {
  const r = useAsync(() => loadMarket(mode), [mode, runId]);
  return { ...r, errorStatus: r.errorStatus };
}

/** What went wrong and the one thing that fixes it, in the reader's words. The raw error stays
    under Technical details. Nothing in the valuation depends on this page: it only shows where the
    sector multiples came from. */
function marketFailure(mode: Mode, status: number | undefined): { title: string; what: string; fix: string } {
  const aside = " Nothing else in the valuation depends on this page.";
  if (mode === "static")
    return {
      title: "This export has no market feed",
      what: "The sector comparables were not included when this file was built, so the page cannot show where the multiples came from." + aside,
      fix: "Rebuild the export with `hc-valuation build`, or open the served dashboard with `hc-valuation run`.",
    };
  if (status === 404)
    return {
      title: "No workbook is loaded yet",
      what: "The server has no valuation run to report on — this happens right after a reset, or before the first upload finishes." + aside,
      fix: "Upload the quarter's workbook from the Activity tab. This page fills in on its own when the run completes.",
    };
  if (status === 0)
    return {
      title: "The dashboard server is not answering",
      what: "The page is open but nothing is listening behind it — the `hc-valuation run` process has stopped or was never started." + aside,
      fix: "In a terminal, from the Val_engine folder: `hc-valuation run` — then reload this page.",
    };
  return {
    title: "The server could not build the market feed",
    what: "The dashboard is running but hit an error assembling the sector comparables." + aside,
    fix: "Restart with `hc-valuation run`. If it happens again, rebuild the comps cache with `hc-valuation market --provider live --refresh` and reload.",
  };
}

export function MarketView({ mode, run, onGoto }: { mode: Mode; run?: ValuationRun; onGoto?: (name: string) => void }) {
  // Re-fetched whenever the run changes (an upload after a reset, a rerun after a decision), so a
  // feed that was not there yet fills in on its own once it is; Retry covers everything else.
  const { data: rep, error, errorStatus, loading, refetch } = useMarket(mode, run?.manifest.run_id);
  const [selected, setSelected] = useState<string | null>(null);

  // default to the sector with the most portfolio positions (the API's first row)
  useEffect(() => {
    if (rep && (selected === null || !rep.sectors.some((s) => s.sector === selected))) setSelected(rep.sectors[0]?.sector ?? null);
  }, [rep, selected]);

  if (loading && !rep) return <div className="p-8 text-muted text-[12px]">Loading the market feed…</div>;
  if (error) {
    const cause = marketFailure(mode, errorStatus);
    return (
      <div className="p-8 max-w-[640px] mx-auto">
        <h1 className="font-semibold text-[16px] mb-2">{cause.title}</h1>
        <p className="text-[12px] text-ink2 mb-2">{cause.what}</p>
        <p className="text-[12px] text-ink mb-4">
          <b>To fix it:</b> {cause.fix}
        </p>
        {mode === "served" && (
          <button type="button" className="btn mb-4" onClick={refetch}>
            Retry
          </button>
        )}
        <details>
          <summary className="text-[11px] text-muted cursor-pointer select-none">Technical details</summary>
          <p className="text-ink2 mono text-[11px] mt-1.5 mb-2">{error}</p>
        </details>
      </div>
    );
  }
  if (loading || !rep) return <div className="p-8 text-muted">Loading market feed…</div>;

  const sector = rep.sectors.find((s) => s.sector === selected) ?? rep.sectors[0];
  const liveCount = rep.sectors.filter((s) => s.live).length;

  return (
    <div className="space-y-4">
      <HeaderStrip rep={rep} served={mode === "served"} />

      {rep.sectors.length === 0 ? (
        <div className="card p-6 text-center text-muted text-[12px]">No sectors in the market report.</div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
          <div>
            <SectionTitle
              right={
                <>
                  {liveCount} of {rep.sectors.length} sectors on live data · EV to trailing revenue as of {shortDate(rep.priced_as_of ?? rep.as_of)}
                </>
              }
            >
              Sector comps
            </SectionTitle>
            <SectorTable sectors={rep.sectors} selected={sector?.sector ?? null} onSelect={setSelected} pricedAsOf={rep.priced_as_of ?? rep.as_of} />
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
                  {Object.keys(sector.history).length} months of history through {monthLabel(sector.as_of_month)}, priced from{" "}
                  {sourceWords(sector.source, sector.live)}. The hairline marks the multiple in force at the valuation date.
                </p>
                <HistoryChart sector={sector} />
              </div>
            </div>
          )}

          {sector && (
            <div className="card p-4 xl:col-span-2 min-w-0">
              <SectionTitle
                right={
                  <>
                    {okCount(sector).sampled
                      ? `${okCount(sector).total} named, none priced`
                      : `${okCount(sector).ok} of ${okCount(sector).total} priced`}
                  </>
                }
              >
                Constituents · {sector.sector}
              </SectionTitle>
              {(okCount(sector).sampled || !rep.reached_live) && (
                <p className="text-[12px] text-ink2 mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
                  <SourceChip live={false} source={sector.source} />
                  <span>
                    These constituents are named to show what the basket contains, but they carry no prices and no booked mark depends on them.
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
