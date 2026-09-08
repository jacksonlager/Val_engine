// The position card: who, one status, what the mark did, why it stopped, the facts beside the
// suggested step, the verbs in one bar, and everything technical folded away. Shared by the
// queue (the whole book) and the New Activity view (the positions the activity tab touched,
// which a reviewer is meant to have read before the rest).
import { useState } from "react";
import type { CompanyResult, MarkStep } from "../types";
import { READINESS_HINT } from "../types";
import { deltaPct, musd, pct, shortDate, signed, signClass } from "../lib/format";
import { actionPhrase, familyLabel, priceSourceLabel, severityShort } from "../lib/labels";
import { CompanyDetail } from "./CompanyDetail";
import {
  DecisionBar,
  exceptionHeadline,
  flagName,
  FlagActionList,
  FlagNoteList,
  PositionStep,
  orderedActionable,
  plainPoint,
  rdClass,
  useFlagNames,
} from "./Flags";
import { FlagHistoryCard, PriorFlagPill } from "./FlagHistory";
import { FlagChip } from "./ui";

/** The event in one line. The full working — the arithmetic, the standard it rests on — is
    repeated verbatim by the findings and again by the suggestion, so the summary keeps only what
    happened and leaves the method to Sources & calculation, where it is on file in full. The
    mark move sits beside this line, so a short first sentence is not a thin one. */
function eventSummary(rationale: string): string {
  const text = plainPoint(rationale).trim();
  // A sentence end, but never one inside a parenthetical: "(Expected to close in Q4 2026, subject
  // to regulatory approval.)" would otherwise be cut open and left unbalanced.
  let depth = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "(") depth++;
    else if (ch === ")") depth = Math.max(0, depth - 1);
    else if (ch === "." && depth === 0 && /\s/.test(text[i + 1] ?? "") && /[A-Z(]/.test(text[i + 2] ?? "")) {
      return text.slice(0, i + 1);
    }
  }
  return text;
}

/** The steps that applied a row from the quarter's activity tab, in the tab's own order. */
export function activitySteps(c: CompanyResult): MarkStep[] {
  return c.steps.filter((s) => s.evidence).sort((a, b) => (a.evidence?.row_index ?? 0) - (b.evidence?.row_index ?? 0));
}

export function hasActivity(c: CompanyResult): boolean {
  return c.steps.some((s) => s.evidence);
}

/** Prior → Proposed (or Provisional), the change, and the approval state in words. A recorded
    decision shows as recorded; "Booked" is reserved for a published quarter. */
function Marks({ c }: { c: CompanyResult }) {
  const d = c.proposed_mark - c.prior_mark;
  const recorded = c.override ? c.override.booked : null;
  const published = c.approval === "Approved and published";
  const inv = c.new_investment_quarter ?? 0;
  const val = c.valuation_change_quarter ?? 0;
  const allInvestment = Math.abs(val) < 0.005 && Math.abs(inv) > 0.005;
  return (
    <div className="shrink-0">
      <dl className="qmarks">
        <div>
          <dt>Prior</dt>
          <dd className="text-ink2">{musd(c.prior_mark)}</dd>
        </div>
        <span className="qarrow" aria-hidden>
          →
        </span>
        <div>
          <dt>{c.provisional ? "Stand-in" : "Proposed"}</dt>
          <dd>
            {c.provisional ? (
              <span className="provisional" title={c.provisional_reason ?? "Stands in for an input that is not on file"}>
                {musd(c.proposed_mark)}
              </span>
            ) : (
              musd(c.proposed_mark)
            )}
          </dd>
        </div>
        <div className="qdelta">
          <dt>Change</dt>
          {/* Cash the fund put in is not appreciation. A move that is only new money is shown in
              neutral ink, and where both are present the split is stated rather than implied. */}
          <dd className={allInvestment ? "text-ink2" : signClass(d)}>
            {signed(d)} <span className="font-normal">({pct(deltaPct(c.prior_mark, c.proposed_mark), 1, true)})</span>
          </dd>
        </div>
        <span className="qsep" aria-hidden />
        <div className="qstate">
          <dt>{published ? "Booked" : recorded !== null ? "Recorded" : "Approval"}</dt>
          <dd className={recorded !== null ? "overridden" : "text-muted font-medium"}>
            {recorded !== null ? musd(recorded) : "Pending"}
          </dd>
        </div>
        <span className="qunit">$M</span>
      </dl>
      {Math.abs(inv) > 0.005 && (
        <div className="qsplit">
          <span className="text-ink2">{signed(inv)} invested</span>
          <span className="qsplit-sep" aria-hidden>
            ·
          </span>
          <span className={Math.abs(val) < 0.005 ? "text-muted" : signClass(val)}>{signed(val)} revaluation</span>
        </div>
      )}
    </div>
  );
}

/** What the proposed mark is made of, when it is made of more than one thing: the equity mark and
    a note leg carried at cost are different assets inside one number, and a reviewer signing the
    number should see both. Only rendered when there is a second component to show. */
function Composition({ c }: { c: CompanyResult }) {
  if (c.note_at_cost <= 0.005) return null;
  // A note funded this quarter is new money; one restored from last quarter's sidecar is not.
  const isNew = Math.abs(c.new_investment_quarter - c.note_at_cost) < 0.005 && c.new_investment_quarter > 0.005;
  return (
    <p className="qcomposition m-0">
      <b className="num">${musd(c.equity_mark)}M</b> existing equity <span className="qcomp-op">+</span>{" "}
      <b className="num">${musd(c.note_at_cost)}M</b> {isNew ? "new note" : "note at cost"} <span className="qcomp-op">=</span>{" "}
      <b className="num">${musd(c.proposed_mark)}M</b> proposed value
    </p>
  );
}

export function PositionCard({
  c,
  open,
  toggle,
  writeDisabled,
  onChanged,
  gotoCompany,
  showActivity = false,
}: {
  c: CompanyResult;
  open: boolean;
  toggle: () => void;
  writeDisabled: string | null;
  onChanged: () => void;
  gotoCompany: (n: string) => void;
  /** On the New Activity view: the event rows and how the engine treated each, above the findings. */
  showActivity?: boolean;
}) {
  const names = useFlagNames();
  const events = activitySteps(c);
  const acts = orderedActionable(c);
  const notes = c.flags.filter((f) => f.severity === "MONITOR");
  const lead = acts[0];
  const headline = exceptionHeadline(c, acts, names);
  const [evidence, setEvidence] = useState(false);

  return (
    <div className={`card qcard ${rdClass(c.readiness)} rail`}>
      {/* 1 — who, one badge, and what the mark did */}
      <div className="qhead px-3.5 pl-4 pt-2.5 pb-2">
        <div className="qwho">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-[15px] tracking-tight">{c.company}</span>
            <span className="badge" title={READINESS_HINT[c.readiness]}>
              {c.readiness}
            </span>
            {events.length > 0 && (
              <span className="tag-activity" title={`${events.length} row${events.length === 1 ? "" : "s"} on the ${events[0].evidence?.sheet ?? "Activity"} tab this quarter`}>
                New activity
              </span>
            )}
          </div>
          <div className="text-[11px] text-muted mt-0.5">
            {c.fund} · {c.sector} · {c.stage}
            {c.fv_level !== null && ` · Level ${c.fv_level}`}
            {c.stage === "Acquired (stock)" ? <> · consideration received in shares this quarter</> : c.action !== "Carry" && <> · {actionPhrase(c.action)}</>}
          </div>
        </div>
        <Marks c={c} />
      </div>
      {c.note_at_cost > 0.005 && (
        <div className="px-3.5 pl-4 pb-2">
          <Composition c={c} />
        </div>
      )}

      {/* 1b — on the New Activity view: what came in on the activity tab, and what the engine did with it */}
      {showActivity && events.length > 0 && (
        <div className="px-3.5 pl-4 pt-2 pb-2.5 border-t border-hair">
          <div className="eyebrow-sm">Activity this quarter</div>
          <ul className="activity-list">
            {events.map((s, i) => (
              <li key={i} className="activity-row">
                <div className="activity-what">
                  <span className="font-semibold text-[12.5px]">{s.evidence?.event_type ?? "Event"}</span>
                  <span className="text-[11px] text-muted">
                    {s.evidence &&
                      [s.evidence.date ? shortDate(s.evidence.date) : null, `row ${s.evidence.row_index} of the ${s.evidence.sheet} tab`]
                        .filter(Boolean)
                        .join(" · ")}
                  </span>
                </div>
                <div className="activity-how">
                  <span className="num text-[12.5px] whitespace-nowrap">
                    {musd(s.prior_value)} → <b>{musd(s.new_value)}</b>
                  </span>
                  <span className="activity-say">{eventSummary(s.rationale)}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 2 — why it stopped, in a sentence; then the facts beside the step */}
      {acts.length > 0 && (
        <div className="px-3.5 pl-4 pt-2.5 pb-2 border-t border-hair">
          <h3 className="qheadline">{headline}</h3>
          <div className="resolve">
            <div className="resolve-col">
              <FlagActionList c={c} flags={acts} writeDisabled={writeDisabled} onChanged={onChanged} covered={c.recommendation?.covers} />
            </div>
            {/* the recommendation sits on its own quiet ground, and the verb that acts on it sits
                directly beneath — one prominent button, in the same place on every card */}
            <div className="resolve-col resolve-rec">
              <div className="eyebrow-sm">Suggested next step</div>
              <PositionStep c={c} writeDisabled={writeDisabled} onChanged={onChanged} apply={false} />
              <div className="rec-act">
                {lead && <DecisionBar c={c} f={lead} writeDisabled={writeDisabled} onChanged={onChanged} />}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 3 — monitor findings in a reviewer's words, never mixed into the decisions */}
      {notes.length > 0 && (
        <div className={`px-3.5 pl-4 pt-2 pb-2 ${acts.length > 0 ? "border-t border-hair" : "border-t border-hair"}`}>
          <div className="eyebrow-sm">Monitoring</div>
          <FlagNoteList flags={notes} />
        </div>
      )}

      {/* 4 — the verbs, in one place; the disclosures ride on the right of the same bar */}
      <div className="px-3.5 pl-4 pt-2 pb-2.5 border-t border-hair">
        <div className="decision-bar">
          <div className="decision-actions text-[11.5px] text-muted">
            {lead
              ? "A recorded decision is not an approval — the quarter is approved when it is published."
              : c.readiness === "Ready"
                ? "Ready for approval — nothing for a person to decide."
                : "Nothing to decide."}
          </div>
          <div className="decision-more">
            <Disclosures c={c} evidence={evidence} setEvidence={setEvidence} open={open} toggle={toggle} gotoCompany={gotoCompany} />
          </div>
        </div>
      </div>

      {/* 5 — Evidence & history: rule codes, sources, last quarter, the decision on record */}
      {evidence && (
        <div className="px-3.5 pl-4 pt-2 pb-3 border-t border-hair evidence">
          <div className="grid gap-x-6 gap-y-3 lg:grid-cols-2">
            <div>
              <div className="eyebrow-sm">Findings and their rule codes</div>
              <ul className="m-0 mt-1 p-0 list-none flex flex-col gap-1">
                {c.flags.map((f, i) => (
                  <li key={i} className="flex items-center gap-2 text-[11.5px]">
                    <FlagChip f={f} />
                    <span className="text-ink2">{flagName(f, names)}</span>
                    <span className="text-muted">· {severityShort(f.severity)} · {familyLabel(f.family)}</span>
                  </li>
                ))}
                {c.flags.length === 0 && <li className="text-[11.5px] text-muted">None.</li>}
              </ul>
              {c.provisional_reason && (
                <p className="text-[11.5px] text-ink2 leading-snug mt-2 mb-0">
                  <b>Stand-in:</b> {c.provisional_reason}
                </p>
              )}
              {acts.some((f) => typeof f.evidence.price_source === "string") && (
                <p className="text-[11.5px] text-muted leading-snug mt-1 mb-0">
                  Price source on file:{" "}
                  <span className="text-ink2">
                    {priceSourceLabel(String(acts.find((f) => typeof f.evidence.price_source === "string")!.evidence.price_source))}
                  </span>
                  {typeof lead?.evidence.price_source_note === "string" && <> — {lead.evidence.price_source_note}</>}
                </p>
              )}
              {c.override && (
                <p className="text-[11.5px] text-ink2 leading-snug mt-2 mb-0">
                  <b>Decision on record:</b> ${musd(c.override.booked)}M by {c.override.approver} on {shortDate(c.override.created_at)}
                  {c.override.rule_ids_addressed.length > 0 && <> · resolves {c.override.rule_ids_addressed.join(", ")}</>}
                  {c.override.evidence && typeof c.override.evidence.source === "string" && <> · evidence: {String(c.override.evidence.source)}</>}
                  <br />
                  <span className="text-muted">{c.override.reason}</span>
                </p>
              )}
              <div className="text-[11px] text-muted mt-2">
                Approval: {c.approval}. {c.approval === "Approved and published" ? "Released with the quarter." : "Not yet released."}
              </div>
            </div>
            <div>
              <div className="eyebrow-sm flex items-center gap-2">
                Last quarter <PriorFlagPill c={c} />
              </div>
              <div className="mt-1">
                <FlagHistoryCard c={c} />
              </div>
            </div>
          </div>
        </div>
      )}
      {open && (
        <div className="border-t border-hair">
          <CompanyDetail c={c} writeDisabled={writeDisabled} onChanged={onChanged} showMarks={false} showFlags={false} />
        </div>
      )}
    </div>
  );
}

function Disclosures({
  c,
  evidence,
  setEvidence,
  open,
  toggle,
  gotoCompany,
}: {
  c: CompanyResult;
  evidence: boolean;
  setEvidence: (v: boolean) => void;
  open: boolean;
  toggle: () => void;
  gotoCompany: (n: string) => void;
}) {
  return (
    <>
      <button className="btn btn-ghost" onClick={() => setEvidence(!evidence)} aria-expanded={evidence}>
        <span className="text-[10px] leading-none">{evidence ? "▾" : "▸"}</span>
        Decision history
      </button>
      <button className="btn btn-ghost" onClick={toggle} aria-expanded={open}>
        <span className="text-[10px] leading-none">{open ? "▾" : "▸"}</span>
        {open ? "Hide sources & calculation" : "Sources & calculation"}
      </button>
      <button className="btn btn-ghost" onClick={() => gotoCompany(c.company)}>
        Open in Companies
      </button>
    </>
  );
}
