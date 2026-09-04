import { useCallback, useEffect, useState } from "react";
import type { Disposition, Sources, ValuationRun } from "./types";
import { DISPOSITION_HINT, DISPOSITIONS } from "./types";
import { currentRunStamp, loadHistory, loadRun, loadSignals, STATIC_REASON, type Mode } from "./lib/api";
import { HistoryProvider, type HistoryState } from "./lib/history";
import { SourcesProvider } from "./lib/sources";
import { isoDateTime, shortSha } from "./lib/format";
import { DispChip } from "./components/ui";
import { PublishControls } from "./components/Publish";
import { QueueView } from "./views/Queue";
import { CompaniesView } from "./views/Companies";
import { MovementView } from "./views/Movement";
import { FundsView } from "./views/Funds";
import { OpenItemsView } from "./views/OpenItems";
import { ProposalsView } from "./views/Proposals";
import { MarketView } from "./views/Market";

type View = "queue" | "companies" | "movement" | "funds" | "market" | "open" | "proposals";
const VIEWS: { id: View; label: string }[] = [
  { id: "queue", label: "Queue" },
  { id: "companies", label: "Companies" },
  { id: "movement", label: "Movement" },
  { id: "funds", label: "Funds" },
  { id: "market", label: "Market" },
  { id: "open", label: "Open items" },
  { id: "proposals", label: "Proposals" },
];

function viewFromHash(): View {
  const h = window.location.hash.replace("#", "");
  return (VIEWS.find((v) => v.id === h)?.id ?? "queue") as View;
}

export default function App() {
  const [state, setState] = useState<{ run?: ValuationRun; mode?: Mode; sources?: Sources; error?: string; stale?: boolean }>({});
  // the per-company mark archive; refetched with the run because an override moves the live point
  const [history, setHistory] = useState<HistoryState>({});
  const [view, setView] = useState<View>(viewFromHash);
  const [filter, setFilter] = useState<Disposition | "ALL">("ALL");
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
      },
      (e) => setState((s) => ({ ...s, error: String(e?.message ?? e), stale: false })),
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
    setFilter("ALL");
    setFocus(name);
    go("companies");
  };

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
    <HistoryProvider value={history}>
    <div className={`min-h-full flex flex-col ${state.stale ? "opacity-70 transition-opacity" : ""}`}>
      <header className="sticky top-0 z-30 bg-surface border-b border-line">
        <div className="px-4 py-2 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 min-w-0">
            <span className="font-semibold text-[15px] tracking-tight">Quarterly portfolio valuation engine</span>
            <span className="text-[13px] font-medium">{m.quarter_label}</span>
            <span className="text-[11px] text-muted mono">policy {m.policy_version}</span>
            <span className="text-[11px] text-muted mono" title={`input sha256 ${m.input_sha256}`}>
              run {m.run_id}
            </span>
          </div>
          <nav className="flex flex-wrap gap-1 ml-2" aria-label="Views">
            {VIEWS.map((v) => (
              <button
                key={v.id}
                onClick={() => go(v.id)}
                className={`px-2.5 py-1 rounded-md text-[12px] ${view === v.id ? "bg-accent text-[var(--accent-ink)] font-medium" : "text-ink2 hover:bg-hair"}`}
                aria-current={view === v.id ? "page" : undefined}
              >
                {v.label}
                {v.id === "queue" && run.totals.dispositions.BLOCK > 0 && (
                  <span className={`ml-1.5 mono text-[10px] ${view === v.id ? "" : "text-[var(--block-text)]"}`}>{run.totals.dispositions.BLOCK}</span>
                )}
              </button>
            ))}
          </nav>
          {/* the right-hand cluster wraps onto its own line on a narrow screen rather than pushing the page wider */}
          <div className="ml-auto flex flex-wrap items-center gap-x-2 gap-y-1.5 min-w-0">
            <label className="text-[11px] text-muted">Disposition</label>
            <div className="dfilter" role="group" aria-label="Disposition filter">
              <button className={`btn ${filter === "ALL" ? "btn-primary" : ""}`} onClick={() => setFilter("ALL")}>
                All
              </button>
              {DISPOSITIONS.map((d) => (
                <button
                  key={d}
                  className={`btn disp-${d} ${filter === d ? "" : "btn-ghost"}`}
                  title={`${d} · ${DISPOSITION_HINT[d]}`}
                  aria-label={`${d} (${run.totals.dispositions[d] ?? 0})`}
                  style={filter === d ? { background: "var(--cw)", borderColor: "var(--c)", color: "var(--ct)" } : undefined}
                  onClick={() => setFilter(filter === d ? "ALL" : d)}
                  aria-pressed={filter === d}
                >
                  <span className="dfilter-dot" aria-hidden />
                  <span className="dfilter-label">{d}</span>
                  <span className="mono text-[10px] opacity-80">{run.totals.dispositions[d] ?? 0}</span>
                </button>
              ))}
            </div>
            <span className="border-l border-line h-4 mx-1" aria-hidden />
            <PublishControls run={run} mode={mode} writeDisabled={writeDisabled} refreshKey={reloads} />
            <span
              className={`chip no-dot ${mode === "static" ? "disp-MONITOR" : "disp-CLEAR"} hint`}
              title={mode === "static" ? STATIC_REASON : "Connected to the API; decisions are recorded to the ledger"}
            >
              {mode === "static" ? "static report" : "served"}
            </span>
          </div>
        </div>
        {mode === "static" && (
          <div className="static-banner" role="note">
            Read-only export — decisions (suggestions, overrides, publish) need the served app: run{" "}
            <span className="mono">hc-valuation run</span>.
          </div>
        )}
      </header>

      <main className="flex-1 px-4 py-4 max-w-[1600px] w-full mx-auto">
        {view === "queue" && (
          <QueueView run={run} filter={filter} setFilter={setFilter} writeDisabled={writeDisabled} onChanged={reload} gotoCompany={gotoCompany} />
        )}
        {view === "companies" && <CompaniesView run={run} filter={filter} writeDisabled={writeDisabled} onChanged={reload} focus={focus} />}
        {view === "movement" && <MovementView run={run} />}
        {view === "funds" && <FundsView run={run} gotoCompany={gotoCompany} />}
        {view === "market" && <MarketView mode={mode} />}
        {view === "open" && <OpenItemsView run={run} gotoCompany={gotoCompany} />}
        {view === "proposals" && <ProposalsView run={run} mode={mode} writeDisabled={writeDisabled} onChanged={reload} gotoCompany={gotoCompany} />}
      </main>

      <footer className="border-t border-line bg-surface px-4 py-2 text-[11px] text-muted flex flex-wrap gap-x-5 gap-y-1 items-center">
        <span>
          run <span className="mono text-ink2">{m.run_id}</span>
        </span>
        <span title={m.input_sha256}>
          input <span className="mono text-ink2">{m.input_file}</span> sha256 <span className="mono text-ink2">{shortSha(m.input_sha256, 12)}</span>
        </span>
        <span>
          policy <span className="mono text-ink2">{m.policy_version}</span>
        </span>
        <span>
          engine <span className="mono text-ink2">{m.engine_version}</span>
        </span>
        <span>
          generated <span className="mono text-ink2">{isoDateTime(m.generated_at)}</span>
        </span>
        <span>
          measurement <span className="mono text-ink2">{m.measurement_date}</span> · prior close <span className="mono text-ink2">{m.prior_close}</span>
        </span>
        <span>
          market data <span className="mono text-ink2">{m.market_data_source}</span>
        </span>
        <span>
          adjudication <span className="mono text-ink2">{m.adjudication_enabled ? "enabled" : "disabled"}</span>
        </span>
        <button className={`btn ml-auto ${blockingIssues ? "disp-BLOCK btn-danger" : ""}`} onClick={() => setDrawer(true)}>
          validation issues <span className="mono">{run.validation.length}</span>
          {blockingIssues > 0 && <span className="mono">({blockingIssues} blocking)</span>}
        </button>
      </footer>

      {drawer && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setDrawer(false)} />
          <aside className="drawer p-4" aria-label="Validation issues">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold">Validation issues (X-9xx)</h2>
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
                      {v.blocking && <span className="ml-auto text-[10px] uppercase tracking-wider text-[var(--block-text)]">blocking</span>}
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
    </SourcesProvider>
  );
}
