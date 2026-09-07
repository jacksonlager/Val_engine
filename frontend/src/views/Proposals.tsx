import { useState } from "react";
import type { ProposalDecision, TreatmentProposal, ValuationRun } from "../types";
import { decideProposal, loadProposals, proposalId, type Mode } from "../lib/api";
import { musd, pct, shortDate } from "../lib/format";
import { evidenceLabel, humanize, parameterSource, proposalStatusLabel, proposedKindLabel, provenanceLabel } from "../lib/labels";
import { DispChip, Empty, Field, KV, Modal, useAsync, WriteButton } from "../components/ui";

type Action = "accept_once" | "promote" | "reject";

const BRIEFING_ROWS: [string, string][] = [
  ["what_happened", "What happened"],
  ["why_no_rule", "Why no rule covers it"],
  ["what_it_means", "What it means for the mark"],
  ["suggested_course", "Suggested course"],
  ["what_to_check", "What to check first"],
];

function draftedByClaude(p: TreatmentProposal): boolean {
  return Boolean(p.provenance?.model && String(p.provenance.model).startsWith("claude"));
}

export function ProposalsView({
  run,
  mode,
  writeDisabled,
  onChanged,
  gotoCompany,
}: {
  run: ValuationRun;
  mode: Mode;
  writeDisabled: string | null;
  onChanged: () => void;
  gotoCompany: (n: string) => void;
}) {
  const { data, error, loading, refetch } = useAsync(() => loadProposals(mode), [mode]);
  const [act, setAct] = useState<{ p: TreatmentProposal; a: Action } | null>(null);
  const byCompany = Object.fromEntries(run.companies.map((c) => [c.company, c]));

  if (loading && !data) return <div className="text-muted">Loading proposals…</div>;
  if (error) return <Empty>Could not load proposals: {error}</Empty>;
  const list = data ?? [];
  const m999 = run.companies.filter((c) => c.steps.some((s) => s.rule_id === "M-999"));

  return (
    <div className="space-y-4">
      <p className="text-[12px] text-ink2 max-w-[860px]">
        When an event matches no marking rule in the policy, the engine stops rather than guess: the position is blocked, and a
        suggested treatment is drafted beside it. The draft names the closest existing rule, the calculation it would apply, and the
        facts a person still has to supply. It proposes a <em>rule</em>; the engine computes the number. Nothing here is booked
        without a named approver. Drafting is {run.manifest.adjudication_enabled ? "turned on" : "turned off"} for this run.
      </p>
      {list.length === 0 && (
        <Empty>
          No drafted treatments for this run.
          {m999.length === 0
            ? " Every event in the activity feed matched a marking rule, so none was needed."
            : ` ${m999.length} position${m999.length === 1 ? " was" : "s were"} blocked by an event the policy does not cover, but no draft was written: drafting was turned off, or no model was configured for it.`}
        </Empty>
      )}
      {list.map((p) => {
        const id = proposalId(p);
        const c = p.company ? byCompany[p.company] : undefined;
        const decided = p.status && p.status !== "pending";
        const disabledReason = decided ? `Already ${proposalStatusLabel(p.status!).toLowerCase()}` : writeDisabled;
        return (
          <div key={id} className={`card disp-${p.suggested_severity} stripe p-4 pl-5`}>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              {p.company && (
                <button className="font-semibold text-[14px] hover:underline" onClick={() => gotoCompany(p.company!)}>
                  {p.company}
                </button>
              )}
              <span
                className="text-[12px] text-ink2 hint"
                title={`Event signature — the key that recognises this same case again in a later quarter: ${p.event_signature}`}
              >
                {p.event_type ? humanize(p.event_type) : "Event the policy does not cover"}
              </span>
              <DispChip d={p.suggested_severity} />
              <span className="chip no-dot disp-MONITOR">{proposedKindLabel(p.proposed_kind)}</span>
              {p.status && <span className="chip no-dot disp-CLEAR">{proposalStatusLabel(p.status)}</span>}
              {typeof p.repeat_count === "number" && p.repeat_count > 0 && (
                <span className="text-[11px] text-muted">seen {p.repeat_count}× before</span>
              )}
              <span className={`chip no-dot ${draftedByClaude(p) ? "chip-ai" : "disp-MONITOR"}`} title={p.provenance?.model ? `Drafted by ${p.provenance.model}` : ""}>
                {draftedByClaude(p) ? "Drafted by Claude" : "Drafted by built-in heuristics"}
              </span>
              <span className="ml-auto text-[11px] text-muted num" title="How sure the model is of this draft. Shown for context; it decides nothing.">
                Model confidence {pct(p.confidence, 0)}
              </span>
            </div>
            {p.briefing && Object.keys(p.briefing).length > 0 && (
              <div className="mt-3 grid grid-cols-1 md:grid-cols-[180px_1fr] gap-x-4 gap-y-1.5 text-[12.5px] leading-relaxed">
                {BRIEFING_ROWS.filter(([k]) => p.briefing?.[k]).map(([k, label]) => (
                  <div key={k} className="contents">
                    <div className="text-[11px] uppercase tracking-wider text-muted pt-0.5">{label}</div>
                    <div className="text-ink">{p.briefing![k]}</div>
                  </div>
                ))}
                <div className="md:col-span-2 text-[11px] text-muted">
                  A draft for a person to weigh, not a decision: the mark is unchanged until the committee accepts, promotes or rejects it below.
                </div>
              </div>
            )}
            {c && (
              <div className="text-[11px] text-muted mt-1 num">
                {c.fund} · {c.sector} · prior {musd(c.prior_mark)} · proposed {musd(c.proposed_mark)} · <DispChip d={c.disposition} />
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 mt-3 text-[12px]">
              <div>
                <div className="text-[11px] uppercase tracking-wider text-muted">Closest existing rule</div>
                <div className="mono">{p.analogue_rule_id}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider text-muted">Calculation it would apply</div>
                <div className="mono">{p.formula}</div>
                {Object.keys(p.parameter_map ?? {}).length > 0 && (
                  <table className="dtable text-[11px] w-full mt-1">
                    <thead>
                      <tr>
                        <th>Input</th>
                        <th>Comes from</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(p.parameter_map).map(([k, v]) => (
                        <tr key={k}>
                          <td>{evidenceLabel(k)}</td>
                          <td className="text-muted">{parameterSource(v)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="md:col-span-2">
                <div className="text-[11px] uppercase tracking-wider text-muted">Rationale</div>
                <p className="text-ink2">{p.rationale}</p>
              </div>
              <div className="md:col-span-2">
                <div className="text-[11px] uppercase tracking-wider text-muted">Missing facts — only a person can supply these</div>
                {p.missing_facts.length === 0 ? (
                  <span className="text-muted">None — the draft has everything it needs.</span>
                ) : (
                  <ul className="list-disc pl-5 text-ink2">
                    {p.missing_facts.map((f, i) => (
                      <li key={i}>{f}</li>
                    ))}
                  </ul>
                )}
              </div>
              {p.provenance && Object.keys(p.provenance).length > 0 && (
                <details className="md:col-span-2">
                  <summary className="text-[11px] uppercase tracking-wider text-muted cursor-pointer select-none">How this draft was produced</summary>
                  <div className="mt-1 text-[11.5px] max-w-[420px]">
                    {Object.entries(p.provenance).map(([k, v]) => (
                      <KV key={k} k={provenanceLabel(k)} v={k === "ts" ? shortDate(String(v)) : String(v)} mono={k !== "ts"} />
                    ))}
                  </div>
                </details>
              )}
            </div>
            <div className="flex flex-wrap gap-4 mt-3">
              <div className="max-w-[230px]">
                <WriteButton disabledReason={disabledReason} className="btn" onClick={() => setAct({ p, a: "accept_once" })}>
                  Accept once
                </WriteButton>
                <p className="text-[11px] text-muted mt-1 mb-0 leading-snug">Books this draft for this quarter only, as a recorded decision in your name.</p>
              </div>
              <div className="max-w-[230px]">
                <WriteButton disabledReason={disabledReason} className="btn" onClick={() => setAct({ p, a: "promote" })}>
                  Promote to rule
                </WriteButton>
                <p className="text-[11px] text-muted mt-1 mb-0 leading-snug">Writes the draft into next quarter's policy, so the same case is handled without a draft.</p>
              </div>
              <div className="max-w-[230px]">
                <WriteButton disabledReason={disabledReason} className="btn btn-danger" onClick={() => setAct({ p, a: "reject" })}>
                  Reject
                </WriteButton>
                <p className="text-[11px] text-muted mt-1 mb-0 leading-snug">Leaves the position blocked, for someone to mark by hand.</p>
              </div>
            </div>
          </div>
        );
      })}
      {act && (
        <DecisionModal
          p={act.p}
          a={act.a}
          proposedMark={act.p.company ? byCompany[act.p.company]?.proposed_mark : undefined}
          measurementDate={run.manifest.measurement_date}
          onClose={() => setAct(null)}
          onDone={() => {
            setAct(null);
            refetch();
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function DecisionModal({
  p,
  a,
  proposedMark,
  measurementDate,
  onClose,
  onDone,
}: {
  p: TreatmentProposal;
  a: Action;
  proposedMark?: number;
  measurementDate: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [booked, setBooked] = useState(proposedMark !== undefined ? String(proposedMark) : "");
  const [approver, setApprover] = useState("");
  const [reason, setReason] = useState(
    a === "reject" ? "" : `${a === "accept_once" ? "Accepted once" : "Promoted"} per proposal ${proposalId(p)} (analogue ${p.analogue_rule_id}).`,
  );
  const [effective, setEffective] = useState(nextQuarterStart(measurementDate));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const title = a === "accept_once" ? "Accept once" : a === "promote" ? "Promote to rule" : "Reject proposal";
  const valid =
    approver.trim() &&
    reason.trim() &&
    (a === "accept_once" ? Number.isFinite(parseFloat(booked)) : a === "promote" ? /^\d{4}-\d{2}-\d{2}$/.test(effective) : true);

  const body = (): ProposalDecision =>
    a === "accept_once"
      ? { decision: "accept_once", booked: parseFloat(booked), approver, reason }
      : a === "promote"
        ? { decision: "promote", approver, reason, effective_from: effective }
        : { decision: "reject", approver, reason };

  return (
    <Modal title={`${title} · ${p.company ?? "this draft"}`} onClose={onClose}>
      <p className="text-[12px] text-ink2 mb-3">
        {a === "accept_once" &&
          "Books this mark for this quarter only, recorded as a decision with the draft as its documented reason. No rule is created, so the same event next quarter is drafted again."}
        {a === "promote" &&
          "Writes the draft into next quarter's policy as a rule, with your name and the date it takes effect. Prior quarters are unchanged."}
        {a === "reject" && "The position stays blocked, and the mark has to be set by hand."}
      </p>
      {a === "accept_once" && (
        <Field label="Booked mark ($M)">
          <input className="input mono w-full" value={booked} onChange={(e) => setBooked(e.target.value)} />
        </Field>
      )}
      <Field label="Approver">
        <input className="input w-full" value={approver} onChange={(e) => setApprover(e.target.value)} />
      </Field>
      {a === "promote" && (
        <Field label="Effective from (YYYY-MM-DD)">
          <input className="input mono w-full" value={effective} onChange={(e) => setEffective(e.target.value)} />
        </Field>
      )}
      <Field label="Reason">
        <textarea className="textarea w-full" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {err && <div className="text-[12px] down mb-2">{err}</div>}
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className={`btn ${a === "reject" ? "btn-danger" : "btn-primary"}`}
          disabled={!valid || busy}
          onClick={async () => {
            setBusy(true);
            setErr(null);
            try {
              await decideProposal(proposalId(p), body());
              onDone();
            } catch (e) {
              setErr(String((e as Error).message ?? e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Saving…" : title}
        </button>
      </div>
    </Modal>
  );
}

function nextQuarterStart(measurementDate: string): string {
  const d = new Date(measurementDate + "T00:00:00Z");
  const next = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
  return next.toISOString().slice(0, 10);
}
