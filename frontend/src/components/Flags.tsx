// How a flag reads on screen, and how a reviewer resolves one.
//
// A reviewer scans a queue of positions looking for *why this one stopped*, so the card
// shows the imperative (`action`) and the engine's two or three summary `points` — no
// paragraph. The full reasoning (`message`) and the evidence the rule recorded are one
// click away in a dialog, because a flag that cannot be examined is not an audit trail.
//
// Beside the reasons sit the engine's `suggestions`: one to three ways to resolve the flag,
// each with the mark it would book. Choosing one opens a confirmation that needs a name,
// then records an E-01 override addressed to this rule — the same ledger a hand-typed
// override uses, so the decision flows into the booked mark, the totals, the exports and
// the archive exactly as any committee decision does. The proposal is never rewritten.
//
// `**bold**` inside a point marks the words that carry the decision; nothing else in the
// string is markup, and an unmatched `**` renders literally rather than eating the text.
import { Fragment, useState } from "react";
import type { CompanyResult, Flag, Suggestion } from "../types";
import { postOverride } from "../lib/api";
import { isoDate, musd, signClass, signed } from "../lib/format";
import { DispChip, Field, Modal, WriteButton } from "./ui";

/** `a **b** c` -> a, <strong>b</strong>, c. Splits on pairs only; odd markers stay literal. */
export function Rich({ text }: { text: string }) {
  const parts = text.split("**");
  if (parts.length % 2 === 0) return <>{text}</>; // unbalanced: show it as written
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1 ? <strong key={i}>{p}</strong> : <Fragment key={i}>{p}</Fragment>))}
    </>
  );
}

/** The two or three summary lines the engine wrote for a BLOCK or REVIEW flag. */
export function FlagPoints({ f, className = "" }: { f: Flag; className?: string }) {
  if (f.points.length === 0) return <p className={`text-[12px] text-ink2 leading-[1.5] m-0 ${className}`}>{f.message}</p>;
  return (
    <ul className={`flag-points ${className}`}>
      {f.points.map((p, i) => (
        <li key={i}>
          <Rich text={p} />
        </li>
      ))}
    </ul>
  );
}

/** The long form: what the engine wrote in full, plus the inputs it recorded. */
export function FlagDetailModal({ f, company, onClose }: { f: Flag; company: string; onClose: () => void }) {
  const ev = Object.entries(f.evidence);
  return (
    <Modal title={`${f.rule_id} · ${company}`} onClose={onClose}>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <DispChip d={f.severity} />
        <span className="text-[11px] text-muted">{f.family}</span>
      </div>
      {f.action && <p className="text-[13.5px] font-semibold leading-snug mb-2">{f.action}</p>}
      {f.points.length > 0 && <FlagPoints f={f} className="mb-3" />}
      <div className="text-[11px] uppercase tracking-wider text-muted mt-3 mb-1">In full</div>
      <p className="text-[12.5px] text-ink2 leading-[1.55] m-0 whitespace-normal">{f.message}</p>
      {typeof f.evidence.price_source_note === "string" && (
        <p className="text-[11.5px] text-muted italic leading-snug mt-2">{f.evidence.price_source_note}</p>
      )}
      {ev.length > 0 && (
        <>
          <div className="text-[11px] uppercase tracking-wider text-muted mt-3 mb-1">Evidence</div>
          <div className="inputs">
            {ev.map(([k, v]) => (
              <Fragment key={k}>
                <span className="mono text-[11px] text-muted">{k}</span>
                <span className="num text-[11.5px] text-right">
                  {v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v)}
                </span>
                <span />
              </Fragment>
            ))}
          </div>
        </>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------- suggestions

/** The rule ids a new decision on `c` should address: whatever is already addressed plus
    `ruleId`. An existing override with an empty list means "every flag", so keep that. */
function addressedAfter(c: CompanyResult, ruleId: string): string[] {
  const prior = c.override?.rule_ids_addressed ?? [];
  const base = c.override && prior.length === 0 ? c.flags.map((f) => f.rule_id) : prior;
  return Array.from(new Set([...base, ruleId]));
}

/** The approval step. Nothing is written until a named person confirms the number. */
function SuggestionConfirmModal({
  c,
  f,
  s,
  onClose,
  onDone,
}: {
  c: CompanyResult;
  f: Flag;
  s: Suggestion;
  onClose: () => void;
  onDone: () => void;
}) {
  const [approver, setApprover] = useState("");
  const [reason, setReason] = useState(`Suggested (${f.rule_id}): ${s.label} ${s.reasons.join(" ")}`);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const delta = s.booked - c.proposed_mark;
  const replaces = c.override && Math.abs(c.override.booked - s.booked) > 1e-6;
  const valid = approver.trim().length > 0 && reason.trim().length > 0;
  return (
    <Modal title={`Confirm · ${c.company} · ${f.rule_id}`} onClose={onClose}>
      <p className="text-[13.5px] font-semibold leading-snug mb-1">{s.label}</p>
      <ul className="flag-points mb-3">
        {s.reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
      <div className="card p-2.5 mb-3 text-[12.5px]">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-muted">Proposed by the engine</span>
          <span className="num">{musd(c.proposed_mark)}</span>
        </div>
        <div className="flex items-baseline justify-between gap-3 mt-0.5">
          <span className="text-muted">Will be booked</span>
          <span className="num font-semibold">
            {musd(s.booked)}{" "}
            <span className={`font-normal text-[11.5px] ${signClass(delta)}`}>({signed(delta)})</span>
          </span>
        </div>
        {replaces && c.override && (
          <div className="text-[11px] text-muted mt-1.5 leading-snug">
            Replaces the {musd(c.override.booked)} booked by {c.override.approver} on {isoDate(c.override.created_at)}.
          </div>
        )}
      </div>
      <p className="text-[11.5px] text-muted leading-snug mb-3">
        This records an E-01 override addressed to {f.rule_id}: the booked mark changes, the proposal does not, and the
        decision is written to the ledger under your name. It re-runs into the totals, the exports and the archive.
      </p>
      <Field label="Approver">
        <input className="input w-full" value={approver} onChange={(e) => setApprover(e.target.value)} autoFocus />
      </Field>
      <Field label="Reason (on the ledger)">
        <textarea className="textarea w-full" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {err && <div className="text-[12px] down mb-2">{err}</div>}
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={!valid || busy}
          onClick={async () => {
            setBusy(true);
            setErr(null);
            try {
              await postOverride({
                company: c.company,
                booked: s.booked,
                approver: approver.trim(),
                reason: reason.trim(),
                rule_ids_addressed: addressedAfter(c, f.rule_id),
                source_suggestion: `${f.rule_id}/${s.key}`,
              });
              onDone();
            } catch (e) {
              setErr(String((e as Error).message ?? e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Booking…" : `Confirm and book ${musd(s.booked)}`}
        </button>
      </div>
    </Modal>
  );
}

/** What was decided on this flag, if a recorded override addresses it. */
function decidedOn(c: CompanyResult, f: Flag): { s?: Suggestion; booked: number; approver: string; at: string } | null {
  const o = c.override;
  if (!o) return null;
  const addressesAll = o.rule_ids_addressed.length === 0;
  if (!addressesAll && !o.rule_ids_addressed.includes(f.rule_id)) return null;
  const key = o.source_suggestion?.startsWith(`${f.rule_id}/`) ? o.source_suggestion.slice(f.rule_id.length + 1) : null;
  return { s: key ? f.suggestions.find((s) => s.key === key) : undefined, booked: o.booked, approver: o.approver, at: o.created_at };
}

/** The menu: one card per suggestion, the whole card is the button. */
export function SuggestionCards({
  c,
  f,
  writeDisabled,
  onChanged,
}: {
  c: CompanyResult;
  f: Flag;
  writeDisabled: string | null;
  onChanged: () => void;
}) {
  const [pick, setPick] = useState<Suggestion | null>(null);
  const [change, setChange] = useState(false);
  const decided = decidedOn(c, f);
  if (f.suggestions.length === 0) return null;

  if (decided && !change) {
    return (
      <div className="decided">
        <div className="flex items-center gap-2">
          <span className="chip disp-CLEAR">decided</span>
          <span className="text-[12.5px] font-semibold leading-snug">{decided.s?.label ?? "Override recorded."}</span>
        </div>
        <div className="text-[11.5px] text-muted mt-1">
          Booked <span className="num text-ink2">{musd(decided.booked)}</span> · {decided.approver} · {isoDate(decided.at)}
        </div>
        <button className="btn btn-ghost mt-1 text-[11px]" onClick={() => setChange(true)}>
          Change
        </button>
      </div>
    );
  }

  return (
    <>
      <div className="suggest-grid">
        {f.suggestions.map((s) => {
          const delta = s.booked - c.proposed_mark;
          const isCurrent = decided && Math.abs(decided.booked - s.booked) < 1e-6;
          return (
            <WriteButton
              key={s.key}
              disabledReason={writeDisabled}
              className={`suggest ${isCurrent ? "current" : ""}`}
              onClick={() => setPick(s)}
            >
              <span className="suggest-label">{s.label}</span>
              <ul className="suggest-why">
                {s.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
              <span className="suggest-foot">
                <span className="num">
                  {musd(s.booked)}
                  <span className={`ml-1 text-[10.5px] ${signClass(delta)}`}>
                    {Math.abs(delta) < 5e-3 ? "as proposed" : `(${signed(delta)})`}
                  </span>
                </span>
                <span className="suggest-cta">{isCurrent ? "current" : "Select"}</span>
              </span>
            </WriteButton>
          );
        })}
      </div>
      {decided && change && (
        <button className="btn btn-ghost mt-1 text-[11px]" onClick={() => setChange(false)}>
          Keep current decision
        </button>
      )}
      {pick && (
        <SuggestionConfirmModal
          c={c}
          f={f}
          s={pick}
          onClose={() => setPick(null)}
          onDone={() => {
            setPick(null);
            setChange(false);
            onChanged();
          }}
        />
      )}
    </>
  );
}

/** Every flag a reviewer must act on: rule id, imperative, summary points and details on
    the left; the engine's priced suggestions on the right. */
export function FlagActionList({
  c,
  flags,
  writeDisabled,
  onChanged,
}: {
  c: CompanyResult;
  flags: Flag[];
  writeDisabled: string | null;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<number | null>(null);
  return (
    <>
      <ul className="flag-list">
        {flags.map((f, i) => (
          <li key={i} className="flag-row">
            <div className="flag-why">
              <div className="flex items-baseline gap-2.5">
                <span className="rule-tag mono" title={`${f.severity} · ${f.family}`}>
                  {f.rule_id}
                </span>
                <span className="text-[13.5px] font-semibold leading-snug">{f.action || f.message}</span>
              </div>
              {f.action && (
                <div className="mt-1">
                  <FlagPoints f={f} />
                  <button
                    className="btn btn-ghost mt-1 text-[11px]"
                    onClick={() => setDetail(i)}
                    aria-haspopup="dialog"
                    title={`Read ${f.rule_id} in full, with the inputs behind it`}
                  >
                    Details
                  </button>
                </div>
              )}
            </div>
            {f.suggestions.length > 0 && (
              <div className="flag-do">
                <div className="eyebrow-sm">Suggested resolutions</div>
                <SuggestionCards c={c} f={f} writeDisabled={writeDisabled} onChanged={onChanged} />
              </div>
            )}
          </li>
        ))}
      </ul>
      {detail !== null && flags[detail] && (
        <FlagDetailModal f={flags[detail]} company={c.company} onClose={() => setDetail(null)} />
      )}
    </>
  );
}
