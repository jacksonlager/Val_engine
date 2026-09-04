import { useState } from "react";
import type { CompanyResult, Disposition, ValuationRun } from "../types";
import { DISPOSITIONS } from "../types";
import { deltaPct, musdTile, pct, signed, signClass } from "../lib/format";
import { CompanyDetail } from "../components/CompanyDetail";
import { DispChip, FlagChip, MarkTriple } from "../components/ui";

const TILE_HINT: Record<Disposition, string> = {
  BLOCK: "Cannot be booked until a committee decision is recorded",
  REVIEW: "A reviewer could change the number; read before booking",
  MONITOR: "Annotated only; nothing a reviewer would change this quarter",
  CLEAR: "No flags, or a terminal event this quarter",
};

function Headline({ label, value, sub, cls = "" }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="min-w-[120px]">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`text-[20px] font-semibold leading-tight ${cls}`}>{value}</div>
      {sub && <div className="text-[11px] text-ink2 num">{sub}</div>}
    </div>
  );
}

export function QueueView({
  run,
  filter,
  setFilter,
  writeDisabled,
  onChanged,
  gotoCompany,
}: {
  run: ValuationRun;
  filter: Disposition | "ALL";
  setFilter: (d: Disposition | "ALL") => void;
  writeDisabled: string | null;
  onChanged: () => void;
  gotoCompany: (name: string) => void;
}) {
  const t = run.totals;
  const [open, setOpen] = useState<string | null>(null);
  const dPct = deltaPct(t.prior_nav, t.proposed_nav);
  const listDisp: Disposition = filter === "ALL" ? "BLOCK" : filter;
  const list = run.companies
    .filter((c) => c.disposition === listDisp)
    .sort((a, b) => Math.abs(b.proposed_mark - b.prior_mark) - Math.abs(a.proposed_mark - a.prior_mark));

  return (
    <div className="space-y-5">
      {/* tiles act as filters */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {DISPOSITIONS.map((d) => (
          <button
            key={d}
            className={`tile disp-${d} ${filter === d ? "active" : ""} stripe`}
            onClick={() => setFilter(filter === d ? "ALL" : d)}
            title={TILE_HINT[d]}
            aria-pressed={filter === d}
          >
            <div className="flex items-center justify-between">
              <DispChip d={d} />
              <span className="text-[11px] text-muted">{filter === d ? "filtering" : ""}</span>
            </div>
            <div className="text-[28px] font-semibold leading-none mt-2">{t.dispositions[d] ?? 0}</div>
            <div className="text-[11px] text-muted mt-1">{TILE_HINT[d]}</div>
          </button>
        ))}
      </div>

      {/* headline strip */}
      <div className="card p-4 flex flex-wrap gap-x-8 gap-y-3 items-start">
        <Headline label="Prior NAV" value={musdTile(t.prior_nav)} sub={`at ${run.manifest.prior_close}`} />
        <div className="text-muted text-[20px] pt-4">→</div>
        <Headline
          label="Proposed NAV"
          value={musdTile(t.proposed_nav)}
          sub={`${signed(t.net_movement, 1)}  (${pct(dPct, 1, true)})`}
          cls=""
        />
        {Math.abs(t.booked_nav - t.proposed_nav) > 1e-6 && (
          <Headline label="Booked NAV" value={musdTile(t.booked_nav)} sub="after overrides" />
        )}
        <Headline label="Realized in quarter" value={musdTile(t.realized_quarter)} sub={`cumulative ${musdTile(t.realized_cumulative)}`} />
        <Headline label="Written off" value={musdTile(t.written_off)} sub={`shutdowns at prior mark · exited ${musdTile(t.exited_at_prior_mark)}`} />
        <Headline label="Level-1 positions" value={String(t.level1_positions)} sub={`${t.active_after} active of ${t.positions}`} />
        <Headline label="Top-10 concentration" value={pct(t.top10_concentration)} sub="share of booked NAV" />
        <div className="ml-auto text-[11px] text-muted">$M unless stated</div>
      </div>

      {/* block list */}
      <div>
        <div className="flex items-baseline justify-between mb-2">
          <h2 className="text-[13px] font-semibold">
            <DispChip d={listDisp} className="mr-2" />
            {list.length} position{list.length === 1 ? "" : "s"}
            {listDisp === "BLOCK" ? " waiting on a committee decision" : ""}
          </h2>
          <span className="text-[11px] text-muted">sorted by |Δ| · click a card for its audit chain</span>
        </div>
        {list.length === 0 && <div className="card p-6 text-center text-muted">Nothing in this bucket.</div>}
        <div className="space-y-2">
          {list.map((c) => (
            <QueueCard
              key={c.company}
              c={c}
              open={open === c.company}
              toggle={() => setOpen(open === c.company ? null : c.company)}
              writeDisabled={writeDisabled}
              onChanged={onChanged}
              gotoCompany={gotoCompany}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/** What the label above the action block says, per disposition. */
const ACTION_HEADING: Record<string, string> = {
  BLOCK: "Awaiting a committee decision",
  REVIEW: "To check before booking",
  MONITOR: "Noted for this quarter",
  CLEAR: "Nothing to decide",
};

function QueueCard({
  c,
  open,
  toggle,
  writeDisabled,
  onChanged,
  gotoCompany,
}: {
  c: CompanyResult;
  open: boolean;
  toggle: () => void;
  writeDisabled: string | null;
  onChanged: () => void;
  gotoCompany: (n: string) => void;
}) {
  const d = c.proposed_mark - c.prior_mark;
  // The engine leaves `action` empty on MONITOR: nothing for a person to do is context, not a gate.
  const actions = c.flags.filter((f) => f.severity !== "MONITOR");
  const notes = c.flags.filter((f) => f.severity === "MONITOR");
  return (
    <div className={`card qcard disp-${c.disposition} stripe`}>
      <button className="w-full text-left p-3.5 pl-4" onClick={toggle} aria-expanded={open}>
        {/* who, and how far the mark moved */}
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
          <div className="min-w-[200px]">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-[15px] tracking-tight">{c.company}</span>
              <DispChip d={c.disposition} />
            </div>
            <div className="text-[11px] text-muted mt-0.5">
              {c.fund} · {c.sector} · {c.stage}
              {c.fv_level !== null && ` · Level ${c.fv_level}`}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-muted">prior → proposed → booked · $M</div>
            <div className="mt-0.5 text-[13px]">
              <MarkTriple prior={c.prior_mark} proposed={c.proposed_mark} booked={c.booked_mark} />
            </div>
            <div className={`text-[13px] font-semibold num mt-0.5 ${signClass(d)}`}>
              {signed(d)} <span className="font-normal">({pct(deltaPct(c.prior_mark, c.proposed_mark), 1, true)})</span>
            </div>
          </div>
        </div>

        {/* what a person has to decide, and why the engine could not */}
        {actions.length > 0 && (
          <div className="actions mt-3">
            <div className="eyebrow mb-2">{ACTION_HEADING[c.disposition] ?? "To check"}</div>
            <ul className="space-y-2.5">
              {actions.map((f, i) => (
                <li key={i} className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2.5 gap-y-1 items-baseline">
                  <span className="rule-tag mono" title={`${f.severity} · ${f.family}`}>
                    {f.rule_id}
                  </span>
                  <span className="text-[13.5px] font-semibold leading-snug">{f.action || f.message}</span>
                  {f.action && (
                    <p className="col-start-2 text-[12px] text-ink2 leading-[1.5] max-w-[90ch] m-0">{f.message}</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* monitor flags are context, never mixed in with the actions */}
        {notes.length > 0 && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
            <span>Also noted, nothing to decide:</span>
            {notes.map((f, i) => (
              <FlagChip key={i} f={f} />
            ))}
          </div>
        )}
        {c.flags.length === 0 && <div className="mt-2 text-[11px] text-muted">No flags on this position.</div>}
      </button>
      <div className="flex gap-2 px-4 pb-3 -mt-1">
        <button className="btn btn-ghost" onClick={toggle} aria-expanded={open}>
          <span className="text-[10px] leading-none">{open ? "▾" : "▸"}</span>
          {open ? "Hide audit chain" : "Audit chain"}
        </button>
        <button className="btn btn-ghost" onClick={() => gotoCompany(c.company)}>
          Open in Companies
        </button>
      </div>
      {open && (
        <div className="border-t border-hair">
          <CompanyDetail c={c} writeDisabled={writeDisabled} onChanged={onChanged} />
        </div>
      )}
    </div>
  );
}
