import { Fragment, useState } from "react";
import type { CompanyResult, MarkStep } from "../types";
import { altLabel, isoDate, KIND_LABEL, musd, shortSha, signed, signClass } from "../lib/format";
import { postOverride } from "../lib/api";
import { eventRowRef, inputRef, portfolioRowRef, useSources } from "../lib/sources";
import { CopyRef, DispChip, Field, KV, Label, MarkTriple, Modal, WriteButton } from "./ui";

const nf = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

/** Step inputs are heterogeneous: numbers, dates, provider strings, booleans. */
function inputValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? nf.format(v) + ".0" : nf.format(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** Every input the rule read, with the workbook cell behind it where one exists. */
function StepInputs({ s, company }: { s: MarkStep; company: string }) {
  const sources = useSources();
  const entries = Object.entries(s.inputs);
  if (entries.length === 0) return null;
  const eventRow = s.evidence?.row_index ?? null;
  return (
    <div className="inputs mt-1.5">
      {entries.map(([k, v]) => {
        const cell = inputRef(sources, k, company, eventRow);
        return (
          <Fragment key={k}>
            <span className="mono text-[11px] text-muted">{k}</span>
            <span className="num text-[11.5px] text-right">{inputValue(v)}</span>
            {!sources ? (
              <span />
            ) : cell ? (
              <CopyRef text={cell.ref} title={`Copy ${cell.ref} — ${cell.column}`} />
            ) : (
              <span className="text-[10.5px] text-muted italic">computed</span>
            )}
          </Fragment>
        );
      })}
    </div>
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
              {s.evidence.event_type} · {isoDate(s.evidence.date)}
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
    <div className="card p-3">
      <Label>Source</Label>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] font-medium">{wb.name}</span>
        <CopyRef text={wb.path} label="copy path" mono={false} title={wb.path} />
      </div>
      <div className="mono text-[10.5px] text-muted mt-1">sha256 {shortSha(wb.sha256, 12)}</div>
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
                {e.event_type} · {isoDate(e.date)}
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
  const valid = approver.trim() && reason.trim() && Number.isFinite(parseFloat(booked));
  return (
    <Modal title={`Override · ${c.company}`} onClose={onClose}>
      <p className="text-[12px] text-ink2 mb-3">
        Records an E-01 override. The engine's proposed mark ({musd(c.proposed_mark)}) is never changed; the booked mark
        is replaced and the decision is written to the ledger with your name.
      </p>
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
              await postOverride({ company: c.company, booked: parseFloat(booked), approver, reason });
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

export function CompanyDetail({
  c,
  writeDisabled,
  onChanged,
}: {
  c: CompanyResult;
  writeDisabled: string | null;
  onChanged: () => void;
}) {
  const [override, setOverride] = useState(false);
  const canOverride = c.disposition === "BLOCK" || c.disposition === "REVIEW";
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-6 p-4 whitespace-normal">
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold">Audit chain</h3>
          <span className="text-[11px] text-muted">
            proposed = last step · {c.steps.length} step{c.steps.length === 1 ? "" : "s"}
          </span>
        </div>
        <ol className="mt-2">
          {c.steps.map((s, i) => (
            <StepRow key={s.sequence} s={s} last={i === c.steps.length - 1} company={c.company} />
          ))}
        </ol>

        <h3 className="font-semibold mt-3 mb-2">Flags</h3>
        {c.flags.length === 0 ? (
          <p className="text-muted">No exception flags.</p>
        ) : (
          <ul className="space-y-2">
            {c.flags.map((f, i) => (
              <li key={i} className={`disp-${f.severity} stripe card p-2 pl-3`}>
                <div className="flex items-center gap-2">
                  <DispChip d={f.severity} />
                  <span className="mono font-medium">{f.rule_id}</span>
                  <span className="text-[11px] text-muted">{f.family}</span>
                </div>
                {f.action && <p className="mt-1 text-[13px] font-semibold leading-snug">{f.action}</p>}
                <p className="mt-1 text-ink2 leading-snug">{f.message}</p>
                {typeof f.evidence.price_source_note === "string" && (
                  <p className="mt-1 text-[11.5px] text-muted italic leading-snug">{f.evidence.price_source_note}</p>
                )}
                {Object.keys(f.evidence).length > 0 && (
                  <details className="mt-1">
                    <summary className="text-[11px] text-accent">evidence</summary>
                    <pre className="json mt-1">{JSON.stringify(f.evidence, null, 2)}</pre>
                  </details>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <aside className="space-y-4">
        <SourceCard c={c} />

        <div className="card p-3">
          <Label>Mark</Label>
          <MarkTriple prior={c.prior_mark} proposed={c.proposed_mark} booked={c.booked_mark} />
          <div className="mt-2 text-[12px]">
            <KV k="Equity mark" v={musd(c.equity_mark)} />
            <KV k="Note at cost" v={musd(c.note_at_cost)} />
            <KV k="Latest post-money" v={musd(c.latest_post_money)} />
            <KV k="Staleness anchor" v={isoDate(c.staleness_anchor)} mono />
            <KV k="FV level" v={c.fv_level === null ? "—" : `Level ${c.fv_level}`} />
            <KV k="Status" v={`${c.status_before} → ${c.status_after}`} />
            <KV k="MOIC" v={c.moic_after === null ? "—" : `${musd(c.moic_after)}×`} />
          </div>
        </div>

        <div className="card p-3">
          <Label>Alternative marks</Label>
          {Object.keys(c.alternative_marks).length === 0 ? (
            <p className="text-muted text-[12px]">None recorded for this position.</p>
          ) : (
            <div className="text-[12px]">
              {Object.entries(c.alternative_marks).map(([k, v]) => (
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
          )}
        </div>

        <div className="card p-3">
          <Label>Open items</Label>
          {c.open_items.length === 0 ? (
            <p className="text-muted text-[12px]">None.</p>
          ) : (
            <ul className="text-[12px] space-y-1">
              {c.open_items.map((o, i) => (
                <li key={i}>
                  <span className="font-medium">{KIND_LABEL[o.kind] ?? o.kind}</span>
                  <span className="text-muted"> · opened {isoDate(o.opened)}</span>
                  {o.expected_resolution && <span className="text-muted"> · expected {isoDate(o.expected_resolution)}</span>}
                  {o.escalated && <span className="chip disp-REVIEW ml-1">escalated</span>}
                  <div className="text-ink2">{o.detail}</div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-3">
          <div className="flex items-center justify-between">
            <Label>Override (E-01)</Label>
            {canOverride && (
              <WriteButton disabledReason={writeDisabled} className="btn" onClick={() => setOverride(true)}>
                Override
              </WriteButton>
            )}
          </div>
          {c.override ? (
            <div className="text-[12px]">
              <KV k="Booked" v={musd(c.override.booked)} />
              <KV k="Proposed" v={musd(c.override.proposed)} />
              <KV k="Approver" v={c.override.approver} />
              <KV k="Recorded" v={isoDate(c.override.created_at)} mono />
              {c.override.rule_ids_addressed.length > 0 && (
                <KV k="Addresses" v={<span className="mono">{c.override.rule_ids_addressed.join(", ")}</span>} />
              )}
              {c.override.source_proposal && <KV k="From proposal" v={<span className="mono">{c.override.source_proposal}</span>} />}
              <p className="mt-1 text-ink2">{c.override.reason}</p>
            </div>
          ) : (
            <p className="text-muted text-[12px]">
              {canOverride ? "No override recorded; booked = proposed." : "Not applicable: only BLOCK and REVIEW positions take an override."}
            </p>
          )}
        </div>
      </aside>

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
