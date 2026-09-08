// "Where is the file?" — the one thing a reader of this dashboard asks that the dashboard itself
// cannot answer. The close writes next quarter's starting workbook beside the one it closed; this
// dialog says where, offers it as a download, and gives the folder path to copy. A browser cannot
// open a local folder from a web page, so the path is shown to copy rather than linked and left
// silently dead.
import { useEffect, useState } from "react";

type Output = {
  quarter: string;
  next_quarter: string;
  folder: string;
  filename: string;
  path: string;
  exists: boolean;
  size_bytes: number | null;
  written_at: string | null;
  download_url: string | null;
  source_workbook: string;
};

function kb(n: number | null): string {
  return n === null ? "" : n > 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

export function OutputWorkbookButton() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Output | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setError(null);
    fetch("/api/output-workbook", { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`the dashboard is not being served (${r.status})`))))
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open]);

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      setCopied("copy failed — select the text and copy it");
    }
  };

  return (
    <>
      <button
        className="px-2.5 h-7 inline-flex items-center rounded-[3px] text-[12px] text-ink2 hover:text-ink hover:bg-raised whitespace-nowrap border border-hair"
        onClick={() => setOpen(true)}
        title="Where next quarter's workbook is written, and a copy to download"
      >
        Output workbook
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-[12vh]"
          style={{ background: "rgba(0,0,0,.34)" }}
          onClick={() => setOpen(false)}
          role="presentation"
        >
          <div
            className="w-full max-w-[640px] rounded-[6px] border border-hair p-5"
            style={{ background: "var(--raised)" }}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Output workbook"
          >
            <div className="flex items-baseline justify-between gap-4 mb-1">
              <h2 className="display font-bold text-[16px] m-0">Output workbook</h2>
              <button className="text-[12px] text-muted hover:text-ink" onClick={() => setOpen(false)} aria-label="Close">
                Close
              </button>
            </div>

            {error && <p className="text-[12.5px] text-ink2 mt-3 mb-0">{error}</p>}

            {!error && !data && <p className="text-[12.5px] text-muted mt-3 mb-0">Looking for it…</p>}

            {data && (
              <>
                <p className="text-[12.5px] text-ink2 leading-[1.55] mt-2 mb-3">
                  Closing {data.quarter} writes the starting workbook for <b>{data.next_quarter}</b> — the booked marks
                  carried in as prior marks, with an empty activity tab ready to fill in.
                </p>

                <dl className="grid grid-cols-[128px_minmax(0,1fr)] gap-y-2 gap-x-4 text-[12.5px] m-0">
                  <dt className="text-muted">File</dt>
                  <dd className="m-0 mono break-all">{data.filename}</dd>
                  <dt className="text-muted">Folder</dt>
                  <dd className="m-0 mono break-all">{data.folder}</dd>
                  {data.exists && (
                    <>
                      <dt className="text-muted">Written</dt>
                      <dd className="m-0">
                        {data.written_at ? new Date(data.written_at).toLocaleString() : "—"}
                        {data.size_bytes ? <span className="text-muted"> · {kb(data.size_bytes)}</span> : null}
                      </dd>
                    </>
                  )}
                </dl>

                <div className="flex flex-wrap items-center gap-2 mt-4">
                  {data.exists && data.download_url ? (
                    <a
                      href={data.download_url}
                      download={data.filename}
                      className="px-3 h-8 inline-flex items-center rounded-[3px] text-[12.5px] font-semibold no-underline"
                      style={{ background: "var(--ink)", color: "var(--ground)" }}
                    >
                      Download the workbook
                    </a>
                  ) : (
                    <span className="text-[12.5px] text-ink2">
                      Not written yet — it is produced when the quarter is published as final.
                    </span>
                  )}
                  <button
                    className="px-3 h-8 inline-flex items-center rounded-[3px] text-[12.5px] border border-hair hover:bg-raised"
                    onClick={() => copy(data.folder, "Folder path copied")}
                  >
                    Copy folder path
                  </button>
                  <button
                    className="px-3 h-8 inline-flex items-center rounded-[3px] text-[12.5px] border border-hair hover:bg-raised"
                    onClick={() => copy(data.path, "Full path copied")}
                  >
                    Copy full path
                  </button>
                  {copied && <span className="text-[12px] text-muted">{copied}</span>}
                </div>

                <p className="text-[11.5px] text-muted leading-[1.5] mt-4 mb-0">
                  A browser cannot open a folder on your machine from a web page, so the path is here to copy rather
                  than as a link that would do nothing. Paste it into Finder with <span className="mono">⌘⇧G</span>.
                </p>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
