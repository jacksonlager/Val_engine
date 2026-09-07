// Upload a portfolio workbook. The button lives in the top bar; the dialog shows the file being
// processed stage by stage — saved, quarter found, workbook read, data checked, market data,
// every position valued, next steps chosen — and ends on what came out: the quarter, the
// positions, the readiness buckets. Nothing is booked by an upload; it is a new run to review.
import { useEffect, useRef, useState } from "react";
import type { UploadJob } from "../types";
import { uploadStatus, uploadWorkbook } from "../lib/api";
import { musdTile } from "../lib/format";
import { Modal } from "./ui";

export function UploadButton({ onLoaded, primary = false }: { onLoaded: () => void; primary?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className={`btn ${primary ? "btn-primary" : ""}`} onClick={() => setOpen(true)} title="Upload a portfolio workbook (.xlsx) and run it">
        Upload workbook
      </button>
      {open && <UploadDialog onClose={() => setOpen(false)} onLoaded={onLoaded} />}
    </>
  );
}

function UploadDialog({ onClose, onLoaded }: { onClose: () => void; onLoaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<UploadJob | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef<number | null>(null);
  const clock = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
    if (clock.current) window.clearInterval(clock.current);
  }, []);

  const start = async () => {
    if (!file || busy) return;
    setBusy(true);
    setErr(null);
    const started = Date.now();
    clock.current = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    try {
      const { id } = await uploadWorkbook(file);
      timer.current = window.setInterval(async () => {
        try {
          const j = await uploadStatus(id);
          setJob(j);
          if (j.done) {
            if (timer.current) window.clearInterval(timer.current);
            if (clock.current) window.clearInterval(clock.current);
            setBusy(false);      // the summary stays on screen; "Open Activity" loads the new run
          }
        } catch (e) {
          if (timer.current) window.clearInterval(timer.current);
          setBusy(false);
          setErr(String((e as Error).message ?? e));
        }
      }, 350);
    } catch (e) {
      if (clock.current) window.clearInterval(clock.current);
      setBusy(false);
      setErr(String((e as Error).message ?? e));
    }
  };

  const pct = job ? Math.round((Math.min(job.stage, job.total) / job.total) * 100) : 0;
  const r = job?.result;
  return (
    <Modal title="Upload a portfolio workbook" onClose={busy ? () => undefined : onClose}>
      {!job && (
        <>
          <p className="text-[12px] text-ink2 mb-3">
            An .xlsx in the portfolio schema: a <span className="mono">Portfolio</span> tab (the book at the prior close) and a{" "}
            <span className="mono">Qn YYYY Activity</span> tab (every event in the quarter). The quarter is read from the activity tab's name; its policy
            file is created from the base policy if none exists. Nothing is booked — the result is a new run to review.
          </p>
          <input
            type="file"
            accept=".xlsx"
            className="block text-[12px] mb-3"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          {err && <div className="text-[12px] down mb-2">{err}</div>}
          <div className="flex justify-end gap-2">
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!file || busy} onClick={start}>
              Upload and run
            </button>
          </div>
        </>
      )}
      {job && (
        <>
          <div className="text-[12px] text-ink2 mb-2 flex items-center gap-2">
            {!job.done && <span className="spinner" aria-hidden />}
            <span className="mono">{job.file}</span>
          </div>
          <div className="h-2 rounded bg-hair overflow-hidden mb-1.5" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div
              className={`h-full ${job.error ? "bg-[var(--block)]" : "bg-accent"} ${!job.done ? "bar-active" : ""}`}
              style={{ width: `${job.error ? 100 : Math.max(pct, 4)}%`, transition: "width 250ms" }}
            />
          </div>
          <div className="flex justify-between text-[11px] text-muted mb-1">
            <span>{job.message}</span>
            <span className="num">
              {job.done && !job.error ? `done in ${elapsed}s` : `step ${Math.min(job.stage + 1, job.total)} of ${job.total} · ${elapsed}s`}
            </span>
          </div>
          {!job.done && (
            <div className="text-[11px] text-muted mb-3">
              Rolling every position through the quarter's activity, screening each one, and choosing a next step. A large book, or one
              that needs the live comps feed, can take a little while — nothing to do but wait.
            </div>
          )}
          <ol className="text-[11px] text-muted space-y-0.5 mb-3 pl-4">
            {job.stages.map((s, i) => (
              <li key={s} className={i < job.stage || (job.done && !job.error) ? "text-ink2" : i === job.stage && !job.done ? "text-ink font-medium" : ""}>
                {s}
              </li>
            ))}
          </ol>
          {job.error && (
            <div className="card disp-BLOCK stripe p-3 pl-4 text-[12px] mb-3">
              <div className="font-semibold mb-1">The workbook could not be loaded — the previous run is still shown.</div>
              <div className="mono text-[11px] text-ink2">{job.error}</div>
            </div>
          )}
          {r && (
            <div className="card p-3 text-[12px] mb-3">
              <div className="font-semibold mb-1">
                {r.quarter} · {r.positions} positions · {r.events} activity rows
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <span>
                  <span className="chip disp-BLOCK">Blocked</span> <span className="num">{r.readiness.Blocked ?? 0}</span>
                </span>
                <span>
                  <span className="chip disp-REVIEW">Needs Review</span> <span className="num">{r.readiness["Needs Review"] ?? 0}</span>
                </span>
                <span>
                  <span className="chip disp-CLEAR">Ready</span> <span className="num">{r.readiness.Ready ?? 0}</span>
                </span>
                <span className="text-muted">
                  proposed fair value <span className="num text-ink2">{musdTile(r.proposed_nav)}</span>
                </span>
              </div>
              {r.blocking_issues > 0 && (
                <div className="text-[11px] mt-1.5 text-[var(--block-text)]">
                  {r.blocking_issues} data check{r.blocking_issues === 1 ? "" : "s"} blocking — see Data checks in the footer.
                </div>
              )}
              {job.policy_created && (
                <div className="text-[11px] mt-1.5 text-muted">
                  No policy file existed for {r.quarter}; <span className="mono">{job.policy_created}</span> was written from the base policy.
                </div>
              )}
              {r.synthetic && <div className="text-[11px] mt-1.5 text-[var(--block-text)]">This workbook is marked as synthetic test data.</div>}
            </div>
          )}
          <div className="flex justify-end">
            <button
              className="btn btn-primary"
              disabled={!job.done}
              onClick={() => {
                if (!job.error) onLoaded();
                onClose();
              }}
            >
              {job.error ? "Close" : "Open Activity"}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
