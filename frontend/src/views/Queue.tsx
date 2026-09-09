// The review queue: the landing page, and the only page that is a to-do list.
//
// Two groups, in the order a reviewer works. First, every position the quarter's activity tab
// touched — Ready ones included, because a priced round that produced a clean mark is still new
// information someone should have seen — each card opening with the row, the rule that applied
// it and the mark it produced. Then the rest of the book that still needs a person: the stale
// rounds, the shrinking revenue, the short runway that nothing on the tab explains.
//
// One card per position: who and what state it is in, what the mark did, why it stopped (in a
// sentence), the facts beside the suggested step, the verbs in one bar at the bottom, and
// everything technical folded away under Evidence & history.
//
// The status on a card is `readiness` — Blocked, Needs Review, Ready — one bucket per position.
// `approval` is a second thing: nothing is booked until the quarter is published, so the summary
// says "Approval pending" rather than showing a booked number that does not exist yet.
//
// Three things the card must never do, each of which it used to:
//   · shout — the severity is a 3px rail and one quiet badge, not a saturated panel behind the
//     whole action area, because a page where every card shouts has no priority order at all;
//   · say "Booked" before publication;
//   · lead with a rule code — X-101 is traceability, and lives under Evidence. The headline is
//     a sentence a person would say: "Missing quarter-end share price".
import { useMemo, useState } from "react";
import type { CompanyResult, Readiness, ValuationRun } from "../types";
import { READINESS, READINESS_HINT } from "../types";
import { deltaPct, musdSigned, musdUnit, pct, shortDate, signClass } from "../lib/format";
import { readinessPhrase } from "../lib/labels";
import { rdClass } from "../components/Flags";
import { activitySteps, hasActivity, PositionCard } from "../components/PositionCard";
import { OpenItemsView } from "./OpenItems";

const PAGE = 12;
const RANK: Record<Readiness, number> = { Blocked: 0, "Needs Review": 1, Ready: 2 };

function Headline({ label, value, sub, cls = "" }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="min-w-[120px]">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`text-[20px] font-semibold leading-tight ${cls}`}>{value}</div>
      {sub && <div className="text-[11px] text-ink2 num">{sub}</div>}
    </div>
  );
}

function firstRow(c: CompanyResult): number {
  return activitySteps(c)[0]?.evidence?.row_index ?? 0;
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

  // Group 1: everything the activity tab touched, blocked first, then in the order the rows were
  // entered. The bucket tiles filter it like the rest; with no filter, Ready positions stay in it.
  const touched = useMemo(() => run.companies.filter(hasActivity), [run]);
  const activity = touched
    .filter((c) => !bucket || c.readiness === bucket)
    .sort((a, b) => RANK[a.readiness] - RANK[b.readiness] || firstRow(a) - firstRow(b));
  const rows = useMemo(() => touched.flatMap((c) => activitySteps(c)), [touched]);
  const sheet = rows[0]?.evidence?.sheet ?? "Activity";
  const movement = touched.reduce((a, c) => a + (c.proposed_mark - c.prior_mark), 0);
  const activityOpen = touched.filter((c) => c.readiness !== "Ready").length;

  // The number that answers "can this quarter be published?": how much of the proposed book sits in
  // positions that are not Ready. The bucket tiles above give the counts; this gives what is at stake.
  const uncleared = useMemo(
    () => run.companies.filter((c) => c.readiness !== "Ready").reduce((a, c) => a + c.proposed_mark, 0),
    [run],
  );

  // Group 2: the rest of the book that still needs a person, blocked first, then by size of change.
  const rest = run.companies
    .filter((c) => !hasActivity(c))
    .filter((c) => (bucket ? c.readiness === bucket : c.readiness !== "Ready"))
    .sort((a, b) => RANK[a.readiness] - RANK[b.readiness] || Math.abs(b.proposed_mark - b.prior_mark) - Math.abs(a.proposed_mark - a.prior_mark));
  const visible = rest.slice(0, shown);

  const card = (c: CompanyResult, showActivity: boolean) => (
    <PositionCard
      key={c.company}
      c={c}
      open={open === c.company}
      toggle={() => setOpen(open === c.company ? null : c.company)}
      writeDisabled={writeDisabled}
      onChanged={onChanged}
      gotoCompany={gotoCompany}
      showActivity={showActivity}
    />
  );

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
              <span className="text-[11px] text-muted">{bucket === r ? "Filtering the list" : ""}</span>
            </div>
            <div className="text-[28px] font-semibold leading-none mt-2">{counts[r] ?? 0}</div>
            <div className="text-[11px] text-muted mt-1">{READINESS_HINT[r]}</div>
          </button>
        ))}
      </div>

      {/* headline strip */}
      <div className="card p-4 flex flex-wrap gap-x-8 gap-y-3 items-start">
        <Headline label="Portfolio fair value, prior" value={musdUnit(t.prior_nav)} sub={`at ${shortDate(run.manifest.prior_close)}`} />
        <div className="text-muted text-[20px] pt-4">→</div>
        <Headline label="Portfolio fair value, proposed" value={musdUnit(t.proposed_nav)} sub={`${musdSigned(t.net_movement)}  (${pct(dPct, 1, true)})`} />
        {Math.abs(t.booked_nav - t.proposed_nav) > 1e-6 && (
          <Headline label="After recorded decisions" value={musdUnit(t.booked_nav)} sub="not approved until published" />
        )}
        {/* what moved it. prior + new investment + valuation change − realized = the BOOKED figure
            (valuation change is measured on booked marks, run.py), so once a decision is on the
            ledger this group bridges to "After recorded decisions", not to the proposed tile. */}
        <div className="flex flex-wrap gap-x-5 gap-y-3 items-start pl-6 border-l border-hair" title={
          Math.abs(t.booked_nav - t.proposed_nav) > 1e-6
            ? `Prior ${musdUnit(t.prior_nav)} + ${musdUnit(t.new_investment)} ${musdSigned(t.valuation_change)} − ${musdUnit(t.realized_quarter)} = ${musdUnit(t.booked_nav)} after recorded decisions`
            : `Prior ${musdUnit(t.prior_nav)} + ${musdUnit(t.new_investment)} ${musdSigned(t.valuation_change)} − ${musdUnit(t.realized_quarter)} = ${musdUnit(t.proposed_nav)} proposed`
        }>
          <Headline label="New investment" value={musdUnit(t.new_investment)} sub="cash deployed this quarter" />
          <div className="text-muted text-[20px] pt-4">+</div>
          <Headline
            label="Valuation change"
            value={musdSigned(t.valuation_change)}
            cls={signClass(t.valuation_change)}
            sub={
              (t.written_off > 0.05 ? `including ${musdUnit(t.written_off)} written off` : "the judgment half of the move")
              + (Math.abs(t.booked_nav - t.proposed_nav) > 1e-6 ? " · on booked marks" : "")
            }
          />
          <div className="text-muted text-[20px] pt-4">−</div>
          <Headline label="Realized in quarter" value={musdUnit(t.realized_quarter)} sub="cash returned to the funds" />
        </div>
        <Headline
          label="Fair value not yet cleared"
          value={musdUnit(uncleared)}
          sub={`${needsAPerson} position${needsAPerson === 1 ? "" : "s"} · ${pct(uncleared / (t.proposed_nav || 1))} of the proposed book`}
        />
      </div>

      {/* group 1: what the quarter brought in — read these first */}
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-2">
          <h2 className="text-[13px] font-semibold flex flex-wrap items-baseline gap-x-2">
            <span className="tag-activity">New activity</span>
            <span>
              {activity.length} position{activity.length === 1 ? "" : "s"}
              {bucket ? ` ${readinessPhrase(bucket)}` : ""} from {rows.length} row{rows.length === 1 ? "" : "s"} on the “{sheet}” tab
            </span>
            <span className="font-normal text-muted">
              · {activityOpen} need a person, {touched.length - activityOpen} ready · movement{" "}
              <span className={`num ${signClass(movement)}`}>{musdSigned(movement)}</span> of {musdSigned(t.net_movement)} across the book
            </span>
          </h2>
          <span className="text-[11px] text-muted">read these first · blocked first, then in the order the rows were entered</span>
        </div>
        {activity.length === 0 && (
          <div className="card p-4 text-center text-muted text-[12px]">
            {touched.length === 0 ? "No activity rows this quarter." : `No positions with new activity are ${readinessPhrase(bucket!)}.`}
          </div>
        )}
        <div className="space-y-2.5">{activity.map((c) => card(c, true))}</div>
      </div>

      {/* group 2: the rest of the book that still needs a person */}
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-2">
          <h2 className="text-[13px] font-semibold">
            {`${rest.length} ${bucket ? "" : "more "}position${rest.length === 1 ? "" : "s"} ${
              bucket ? readinessPhrase(bucket) : rest.length === 1 ? "needs a person" : "need a person"
            } with no activity this quarter`}
            <span className="font-normal text-muted">
              {" · "}
              {bucket ? `${needsAPerson} need a person in total` : `${counts.Blocked ?? 0} blocked, ${counts["Needs Review"] ?? 0} to review across the book`}
            </span>
          </h2>
          <span className="text-[11px] text-muted">stale rounds, shrinking revenue, short runway · blocked first, then by size of change</span>
        </div>
        {rest.length === 0 && <div className="card p-6 text-center text-muted">Nothing here.</div>}
        <div className="space-y-2.5">{visible.map((c) => card(c, false))}</div>
        {rest.length > shown && (
          <div className="flex justify-center mt-3">
            <button className="btn" onClick={() => setShown((n) => n + PAGE)}>
              {rest.length - shown <= PAGE
                ? `Show the last ${rest.length - shown}`
                : `Show ${PAGE} more of the ${rest.length - shown} still hidden`}
            </button>
          </div>
        )}
      </div>

      {/* carried across the quarter boundary (E-07): kept in sight, out of the way */}
      {run.open_items.length > 0 && (
        <details className="card p-3">
          <summary className="text-[11px] uppercase tracking-wider text-muted cursor-pointer select-none">
            Open items carried from prior quarters — {run.open_items.length} in total
            {run.open_items.some((o) => o.escalated) ? `, ${run.open_items.filter((o) => o.escalated).length} open too long` : ""}
          </summary>
          <div className="mt-2">
            <OpenItemsView run={run} gotoCompany={gotoCompany} />
          </div>
        </details>
      )}
    </div>
  );
}
