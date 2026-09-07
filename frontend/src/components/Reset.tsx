// Reset: back to the landing screen with nothing uploaded, as if the tool had just been handed over.
// Quiet button in the top bar; a dialog with one sentence on what goes, and a confirm button —
// every upload, every decision and every published snapshot is removed; policy and market cache stay.
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
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const go = async () => {
    if (busy) return;
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
      <p className="text-[13px] text-ink2 mb-4 leading-relaxed">
        This removes every uploaded workbook, every decision on the ledger and every published snapshot, and returns to the
        landing screen; the policy files and the market-data cache are kept.
      </p>
      {err && <div className="text-[12px] down mb-2">{err}</div>}
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button className="btn btn-danger disp-BLOCK" disabled={busy} onClick={go} autoFocus>
          {busy ? "Resetting…" : "Confirm reset"}
        </button>
      </div>
    </Modal>
  );
}
