// The review queue: the landing page, and the only page that is a to-do list.
//
// One card per position, in the order a reviewer works: who and what state it is in, what the
// mark did, why it stopped (in a sentence), the facts beside the suggested step, the verbs in
// one bar at the bottom, and everything technical folded away under Evidence & history.
//
// The status on a card is `readiness` — Blocked, Needs Review, Ready — one bucket per position.
// `approval` is a second thing:
// nothing is booked until the quarter is published, so the summary says "Approval pending"
// rather than showing a booked number that does not exist yet.
//
// Three things the card must never do, each of which it used to:
//   · shout — the severity is a 3px rail and one quiet badge, not a saturated panel behind the
//     whole action area, because a page where every card shouts has no priority order at all;
//   · say "Booked" before publication;
//   · lead with a rule code — X-101 is traceability, and lives under Evidence. The headline is
//     a sentence a person would say: "Missing quarter-end share price".
import { useState } from "react";
import type { Readiness, ValuationRun } from "../types";
import { READINESS, READINESS_HINT } from "../types";
import { deltaPct, musdTile, pct, signed } from "../lib/format";
import { rdClass } from "../components/Flags";
import { PositionCard } from "../components/PositionCard";
import { OpenItemsView } from "./OpenItems";

const PAGE = 12;

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
  writeDisabled,
  onChanged,
  gotoCompany,
}: {
  run: ValuationRun;
  writeDisabled: string | null;
  onChanged: () => void;
  gotoCompany: (name: string) => void;
}) {
  const t = run.totals;
  const [open, setOpen] = useState<string | null>(null);
  const [bucket, setBucket] = useState<Readiness | null>(null);
  const [shown, setShown] = useState(PAGE);
  const dPct = deltaPct(t.prior_nav, t.proposed_nav);
  const counts = t.readiness ?? {};
  const needsAPerson = (counts.Blocked ?? 0) + (counts["Needs Review"] ?? 0);

  const rank: Record<Readiness, number> = { Blocked: 0, "Needs Review": 1, Ready: 2 };
  const list = run.companies
    .filter((c) => (bucket ? c.readiness === bucket : c.readiness !== "Ready"))
    .sort((a, b) => rank[a.readiness] - rank[b.readiness] || Math.abs(b.proposed_mark - b.prior_mark) - Math.abs(a.proposed_mark - a.prior_mark));
  const visible = list.slice(0, shown);

  return (
    <div className="space-y-5">
      {/* readiness buckets as filters */}
      <div className="grid grid-cols-3 gap-3">
        {READINESS.map((r) => (
          <button
            key={r}
            className={`tile ${rdClass(r)} ${bucket === r ? "active" : ""} stripe`}
            onClick={() => {
              setBucket(bucket === r ? null : r);
              setShown(PAGE);
            }}
            title={READINESS_HINT[r]}
            aria-pressed={bucket === r}
          >
            <div className="flex items-center justify-between">
              <span className="badge">{r}</span>
              <span className="text-[11px] text-muted">{bucket === r ? "filtering" : ""}</span>
            </div>
            <div className="text-[28px] font-semibold leading-none mt-2">{counts[r] ?? 0}</div>
            <div className="text-[11px] text-muted mt-1">{READINESS_HINT[r]}</div>
          </button>
        ))}
      </div>

      {/* headline strip */}
      <div className="card p-4 flex flex-wrap gap-x-8 gap-y-3 items-start">
        <Headline label="Portfolio fair value, prior" value={musdTile(t.prior_nav)} sub={`at ${run.manifest.prior_close}`} />
        <div className="text-muted text-[20px] pt-4">→</div>
        <Headline label="Portfolio fair value, proposed" value={musdTile(t.proposed_nav)} sub={`${signed(t.net_movement, 1)}  (${pct(dPct, 1, true)})`} />
        {Math.abs(t.booked_nav - t.proposed_nav) > 1e-6 && (
          <Headline label="After recorded decisions" value={musdTile(t.booked_nav)} sub="not approved until published" />
        )}
        <Headline label="Realized in quarter" value={musdTile(t.realized_quarter)} sub={`cumulative ${musdTile(t.realized_cumulative)}`} />
        <Headline label="Written off" value={musdTile(t.written_off)} sub={`shutdowns at prior mark · exited ${musdTile(t.exited_at_prior_mark)}`} />
        <Headline label="Top-10 concentration" value={pct(t.top10_concentration)} sub="share of the proposed book" />
        <div className="ml-auto text-[11px] text-muted">$M unless stated</div>
      </div>

      {/* the queue itself */}
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-2">
          <h2 className="text-[13px] font-semibold">
            {bucket ? `${list.length} ${bucket.toLowerCase()}` : `${list.length} position${list.length === 1 ? "" : "s"} need a person`}
            <span className="font-normal text-muted">
              {" · "}
              {bucket ? `${needsAPerson} need a person in total` : `${counts.Blocked ?? 0} blocked, ${counts["Needs Review"] ?? 0} to review`}
            </span>
          </h2>
          <span className="text-[11px] text-muted">blocked first, then by size of change</span>
        </div>
        {list.length === 0 && <div className="card p-6 text-center text-muted">Nothing here.</div>}
        <div className="space-y-2.5">
          {visible.map((c) => (
            <PositionCard
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
        {list.length > shown && (
          <div className="flex justify-center mt-3">
            <button className="btn" onClick={() => setShown((n) => n + PAGE)}>
              Show {Math.min(PAGE, list.length - shown)} more of {list.length - shown}
            </button>
          </div>
        )}
      </div>

      {/* carried across the quarter boundary (E-07): kept in sight, out of the way */}
      {run.open_items.length > 0 && (
        <details className="card p-3">
          <summary className="text-[11px] uppercase tracking-wider text-muted cursor-pointer select-none">
            Open items carried from prior quarters ({run.open_items.length}
            {run.open_items.some((o) => o.escalated) ? `, ${run.open_items.filter((o) => o.escalated).length} escalated` : ""})
          </summary>
          <div className="mt-2">
            <OpenItemsView run={run} gotoCompany={gotoCompany} />
          </div>
        </details>
      )}
    </div>
  );
}

