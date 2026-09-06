// What the position was flagged last quarter, and before: a heads-up for the reviewer that a
// BLOCK today was a MONITOR three months ago (or was already REVIEW, and nobody moved it).
//
// Reads the mark archive (/api/history): every point carries the flags the position had that
// quarter and where they came from — a released snapshot, HC's backfill, or the prior-close
// book re-screened by the current policy (tagged "reconstructed", the bridge for the first
// quarter on the engine). Nothing here is a number; it is the trail behind the flags.
import { useState } from "react";
import type { CompanyResult, Disposition, MarkHistoryPoint } from "../types";
import { useHistory } from "../lib/history";
import { DispChip, Label } from "./ui";
import { useRationale } from "../lib/rationale";

const SOURCE_LABEL: Record<string, string> = {
  published: "released snapshot",
  backfill: "HC records",
  reconstructed: "reconstructed from the prior-close book",
  live: "this run",
};

/** The archive points before the current quarter, newest first, that carry a disposition. */
export function priorPoints(asOf: string | undefined, points: MarkHistoryPoint[] | undefined): MarkHistoryPoint[] {
  return (points ?? []).filter((p) => p.quarter !== asOf && p.disposition !== null).slice().reverse();
}

function shortQuarter(q: string): string {
  // "Q2 2026" -> "Q2 ’26"
  const m = /^Q([1-4])\s+(\d{4})$/.exec(q);
  return m ? `Q${m[1]} ’${m[2].slice(2)}` : q;
}

/** Compact, colour-coded: the previous quarter's disposition, with the flags in the tooltip.
    Rendered beside the current disposition on the queue card and the Companies detail strip. */
export function PriorFlagPill({ c, className = "" }: { c: CompanyResult; className?: string }) {
  const { data } = useHistory();
  const prior = priorPoints(data?.as_of_quarter, data?.companies[c.company])[0];
  if (!prior || !prior.disposition) return null;
  const d = prior.disposition as Disposition;
  const ids = prior.flags.map((f) => f.rule_id);
  const nowIds = new Set(c.flags.map((f) => f.rule_id));
  const carried = ids.filter((id) => nowIds.has(id));
  const gone = ids.filter((id) => !nowIds.has(id));
  const fresh = c.flags.map((f) => f.rule_id).filter((id) => !ids.includes(id));
  const moved = d !== c.disposition;
  const title =
    `${prior.quarter}: ${d}${ids.length ? " — " + ids.join(", ") : " — no flags"} (${SOURCE_LABEL[prior.flags_source ?? ""] ?? "archive"}).` +
    (moved ? ` Now ${c.disposition}.` : " Unchanged.") +
    (carried.length ? ` Still open: ${carried.join(", ")}.` : "") +
    (fresh.length ? ` New this quarter: ${fresh.join(", ")}.` : "") +
    (gone.length ? ` Cleared: ${gone.join(", ")}.` : "");
  return (
    <span className={`chip no-dot disp-${d} prior-pill hint ${className}`} title={title}>
      <span className="prior-q">{shortQuarter(prior.quarter)}</span> {d}
      {moved && <span className="prior-arrow" aria-hidden>→</span>}
    </span>
  );
}

/** The full trail for the detail panel: one row per archived quarter with its disposition and
    flag chips, the current quarter's flags marked new / carried, and the source of each row. */
export function FlagHistoryCard({ c }: { c: CompanyResult }) {
  const { data, error } = useHistory();
  const rationale = useRationale();
  const [showAll, setShowAll] = useState(false);
  const points = data?.companies[c.company] ?? [];
  const prior = priorPoints(data?.as_of_quarter, points);
  const lastIds = new Set(prior[0]?.flags.map((f) => f.rule_id) ?? []);
  const rows = showAll ? prior : prior.slice(0, 3);
  const nameOf = (id: string) => rationale?.rules.find((r) => r.id === id)?.name ?? "";
  return (
    <div className="card p-3">
      <div className="flex items-baseline justify-between gap-2">
        <Label>Flag history</Label>
        {prior.length > 3 && (
          <button className="btn btn-ghost text-[11px]" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Latest three" : `All ${prior.length} quarters`}
          </button>
        )}
      </div>
      {error && <p className="text-[11.5px] text-muted m-0">History unavailable: {error}</p>}
      {!error && prior.length === 0 && (
        <p className="text-[11.5px] text-muted m-0 leading-snug">
          No earlier quarter on record for this position. The trail starts with the first published quarter; HC can backfill earlier
          flags in <span className="mono">data/mark_history.yaml</span>.
        </p>
      )}
      {prior.length > 0 && (
        <div className="fh">
          {/* this quarter, for contrast: which flags are new and which were already there */}
          <div className="fh-row fh-now">
            <span className="fh-q">{data?.as_of_quarter ? shortQuarter(data.as_of_quarter) : "now"}</span>
            <DispChip d={c.disposition} />
            <span className="fh-flags">
              {c.flags.length === 0 && <span className="text-[11px] text-muted">no flags</span>}
              {c.flags.map((f) => (
                <span key={f.rule_id} className={`chip disp-${f.severity}`} title={`${f.severity} · ${f.family}${nameOf(f.rule_id) ? " · " + nameOf(f.rule_id) : ""}`}>
                  <span className="mono">{f.rule_id}</span>
                  {prior[0] && !lastIds.has(f.rule_id) && <span className="fh-new">new</span>}
                </span>
              ))}
            </span>
          </div>
          {rows.map((p) => (
            <div key={p.quarter} className="fh-row">
              <span className="fh-q" title={`${p.quarter} · flags ${SOURCE_LABEL[p.flags_source ?? ""] ?? "from the archive"}`}>
                {shortQuarter(p.quarter)}
              </span>
              {p.disposition && <DispChip d={p.disposition} />}
              <span className="fh-flags">
                {p.flags.length === 0 && <span className="text-[11px] text-muted">no flags</span>}
                {p.flags.map((f) => (
                  <span
                    key={f.rule_id}
                    className={`chip ${f.severity ? `disp-${f.severity}` : "no-dot"}`}
                    title={`${f.severity ?? "severity not recorded"}${f.family ? " · " + f.family : ""}${nameOf(f.rule_id) ? " · " + nameOf(f.rule_id) : ""}`}
                  >
                    <span className="mono">{f.rule_id}</span>
                  </span>
                ))}
              </span>
              <span className="fh-src">{p.flags_source === "reconstructed" ? "reconstructed" : p.flags_source === "backfill" ? "HC records" : p.flags_source === "published" ? "released" : ""}</span>
            </div>
          ))}
        </div>
      )}
      {prior.some((p) => p.flags_source === "reconstructed") && (
        <p className="text-[10.5px] text-muted mt-2 mb-0 leading-snug">
          <i>reconstructed</i> = no snapshot was released for that quarter, so the book it closed on was re-screened by the current policy
          at that date: staleness at the prior close, growth, runway and multiple screens on the metrics the book carried. Once a quarter
          is published, its released flags replace this.
        </p>
      )}
    </div>
  );
}
