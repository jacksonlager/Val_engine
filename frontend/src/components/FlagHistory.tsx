// What the position was flagged last quarter, and before: a heads-up for the reviewer that a
// BLOCK today was a MONITOR three months ago (or was already REVIEW, and nobody moved it).
//
// Reads the mark archive (/api/history): every point carries the flags the position had that
// quarter and where they came from — a released snapshot, HC's backfill, or the prior-close
// book re-screened by the current policy (source value "reconstructed", shown as "re-screened",
// the bridge for the first quarter on the engine). Nothing here is a number; it is the trail
// behind the flags.
import { useState } from "react";
import type { CompanyResult, Disposition, MarkHistoryPoint } from "../types";
import { useHistory } from "../lib/history";
import { musd } from "../lib/format";
import { dispositionLabel, familyLabel, severityShort } from "../lib/labels";
import { DispChip, Label } from "./ui";
import { useRationale } from "../lib/rationale";

const SOURCE_LABEL: Record<string, string> = {
  published: "released snapshot",
  backfill: "HC records",
  reconstructed: "re-screened from the prior-close book",
  live: "this run",
};

/** Every archived quarter before this one, newest first. A point with `disposition === null`
    is a quarter whose *mark* is on record but whose flags are not — the normal state before the
    first release, reported as such rather than left blank or filled in. */
export function priorPoints(asOf: string | undefined, points: MarkHistoryPoint[] | undefined): MarkHistoryPoint[] {
  return (points ?? []).filter((p) => p.quarter !== asOf).slice().reverse();
}

const NO_RECORD =
  "No findings on record for that quarter: the archive fills from the publish ledger, and nothing had been released before this one. " +
  "Publish this quarter and next quarter's panel shows what each position was flagged for now.";

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
  if (!prior) return null;
  if (!prior.disposition)
    return (
      <span className={`chip no-dot prior-pill prior-none hint ${className}`} title={`${prior.quarter}: ${NO_RECORD}`}>
        <span className="prior-q">{shortQuarter(prior.quarter)}</span>: no findings on record
      </span>
    );
  const d = prior.disposition as Disposition;
  const ids = prior.flags.map((f) => f.rule_id);
  const nowIds = new Set(c.flags.map((f) => f.rule_id));
  const carried = ids.filter((id) => nowIds.has(id));
  const gone = ids.filter((id) => !nowIds.has(id));
  const fresh = c.flags.map((f) => f.rule_id).filter((id) => !ids.includes(id));
  const moved = d !== c.disposition;
  const title =
    `${prior.quarter}: ${dispositionLabel(d)}${ids.length ? " — " + ids.join(", ") : " — no flags"} (${SOURCE_LABEL[prior.flags_source ?? ""] ?? "archive"}).` +
    (moved ? ` Now ${dispositionLabel(c.disposition).toLowerCase()}.` : " Unchanged.") +
    (carried.length ? ` Still open: ${carried.join(", ")}.` : "") +
    (fresh.length ? ` New this quarter: ${fresh.join(", ")}.` : "") +
    (gone.length ? ` Cleared: ${gone.join(", ")}.` : "");
  return (
    <span className={`chip no-dot disp-${d} prior-pill hint ${className}`} title={title}>
      <span className="prior-q">{shortQuarter(prior.quarter)}</span>: {dispositionLabel(d)}
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
  // "new" only means something against a quarter whose flags are actually on record
  const last = prior.find((p) => p.disposition !== null);
  const lastIds = new Set(last?.flags.map((f) => f.rule_id) ?? []);
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
          No earlier quarter on record for this position — it is new to the book this quarter.
        </p>
      )}
      {prior.length > 0 && (
        <div className="fh">
          {/* this quarter, for contrast: which flags are new and which were already there */}
          <div className="fh-row fh-now">
            <span className="fh-q">{data?.as_of_quarter ? shortQuarter(data.as_of_quarter) : "now"}</span>
            {/* this quarter reads as readiness — the vocabulary the card uses; earlier rows keep the
                disposition that was on record, because that is what was released */}
            <span
              className={`badge ${c.readiness === "Needs Review" ? "rd-NeedsReview" : `rd-${c.readiness}`}`}
              title={`Where the findings leave this position: ${dispositionLabel(c.disposition).toLowerCase()}`}
            >
              {c.readiness}
            </span>
            <span className="fh-flags">
              {c.flags.length === 0 && <span className="text-[11px] text-muted">no flags</span>}
              {c.flags.map((f) => (
                <span
                  key={f.rule_id}
                  className={`chip disp-${f.severity}`}
                  title={`${familyLabel(f.family)} · ${severityShort(f.severity)}${nameOf(f.rule_id) ? " · " + nameOf(f.rule_id) : ""}`}
                >
                  <span className="mono">{f.rule_id}</span>
                  {last && !lastIds.has(f.rule_id) && <span className="fh-new">new</span>}
                </span>
              ))}
            </span>
          </div>
          {rows.map((p) =>
            !p.disposition ? (
              <div key={p.quarter} className="fh-row fh-none">
                <span className="fh-q">{shortQuarter(p.quarter)}</span>
                <span className="chip no-dot prior-none">not on record</span>
                <span className="fh-flags text-[11px] text-muted">The mark of ${musd(p.mark)}M is on record; its flags are not.</span>
                <span className="fh-src" />
              </div>
            ) : (
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
                    title={`${f.family ? familyLabel(f.family) + " · " : ""}${
                      f.severity ? severityShort(f.severity) : "severity not recorded"
                    }${nameOf(f.rule_id) ? " · " + nameOf(f.rule_id) : ""}`}
                  >
                    <span className="mono">{f.rule_id}</span>
                  </span>
                ))}
              </span>
              <span className="fh-src">{p.flags_source === "reconstructed" ? "re-screened" : p.flags_source === "backfill" ? "HC records" : p.flags_source === "published" ? "released" : ""}</span>
            </div>
            ),
          )}
        </div>
      )}
      {prior.some((p) => !p.disposition) && (
        <p className="text-[10.5px] text-muted mt-2 mb-0 leading-snug">
          The trail fills itself: publishing a quarter writes that quarter's flags into the archive, so from the next close this card shows
          what each position was flagged for now. Earlier quarters can be entered by hand in the{" "}
          <span className="hint underline decoration-dotted underline-offset-2" title="data/mark_history.yaml">
            mark history file
          </span>
          .
        </p>
      )}
      {prior.some((p) => p.flags_source === "reconstructed") && (
        <p className="text-[10.5px] text-muted mt-2 mb-0 leading-snug">
          <i>Re-screened</i> means no snapshot was released for that quarter, so the book it closed on was screened again by the current
          policy at that date: staleness at the prior close, growth, runway and multiple screens on the metrics the book carried. Once a
          quarter is published, its released flags replace this.
        </p>
      )}
    </div>
  );
}
