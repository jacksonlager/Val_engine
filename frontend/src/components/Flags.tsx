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
import { Fragment, useState, type ReactNode } from "react";
import type { CompanyResult, Flag, PositionRecommendation, Readiness, Recommendation, Suggestion } from "../types";
import { postOverride } from "../lib/api";
import { useRationale, useRuleRationale } from "../lib/rationale";
import { isoDate, musd, pct, shortDate, signClass, signed } from "../lib/format";
import { evidenceLabel, evidenceValue, familyLabel, FAMILY_LABEL, marketSourceLabel, plainSystemPhrase, severityPhrase } from "../lib/labels";
import { DispChip, Field, Modal, WriteButton } from "./ui";

/** `a **b** c` -> a, <strong>b</strong>, c. Splits on pairs only; odd markers stay literal. */
export function Rich({ text }: { text: string }) {
  // engine text carries ISO dates (2027-03-19); a reader sees "19 Mar 2027" like every other date on the page
  const parts = text.replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (d) => shortDate(d)).split("**");
  if (parts.length % 2 === 0) return <>{text}</>; // unbalanced: show it as written
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1 ? <strong key={i}>{p}</strong> : <Fragment key={i}>{p}</Fragment>))}
    </>
  );
}

/** A stub reference such as "(stub:seeded_to_ipo_print)" is provenance, not a fact about the
    company; it belongs under Evidence & history, not in the reason a reviewer reads first. */
export function plainPoint(p: string): string {
  return plainSystemPhrase(p)
    .replace(/\s*\((?:source: )?(?:stub|fixture|live):[^)]*\)/g, "")
    .replace(/\s*\((?:[MXE]-\d{3})\)/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** The two or three summary lines the engine wrote for a BLOCK or REVIEW flag. */
export function FlagPoints({
  f,
  className = "",
  plain = false,
  limit,
}: {
  f: Flag;
  className?: string;
  plain?: boolean;
  /** Two or three lines is what a reviewer reads; the rest is in Evidence. */
  limit?: number;
}) {
  if (f.points.length === 0)
    return <p className={`text-[12px] text-ink2 leading-[1.5] m-0 ${className}`}>{plainSystemPhrase(f.message)}</p>;
  const shown = limit ? f.points.slice(0, limit) : f.points;
  return (
    <ul className={`flag-points ${className}`}>
      {shown.map((p, i) => (
        <li key={i}>
          <Rich text={plain ? plainPoint(p) : p} />
        </li>
      ))}
    </ul>
  );
}

/** Readiness as a CSS hook: `rd-Blocked` / `rd-NeedsReview` / `rd-Ready` set --c/--ct/--cw. */
export function rdClass(r: Readiness): string {
  return r === "Needs Review" ? "rd-NeedsReview" : `rd-${r}`;
}

/** Two exceptions share one rule id but read nothing alike to a person; the evidence says
    which is which. Everything else takes the catalogue's own plain name. */
function refinedName(f: Flag): string | null {
  if (f.rule_id === "X-101") {
    if (typeof f.evidence.deal_value === "number") return "Signed acquisition that has not closed";
    if (f.evidence.price_source !== undefined) return "Missing quarter-end share price";
  }
  return null;
}

/** The plain name of one finding — never a rule code. */
export function flagName(f: Flag, names: Map<string, string> | undefined): string {
  return refinedName(f) ?? names?.get(f.rule_id) ?? FAMILY_LABEL[f.family] ?? "Needs a reviewer";
}

export function useFlagNames(): Map<string, string> | undefined {
  const rat = useRationale();
  return rat ? new Map(rat.rules.map((r) => [r.id, r.name])) : undefined;
}

export function actionableFlags(c: CompanyResult): Flag[] {
  return c.flags.filter((f) => f.severity !== "MONITOR");
}

/** Is this the finding that says an input is missing? A stand-in mark (provisional) or a rule
    from the missing-input set: the reason there is no supported mark at all, and the one an
    override must not step past without saying so. */
const MISSING_INPUT_RULES = new Set(["X-900", "X-112", "X-113", "X-116", "X-918", "M-999"]);
export function missingInput(c: CompanyResult, f: Flag): boolean {
  if (MISSING_INPUT_RULES.has(f.rule_id)) return true;
  return isStandInPrice(c, f);
}

/** The finding that carries the stand-in price: X-101 in the listing quarter (M-040), X-113 in every
    quarter after it (M-041 on a quote no feed could observe). Both record `price_source`. */
function isStandInPrice(c: CompanyResult, f: Flag): boolean {
  return (f.rule_id === "X-101" || f.rule_id === "X-113") && c.provisional && f.evidence.price_source !== undefined;
}

/** A missing quarter-end quote is the one blocker a reviewer can clear by supplying the
    input, rather than by deciding around it. */
export function needsClosingPrice(c: CompanyResult, f: Flag): boolean {
  return c.listed && isStandInPrice(c, f);
}

/** The headline: why this position stopped, in one plain line. A missing input outranks
    everything else, because it is the reason there is no supported mark at all. */
export function exceptionHeadline(c: CompanyResult, acts: Flag[], names: Map<string, string> | undefined): string {
  if (acts.length === 0) return c.monitor ? "Nothing to decide — monitoring only" : "No exceptions raised";
  // Name what is actually wrong. "and 1 more finding" told a reviewer there was something else
  // without saying what, which is the one thing a headline must not do. Beyond three the tail is
  // counted rather than listed, because the list below has them all in order anyway.
  const all = acts.map((f) => flagName(f, names));
  const shown = all.slice(0, 3);
  const rest = all.length - shown.length;
  const joined =
    shown.length === 1
      ? shown[0]
      : shown.slice(0, -1).join(", ") + " and " + shown[shown.length - 1].charAt(0).toLowerCase() + shown[shown.length - 1].slice(1);
  return rest > 0 ? `${joined}, and ${rest} more` : joined;
}

/** What is still outstanding on a finding the suggested step speaks to. A step is a proposal, not
    a resolution: nothing is settled until a person records a decision, and where the finding is a
    missing input, not even then — the input has to arrive. Named specifically so the reviewer
    knows what to go and get. */
/** A finding whose own evidence says its inputs predate an event this quarter — the runway
    computed from a cash balance filed before the round that has just closed. The number is real;
    it is simply not yet a fact about the position as it now stands. */
export function unverifiedNote(f: Flag): string | null {
  const fin = f.evidence.financings_in_quarter;
  if (Array.isArray(fin) && fin.length > 0) {
    return "Estimated, not verified: measured on cash and burn filed before this quarter's financing.";
  }
  return null;
}

export function pendingLabel(f: Flag): string {
  switch (f.rule_id) {
    case "X-113":
      return "Pending the quarter-end close";
    case "X-304":
    case "X-303":
      return "Pending updated cash data";
    case "X-112":
      return "Pending the acquirer's share terms";
    case "X-116":
      return "Pending a recovery estimate";
    case "X-900":
      return "Pending a corrected workbook row";
    case "X-918":
      return "Pending a Portfolio row";
    case "M-999":
      return "Pending an agreed treatment";
    default:
      return "Pending your confirmation";
  }
}

/** The flags in the order a reviewer should meet them: the missing-input finding first, then
    BLOCK before REVIEW, then as the engine listed them. */
export function orderedActionable(c: CompanyResult): Flag[] {
  const rank = (f: Flag) => (missingInput(c, f) ? 0 : f.severity === "BLOCK" ? 1 : 2);
  return actionableFlags(c)
    .map((f, i) => ({ f, i }))
    .sort((a, b) => rank(a.f) - rank(b.f) || a.i - b.i)
    .map((x) => x.f);
}

/** One short verb per engine option, for a button. The option's own label is a sentence. */
const OPTION_VERB: Record<string, string> = {
  as_proposed: "Accept proposed mark",
  hold_prior: "Hold prior mark",
  full_value: "Book full deal value",
  structure_adjusted: "Apply structure haircut",
  calibrate: "Calibrate to public comps",
  impair_note: "Impair the note",
  to_cost: "Mark down to cost",
  reconfirm: "Re-confirm booked mark",
  adopt_proposed: "Adopt revised proposal",
  at_cost: "Mark to cost",
  write_to_zero: "Write down to zero",
  at_secondary_price: "Book at the secondary price",
  at_ipo_print: "Book at the listing-day price",
  at_market_close: "Book at the market close",
  at_proceeds_price: "Book at the price the proceeds imply",
  at_last_round: "Book at the last round's price",
  probability_weighted: "Book the probability-weighted figure",
  with_lockup_discount: "Apply the lock-up discount",
  term_sheet_indicated: "Book the term sheet's indicated value",
  calibrated_to_comps: "Calibrate to public comps",
};
export function optionVerb(s: Suggestion): string {
  return OPTION_VERB[s.key] ?? "Apply suggested step";
}

/** The long form: what the engine wrote in full, plus the inputs it recorded. */
export function FlagDetailModal({ f, company, onClose }: { f: Flag; company: string; onClose: () => void }) {
  const ev = Object.entries(f.evidence);
  const why = useRuleRationale(f.rule_id);
  const names = useFlagNames();
  const name = flagName(f, names);
  return (
    <Modal title={`${name} · ${company}`} onClose={onClose}>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <DispChip d={f.severity} />
        <span className="mono text-[11px] text-muted">{f.rule_id}</span>
        <span className="text-[11px] text-muted">{familyLabel(f.family)}</span>
        {why && (
          <>
            {why.name !== name && <span className="text-[12px] font-medium">{why.name}</span>}
            <span className={`rtag ${why.source === "brief" ? "rtag-brief" : "rtag-ours"} ml-auto`}
                  title={why.source === "brief" ? `The brief names this exception: “${why.brief_text}”` : "A rule we added; the bullets below are its defence"}>
              {why.source === "brief" ? "Named in the assignment brief" : "Rule we added"}
            </span>
          </>
        )}
      </div>
      {f.action && <p className="text-[13.5px] font-semibold leading-snug mb-2">{f.action}</p>}
      {f.points.length > 0 && <FlagPoints f={f} className="mb-3" />}
      <div className="text-[11px] uppercase tracking-wider text-muted mt-3 mb-1">In full</div>
      <p className="text-[12.5px] text-ink2 leading-[1.55] m-0 whitespace-normal">{plainSystemPhrase(f.message)}</p>
      {why && (
        <>
          <div className="text-[11px] uppercase tracking-wider text-muted mt-3 mb-1">Why this rule, why this severity</div>
          <ul className="flag-points m-0">
            <li><b>Why it is a flag.</b> {why.why_flag}</li>
            <li><b>Why it {severityPhrase(f.severity)}.</b> {why.why_severity}</li>
          </ul>
          <div className="text-[10.5px] text-muted mt-1">
            Test applied: <span className="mono">{why.reads}</span>
          </div>
        </>
      )}
      {typeof f.evidence.price_source_note === "string" && (
        <p className="text-[11.5px] text-muted italic leading-snug mt-2">{f.evidence.price_source_note}</p>
      )}
      {ev.length > 0 && (
        <>
          <div className="text-[11px] uppercase tracking-wider text-muted mt-3 mb-1">Evidence</div>
          <div className="inputs">
            {ev.map(([k, v]) => (
              <Fragment key={k}>
                <span className="text-[11px] text-muted" title={k}>
                  {evidenceLabel(k)}
                </span>
                <span className="num text-[11.5px] text-right">
                  {Array.isArray(v)
                    ? v.map((x) => evidenceValue(x)).join("; ")
                    : v !== null && typeof v === "object"
                      ? Object.entries(v as Record<string, unknown>)
                          .map(([a, b]) => `${evidenceLabel(a)}: ${evidenceValue(b)}`)
                          .join("; ")
                      : evidenceValue(v)}
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

// ---------------------------------------------------------------- deciding

/** What a reviewer is about to book: one of the engine's priced options, the proposal as it
    stands, a number they typed, or a number derived from a quarter-end price they supplied.
    The ledger records which (`source_suggestion`), and for a price, the evidence itself. */
export type ClosingPriceEvidence = {
  kind: "closing_price";
  as_of: string;
  market_cap_musd: number;
  price?: number;
  shares_m?: number;
  source: string;
  ownership: number;
};
export type Choice =
  | { kind: "step"; s: Suggestion; rec: PositionRecommendation }
  | { kind: "option"; s: Suggestion }
  | { kind: "proposed" }
  | { kind: "manual"; booked: number }
  | { kind: "price"; booked: number; evidence: ClosingPriceEvidence };

function choiceBooked(c: CompanyResult, ch: Choice): number {
  return ch.kind === "option" || ch.kind === "step" ? ch.s.booked : ch.kind === "proposed" ? c.proposed_mark : ch.booked;
}

/** The engine writes its labels and reasons as sentences, but not always with the full stop.
    The ledger reason is prose a person signs, so every clause ends like one. */
function fullStop(t: string): string {
  const s = t.trim();
  return !s || /[.!?]$/.test(s) ? s : `${s}.`;
}

/** The approval step. Nothing is written until a named person confirms the number — and for
    a number the reviewer typed, until they have written down why. On a finding that says an
    input is missing, a decision that does not supply it must say, in so many words, that it
    is stepping past the gap: the ledger then carries that admission, not a silent bypass. */
function ConfirmModal({
  c,
  f,
  choice,
  onClose,
  onDone,
}: {
  c: CompanyResult;
  f: Flag;
  choice: Choice;
  onClose: () => void;
  onDone: () => void;
}) {
  const [approver, setApprover] = useState("");
  const names = useFlagNames();
  const finding = flagName(f, names);
  const s = choice.kind === "option" || choice.kind === "step" ? choice.s : null;
  const step = choice.kind === "step" ? choice.rec : null;
  const acts = orderedActionable(c);
  // What this decision closes. The chooser proposes it; the reviewer signs it, and can untick.
  const [settles, setSettles] = useState<string[]>(
    step ? acts.filter((x) => step.covers.includes(x.rule_id)).map((x) => x.rule_id) : [f.rule_id],
  );
  const rec = !step && s && f.recommendation && f.recommendation.key === s.key ? f.recommendation : null;
  // Reads inside the ledger sentence, so it is a phrase and not a label: "… (Suggested by
  // Claude (claude-sonnet-4-5); ledger reference X-106.)"
  const who = rec
    ? rec.source === "claude"
      ? `Suggested by Claude${rec.model ? ` (${rec.model})` : ""}`
      : "The policy default"
    : "An option the engine offered";
  const booked = choiceBooked(c, choice);
  const gap = missingInput(c, f) && choice.kind !== "price";
  const [acknowledged, setAcknowledged] = useState(false);
  // An engine option arrives with its reasoning; the proposal with the engine's; a typed number
  // with nothing — the person who chose it is the only one who knows why, and must say so.
  const [reason, setReason] = useState(
    s ? `${[s.label, ...s.reasons].map(fullStop).filter(Boolean).join(" ")} (${who}; ledger reference ${f.rule_id}.)`
      : choice.kind === "proposed" ? `Accepted the engine's proposed mark of $${musd(c.proposed_mark)}M on "${finding}" (ledger reference ${f.rule_id}); no adjustment.`
      : choice.kind === "price"
        ? `Quarter-end market cap of $${choice.evidence.market_cap_musd.toLocaleString(undefined, { maximumFractionDigits: 1 })}M at ${choice.evidence.as_of} from ${choice.evidence.source}` +
          (choice.evidence.price && choice.evidence.shares_m ? ` (${choice.evidence.price} × ${choice.evidence.shares_m}M shares)` : "") +
          ` × ${pct(choice.evidence.ownership, 1)} held = $${musd(booked)}M. Replaces the listing-day stand-in.`
        : "",
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const delta = booked - c.proposed_mark;
  const replaces = c.override && Math.abs(c.override.booked - booked) > 1e-6;
  const valid = approver.trim().length > 0 && reason.trim().length > 0 && settles.length > 0 && (!gap || acknowledged);
  const source = s ? `${f.rule_id}/${s.key}` : `${f.rule_id}/${choice.kind}`;
  const title = step ? step.label : s ? (rec ? rec.label : s.label)
    : choice.kind === "proposed" ? `Accept the proposed mark of $${musd(c.proposed_mark)}M.`
    : choice.kind === "price" ? `Book $${musd(booked)}M from the quarter-end price you supplied.`
    : `Book $${musd(booked)}M, entered by the approver.`;
  const points = step ? step.reasons : s ? (rec ? rec.reasons : s.reasons)
    : choice.kind === "proposed" ? ["The engine's proposal stands as the booked mark; the flag is recorded as considered and resolved."]
    : choice.kind === "price" ? ["The market cap and its source travel with the decision on the ledger, so the number can be checked against the quote later."]
    : ["Not one of the engine's priced options. The reason below is the whole of the support for this number on the ledger."];
  return (
    <Modal title={`Record a decision on ${c.company}`} onClose={onClose}>
      <div className="flex items-center gap-2 mb-1">
        <p className="text-[13.5px] font-semibold leading-snug m-0">{title}</p>
        {rec && <SourceChip rec={rec} />}
        {step && <StepSource rec={step} />}
        {choice.kind === "manual" && <span className="chip disp-REVIEW no-dot">Manual entry</span>}
        {choice.kind === "price" && <span className="chip disp-CLEAR no-dot">Evidence attached</span>}
      </div>
      <ul className="flag-points mb-3">
        {points.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
      <div className="card p-2.5 mb-3 text-[12.5px]">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-muted">Proposed by the engine</span>
          <span className="num">{musd(c.proposed_mark)}</span>
        </div>
        <div className="flex items-baseline justify-between gap-3 mt-0.5">
          <span className="text-muted">Will be recorded</span>
          <span className="num font-semibold">
            {musd(booked)}{" "}
            <span className={`font-normal text-[11.5px] ${signClass(delta)}`}>({signed(delta)})</span>
          </span>
        </div>
        {replaces && c.override && (
          <div className="text-[11px] text-muted mt-1.5 leading-snug">
            Replaces the ${musd(c.override.booked)}M recorded by {c.override.approver} on {isoDate(c.override.created_at)}.
          </div>
        )}
      </div>
      <p className="text-[11.5px] text-muted leading-snug mb-3">
        This records a committee decision on “{finding}” under your name (ledger reference {f.rule_id}): the recorded mark
        changes, the proposal does not. It re-runs into the totals, the exports and the archive. Nothing is booked until the
        quarter is published.
      </p>
      {gap && (
        <label className="ack">
          <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
          <span>
            <b>This finding says an input is missing</b>
            {c.provisional_reason ? ` — ${plainPoint(c.provisional_reason.split(".")[0])}.` : "."} I am recording a mark without it,
            and the ledger will say so.
          </span>
        </label>
      )}
      {acts.length > 1 && (
        <div className="settles">
          <div className="eyebrow-sm">What this decision settles</div>
          {acts.map((x, i) => (
            <label key={x.rule_id} className="settles-row">
              <input
                type="checkbox"
                checked={settles.includes(x.rule_id)}
                onChange={(e) =>
                  setSettles((v) => (e.target.checked ? [...v, x.rule_id] : v.filter((r) => r !== x.rule_id)))
                }
              />
              <span>
                <b>{i + 1}.</b> {flagName(x, names)}
                {step && step.covers.includes(x.rule_id) && x.rule_id !== step.rule_id && (
                  <span className="text-muted"> — the step settles this too</span>
                )}
              </span>
            </label>
          ))}
          <div className="text-[11px] text-muted mt-1">
            {settles.length < acts.length
              ? `${acts.length - settles.length} finding${acts.length - settles.length === 1 ? " stays" : "s stay"} open; the position remains under review.`
              : "Every open finding on this position is closed by this decision."}
          </div>
        </div>
      )}
      <Field label="Approver">
        <input className="input w-full" value={approver} onChange={(e) => setApprover(e.target.value)} autoFocus />
      </Field>
      <Field label={choice.kind === "manual" ? "Reason (on the ledger) — required for a number you entered" : "Reason (on the ledger) — editable"}>
        <textarea
          className="textarea w-full"
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={choice.kind === "manual" ? "What supports this mark, and what the engine could not see" : undefined}
        />
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
                booked,
                approver: approver.trim(),
                reason: (gap ? "[input still missing] " : "") + reason.trim(),
                // whatever a prior decision already closed, plus what this one says it closes
                rule_ids_addressed: Array.from(
                  new Set([
                    ...(c.override && c.override.rule_ids_addressed.length === 0
                      ? c.flags.map((x) => x.rule_id)
                      : c.override?.rule_ids_addressed ?? []),
                    ...settles,
                  ]),
                ),
                source_suggestion: source,
                ...(choice.kind === "price" ? { evidence: choice.evidence } : {}),
              });
              onDone();
            } catch (e) {
              setErr(String((e as Error).message ?? e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Recording…" : `Confirm and record $${musd(booked)}M`}
        </button>
      </div>
    </Modal>
  );
}

/** The primary action on a newly listed position with no quarter-end quote: supply the price.
    Market cap directly, or price × shares; the mark follows from HC's stake. Nothing is
    written here — Continue hands the number and its evidence to the confirmation. */
function ClosingPriceModal({ c, f, onClose, onContinue }: { c: CompanyResult; f: Flag; onClose: () => void; onContinue: (ch: Choice) => void }) {
  // both findings that carry a stand-in price (X-101 on the listing, X-113 on every carry after it) record the date
  const asOf = String(f.evidence.measurement_date ?? c.staleness_anchor);
  const [mode, setMode] = useState<"cap" | "px">("cap");
  const [cap, setCap] = useState("");
  const [px, setPx] = useState("");
  const [sh, setSh] = useState("");
  const [source, setSource] = useState("");
  const num = (t: string) => Number(t.replace(/,/g, ""));
  const capValue = mode === "cap" ? num(cap) : num(px) * num(sh);
  const priced = Number.isFinite(capValue) && capValue > 0;
  const ok = priced && source.trim().length > 0;
  const mark = priced ? Math.round(capValue * c.ownership_after * 1e6) / 1e6 : null;
  const standIn = typeof f.evidence.ipo_print_mark === "number" ? (f.evidence.ipo_print_mark as number) : c.proposed_mark;
  return (
    <Modal title={`Add closing price · ${c.company}`} onClose={onClose}>
      <p className="text-[12.5px] text-ink2 leading-snug m-0 mb-3">
        No {asOf} quote is on file, so the mark stands in the listing-day market cap. Enter the quarter-end figure and where it
        came from; the mark is HC's {pct(c.ownership_after, 1)} of it.
      </p>
      <div className="flex gap-1 mb-3" role="tablist">
        <button className={`btn ${mode === "cap" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("cap")} role="tab" aria-selected={mode === "cap"}>
          Market cap
        </button>
        <button className={`btn ${mode === "px" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("px")} role="tab" aria-selected={mode === "px"}>
          Price × shares
        </button>
      </div>
      {mode === "cap" ? (
        <Field label={`Market cap at ${shortDate(asOf)} ($M)`}>
          <input className="input w-full num" inputMode="decimal" value={cap} onChange={(e) => setCap(e.target.value)} autoFocus placeholder="e.g. 3,712" />
        </Field>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <Field label={`Closing price at ${shortDate(asOf)}`}>
            <input className="input w-full num" inputMode="decimal" value={px} onChange={(e) => setPx(e.target.value)} autoFocus placeholder="e.g. 41.20" />
          </Field>
          <Field label="Shares outstanding (M)">
            <input className="input w-full num" inputMode="decimal" value={sh} onChange={(e) => setSh(e.target.value)} placeholder="e.g. 90.1" />
          </Field>
        </div>
      )}
      <Field label="Source (required)">
        <input className="input w-full" value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. Nasdaq official close via Bloomberg" />
      </Field>
      <div className="card p-2.5 mb-3 text-[12.5px]">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-muted">Listing-day stand-in</span>
          <span className="num">{musd(standIn)}</span>
        </div>
        <div className="flex items-baseline justify-between gap-3 mt-0.5">
          <span className="text-muted">From the price you entered</span>
          <span className="num font-semibold">{mark === null ? "—" : musd(mark)}</span>
        </div>
        {priced && !ok && <div className="text-[11px] text-muted mt-1.5">Name the source to continue — it travels with the decision.</div>}
      </div>
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={!ok || mark === null}
          onClick={() =>
            mark !== null &&
            onContinue({
              kind: "price",
              booked: mark,
              evidence: {
                kind: "closing_price",
                as_of: asOf,
                market_cap_musd: Math.round(capValue * 1e3) / 1e3,
                ...(mode === "px" ? { price: num(px), shares_m: num(sh) } : {}),
                source: source.trim(),
                ownership: c.ownership_after,
              },
            })
          }
        >
          Continue to confirm
        </button>
      </div>
    </Modal>
  );
}

/** What was decided on this flag, if a recorded decision addresses it. */
export function decidedOn(c: CompanyResult, f: Flag): { s?: Suggestion; booked: number; approver: string; at: string; how?: string } | null {
  const o = c.override;
  if (!o) return null;
  const addressesAll = o.rule_ids_addressed.length === 0;
  if (!addressesAll && !o.rule_ids_addressed.includes(f.rule_id)) return null;
  const key = o.source_suggestion?.startsWith(`${f.rule_id}/`) ? o.source_suggestion.slice(f.rule_id.length + 1) : null;
  const how = key === "manual" ? "Mark entered by the approver." : key === "proposed" ? "Proposed mark accepted." : key === "price" ? "Quarter-end price supplied." : undefined;
  return { s: key ? f.suggestions.find((s) => s.key === key) : undefined, booked: o.booked, approver: o.approver, at: o.created_at, how };
}

/** Who chose the recommendation, as a small label. */
function SourceChip({ rec }: { rec: Recommendation }) {
  if (rec.source === "claude") {
    return (
      <span className="chip chip-ai no-dot" title={`Drafted by ${rec.model ?? "Claude"} from the engine's priced options${rec.confidence !== null ? ` · confidence ${Math.round(rec.confidence * 100)}%` : ""}; editable before it is recorded`}>
        AI draft
      </span>
    );
  }
  return (
    <span className="chip disp-NONE no-dot" title={rec.note ?? "The rule's own default resolution"}>
      Policy suggestion
    </span>
  );
}

/** Who chose the position's one next step. An AI draft is labelled and editable; a policy
    suggestion is the rule's own default, which is what a run with no key falls back to. */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthLabel(k: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(k ?? "");
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : k;
}

function num_(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Which recorded alternative a suggestion's number *is*. Matching on the value, not on the
    option's key, is what keeps a derivation honest: it describes the figure actually shown. */
function altKind(c: CompanyResult, s: Suggestion): string | null {
  for (const [k, v] of Object.entries(c.alternative_marks ?? {})) {
    if (Math.abs(s.booked - v) < 5e-3) return k;
  }
  return null;
}

/** How the figure in front of the reviewer was arrived at — assembled only from numbers the run
    recorded. Null when nothing is on file: no derivation is better than an invented one. */
function calcBasis(c: CompanyResult, s: Suggestion): string | null {
  const alt = altKind(c, s);
  if (alt === "calibrated_to_comps") {
    const i = c.steps.find((x) => x.rule_id === "M-080")?.inputs;
    const then = num_(i?.comp_multiple_at_round);
    const now = num_(i?.comp_multiple_now);
    const raw = num_(i?.factor_raw);
    const bounded = num_(i?.factor_bounded);
    if (i === undefined || then === null || now === null || raw === null || bounded === null) return null;
    return (
      `${String(i.sector ?? "Sector")} comparables moved ${then.toFixed(1)}× in ${monthLabel(String(i.comp_month_used))} to ` +
      `${now.toFixed(1)}× at the measurement date, ${pct(raw - 1, 0, true)}` +
      (i.bound_hit ? `, held to ${pct(bounded - 1, 0, true)} by the policy limit` : "") +
      `. Applied to the $${musd(c.equity_mark)}M equity mark: $${musd(s.booked)}M.`
    );
  }
  if (alt === "structure_adjusted") {
    const h = num_(c.flags.find((f) => num_(f.evidence.structure_haircut_pct) !== null)?.evidence.structure_haircut_pct);
    return h === null ? null : `The policy's ${pct(h, 0)} junior-class haircut applied to the round price: $${musd(s.booked)}M.`;
  }
  if (s.key === "hold_prior") return `The prior mark, $${musd(c.prior_mark)}M, carried unchanged.`;
  if (s.key === "as_proposed" || s.key === "adopt_proposed") return `The engine's proposed mark, $${musd(c.proposed_mark)}M, unchanged.`;
  if (s.key === "to_cost" || s.key === "at_cost") return `Invested capital to date, $${musd(c.invested_after)}M.`;
  if (s.key === "write_to_zero") return "The position written to zero.";
  return null;
}

/** What a person has to check before this figure can be booked. A computed alternative is not a
    validated one, and the card must not read as though it were. */
function prerequisite(c: CompanyResult, s: Suggestion, covers: Flag[] = []): string {
  // A finding the step speaks to names its own precondition better than the option key can:
  // "confirm post-financing cash and monthly burn" is actionable, "confirm the inputs" is not.
  const byFinding: Record<string, string> = {
    "X-304": "Before approval: confirm post-financing cash and monthly burn.",
    "X-303": "Before approval: confirm post-financing cash and monthly burn.",
    "X-113": "Before approval: obtain the quarter-end closing price and its source.",
    "X-112": "Before approval: confirm the acquirer's share count, listing and lock-up terms.",
    "X-116": "Before approval: obtain a recovery estimate for the reorganisation.",
    "X-102": "Before approval: read the round documents and confirm the preference stack and pay-to-play.",
    "X-106": "Before approval: confirm nobody re-tested the price, and that the extension terms are as filed.",
    "X-119": "Before approval: reconcile HC's cheque against the stated post-money.",
    "X-123": "Before approval: confirm the mechanism that raised HC's stake without a cheque.",
    "X-134": "Before approval: confirm why the row carries a figure its event type does not use.",
    "X-900": "Before approval: correct the workbook row the data checks name, and rerun.",
  };
  for (const f of covers) {
    const line = byFinding[f.rule_id];
    if (line) return line;
  }
  const alt = altKind(c, s);
  if (alt === "calibrated_to_comps")
    return "Before approval: confirm the comparable companies, the underlying data, and the adjustment limit.";
  if (alt === "structure_adjusted")
    return "Before approval: confirm the preference stack, and that the policy haircut is the right stand-in for it.";
  switch (s.key) {
    case "hold_prior":
      return "Before approval: confirm the prior mark still holds at the measurement date.";
    case "as_proposed":
    case "adopt_proposed":
      return "Before approval: confirm the inputs the proposed mark rests on.";
    case "to_cost":
    case "at_cost":
      return "Before approval: confirm invested cost is a defensible floor for this position.";
    default:
      return "Before approval: confirm the inputs behind this figure.";
  }
}

/** The comparable set and the feed behind a calibrated figure, straight off the recorded step. */
function sourceRows(c: CompanyResult, s: Suggestion): [string, string][] {
  if (altKind(c, s) !== "calibrated_to_comps") return [];
  const i = c.steps.find((x) => x.rule_id === "M-080")?.inputs;
  if (!i) return [];
  const nThen = num_(i.n_constituents_at_round);
  const nNow = num_(i.n_constituents_now);
  const rows: [string, string][] = [["Comparable set", String(i.sector ?? "—")]];
  if (nNow !== null || nThen !== null) {
    rows.push(["Constituents", `${nNow ?? "—"} at the measurement date · ${nThen ?? "—"} in ${monthLabel(String(i.comp_month_used))}`]);
  }
  rows.push(["Feed", marketSourceLabel(typeof i.comps_source === "string" ? i.comps_source : null)]);
  const age = num_(i.age_months);
  if (age !== null) rows.push(["Price age", `${age} months since ${monthLabel(String(i.round_month))}`]);
  return rows;
}

function StepSource({ rec }: { rec: PositionRecommendation }) {
  if (rec.source === "claude") {
    return (
      <span
        className="chip chip-ai no-dot"
        title={`Drafted by ${rec.model ?? "Claude"} across every open finding on this position${
          rec.confidence !== null ? ` · confidence ${Math.round(rec.confidence * 100)}%` : ""
        }; the number comes from the engine's priced option, and the wording is editable before it is recorded`}
      >
        AI draft
      </span>
    );
  }
  return (
    <span className="chip disp-NONE no-dot" title={rec.note ?? "The first finding's own default resolution"}>
      Policy suggestion
    </span>
  );
}

/** One suggested next step for the whole position, not one per finding. The chooser weighed
    every open finding and picked which to act on first; the panel says which finding it leads
    with, what it settles, and keeps the reasoning and the other priced options one click away. */
export function PositionStep({
  c,
  writeDisabled,
  onChanged,
  apply = true,
}: {
  c: CompanyResult;
  writeDisabled: string | null;
  onChanged: () => void;
  apply?: boolean;
}) {
  const [pick, setPick] = useState<Choice | null>(null);
  const names = useFlagNames();
  const acts = orderedActionable(c);
  const rec = c.recommendation;
  const lead = rec ? acts.find((f) => f.rule_id === rec.rule_id) : acts[0];
  const decided = lead ? decidedOn(c, lead) : null;
  if (!lead) return null;
  const chosen = (rec && lead.suggestions.find((s) => s.key === rec.key)) ?? lead.suggestions[0];
  if (!chosen) return null;
  const delta = chosen.booked - c.proposed_mark;
  const price = needsClosingPrice(c, lead);
  const asOf = lead.evidence.measurement_date ? String(lead.evidence.measurement_date) : "quarter-end";
  // One row per distinct resolution. The same option raised on two findings — "keep the mark as
  // proposed" on both — is one thing a reviewer can do, not two, and listing it twice (and again
  // alongside the recommended one) was reading as three choices where there were two.
  const seenOption = new Set<string>([`${chosen.key}|${chosen.booked.toFixed(4)}`]);
  const others = acts
    .flatMap((f) => f.suggestions.map((s) => ({ f, s })))
    .filter(({ s }) => {
      const k = `${s.key}|${s.booked.toFixed(4)}`;
      if (seenOption.has(k)) return false;
      seenOption.add(k);
      return true;
    });
  const coveredFlags = (rec ? rec.covers : [lead.rule_id])
    .map((id) => acts.find((f) => f.rule_id === id))
    .filter((f): f is Flag => f !== undefined);
  const covered = coveredFlags.map((f) => flagName(f, names));
  const stillOpen = acts.length - covered.length;

  if (decided) {
    return (
      <div className="decided">
        <div className="flex items-center gap-2">
          <span className="chip disp-CLEAR">Decision recorded</span>
          <span className="text-[12.5px] font-semibold leading-snug">{decided.s?.label ?? decided.how ?? "Decision recorded."}</span>
        </div>
        <div className="text-[11.5px] text-muted mt-1">
          Recorded $<span className="num text-ink2">{musd(decided.booked)}</span>M · {decided.approver} · {isoDate(decided.at)}
        </div>
      </div>
    );
  }

  const basis = price ? null : calcBasis(c, chosen);
  const sources = price ? [] : sourceRows(c, chosen);
  const reasons = price
    ? [`A listed security is worth its ${shortDate(asOf)} close (Level 1, ASC 820); no quote is on file, so the number shown is the listing-day cap standing in.`, ...(rec ? rec.reasons : chosen.reasons)]
    : rec
      ? rec.reasons
      : chosen.reasons;
  // Two supporting lines, no more: what happened and why it matters. How the number was arrived at
  // is a working, not a reason, and lives under Sources & calculation with the rest of the
  // provenance. The stand-in case prepends its own line, so it is left unlabelled.
  const POINT_KEYS = price ? [] : ["What happened", "Why it matters"];
  const shownReasons = reasons.slice(0, price ? 3 : 2);

  return (
    <div className="step">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="step-head num">
          {price ? "Stand-in mark" : "Recommended mark"} ${musd(chosen.booked)}M
        </span>
        <span className={`text-[11.5px] num ${price ? "text-muted" : signClass(delta)}`}>
          {price
            ? "not bookable until priced"
            : Math.abs(delta) < 5e-3
              ? "as proposed"
              : `${delta > 0 ? "+" : "−"}$${musd(Math.abs(delta))}M from the proposed $${musd(c.proposed_mark)}M`}
        </span>
        {rec ? <span className="ml-auto">{<StepSource rec={rec} />}</span> : null}
      </div>

      <p className="step-say m-0">
        {price
          ? `Add the ${shortDate(asOf)} closing price and recalculate; until it is on file the listing-day stand-in holds.`
          : rec
            ? <Rich text={rec.label} />
            : <Rich text={chosen.label} />}
      </p>

      {covered.length > 0 && (
        <p className="step-addresses m-0">
          Addresses: {covered.join(" · ")}
          {stillOpen > 0 && ` · ${stillOpen} further finding${stillOpen === 1 ? "" : "s"} not addressed by this step`}
        </p>
      )}

      <ul className="step-points">
        {shownReasons.map((x, i) => (
          <li key={i}>
            {POINT_KEYS[i] ? <span className="step-point-k">{POINT_KEYS[i]} — </span> : null}
            <Rich text={x} />
          </li>
        ))}
      </ul>

      <p className="step-before m-0">
        {price
          ? "Before approval: obtain the quarter-end closing price and its source. A stand-in mark cannot be booked."
          : prerequisite(c, chosen, coveredFlags)}
      </p>

      <div className="step-more">
        {(basis || sources.length > 0 || rec?.rationale || rec?.note) && (
          <details className="step-why">
            <summary>Sources &amp; calculation</summary>
            <div className="step-why-body">
              {basis && (
                <div>
                  <div className="step-sub">How this figure was calculated</div>
                  <p className="m-0 mt-1 text-[11.5px] leading-[1.55] text-ink2">{basis}</p>
                </div>
              )}
              {sources.length > 0 && (
                <dl className="step-src">
                  {sources.map(([k, v]) => (
                    <Fragment key={k}>
                      <dt>{k}</dt>
                      <dd className="num">{v}</dd>
                    </Fragment>
                  ))}
                </dl>
              )}
              {rec?.rationale && (
                <div>
                  <div className="step-sub">Methodology</div>
                  <p className="suggest-rationale m-0 mt-1"><Rich text={rec.rationale} /></p>
                </div>
              )}
              {rec?.note && <p className="suggest-rationale m-0">{rec.note}</p>}
            </div>
          </details>
        )}
        {others.length > 0 && (
          <details className="step-why">
            <summary>Other approaches ({others.length})</summary>
            <div className="step-why-body">
              {others.map(({ f, s }) => {
                const d = s.booked - c.proposed_mark;
                return (
                  <div key={`${f.rule_id}/${s.key}`} className="step-other">
                    <span className="text-[11.5px] font-normal leading-snug">{s.label}</span>
                    <span className="num text-[11.5px] whitespace-nowrap">
                      ${musd(s.booked)}M <span className={`text-[10.5px] ${signClass(d)}`}>({signed(d)})</span>
                    </span>
                    <WriteButton disabledReason={writeDisabled} className="btn btn-ghost text-[11px]" onClick={() => setPick({ kind: "option", s })}>
                      {optionVerb(s)}
                    </WriteButton>
                    <span className="step-other-answers">Answers: {flagName(f, names)}</span>
                  </div>
                );
              })}
            </div>
          </details>
        )}
      </div>

      {apply && !price && (
        <div>
          <WriteButton
            disabledReason={writeDisabled}
            className="btn btn-ghost text-[11px]"
            onClick={() => setPick(rec ? { kind: "step", s: chosen, rec } : { kind: "option", s: chosen })}
          >
            {optionVerb(chosen)}
          </WriteButton>
        </div>
      )}
      {pick && (
        <ConfirmModal
          c={c}
          f={pick.kind === "option" ? acts.find((x) => x.suggestions.some((s) => s.key === (pick as { s: Suggestion }).s.key)) ?? lead : lead}
          choice={pick}
          onClose={() => setPick(null)}
          onDone={() => {
            setPick(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

/** The card's bottom bar: one primary action that addresses the blocker, Override as the
    secondary route whose input appears only when asked for, and nothing else. The primary is
    "Add closing price" when that is what is missing, otherwise the suggested step itself. */
export function DecisionBar({
  c,
  f,
  writeDisabled,
  onChanged,
  children,
}: {
  c: CompanyResult;
  f: Flag;
  writeDisabled: string | null;
  onChanged: () => void;
  children?: ReactNode;
}) {
  const [pick, setPick] = useState<Choice | null>(null);
  const [pricing, setPricing] = useState(false);
  const [overriding, setOverriding] = useState(false);
  const [text, setText] = useState("");
  // the bar applies the position's one step, so the button and the panel beside it agree
  const rec = c.recommendation;
  const acts = orderedActionable(c);
  const lead = (rec ? acts.find((x) => x.rule_id === rec.rule_id) : undefined) ?? f;
  const chosen = (rec && lead.suggestions.find((x) => x.key === rec.key)) ?? lead.suggestions[0];
  const decided = decidedOn(c, lead);
  const price = needsClosingPrice(c, lead);
  const value = Number(text.replace(/,/g, ""));
  const ok = text.trim() !== "" && Number.isFinite(value) && value >= 0;
  const done = () => {
    setPick(null);
    setOverriding(false);
    setText("");
    onChanged();
  };
  return (
    <div className="decision-bar">
      <div className="decision-actions">
        {decided ? (
          <WriteButton disabledReason={writeDisabled} className="btn" onClick={() => setOverriding((v) => !v)}>
            Change decision
          </WriteButton>
        ) : price ? (
          <WriteButton disabledReason={writeDisabled} className="btn btn-primary" onClick={() => setPricing(true)} title="Enter the quarter-end market cap or price and its source">
            Add closing price
          </WriteButton>
        ) : chosen ? (
          <WriteButton
            disabledReason={writeDisabled}
            className="btn btn-primary"
            onClick={() => setPick(rec ? { kind: "step", s: chosen, rec } : { kind: "option", s: chosen })}
            title={rec ? rec.label : chosen.label}
          >
            {/* one text node: .btn is a flex row with a gap, so a nested <span> around the
                number would space it out as "$ 13.93 M" */}
            {`${optionVerb(chosen)} · $${musd(chosen.booked)}M`}
          </WriteButton>
        ) : null}
        {!decided && (
          <WriteButton
            disabledReason={writeDisabled}
            className={`btn ${overriding ? "" : "btn-ghost"}`}
            onClick={() => setOverriding((v) => !v)}
            title="Record a different number under your name; the reason is required and the ledger says the input was still missing"
          >
            Override
          </WriteButton>
        )}
        {overriding && (
          <form
            className="override-entry"
            onSubmit={(e) => {
              e.preventDefault();
              if (ok) setPick({ kind: "manual", booked: Math.round(value * 1e6) / 1e6 });
            }}
          >
            <span className="text-[11px] text-muted">$M</span>
            <input className="input decide-input num" inputMode="decimal" placeholder={musd(c.proposed_mark)} value={text} onChange={(e) => setText(e.target.value)} autoFocus aria-label="Mark to record, in $M" />
            <button type="submit" className="btn decide-confirm" disabled={!ok}>
              Confirm
            </button>
            <button type="button" className="btn btn-ghost text-[11px]" onClick={() => setPick({ kind: "proposed" })} title={`Record the proposal of $${musd(c.proposed_mark)}M as it stands`}>
              Accept the proposed mark instead
            </button>
          </form>
        )}
      </div>
      <div className="decision-more">{children}</div>
      {pricing && (
        <ClosingPriceModal
          c={c}
          f={lead}
          onClose={() => setPricing(false)}
          onContinue={(ch) => {
            setPricing(false);
            setPick(ch);
          }}
        />
      )}
      {pick && (
        <ConfirmModal
          c={c}
          f={lead}
          choice={pick}
          onClose={() => {
            setPick(null);
            setOverriding(false);
          }}
          onDone={done}
        />
      )}
    </div>
  );
}

/** MONITOR findings in a reviewer's words: what each one means, then the engine's sentence.
    A watch item rendered as a card competes with the findings that actually need a person,
    which is how a queue stops being read; a line each is enough. */
export function FlagNoteList({ flags }: { flags: Flag[] }) {
  const names = useFlagNames();
  if (flags.length === 0) return null;
  return (
    <ul className="note-list">
      {flags.map((f, i) => (
        <li key={i} className="note-row">
          <span className="note-family">{flagName(f, names)}</span>
          <span className="note-text">{plainPoint(f.message)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Every finding a reviewer must act on, two columns each: why it was flagged on the left,
    the suggested next step on the right; stacked on a narrow screen. Rule codes and the
    long form live behind Evidence, not in the row. `primaryFor` names the finding whose
    action the card's bottom bar carries, so its column shows no second button. */
export function FlagActionList({
  c,
  flags,
  writeDisabled,
  onChanged,
  covered,
}: {
  c: CompanyResult;
  flags: Flag[];
  writeDisabled: string | null;
  onChanged: () => void;
  /** rule ids the position's one suggested step settles — marked, so a reviewer can see at a
      glance which findings the step in the next panel leaves open. */
  covered?: string[];
}) {
  const [detail, setDetail] = useState<number | null>(null);
  const names = useFlagNames();
  void writeDisabled;
  void onChanged;
  return (
    <>
      <div className="eyebrow-sm">
        {flags.length > 1 ? `The ${flags.length} findings` : "The finding"}
      </div>
      <ol className="finding-list">
        {flags.map((f, i) => (
          <li key={i} className="finding">
            <span className="finding-n" aria-hidden>
              {i + 1}
            </span>
            <div className="finding-body">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-[12.5px] font-semibold leading-snug">{flagName(f, names)}</span>
                {f.severity === "BLOCK" && (
                  <span className="chip disp-BLOCK no-dot" style={{ fontSize: 10 }}>
                    Blocks approval
                  </span>
                )}
                {flags.length > 1 && covered?.includes(f.rule_id) && (
                  <span
                    className="chip disp-MONITOR no-dot"
                    style={{ fontSize: 10 }}
                    title="The suggested next step speaks to this finding. A suggestion is a proposal, not a resolution — nothing is settled until a decision is recorded, and a missing input has to arrive first."
                  >
                    {pendingLabel(f)}
                  </span>
                )}
              </div>
              <FlagPoints f={f} plain limit={3} className="mt-1" />
              {unverifiedNote(f) && <p className="finding-unverified m-0 mt-1">{unverifiedNote(f)}</p>}
              <button
                className="btn btn-ghost mt-1 text-[11px]"
                onClick={() => setDetail(i)}
                aria-haspopup="dialog"
                title={`Read ${f.rule_id} in full, with the inputs behind it`}
              >
                Evidence
              </button>
            </div>
          </li>
        ))}
      </ol>
      {detail !== null && flags[detail] && (
        <FlagDetailModal f={flags[detail]} company={c.company} onClose={() => setDetail(null)} />
      )}
    </>
  );
}
