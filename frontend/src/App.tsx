import { useCallback, useEffect, useState } from "react";
import type { Rationale, Sources, ValuationRun, WorkbookProfile } from "./types";
import { currentRunStamp, fetchWorkbooks, loadHistory, loadProposals, loadRationale, loadRun, loadSignals, NoWorkbookError, selectWorkbook, STATIC_REASON, type Mode } from "./lib/api";
import { UploadButton } from "./components/Upload";
import { ResetButton } from "./components/Reset";
import type { ResetResult } from "./types";
import { HistoryProvider, type HistoryState } from "./lib/history";
import { SourcesProvider } from "./lib/sources";
import { RationaleProvider } from "./lib/rationale";
import { shortDate, isoDateTime } from "./lib/format";
import { marketSourceLabel, shortRef } from "./lib/labels";
import { DispChip } from "./components/ui";
import { PublishControls } from "./components/Publish";
import { QueueView } from "./views/Queue";
import { CompaniesView } from "./views/Companies";
import { MovementView } from "./views/Movement";
import { FundsView } from "./views/Funds";
import { OpenItemsView } from "./views/OpenItems";
import { ProposalsView } from "./views/Proposals";
import { MarketView } from "./views/Market";
import { RulesView } from "./views/Rules";

type View = "queue" | "companies" | "movement" | "funds" | "market" | "rules" | "open" | "proposals";
// The Queue first — what the quarter brought in sits at its top, then the rest of the book that
// needs a person — then the views the brief asks for: the auditor's table, what moved and why,
// and where the market numbers came from. Funds lives on the executive dashboard; open items
// sit at the foot of the Queue; Proposals appears only when the engine actually has one.
// The other routes still answer to their hash (#funds, #open) for anyone who bookmarked them;
// #activity, the former New Activity tab, lands on the Queue.
const VIEWS: { id: View; label: string }[] = [
  { id: "queue", label: "Activity" },   // the review queue: what the quarter brought in, then the rest of the book
  { id: "companies", label: "Companies" },
  { id: "movement", label: "Movement" },
  { id: "market", label: "Market" },
  { id: "rules", label: "Rules" },
];
const ALL_VIEWS: View[] = ["queue", "companies", "movement", "funds", "market", "rules", "open", "proposals"];

/** The workbook the served run reads, and the others it could. Switching asks the server to
    recompute on that file — with its quarter's policy and its own decision ledger — so the run
    id changes and the page reloads. A synthetic profile is said so beside the name. */
function WorkbookSwitcher({
  served,
  refreshKey,
  onSwitched,
  onBusy,
}: {
  served: boolean;
  refreshKey: number;
  onSwitched: () => void;
  /** the app shows a full-page "Running the valuation…" overlay while a switch is in progress */
  onBusy?: (busy: boolean) => void;
}) {
  const [profiles, setProfiles] = useState<WorkbookProfile[]>([]);
  const [busy, setBusyState] = useState(false);
  const setBusy = (b: boolean) => {
    setBusyState(b);
    onBusy?.(b);
  };
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!served) return;
    fetchWorkbooks().then(setProfiles, () => setProfiles([]));
  }, [served, refreshKey]);
  if (!served || profiles.length < 2) return null;
  const current = profiles.find((p) => p.current);
  const change = async (id: string) => {
    if (!id || id === current?.id) return;
    setBusy(true);
    setError(null);
    try {
      await selectWorkbook(id);
      onSwitched();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px]">
      <label className="text-muted" htmlFor="workbook-select">
        Workbook
      </label>
      <select
        id="workbook-select"
        className="rounded-md border border-line bg-surface px-1.5 py-0.5 text-[12px] max-w-[320px]"
        value={current?.id ?? ""}
        disabled={busy}
        onChange={(e) => change(e.target.value)}
        title={current ? `${current.workbook}\nPolicy: ${current.policy ?? "—"}\nDecisions recorded in: ${current.ledger_dir}` : undefined}
      >
        {profiles.map((p) => (
          <option key={p.id} value={p.id} disabled={!p.usable} title={p.usable ? p.workbook : p.reason}>
            {(p.quarter ?? p.workbook) + (p.synthetic ? " · synthetic test data" : "") + (p.usable ? "" : ` (${p.reason})`)}
          </option>
        ))}
      </select>
      {busy && (
        <span className="text-muted inline-flex items-center gap-1.5">
          <span className="spinner" aria-hidden /> running…
        </span>
      )}
      {error && <span className="text-[var(--block-text)]">{error}</span>}
    </span>
  );
}

function viewFromHash(): View {
  const h = window.location.hash.replace("#", "");
  return (ALL_VIEWS.includes(h as View) ? h : "queue") as View;
}

export default function App() {
  const [state, setState] = useState<{ run?: ValuationRun; mode?: Mode; sources?: Sources; error?: string; stale?: boolean; empty?: boolean }>({});
  // a full-page overlay while a workbook switch recomputes, and the note the landing page shows after a reset
  const [switching, setSwitching] = useState(false);
  const [resetNote, setResetNote] = useState<ResetResult | null>(null);
  const afterReset = (r: ResetResult) => {
    setResetNote(r);
    setState({ empty: true });
    window.location.hash = "";
  };
  // the per-company mark archive; refetched with the run because an override moves the live point
  const [history, setHistory] = useState<HistoryState>({});
  // why every rule exists (rules/rationale.yaml); shown on the Rules tab and beside each flag
  const [rationale, setRationale] = useState<Rationale | undefined>(undefined);
  // E-09 drafts for events no rule recognises; the tab exists only while there are some
  const [proposalCount, setProposalCount] = useState(0);
  const [view, setView] = useState<View>(viewFromHash);
  const [focus, setFocus] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  // bumped on every reload so the published-status line refetches after a rerun
  const [reloads, setReloads] = useState(0);

  const reload = useCallback(() => {
    setState((s) => ({ ...s, stale: true }));
    loadRun().then(
      ({ run, mode, sources }) => {
        setState({ run, mode, sources });
        setReloads((n) => n + 1);
        Promise.all([loadHistory(mode).then((data) => ({ data }), (e) => ({ error: String(e?.message ?? e) })), loadSignals(mode)]).then(
          ([h, signals]) => setHistory({ ...h, signals }),
        );
        loadProposals(mode).then((p) => setProposalCount(p.length), () => setProposalCount(0));
        loadRationale(mode).then(setRationale, () => setRationale(undefined));
      },
      (e) =>
        e instanceof NoWorkbookError
          ? setState({ empty: true })
          : setState((s) => ({ ...s, error: String(e?.message ?? e), stale: false })),
    );
  }, []);

  useEffect(reload, [reload]);
  // Self-refreshing page: `hc-valuation run --watch` recomputes when the workbook, policy or a
  // ledger changes; the page notices the new run id and reloads itself. Served mode only.
  useEffect(() => {
    if (state.mode !== "served" || !state.run) return;
    const mine = `${state.run.manifest.run_id}@${state.run.manifest.generated_at}`;
    const t = window.setInterval(async () => {
      const stamp = await currentRunStamp();
      if (stamp && stamp !== mine) reload();
    }, 5000);
    return () => window.clearInterval(t);
  }, [state.mode, state.run, reload]);
  useEffect(() => {
    const on = () => setView(viewFromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const go = (v: View) => {
    window.location.hash = v;
    setView(v);
  };
  const gotoCompany = (name: string) => {
    setFocus(name);
    go("companies");
  };

  if (state.empty && !state.run)
    return (
      <div className="min-h-full flex flex-col">
        <header className="sticky top-0 z-30 bg-surface border-b border-line">
          <div className="px-4 py-2 flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="font-semibold text-[15px] tracking-tight">Quarterly portfolio valuation engine</span>
            <div className="ml-auto">
              <UploadButton onLoaded={reload} primary />
            </div>
          </div>
        </header>
        <main className="flex-1 px-4 py-16 max-w-[720px] w-full mx-auto text-center">
          <h1 className="font-semibold text-[18px] mb-2">No workbook loaded yet</h1>
          <p className="text-[11.5px] text-muted mb-4">
            {resetNote
              ? `Reset cleared ${resetNote.files} file${resetNote.files === 1 ? "" : "s"} — the ledger is empty and nothing is published.`
              : "Nothing has been uploaded yet."}
          </p>
          <p className="text-[13px] text-ink2 mb-6 leading-relaxed">
            Upload the quarter's portfolio workbook — a <span className="mono">Portfolio</span> tab with the book at the prior close and a{" "}
            <span className="mono">Qn YYYY Activity</span> tab with every event in the quarter. The engine rolls every position forward, proposes a
            mark, and puts in front of you everything a person must decide before the quarter can be published.
          </p>
          <UploadButton onLoaded={reload} primary />
        </main>
      </div>
    );
  if (state.error && !state.run)
    return (
      <div className="p-8 max-w-[640px] mx-auto">
        <h1 className="font-semibold text-[16px] mb-2">Could not load the valuation run</h1>
        <p className="text-ink2 mono text-[12px] mb-4">{state.error}</p>
        <p className="text-[12px] text-muted">
          Serve the dashboard with <span className="mono">hc-valuation run</span> (exposes /api/run), or open a static report built with{" "}
          <span className="mono">hc-valuation build</span>, which inlines the run as <span className="mono">window.__HC_RUN__</span>.
        </p>
      </div>
    );
  if (!state.run || !state.mode) return <div className="p-8 text-muted">Loading run…</div>;

  const { run, mode } = state;
  const writeDisabled = mode === "static" ? STATIC_REASON : null;
  const m = run.manifest;
  const blockingIssues = run.validation.filter((v) => v.blocking).length;

  return (
    <SourcesProvider value={state.sources}>
    <RationaleProvider value={rationale}>
    <HistoryProvider value={history}>
    <div className={`min-h-full flex flex-col ${state.stale ? "opacity-70 transition-opacity" : ""}`}>
      <header className="sticky top-0 z-30 bg-surface border-b border-line">
        <div className="px-4 py-2 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 min-w-0">
            <span className="font-semibold text-[15px] tracking-tight">Quarterly portfolio valuation engine</span>
            <span className="text-[13px] font-medium">{m.quarter_label}</span>
          </div>
          <nav className="flex flex-wrap gap-1 ml-2" aria-label="Views">
            {[...VIEWS, ...(proposalCount > 0 || view === "proposals" ? [{ id: "proposals" as View, label: "Proposals" }] : [])].map((v) => (
              <button
                key={v.id}
                onClick={() => go(v.id)}
                className={
                  v.id === "queue"
                    // Activity is where the work is: a size up and semibold, and outlined when it is not the current view
                    ? `px-3 py-1 rounded-md text-[13px] font-semibold ${view === v.id ? "bg-accent text-[var(--accent-ink)]" : "text-ink border border-[var(--accent)] hover:bg-hair"}`
                    : `px-2.5 py-1 rounded-md text-[12px] ${view === v.id ? "bg-accent text-[var(--accent-ink)] font-medium" : "text-ink2 hover:bg-hair"}`
                }
                aria-current={view === v.id ? "page" : undefined}
              >
                {v.label}
                {v.id === "queue" && (run.totals.readiness?.Blocked ?? 0) > 0 && (
                  <span className={`ml-1.5 mono text-[10px] ${view === v.id ? "" : "text-[var(--block-text)]"}`} title="Blocked positions">
                    {run.totals.readiness?.Blocked ?? 0}
                  </span>
                )}
                {v.id === "proposals" && proposalCount > 0 && (
                  <span className={`ml-1.5 mono text-[10px] ${view === v.id ? "" : "text-[var(--review-text)]"}`}>{proposalCount}</span>
                )}
              </button>
            ))}
          </nav>
          {/* the right-hand cluster wraps onto its own line on a narrow screen rather than pushing the page wider */}
          {/* The chrome carries one status system and no filters: the queue filters by readiness
              bucket on its own tiles, and Companies has its own filter bar. A second severity
              filter up here only competed with them. */}
          <div className="ml-auto flex flex-wrap items-center gap-x-2 gap-y-1.5 min-w-0">
            {mode === "served" && <UploadButton onLoaded={reload} />}
            <WorkbookSwitcher served={mode === "served"} refreshKey={reloads} onSwitched={reload} onBusy={setSwitching} />
            <PublishControls run={run} mode={mode} writeDisabled={writeDisabled} refreshKey={reloads} onGoto={gotoCompany} />
            <span
              className={`chip no-dot ${mode === "static" ? "disp-MONITOR" : "disp-CLEAR"} hint`}
              title={mode === "static" ? STATIC_REASON : "Decisions taken here are recorded to the ledger."}
            >
              {mode === "static" ? "Read-only copy" : "Decisions are being recorded"}
            </span>
            {mode === "served" && <ResetButton onReset={afterReset} />}
          </div>
        </div>
        {(m.market_data_source.startsWith("synthetic:") || /synthetic|SYNTHETIC/.test(m.input_file)) && (
          <div
            className="static-banner"
            role="alert"
            style={{ background: "var(--block-wash)", color: "var(--block-text)", borderBottomColor: "var(--block)" }}
          >
            Synthetic test quarter — the workbook <span className="mono">{m.input_file}</span> is invented test data
            {m.market_data_source.startsWith("synthetic:") ? ", and the sector multiples on the Market tab were invented by a script" : ""}.
            Nothing on this page is a real position or a real market observation.
          </div>
        )}
        {mode === "static" && (
          <div className="static-banner" role="note">
            Read-only export — decisions (suggestions, overrides, publish) need the served app: run{" "}
            <span className="mono">hc-valuation run</span>.
          </div>
        )}
      </header>

      {switching && (
        <div className="overlay" role="status" aria-live="polite">
          <div className="overlay-card">
            <span className="spinner spinner-lg" aria-hidden />
            <div>
              <div className="font-semibold text-[13px]">Running the valuation…</div>
              <div className="text-[11.5px] text-muted">Rolling every position forward and screening it. This can take a little while.</div>
            </div>
          </div>
        </div>
      )}
      <main className="flex-1 px-4 py-4 max-w-[1600px] w-full mx-auto">
        {view === "queue" && (
          <QueueView run={run} writeDisabled={writeDisabled} onChanged={reload} gotoCompany={gotoCompany} />
        )}
        {view === "companies" && <CompaniesView run={run} writeDisabled={writeDisabled} onChanged={reload} focus={focus} />}
        {view === "movement" && <MovementView run={run} onGoto={gotoCompany} />}
        {view === "funds" && <FundsView run={run} gotoCompany={gotoCompany} />}
        {view === "market" && <MarketView mode={mode} run={run} onGoto={gotoCompany} />}
        {view === "rules" && <RulesView run={run} gotoCompany={gotoCompany} />}
        {view === "open" && <OpenItemsView run={run} gotoCompany={gotoCompany} />}
        {view === "proposals" && <ProposalsView run={run} mode={mode} writeDisabled={writeDisabled} onChanged={reload} gotoCompany={gotoCompany} />}
      </main>

      {/* The footer used to be eight lowercase `key value` pairs — a log line, not a footer. The
          two dates are the only things a reviewer reads at a glance; everything else is provenance
          that has to stay available (a run id ties a screenshot to a ledger entry, the file
          fingerprint proves which workbook was read) but belongs behind a disclosure. */}
      <footer className="border-t border-line bg-surface px-4 py-2 text-[11px] text-muted flex flex-wrap gap-x-4 gap-y-1 items-center">
        <span>
          Valued at <span className="text-ink2">{shortDate(m.measurement_date)}</span> against the{" "}
          <span className="text-ink2">{shortDate(m.prior_close)}</span> close.
        </span>
        <details className="rundetails">
          <summary>Run details</summary>
          <div className="rundetails-body">
            <div>
              <span>Run reference</span>
              <span className="mono" title={m.run_id}>
                {shortRef(m.run_id, 12)}
              </span>
            </div>
            <div>
              <span>Source workbook</span>
              <span>{m.input_file}</span>
            </div>
            <div>
              <span title="SHA-256 of the workbook this run read — it identifies the exact file, byte for byte">File fingerprint</span>
              <span className="mono" title={m.input_sha256}>
                {shortRef(m.input_sha256, 12)}
              </span>
            </div>
            <div>
              <span>Policy version</span>
              <span className="mono">{m.policy_version}</span>
            </div>
            <div>
              <span>Engine version</span>
              <span className="mono">{m.engine_version}</span>
            </div>
            <div>
              <span>Generated</span>
              <span>{isoDateTime(m.generated_at)}</span>
            </div>
            <div>
              <span>Market data</span>
              <span title={m.market_data_source}>{marketSourceLabel(m.market_data_source)}</span>
            </div>
            <div>
              <span title="When an event matches no marking rule, the engine drafts a suggested treatment beside the blocked position.">
                Drafting for uncovered events
              </span>
              <span>{m.adjudication_enabled ? "On" : "Off"}</span>
            </div>
          </div>
        </details>
        <button className={`btn ml-auto ${blockingIssues ? "disp-BLOCK btn-danger" : ""}`} onClick={() => setDrawer(true)}>
          {run.validation.length === 0
            ? "Data checks: all passed"
            : `Data checks: ${run.validation.length} issue${run.validation.length === 1 ? "" : "s"}${
                blockingIssues > 0 ? ` (${blockingIssues} blocking)` : ""
              }`}
        </button>
      </footer>

      {drawer && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setDrawer(false)} />
          <aside className="drawer p-4" aria-label="Validation issues">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold">Data checks on the workbook</h2>
              <button className="btn btn-ghost" onClick={() => setDrawer(false)}>
                Close
              </button>
            </div>
            {run.validation.length === 0 ? (
              <p className="text-muted text-[12px]">
                None. The workbook passed every ingestion integrity check: every activity row names a known company, prior marks reconcile
                to ownership × post-money within tolerance, no duplicates, no events outside the quarter.
              </p>
            ) : (
              <ul className="space-y-2">
                {run.validation.map((v, i) => (
                  <li key={i} className={`card disp-${v.severity} stripe p-2 pl-3 text-[12px]`}>
                    <div className="flex items-center gap-2">
                      <DispChip d={v.severity} />
                      <span className="mono font-medium">{v.rule_id}</span>
                      {v.company && <span>{v.company}</span>}
                      {v.sheet && (
                        <span className="text-muted">
                          {v.sheet}
                          {v.row_index !== null && ` row ${v.row_index}`}
                        </span>
                      )}
                      {v.blocking && (
                        <span className="ml-auto text-[10px] uppercase tracking-wider text-[var(--block-text)]" title="This has to be fixed before the quarter can be published.">
                          Blocking
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-ink2">{v.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </aside>
        </>
      )}
    </div>
    </HistoryProvider>
    </RationaleProvider>
    </SourcesProvider>
  );
}
