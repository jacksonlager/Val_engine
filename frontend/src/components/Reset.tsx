// Reset: back to the landing screen with nothing uploaded, as if the tool had just been handed over.
// Quiet button in the top bar; a dialog that says exactly what goes and what stays, and will not
// act until the word RESET is typed — every decision and every published snapshot is removed.
import { useState } from "react";
import type { ResetResult } from "../types";
import { resetApp } from "../lib/api";
import { Modal } from "./ui";

export function ResetButton({ onReset }: { onReset: (r: ResetResult) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="btn btn-ghost" onClick={() => setOpen(true)} title="Clear every upload, decision and published snapshot and return to the landing screen">
        Reset
      </button>
      {open && <ResetDialog onClose={() => setOpen(false)} onReset={onReset} />}
    </>
  );
}

function ResetDialog({ onClose, onReset }: { onClose: () => void; onReset: (r: ResetResult) => void }) {
  const [word, setWord] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ok = word.trim() === "RESET";
  const go = async () => {
    if (!ok || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await resetApp();
      onReset(r);
      onClose();
    } catch (e) {
      setErr(String((e as Error).message ?? e));
      setBusy(false);
    }
  };
  return (
    <Modal title="Reset the tool" onClose={busy ? () => undefined : onClose}>
      <p className="text-[12px] text-ink2 mb-2">This returns the tool to the landing screen, as if nothing had been uploaded yet.</p>
      <div className="grid grid-cols-2 gap-3 text-[11.5px] mb-3">
        <div className="card disp-BLOCK stripe p-2.5 pl-3">
          <div className="font-semibold mb-1">Removed</div>
          <ul className="m-0 pl-4 space-y-0.5 text-ink2">
            <li>every uploaded workbook, and any next-quarter workbook a close emitted</li>
            <li>every decision on the committee ledger</li>
            <li>every published snapshot (the executive dashboard goes blank)</li>
            <li>carried open items, proposals, precedents, cached recommendations</li>
          </ul>
        </div>
        <div className="card p-2.5">
          <div className="font-semibold mb-1">Kept</div>
          <ul className="m-0 pl-4 space-y-0.5 text-ink2">
            <li>the policy files (rules/)</li>
            <li>the market-data cache and the vendor fixtures</li>
            <li>the repository's own sample workbook</li>
            <li>nothing under the assessment source folder is touched</li>
          </ul>
        </div>
      </div>
      <label className="text-[12px] text-ink2 block mb-1" htmlFor="reset-word">
        Type <span className="mono font-semibold">RESET</span> to confirm
      </label>
      <input
        id="reset-word"
        className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] mono w-full mb-3"
        value={word}
        onChange={(e) => setWord(e.target.value)}
        autoFocus
        disabled={busy}
      />
      {err && <div className="text-[12px] down mb-2">{err}</div>}
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button className="btn btn-danger disp-BLOCK" disabled={!ok || busy} onClick={go}>
          {busy ? "Resetting…" : "Reset everything"}
        </button>
      </div>
    </Modal>
  );
}
