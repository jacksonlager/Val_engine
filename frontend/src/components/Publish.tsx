// The publish gate in the top bar: executives see only what the back office releases.
// "Publish" freezes the current booked marks as the quarter's executive snapshot under a
// named approver; the quiet status line beside it says what executives are looking at now
// and whether the live run has moved on since.
import { useEffect, useMemo, useState } from "react";
import type { CompanyResult, PublishRecord, ValuationRun } from "../types";
import { fetchPublished, publishRun, type Mode } from "../lib/api";
import { musd, relativeTime } from "../lib/format";
import { dispositionLabel, publishStatusLabel, shortRef } from "../lib/labels";
import { Field, Modal, useAsync, WriteButton } from "./ui";

/** The decision gate. A position that is still BLOCK ("decision required before booking") or REVIEW
    ("check required to confirm the mark") holds the whole book back: nothing is released to executives
    until a person has decided or confirmed every one. Mirrors `outstanding()` on the server, which
    refuses the publish (409) regardless of what the browser thinks. */
export type Outstanding = { c: CompanyResult; rules: string[] };

export function outstanding(run: ValuationRun): Outstanding[] {
  const out: Outstanding[] = [];
  for (const c of run.companies) {
    if (c.disposition !== "BLOCK" && c.disposition !== "REVIEW") continue;
    const addressed = new Set(c.override?.rule_ids_addressed ?? []);
    const rules = c.flags.filter((f) => (f.severity === "BLOCK" || f.severity === "REVIEW") && !addressed.has(f.rule_id)).map((f) => f.rule_id);
    out.push({ c, rules });
  }
  // decisions first, then confirmations; alphabetical within each
  return out.sort((a, b) => (a.c.disposition === b.c.disposition ? a.c.company.localeCompare(b.c.company) : a.c.disposition === "BLOCK" ? -1 : 1));
}

const EXEC_STATIC_REASON = "Not available in this static report — run the dashboard app to publish and to open the executive view.";

/** "just now" … "6d ago" within the last week; otherwise (older, or dated in the future) the date itself. */
const ago = relativeTime;

export function PublishControls({
  run,
  mode,
  writeDisabled,
  refreshKey,
  onGoto,
}: {
  run: ValuationRun;
  mode: Mode;
  writeDisabled: string | null;
  /** bumped by the app on every reload so the status line refetches after a rerun */
  refreshKey: number;
  /** jump to a company's expanded row so the reviewer can decide it */
  onGoto?: (company: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [gate, setGate] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const served = mode === "served";
  const waiting = useMemo(() => outstanding(run), [run]);
  const locked = waiting.length > 0;
  const published = useAsync<PublishRecord[]>(() => (served ? fetchPublished() : Promise.resolve([])), [served, refreshKey]);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 12000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const m = run.manifest;
  const current = published.data?.find((p) => p.quarter === m.quarter_label);
  // the snapshot on disk was made from another workbook (a fresh version of the quarter's file was uploaded):
  // not "changes since" but a different book altogether, and the header must say so
  const otherWorkbook = !!current && !!current.input_sha256 && current.input_sha256 !== m.input_sha256;
  const changedSince = !!current && !!current.run_id && current.run_id !== m.run_id && !otherWorkbook;

  return (
    <>
      {served && (
        <span className="text-[11px] text-muted whitespace-nowrap" aria-live="polite">
          {published.error ? (
            <span title={`The publication status could not be loaded. Technical detail: ${published.error}`}>Publication status unavailable</span>
          ) : current ? (
            <>
              <span title={`Published ${current.published_at} by ${current.published_by} (run ${current.run_id ?? "?"})`}>
                Published as {publishStatusLabel(current.status)} · {ago(current.published_at)} · {current.published_by}
              </span>
              {otherWorkbook && (
                <span
                  className="text-[var(--block-text)]"
                  title={`The published snapshot was made from a different workbook (file ${shortRef(current.input_sha256 ?? "", 12)}); this run reads ${shortRef(m.input_sha256, 12)}. Publishing again replaces it.`}
                >
                  {" "}
                  · published earlier from a different workbook
                </span>
              )}
              {changedSince && (
                <span
                  className="text-[var(--review-text)]"
                  title={`The published snapshot is older than the current run. Executives see run ${shortRef(current.run_id)}; this is run ${shortRef(m.run_id)}.`}
                >
                  {" "}
                  · changed since publication
                </span>
              )}
            </>
          ) : published.loading ? (
            "…"
          ) : (
            "Not yet published"
          )}
        </span>
      )}
      <WriteButton
        disabledReason={writeDisabled ? EXEC_STATIC_REASON : null}
        className={`btn btn-primary${locked ? " btn-locked" : ""}`}
        onClick={() => (locked ? setGate(true) : setOpen(true))}
        title={
          locked
            ? `${waiting.length} position${waiting.length === 1 ? " still needs" : "s still need"} a decision or confirmation before publishing`
            : "Release the booked marks to executives"
        }
      >
        {locked ? (
          <>
            <span aria-hidden>🔒</span> Publish <span className="lock-count">{waiting.length}</span>
          </>
        ) : (
          "Publish"
        )}
      </WriteButton>
      <span title={writeDisabled ? EXEC_STATIC_REASON : "Open the executive dashboard (published snapshots only)"} className="inline-block">
        {writeDisabled ? (
          <a className="btn btn-ghost" aria-disabled="true" tabIndex={-1} role="link">
            Executive dashboard ↗
          </a>
        ) : (
          <a className="btn btn-ghost" href="/exec/" target="_blank" rel="noopener">
            Executive dashboard ↗
          </a>
        )}
      </span>

      {gate && (
        <GateModal
          run={run}
          items={waiting}
          onClose={() => setGate(false)}
          onGoto={(name) => {
            setGate(false);
            onGoto?.(name);
          }}
        />
      )}
      {open && (
        <PublishModal
          run={run}
          onClose={() => setOpen(false)}
          onDone={(rec) => {
            setOpen(false);
            const next = rec.next_quarter_input ? ` Next quarter's workbook written: ${rec.next_quarter_input.split("/").pop()} — it is in the Workbook select.` : "";
            const failed = rec.next_quarter_input_error ? ` The next-quarter workbook could not be written (${rec.next_quarter_input_error}); run hc-valuation build.` : "";
            setToast(`Published ${rec.quarter} as ${publishStatusLabel(rec.status)}, released by ${rec.published_by}.${next}${failed}`);
            published.refetch();
          }}
        />
      )}
      {toast && (
        <div className="toast disp-CLEAR" role="status">
          {toast}
        </div>
      )}
    </>
  );
}

function PublishModal({ run, onClose, onDone }: { run: ValuationRun; onClose: () => void; onDone: (rec: PublishRecord) => void }) {
  const [approver, setApprover] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const valid = approver.trim().length > 0;
  const quarter = run.manifest.quarter_label;
  const decided = run.companies.filter((c) => c.override).length;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const rec = await publishRun(approver.trim(), note.trim());
      onDone(rec);
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Publish · ${quarter}`} onClose={onClose}>
      <p className="text-[12px] text-ink2 mb-3">
        Freeze the current booked marks as the executive snapshot for {quarter}. Executives see only published snapshots.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Your name (a second person: the approver on this quarter's overrides may not also release them)">
          <input className="input w-full" value={approver} onChange={(e) => setApprover(e.target.value)} autoFocus required />
        </Field>
        <Field label="Note (optional, shown on the executive page)">
          <input className="input w-full" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="text-[12px] text-[var(--clear-text)] mb-3">
          Every blocked position, and every one that needed review, has been decided or confirmed ({decided} committee{" "}
          {decided === 1 ? "decision" : "decisions"} on the ledger). This will publish as <span className="font-semibold">final</span>.
        </div>
        {err && <div className="text-[12px] down mb-2">{err}</div>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={!valid || busy}>
            {busy ? "Publishing…" : "Publish to executives"}
          </button>
        </div>
      </form>
    </Modal>
  );
}


/** The lock. Opens instead of the publish form while any position is still waiting on a person,
    lists exactly what is left, and can only be closed — there is no "publish anyway". */
function GateModal({
  run,
  items,
  onClose,
  onGoto,
}: {
  run: ValuationRun;
  items: Outstanding[];
  onClose: () => void;
  onGoto: (company: string) => void;
}) {
  const blocks = items.filter((i) => i.c.disposition === "BLOCK").length;
  const reviews = items.length - blocks;
  const quarter = run.manifest.quarter_label;
  return (
    <Modal title={`Publish is locked · ${quarter}`} onClose={onClose} className="modal-wide">
      <p className="text-[12px] text-ink2 mb-2">
        Nothing is released to executives until every position has been decided or confirmed. This keeps a mark from being published
        on a row nobody looked at.
      </p>
      <div className="gate-summary">
        <span className="chip disp-BLOCK">
          {blocks} {blocks === 1 ? "decision" : "decisions"} required
        </span>
        <span className="chip disp-REVIEW">
          {reviews} {reviews === 1 ? "check" : "checks"} to confirm
        </span>
      </div>
      <ul className="gate-list" aria-label="Positions still waiting">
        {items.map(({ c, rules }) => (
          <li key={c.company} className="gate-row" title={rules.length > 0 ? `Open findings: ${rules.join(", ")}` : undefined}>
            <span className={`chip disp-${c.disposition} no-dot gate-disp`} title={c.disposition === "BLOCK" ? "Decision required" : "Confirmation required"}>
              {dispositionLabel(c.disposition)}
            </span>
            <span className="gate-name">
              <span className="font-semibold">{c.company}</span>
              {rules.length > 0 && (
                <span className="text-[10.5px] text-muted">
                  {" "}
                  {rules.length} open finding{rules.length === 1 ? "" : "s"}
                </span>
              )}
            </span>
            <span className="num text-[11.5px] text-ink2 whitespace-nowrap" title="Proposed mark">
              {musd(c.proposed_mark)}
            </span>
            <button type="button" className="btn btn-ghost gate-open" onClick={() => onGoto(c.company)}>
              {c.disposition === "BLOCK" ? "Decide" : "Confirm"} →
            </button>
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-muted mt-2 mb-3">
        Choosing a resolution on a flag, or confirming the mark as proposed, records a committee override under your name and clears
        that row. The button unlocks on its own once the list is empty.
      </p>
      <div className="flex justify-end">
        <button type="button" className="btn btn-primary" onClick={onClose} autoFocus>
          Close
        </button>
      </div>
    </Modal>
  );
}
