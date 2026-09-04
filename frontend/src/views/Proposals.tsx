import { useState } from "react";
import type { ProposalDecision, TreatmentProposal, ValuationRun } from "../types";
import { decideProposal, loadProposals, proposalId, type Mode } from "../lib/api";
import { musd, pct } from "../lib/format";
import { DispChip, Empty, Field, Modal, useAsync, WriteButton } from "../components/ui";

type Action = "accept_once" | "promote" | "reject";

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
        E-09 novel-case adjudication. When M-999 halts on an event the policy has never seen, an adjudicator drafts a
        treatment beside the blocked position: the rule it reasons by analogy from, a formula in the restricted expression
        language, and the facts the schema does not contain. It proposes a <em>rule</em>; the engine computes the number. Nothing
        here is booked without a named approver. Adjudication is {run.manifest.adjudication_enabled ? "enabled" : "disabled"} in this
        run.
      </p>
      {list.length === 0 && (
        <Empty>
          No proposals for this run.
          {m999.length === 0
            ? " No M-999 halts: every event in the activity feed matched a registered marking rule."
            : ` ${m999.length} position(s) halted on M-999 without a proposal — adjudication was off or no model was configured.`}
        </Empty>
      )}
      {list.map((p) => {
        const id = proposalId(p);
        const c = p.company ? byCompany[p.company] : undefined;
        const decided = p.status && p.status !== "pending";
        return (
          <div key={id} className={`card disp-${p.suggested_severity} stripe p-4 pl-5`}>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              {p.company && (
                <button className="font-semibold text-[14px] hover:underline" onClick={() => gotoCompany(p.company!)}>
                  {p.company}
                </button>
              )}
              {p.event_type && <span className="text-[12px] text-ink2">{p.event_type}</span>}
              <span className="mono text-[11px] text-muted">{p.event_signature}</span>
              <DispChip d={p.suggested_severity} />
              <span className="chip no-dot disp-MONITOR">{p.proposed_kind}</span>
              {p.status && <span className="chip no-dot disp-CLEAR">{p.status}</span>}
              {typeof p.repeat_count === "number" && p.repeat_count > 0 && (
                <span className="text-[11px] text-muted">seen {p.repeat_count}× before</span>
              )}
              <span className="ml-auto text-[11px] text-muted num" title="Displayed only; gates nothing">
                confidence {pct(p.confidence, 0)}
              </span>
            </div>
            {c && (
              <div className="text-[11px] text-muted mt-1 num">
                {c.fund} · {c.sector} · prior {musd(c.prior_mark)} · proposed {musd(c.proposed_mark)} · <DispChip d={c.disposition} />
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 mt-3 text-[12px]">
              <div>
                <div className="text-[11px] uppercase tracking-wider text-muted">Analogue rule</div>
                <div className="mono">{p.analogue_rule_id}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider text-muted">Proposed formula</div>
                <div className="mono">{p.formula}</div>
                {Object.keys(p.parameter_map ?? {}).length > 0 && (
                  <div className="mono text-[11px] text-muted mt-0.5">
                    {Object.entries(p.parameter_map)
                      .map(([k, v]) => `${k} ← ${v}`)
                      .join(" · ")}
                  </div>
                )}
              </div>
              <div className="md:col-span-2">
                <div className="text-[11px] uppercase tracking-wider text-muted">Rationale</div>
                <p className="text-ink2">{p.rationale}</p>
              </div>
              <div className="md:col-span-2">
                <div className="text-[11px] uppercase tracking-wider text-muted">Missing facts — only a person can supply these</div>
                {p.missing_facts.length === 0 ? (
                  <span className="text-muted">none</span>
                ) : (
                  <ul className="list-disc pl-5 text-ink2">
                    {p.missing_facts.map((f, i) => (
                      <li key={i}>{f}</li>
                    ))}
                  </ul>
                )}
              </div>
              {p.provenance && (
                <div className="md:col-span-2 mono text-[10px] text-muted">
                  {Object.entries(p.provenance)
                    .map(([k, v]) => `${k}=${String(v)}`)
                    .join("  ")}
                </div>
              )}
            </div>
            <div className="flex gap-2 mt-3">
              <WriteButton disabledReason={decided ? `Already ${p.status}` : writeDisabled} className="btn" onClick={() => setAct({ p, a: "accept_once" })}>
                Accept once
              </WriteButton>
              <WriteButton disabledReason={decided ? `Already ${p.status}` : writeDisabled} className="btn" onClick={() => setAct({ p, a: "promote" })}>
                Promote to rule
              </WriteButton>
              <WriteButton disabledReason={decided ? `Already ${p.status}` : writeDisabled} className="btn btn-danger" onClick={() => setAct({ p, a: "reject" })}>
                Reject
              </WriteButton>
              <span className="text-[11px] text-muted self-center ml-2">
                accept once → E-01 override with this draft as reason · promote → declarative rule in next quarter's policy · reject → manual override
              </span>
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
    <Modal title={`${title} · ${p.company ?? p.event_signature}`} onClose={onClose}>
      <p className="text-[12px] text-ink2 mb-3">
        {a === "accept_once" &&
          "Applied as an E-01 override with the draft as documented reason. No rule is created; the same event next quarter is adjudicated again."}
        {a === "promote" &&
          "Writes the proposal into the next quarter's policy as a declarative rule with your name and an effective-from date. Prior quarters are unchanged."}
        {a === "reject" && "The position stays blocked and falls back to a manual override."}
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
