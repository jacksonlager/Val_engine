// New Activity: the positions the quarter's activity tab touched, and what the engine did with
// each row — read before the rest of the book. A reviewer who has been through this page has
// been informed of every decision the new information produced; the Queue then covers the
// whole portfolio, where these same positions carry a "New activity" label.
//
// Every position with a row is here, Ready ones included: a priced round that produced a clean
// mark is still new information someone should have seen.
import { useMemo, useState } from "react";
import type { CompanyResult, Readiness, ValuationRun } from "../types";
import { READINESS, READINESS_HINT } from "../types";
import { musd, signed, signClass } from "../lib/format";
import { activitySteps, hasActivity, PositionCard } from "../components/PositionCard";
import { rdClass } from "../components/Flags";

const RANK: Record<Readiness, number> = { Blocked: 0, "Needs Review": 1, Ready: 2 };

export function ActivityView({
  run,
  writeDisabled,
  onChanged,
  gotoCompany,
}: {
  run: ValuationRun;
  writeDisabled: string | null;
  onChanged: () => void;
  gotoCompany: (name: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [bucket, setBucket] = useState<Readiness | null>(null);

  const touched = useMemo(() => run.companies.filter(hasActivity), [run]);
  const events = useMemo(() => touched.flatMap((c) => activitySteps(c)), [touched]);
  const sheet = events[0]?.evidence?.sheet ?? "activity";
  const counts = useMemo(() => {
    const out: Record<Readiness, number> = { Blocked: 0, "Needs Review": 0, Ready: 0 };
    touched.forEach((c) => (out[c.readiness] += 1));
    return out;
  }, [touched]);
  const types = useMemo(() => {
    const m = new Map<string, number>();
    events.forEach((s) => m.set(s.evidence?.event_type ?? "Event", (m.get(s.evidence?.event_type ?? "Event") ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [events]);
  const movement = touched.reduce((a, c) => a + (c.proposed_mark - c.prior_mark), 0);

  // blocked first, then the order the rows were entered on the tab
  const list = touched
    .filter((c) => !bucket || c.readiness === bucket)
    .sort((a, b) => RANK[a.readiness] - RANK[b.readiness] || firstRow(a) - firstRow(b));

  return (
    <div className="space-y-5">
      <div className="card p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <div>
            <h2 className="text-[15px] font-semibold m-0">
              {events.length} row{events.length === 1 ? "" : "s"} on the <span className="mono text-[13px]">{sheet}</span> tab · {touched.length} position
              {touched.length === 1 ? "" : "s"}
            </h2>
            <p className="text-[12px] text-ink2 m-0 mt-1 max-w-[80ch] leading-snug">
              Everything the quarter brought in, and how the engine treated it, before the {run.companies.length - touched.length} positions it left
              alone. Each card shows the row, the rule that applied it and the mark it produced; the findings and the decision follow, as on the
              Queue.
            </p>
          </div>
          <div className="text-right">
            <div className="text-[11px] uppercase tracking-wider text-muted">Movement from these rows</div>
            <div className={`text-[20px] font-semibold leading-tight num ${signClass(movement)}`}>{signed(movement, 1)}</div>
            <div className="text-[11px] text-muted num">of {signed(run.totals.net_movement, 1)} across the book · $M</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-[11.5px] text-muted">
          {types.map(([t, n]) => (
            <span key={t}>
              <span className="text-ink2">{t}</span> <span className="num">×{n}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {READINESS.map((r) => (
          <button
            key={r}
            className={`tile ${rdClass(r)} ${bucket === r ? "active" : ""} stripe`}
            onClick={() => setBucket(bucket === r ? null : r)}
            title={READINESS_HINT[r]}
            aria-pressed={bucket === r}
          >
            <div className="flex items-center justify-between">
              <span className="badge">{r}</span>
              <span className="text-[11px] text-muted">{bucket === r ? "filtering" : ""}</span>
            </div>
            <div className="text-[28px] font-semibold leading-none mt-2">{counts[r]}</div>
            <div className="text-[11px] text-muted mt-1">of the positions with new activity</div>
          </button>
        ))}
      </div>

      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-2">
          <h2 className="text-[13px] font-semibold">
            {list.length} position{list.length === 1 ? "" : "s"}
            {bucket ? ` · ${bucket.toLowerCase()}` : ""}
            <span className="font-normal text-muted"> · {counts.Blocked + counts["Needs Review"]} need a person, {counts.Ready} ready</span>
          </h2>
          <span className="text-[11px] text-muted">blocked first, then in the order the rows were entered</span>
        </div>
        {list.length === 0 && <div className="card p-6 text-center text-muted">No activity rows this quarter.</div>}
        <div className="space-y-2.5">
          {list.map((c) => (
            <PositionCard
              key={c.company}
              c={c}
              open={open === c.company}
              toggle={() => setOpen(open === c.company ? null : c.company)}
              writeDisabled={writeDisabled}
              onChanged={onChanged}
              gotoCompany={gotoCompany}
              showActivity
            />
          ))}
        </div>
      </div>

      {touched.length > 0 && (
        <p className="text-[11.5px] text-muted m-0">
          Realized this quarter from these rows: {musd(touched.reduce((a, c) => a + c.realized_quarter, 0), 1)} · the same positions carry a{" "}
          <span className="tag-activity">New activity</span> label on the Queue.
        </p>
      )}
    </div>
  );
}

function firstRow(c: CompanyResult): number {
  return activitySteps(c)[0]?.evidence?.row_index ?? 0;
}
