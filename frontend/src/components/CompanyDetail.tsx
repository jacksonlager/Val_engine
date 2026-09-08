import { Fragment, useState, type ReactNode } from "react";
import { READINESS_HINT, type CompanyResult, type MarkStep } from "../types";
import { isoDate, musd, pct, signed, signClass } from "../lib/format";
import { altLabel, evidenceLabel, evidenceValue, humanize, kindLabel, readinessClass, severityShort, shortRef } from "../lib/labels";
import { postOverride } from "../lib/api";
import { eventRowRef, inputRef, portfolioRowRef, useSources } from "../lib/sources";
import { flagName, FlagActionList, FlagDetailModal, FlagNoteList, useFlagNames } from "./Flags";
import { MarkHistoryCard } from "./MarkHistoryChart";
import { FlagHistoryCard, PriorFlagPill } from "./FlagHistory";
import { VendorSignalsCard } from "./VendorSignals";
import { CopyRef, Field, KV, Label, Modal, WriteButton, ReadinessChip } from "./ui";

const nf = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

/** Step inputs are heterogeneous: numbers, dates, provider strings, booleans. Numbers keep the
    engine's precision; everything else goes through the display vocabulary, so a policy token
    (`last_round`) and a flag (`true`) arrive as words. The raw key stays in the row's tooltip. */
function inputValue(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? nf.format(v) + ".0" : nf.format(v);
  if (v !== null && typeof v === "object") return JSON.stringify(v);
  return evidenceValue(v);
}

/** Every input the rule read, with the workbook cell behind it where one exists. */
function StepInputs({ s, company }: { s: MarkStep; company: string }) {
  const sources = useSources();
  const entries = Object.entries(s.inputs);
  if (entries.length === 0) return null;
  const eventRow = s.evidence?.row_index ?? null;
  // The rule's arithmetic, one row per input with the workbook cell behind it. Folded away by
  // default: the rationale above is what a reviewer reads, this is what an auditor opens.
  return (
    <details className="step-io mt-1.5">
      <summary>
        {entries.length} input{entries.length === 1 ? "" : "s"} and their cells
      </summary>
    <div className="inputs mt-1.5">
      {entries.map(([k, v]) => {
        const cell = inputRef(sources, k, company, eventRow);
        return (
          <Fragment key={k}>
            <span className="text-[11px] text-muted" title={k}>
              {evidenceLabel(k)}
            </span>
            <span className="num text-[11.5px] text-right">{inputValue(v)}</span>
            {!sources ? (
              <span />
            ) : cell ? (
              <CopyRef text={cell.ref} title={`Copy ${cell.ref} — ${cell.column}`} />
            ) : sources.derived_inputs?.[k] ? (
              <span className="text-[10.5px] text-muted italic" title={sources.derived_inputs[k]}>
                {sources.derived_inputs[k].split(":")[0]}
              </span>
            ) : (
              <span className="text-[10.5px] text-muted italic">computed</span>
            )}
          </Fragment>
        );
      })}
    </div>
    </details>
  );
}

function StepRow({ s, last, company }: { s: MarkStep; last: boolean; company: string }) {
  const d = s.new_value - s.prior_value;
  const sources = useSources();
  const rowRef = s.evidence ? eventRowRef(sources, s.evidence.row_index) : null;
  return (
    <li className="relative pl-7 pb-3">
      {/* vertical connector */}
      {!last && <span className="absolute left-[9px] top-5 bottom-0 w-px bg-line" aria-hidden />}
      <span className="absolute left-0 top-0.5 w-[19px] h-[19px] rounded-full border border-line bg-raised text-[10px] mono flex items-center justify-center">
        {s.sequence}
      </span>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="mono font-medium">{s.rule_id}</span>
        <span className="mono text-[10px] text-muted">v{s.rule_version}</span>
        <span className="num">
          {musd(s.prior_value)} <span className="text-muted">→</span> {musd(s.new_value)}
          {Math.abs(d) > 1e-6 && <span className={`ml-2 ${signClass(d)}`}>({signed(d)})</span>}
        </span>
        {s.evidence && (
          <span className="flex items-baseline gap-1.5 text-[11px] text-muted">
            {rowRef ? <CopyRef text={rowRef} /> : <span className="mono">{s.evidence.sheet} row {s.evidence.row_index}</span>}
            <span>
              {humanize(s.evidence.event_type)} · {isoDate(s.evidence.date)}
            </span>
          </span>
        )}
      </div>
      <p className="text-ink2 mt-0.5 leading-snug whitespace-normal">{s.rationale}</p>
      <StepInputs s={s} company={company} />
    </li>
  );
}

/** Where this company's numbers were read from, down to the row. */
function SourceCard({ c }: { c: CompanyResult }) {
  const sources = useSources();
  if (!sources) return null;
  const wb = sources.workbook;
  const posRef = portfolioRowRef(sources, c.company);
  const events = sources.companies?.[c.company]?.events ?? [];
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] font-medium">{wb.name}</span>
        <CopyRef text={wb.path} label="copy path" mono={false} title={wb.path} />
      </div>
      <div className="text-[10.5px] text-muted mt-1" title="SHA-256 of the workbook this run read — it identifies the exact file, byte for byte">
        File fingerprint <span className="mono">{shortRef(wb.sha256, 12)}</span>
      </div>
      <div className="mt-2 flex flex-col gap-1.5">
        {posRef && (
          <div className="flex items-baseline gap-2">
            <CopyRef text={posRef} />
            <span className="text-[11px] text-muted">position row</span>
          </div>
        )}
        {events.map((e, i) => {
          const ref = eventRowRef(sources, e.row);
          return (
            <div key={i} className="flex items-baseline gap-2">
              {ref && <CopyRef text={ref} />}
              <span className="text-[11px] text-muted">
                {humanize(e.event_type)} · {isoDate(e.date)}
              </span>
            </div>
          );
        })}
        {!posRef && events.length === 0 && <span className="text-[11px] text-muted">No workbook rows recorded.</span>}
      </div>
      <p className="text-[11px] text-muted mt-2 leading-snug">
        Paste a reference into Excel's Name Box to jump to the cell; paste the path into File → Open.
      </p>
    </div>
  );
}

export function OverrideModal({
  c,
  onClose,
  onDone,
}: {
  c: CompanyResult;
  onClose: () => void;
  onDone: () => void;
}) {
  const [booked, setBooked] = useState(String(c.proposed_mark));
  const [approver, setApprover] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // A decision names what it decides: every open BLOCK / REVIEW is ticked by default, MONITOR
  // items are offered unticked. The API refuses an override on a flagged position that names nothing.
  const [addressed, setAddressed] = useState<Set<string>>(
    () => new Set(c.flags.filter((f) => f.severity !== "MONITOR").map((f) => f.rule_id)),
  );
  const toggle = (id: string) =>
    setAddressed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const names = useFlagNames();
  const needsRules = c.flags.length > 0;
  const valid = approver.trim() && reason.trim() && Number.isFinite(parseFloat(booked)) && (!needsRules || addressed.size > 0);
  return (
    <Modal title={`Override · ${c.company}`} onClose={onClose}>
      <p className="text-[12px] text-ink2 mb-3">
        Records the committee's decision. The engine's proposed mark ({musd(c.proposed_mark)}) is never changed; the booked mark
        is replaced and the decision is written to the ledger with your name.
      </p>
      {needsRules && (
        <Field label="What this decision settles">
          <div className="flex flex-col gap-1 mb-1">
            {c.flags.map((f) => (
              <label key={f.rule_id} className="flex items-baseline gap-2 text-[12px] cursor-pointer">
                <input type="checkbox" checked={addressed.has(f.rule_id)} onChange={() => toggle(f.rule_id)} />
                <span className="text-ink2 truncate">{flagName(f, names)}</span>
                <span className="text-muted">{severityShort(f.severity)}</span>
                {/* the code stays on the row: it is what the ledger records against this decision */}
                <span className="mono text-[10.5px] text-muted ml-auto">{f.rule_id}</span>
              </label>
            ))}
          </div>
          {addressed.size === 0 && (
            <div className="text-[11px] down">Tick at least one finding — a decision must say what it settles.</div>
          )}
        </Field>
      )}
      <Field label="Booked mark ($M)">
        <input className="input mono w-full" value={booked} onChange={(e) => setBooked(e.target.value)} />
      </Field>
      {Object.keys(c.alternative_marks).length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3 -mt-1">
          {Object.entries(c.alternative_marks).map(([k, v]) => (
            <button key={k} className="btn btn-ghost text-[11px]" onClick={() => setBooked(String(v))}>
              {altLabel(k)} <span className="mono">{musd(v)}</span>
            </button>
          ))}
        </div>
      )}
      <Field label="Approver">
        <input className="input w-full" value={approver} onChange={(e) => setApprover(e.target.value)} />
      </Field>
      <Field label="Reason">
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
                booked: parseFloat(booked),
                approver: approver.trim(),
                reason: reason.trim(),
                rule_ids_addressed: Array.from(addressed),
              });
              onDone();
            } catch (e) {
              setErr(String((e as Error).message ?? e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Saving…" : "Record override"}
        </button>
      </div>
    </Modal>
  );
}

/** A compact fact, label over value, for the Position card. */
function Fact({ k, v, mono = false }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="fact">
      <div className="fact-k">{k}</div>
      <div className={`fact-v ${mono ? "mono" : "num"}`}>{v}</div>
    </div>
  );
}

/** Prior → proposed → booked, the change, and what the disposition asks of the reader.
    Shown in the Companies view; the queue card already carries these in its header. */
function DecisionStrip({ c }: { c: CompanyResult }) {
  const d = c.proposed_mark - c.prior_mark;
  const overridden = Math.abs(c.booked_mark - c.proposed_mark) > 1e-6;
  return (
    <div className={`dstrip ${readinessClass(c.readiness)}`}>
      <dl className="qmarks">
        <div>
          <dt>Prior</dt>
          <dd className="text-ink2">{musd(c.prior_mark)}</dd>
        </div>
        <span className="qarrow" aria-hidden>→</span>
        <div>
          <dt>Proposed</dt>
          <dd>{musd(c.proposed_mark)}</dd>
        </div>
        <span className="qarrow" aria-hidden>→</span>
        <div>
          <dt>Booked</dt>
          <dd className={overridden ? "overridden" : ""}>{musd(c.booked_mark)}</dd>
        </div>
        <div className="qdelta">
          <dt>Change</dt>
          <dd className={signClass(d)}>
            {signed(d)} <span className="font-normal">({pct(c.prior_mark ? d / c.prior_mark : null, 1, true)})</span>
          </dd>
        </div>
        <span className="qunit">$M</span>
      </dl>
      <div className="dstrip-disp">
        <ReadinessChip r={c.readiness} />
        <PriorFlagPill c={c} />
        <span className="text-[12px] text-ink2">{READINESS_HINT[c.readiness]}</span>
      </div>
    </div>
  );
}

export function CompanyDetail({
  c,
  writeDisabled,
  onChanged,
  showMarks = true,
  showFlags = true,
}: {
  c: CompanyResult;
  writeDisabled: string | null;
  onChanged: () => void;
  /** false inside the queue card, whose header already shows the marks */
  showMarks?: boolean;
  /** false inside the queue card, which already lists every flag with its suggestions;
      the chain and the committee decision still render */
  showFlags?: boolean;
}) {
  const [override, setOverride] = useState(false);
  const [flagDetail, setFlagDetail] = useState<number | null>(null);
  const canOverride = c.disposition === "BLOCK" || c.disposition === "REVIEW";
  const actions = c.flags.filter((f) => f.severity !== "MONITOR");
  const notes = c.flags.filter((f) => f.severity === "MONITOR");
  const alts = Object.entries(c.alternative_marks);
  return (
    <div className="p-3 whitespace-normal">
      {showMarks && <DecisionStrip c={c} />}
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-x-5 gap-y-4 mt-3">
        {/* ------------------------------------------------ what moved and why, then the decision */}
        <section className="min-w-0">
          <div className="flex items-baseline justify-between mb-1.5">
            <h3 className="font-semibold">What moved and why</h3>
            <span className="text-[11px] text-muted">
              {c.steps.length} step{c.steps.length === 1 ? "" : "s"} · the proposed mark is the last one
            </span>
          </div>
          <ol className="mt-1">
            {c.steps.map((s, i) => (
              <StepRow key={s.sequence} s={s} last={i === c.steps.length - 1} company={c.company} />
            ))}
          </ol>

          <div className="flex items-baseline justify-between mt-3 mb-1.5">
            <h3 className="font-semibold">{showFlags && actions.length > 0 ? "What to decide" : "Decision"}</h3>
            {showFlags && c.flags.length > 0 && (
              <span className="text-[11px] text-muted">
                {actions.length} to act on · {notes.length} noted
              </span>
            )}
          </div>
          {!showFlags ? null : c.flags.length === 0 ? (
            <p className="text-muted text-[12px]">No exception flags — nothing for a reviewer to decide.</p>
          ) : (
            <>
              {/* disp-* so the rule between two decisions picks up the disposition's hue */}
              {actions.length > 0 && (
                <div className={`card p-3 disp-${c.disposition}`}>
                  <FlagActionList c={c} flags={actions} writeDisabled={writeDisabled} onChanged={onChanged} />
                </div>
              )}
              {notes.length > 0 && (
                <div className="mt-2">
                  <div className="eyebrow-sm">Also noted, nothing to decide</div>
                  <FlagNoteList flags={notes} />
                </div>
              )}
            </>
          )}

          {/* the recorded decision, or the door to a custom one */}
          <div className="card p-2.5 mt-2 flex flex-wrap items-start gap-x-4 gap-y-1.5">
            <div className="min-w-0 flex-1 text-[12px]">
              <Label>
                <span title="Rule E-01 — a decision recorded against the engine's proposed mark">Committee decision</span>
              </Label>
              {c.override ? (
                <>
                  <div>
                    <span className="num font-semibold">{musd(c.override.booked)}</span>
                    <span className="text-muted"> booked against </span>
                    <span className="num">{musd(c.override.proposed)}</span>
                    <span className="text-muted"> proposed · {c.override.approver} · </span>
                    <span className="mono">{isoDate(c.override.created_at)}</span>
                    {c.override.rule_ids_addressed.length > 0 && (
                      <span className="text-muted">
                        {" "}· addresses <span className="mono">{c.override.rule_ids_addressed.join(", ")}</span>
                      </span>
                    )}
                  </div>
                  <p className="text-ink2 mt-0.5 leading-snug">{c.override.reason}</p>
                </>
              ) : (
                <p className="text-muted">
                  {canOverride
                    ? "None recorded, so the booked mark is the proposed mark. Accept a suggestion above, or record a custom figure."
                    : "Not needed: only blocking positions, and those needing a review, take a decision."}
                </p>
              )}
            </div>
            {canOverride && (
              <WriteButton disabledReason={writeDisabled} className="btn" onClick={() => setOverride(true)}>
                {c.override ? "Change" : "Custom override"}
              </WriteButton>
            )}
          </div>
        </section>

        {/* ------------------------------------------------ what this position has been, beside the story.
            Only the two histories ride here: a rail much taller than the story leaves a hole beside it,
            and a rail much shorter leaves one beside the flags. It sticks so a long flag list still has
            the prior-quarter context in view. Everything else is reference data and sits below. */}
        <aside className="min-w-0 space-y-3 xl:sticky xl:top-[76px] xl:self-start">
          <FlagHistoryCard c={c} />
          <MarkHistoryCard company={c.company} />
        </aside>
      </div>

      {/* ------------------------------------------------ reference, across the full width: the numbers
          behind the position, the vendor context, and the cells a workpaper cites. */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-x-5 gap-y-3 mt-4">
        <div className="min-w-0 space-y-3">
          <div className="card p-3">
            <Label>Position</Label>
            <div className="facts">
              <Fact k="Equity mark" v={musd(c.equity_mark)} />
              {/* facts that carry no information stay out of the grid */}
              {Math.abs(c.note_at_cost) > 1e-6 && <Fact k="Note at cost" v={musd(c.note_at_cost)} />}
              <Fact k="Latest post-money" v={musd(c.latest_post_money)} />
              <Fact
                k="Ownership"
                v={Math.abs(c.ownership_after - c.ownership_before) > 1e-6 ? `${pct(c.ownership_before)} → ${pct(c.ownership_after)}` : pct(c.ownership_after)}
              />
              <Fact k="Invested" v={musd(c.invested_after)} />
              {(Math.abs(c.realized_quarter) > 1e-6 || Math.abs(c.realized_cumulative) > 1e-6) && (
                <Fact k="Realized this quarter / to date" v={`${musd(c.realized_quarter)} / ${musd(c.realized_cumulative)}`} />
              )}
              <Fact k="MOIC" v={c.moic_after === null ? "—" : `${musd(c.moic_after)}×`} />
              <Fact k="Fair value level" v={c.fv_level === null ? "—" : `Level ${c.fv_level}`} />
              <Fact k="Status" v={c.status_before === c.status_after ? c.status_after : `${c.status_before} → ${c.status_after}`} />
              <Fact k="Priced from" v={isoDate(c.staleness_anchor)} mono />
            </div>

            {alts.length > 0 && (
              <>
                <Label>Alternative marks</Label>
                <div className="text-[12px] -mt-0.5 mb-2">
                  {alts.map(([k, v]) => (
                    <KV
                      key={k}
                      k={altLabel(k)}
                      v={
                        <>
                          {musd(v)}{" "}
                          <span className={`text-[11px] ${signClass(v - c.proposed_mark)}`}>({signed(v - c.proposed_mark)})</span>
                        </>
                      }
                    />
                  ))}
                </div>
              </>
            )}

            {c.open_items.length > 0 && (
              <>
                <Label>Open items</Label>
                <ul className="text-[12px] space-y-1">
                  {c.open_items.map((o, i) => (
                    <li key={i}>
                      <span className="font-medium">{kindLabel(o.kind)}</span>
                      <span className="text-muted"> · opened {isoDate(o.opened)}</span>
                      {o.expected_resolution && <span className="text-muted"> · expected {isoDate(o.expected_resolution)}</span>}
                      {o.escalated && <span className="chip disp-REVIEW ml-1">Escalated</span>}
                      <div className="text-ink2 leading-snug">{o.detail}</div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>

          <details className="card p-3">
            <summary className="text-[11px] uppercase tracking-wider text-muted cursor-pointer select-none">
              Source cells (for the workpaper)
            </summary>
            <div className="mt-2">
              <SourceCard c={c} />
            </div>
          </details>
        </div>

        <VendorSignalsCard company={c.company} />
      </div>

      {flagDetail !== null && c.flags[flagDetail] && (
        <FlagDetailModal f={c.flags[flagDetail]} company={c.company} onClose={() => setFlagDetail(null)} />
      )}

      {override && (
        <OverrideModal
          c={c}
          onClose={() => setOverride(false)}
          onDone={() => {
            setOverride(false);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
