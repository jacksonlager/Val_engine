// The publish gate in the top bar: executives see only what the back office releases.
// "Publish" freezes the current booked marks as the quarter's executive snapshot under a
// named approver; the quiet status line beside it says what executives are looking at now
// and whether the live run has moved on since.
import { useEffect, useState } from "react";
import type { PublishRecord, ValuationRun } from "../types";
import { fetchPublished, publishRun, type Mode } from "../lib/api";
import { isoDate } from "../lib/format";
import { Field, Modal, useAsync, WriteButton } from "./ui";

const EXEC_STATIC_REASON = "Available when served";

/** "just now", "12m ago", "3h ago", "2d ago", then the date. */
function ago(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return isoDate(iso);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`;
  return isoDate(iso);
}

export function PublishControls({
  run,
  mode,
  writeDisabled,
  refreshKey,
}: {
  run: ValuationRun;
  mode: Mode;
  writeDisabled: string | null;
  /** bumped by the app on every reload so the status line refetches after a rerun */
  refreshKey: number;
}) {
  const [open, setOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const served = mode === "served";
  const published = useAsync<PublishRecord[]>(() => (served ? fetchPublished() : Promise.resolve([])), [served, refreshKey]);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const m = run.manifest;
  const current = published.data?.find((p) => p.quarter === m.quarter_label);
  const changedSince = !!current && !!current.run_id && current.run_id !== m.run_id;

  return (
    <>
      {served && (
        <span className="mono text-[11px] text-muted whitespace-nowrap" aria-live="polite">
          {published.error ? (
            <span title={published.error}>published status unavailable</span>
          ) : current ? (
            <>
              <span title={`Published ${current.published_at} by ${current.published_by} (run ${current.run_id ?? "?"})`}>
                Published {current.status} · {ago(current.published_at)} · {current.published_by}
              </span>
              {changedSince && (
                <span className="text-[var(--review-text)]" title={`Executives see run ${current.run_id}; this is run ${m.run_id}`}>
                  {" "}
                  · changes since
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
      <WriteButton disabledReason={writeDisabled ? EXEC_STATIC_REASON : null} className="btn btn-primary" onClick={() => setOpen(true)}>
        Publish
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

      {open && (
        <PublishModal
          run={run}
          onClose={() => setOpen(false)}
          onDone={(rec) => {
            setOpen(false);
            setToast(`Published ${rec.quarter} as ${rec.status.toUpperCase()} by ${rec.published_by}`);
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
  const blocks = run.totals.dispositions.BLOCK ?? 0;
  const valid = approver.trim().length > 0;
  const quarter = run.manifest.quarter_label;

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
        <Field label="Your name">
          <input className="input w-full" value={approver} onChange={(e) => setApprover(e.target.value)} autoFocus required />
        </Field>
        <Field label="Note (optional, shown on the executive page)">
          <input className="input w-full" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {blocks > 0 ? (
          <div className="text-[12px] text-[var(--review-text)] mb-3">
            This will publish as <span className="font-semibold">PROPOSED</span> — {blocks} {blocks === 1 ? "position" : "positions"} still{" "}
            {blocks === 1 ? "awaits" : "await"} a committee decision.
          </div>
        ) : (
          <div className="text-[12px] text-[var(--clear-text)] mb-3">
            This will publish as <span className="font-semibold">FINAL</span>.
          </div>
        )}
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
