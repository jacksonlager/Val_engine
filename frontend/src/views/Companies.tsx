import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import type { CompanyResult, ValuationRun } from "../types";
import { READINESSES, READINESS_ORDER } from "../types";
import { deltaPct, months, mult, musd, pct, signed, signClass } from "../lib/format";
import { readinessClass } from "../lib/labels";
import { CompanyDetail } from "../components/CompanyDetail";
import { EscalatedChip, escalatedReviewFamilies, FlagChip, ReadinessChip } from "../components/ui";

const col = createColumnHelper<CompanyResult>();

/** r: right-aligned numeric; hide: a CSS class that drops the column below a viewport width. */
type ColMeta = { r?: boolean; hide?: string };

function Num({ v, d = 2 }: { v: number | null; d?: number }) {
  return <span className="num">{musd(v, d)}</span>;
}

export function CompaniesView({
  run,
  writeDisabled,
  onChanged,
  focus,
}: {
  run: ValuationRun;
  writeDisabled: string | null;
  onChanged: () => void;
  focus: string | null;
}) {
  const [search, setSearch] = useState("");
  // the severity filter lives here, beside the others it belongs with, rather than in the chrome
  const [filter, setFilter] = useState<string>("ALL");
  const [fund, setFund] = useState("");
  const [sector, setSector] = useState("");
  const [rule, setRule] = useState("");
  const [hasEvent, setHasEvent] = useState(false);
  const [sorting, setSorting] = useState<SortingState>([{ id: "readiness", desc: false }]);
  const [expanded, setExpanded] = useState<string | null>(focus);
  // The table scrolls horizontally; the expanded detail row is pinned to the visible
  // width so the audit chain never hides off-screen to the right.
  const scroller = useRef<HTMLDivElement>(null);
  const [visibleWidth, setVisibleWidth] = useState<number | undefined>(undefined);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setVisibleWidth(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (focus) {
      setExpanded(focus);
      setSearch("");
      setFilter("ALL");
      setFund("");
      setSector("");
      setRule("");
      setHasEvent(false);
      setTimeout(() => document.getElementById(`row-${focus}`)?.scrollIntoView({ block: "center" }), 50);
    }
  }, [focus]);

  const funds = useMemo(() => [...new Set(run.companies.map((c) => c.fund))].sort(), [run]);
  const sectors = useMemo(() => [...new Set(run.companies.map((c) => c.sector))].sort(), [run]);
  const rules = useMemo(() => {
    const s = new Set<string>();
    run.companies.forEach((c) => {
      c.flags.forEach((f) => s.add(f.rule_id));
      c.steps.forEach((st) => s.add(st.rule_id));
    });
    return [...s].sort();
  }, [run]);

  const rows = useMemo(
    () =>
      run.companies.filter((c) => {
        if (filter !== "ALL" && c.readiness !== filter) return false;
        if (fund && c.fund !== fund) return false;
        if (sector && c.sector !== sector) return false;
        if (rule && !c.flags.some((f) => f.rule_id === rule) && !c.steps.some((s) => s.rule_id === rule)) return false;
        if (hasEvent && !c.steps.some((s) => s.evidence)) return false;
        if (search) {
          const q = search.toLowerCase();
          const hay = `${c.company} ${c.fund} ${c.sector} ${c.stage} ${c.readiness} ${c.flags.map((f) => f.rule_id).join(" ")}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      }),
    [run, filter, fund, sector, rule, hasEvent, search],
  );


  const columns = useMemo<ColumnDef<CompanyResult, any>[]>(
    () => [
      col.accessor("company", {
        header: "Company",
        cell: (i) => (
          <span className="font-medium">
            {i.getValue()}
            {i.row.original.override && (
              <span className="chip no-dot disp-REVIEW ml-1" title="A committee decision set the booked mark on this position (E-01).">
                Decision recorded
              </span>
            )}
          </span>
        ),
      }),
      col.accessor("readiness", {
        header: "Review status",   // right after the name: the column the reader sorts by, never at the scroll edge ("Status" further right is Active / Acquired / Shut Down)
        sortingFn: (a, b) => READINESS_ORDER[a.original.readiness] - READINESS_ORDER[b.original.readiness],
        cell: (i) => {
          const n = escalatedReviewFamilies(i.row.original);
          return (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <ReadinessChip r={i.getValue()} />
              <EscalatedChip n={n} short />
            </span>
          );
        },
      }),
      col.accessor("fund", { header: "Fund" }),
      // Sector and Stage are in the card subtitle and the audit chain; they give way first on a narrower screen
      col.accessor("sector", { header: "Sector", meta: { hide: "hide-lt-1300" } }),
      col.accessor("stage", { header: "Stage", meta: { hide: "hide-lt-1500" } }),
      col.accessor("status_after", {
        header: "Status",
        cell: (i) => (
          <span className={i.getValue() !== i.row.original.status_before ? "font-medium" : ""}>
            {i.row.original.status_before !== i.getValue() ? `${i.row.original.status_before} → ` : ""}
            {i.getValue()}
          </span>
        ),
      }),
      col.accessor("fv_level", { header: "FV", meta: { r: true }, cell: (i) => <span className="num">{i.getValue() === null ? "—" : `L${i.getValue()}`}</span> }),
      col.accessor("prior_mark", { header: "Prior", meta: { r: true }, cell: (i) => <Num v={i.getValue()} /> }),
      col.accessor("proposed_mark", { header: "Proposed", meta: { r: true }, cell: (i) => <Num v={i.getValue()} /> }),
      col.accessor("booked_mark", {
        header: "Booked",
        meta: { r: true },
        cell: (i) => <span className={`num ${i.row.original.override ? "font-semibold" : "text-ink2"}`}>{musd(i.getValue())}</span>,
      }),
      col.accessor((r) => r.proposed_mark - r.prior_mark, {
        id: "delta",
        header: "Δ",
        meta: { r: true },
        cell: (i) => <span className={`num ${signClass(i.getValue())}`}>{signed(i.getValue())}</span>,
      }),
      col.accessor((r) => deltaPct(r.prior_mark, r.proposed_mark), {
        id: "delta_pct",
        header: "Δ%",
        meta: { r: true },
        sortUndefined: "last",
        cell: (i) => <span className={`num ${signClass(i.getValue())}`}>{pct(i.getValue(), 1, true)}</span>,
      }),
      col.accessor("ownership_after", {
        header: "Own.",
        meta: { r: true },
        cell: (i) => {
          const b = i.row.original.ownership_before;
          const a = i.getValue();
          return (
            <span className="num">
              {Math.abs(a - b) > 1e-6 ? (
                <>
                  <span className="text-muted">{pct(b)} → </span>
                  {pct(a)}
                </>
              ) : (
                pct(a)
              )}
            </span>
          );
        },
      }),
      col.accessor("invested_after", { header: "Inv.", meta: { r: true }, cell: (i) => <Num v={i.getValue()} /> }),
      col.accessor("realized_quarter", {
        header: "Realized (Q)",
        meta: { r: true },
        cell: (i) => <span className={`num ${i.getValue() ? "" : "text-muted"}`}>{i.getValue() ? musd(i.getValue()) : "—"}</span>,
      }),
      col.accessor("arr", { header: "ARR", meta: { r: true }, sortUndefined: "last", cell: (i) => <Num v={i.getValue()} d={1} /> }),
      col.accessor("arr_growth", {
        header: "ARR Δ",
        meta: { r: true },
        sortUndefined: "last",
        cell: (i) => <span className={`num ${signClass(i.getValue())}`}>{pct(i.getValue(), 0, true)}</span>,
      }),
      col.accessor("runway_months_aged", {
        header: "Runway",
        meta: { r: true },
        sortUndefined: "last",
        cell: (i) => <span className="num">{months(i.getValue())}</span>,
      }),
      col.accessor("implied_multiple", {
        header: "Implied ×",
        meta: { r: true },
        sortUndefined: "last",
        cell: (i) => <span className="num">{mult(i.getValue())}</span>,
      }),
      col.accessor((r) => r.flags.length, {
        id: "flags",
        header: "Flags",
        cell: (i) => (
          <span className="flex flex-nowrap gap-1">
            {i.row.original.flags.map((f, k) => (
              <FlagChip key={k} f={f} />
            ))}
          </span>
        ),
      }),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getRowId: (r) => r.company,
  });

  const sumProposed = rows.reduce((s, c) => s + c.proposed_mark, 0);
  const sumPrior = rows.reduce((s, c) => s + c.prior_mark, 0);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <input
          className="input w-56"
          placeholder="Search company, sector, rule…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="select" value={filter} onChange={(e) => setFilter(e.target.value)} title="Positions in this state">
          <option value="ALL">Any status</option>
          {READINESSES.map((r) => (
            <option key={r} value={r}>
              {r} ({run.totals.readiness?.[r] ?? 0})
            </option>
          ))}
        </select>
        <select className="select" value={fund} onChange={(e) => setFund(e.target.value)}>
          <option value="">All funds</option>
          {funds.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
        <select className="select" value={sector} onChange={(e) => setSector(e.target.value)}>
          <option value="">All sectors</option>
          {sectors.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
        <select className="select mono" value={rule} onChange={(e) => setRule(e.target.value)}>
          <option value="">Any rule</option>
          {rules.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-[12px] cursor-pointer">
          <input type="checkbox" checked={hasEvent} onChange={(e) => setHasEvent(e.target.checked)} /> New activity
        </label>
        <span className="ml-auto text-[11px] text-muted num">
          {rows.length} of {run.companies.length} · prior {musd(sumPrior, 1)} → proposed {musd(sumProposed, 1)}
        </span>
      </div>

      <div className="card dtable-wrap" ref={scroller}>
        <table className="dtable compact text-[12px]">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const meta = h.column.columnDef.meta as ColMeta | undefined;
                  const r = meta?.r;
                  const sorted = h.column.getIsSorted();
                  return (
                    <th
                      key={h.id}
                      className={`sortable ${r ? "r" : ""} ${h.index === 0 ? "sticky-col" : ""} ${meta?.hide ?? ""}`}
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
              const c = row.original;
              const isOpen = expanded === c.company;
              return (
                <Fragment key={row.id}>
                  <tr
                    id={`row-${c.company}`}
                    className={`row ${readinessClass(c.readiness)} ${isOpen ? "expanded" : ""}`}
                    onClick={() => setExpanded(isOpen ? null : c.company)}
                    aria-expanded={isOpen}
                  >
                    {row.getVisibleCells().map((cell, k) => {
                      const meta = cell.column.columnDef.meta as ColMeta | undefined;
                      const r = meta?.r;
                      return (
                        <td key={cell.id} className={`${r ? "r" : ""} ${k === 0 ? "stripe sticky-col" : ""} ${meta?.hide ?? ""}`}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      );
                    })}
                  </tr>
                  {isOpen && (
                    <tr className="expanded">
                      <td colSpan={columns.length} className="p-0 whitespace-normal">
                        <div style={{ position: "sticky", left: 0, width: visibleWidth }}>
                          <CompanyDetail c={c} writeDisabled={writeDisabled} onChanged={onChanged} />
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="text-center text-muted py-8">
                  No companies match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
