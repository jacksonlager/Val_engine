// Data loading. Two modes:
//   served  — the FastAPI app serves this bundle at '/' and exposes /api/*
//   static  — the run is inlined as window.__HC_RUN__ (hc-valuation build); no API,
//             so every write action is disabled with an explanation.
import type { MarkHistory, MarketReport, Rationale, Signals, OverrideRequest, ProposalDecision, PublishRecord, Sources, TreatmentProposal, UploadJob, ValuationRun, WorkbookProfile } from "../types";

export type Mode = "served" | "static";

export interface Loaded {
  run: ValuationRun;
  mode: Mode;
  /** the served app has no workbook loaded yet: show the empty page with the Upload button */
  empty?: boolean;
  /** Cell provenance. Optional everywhere: an older server or an export without it
      simply means the detail panel shows no references. */
  sources?: Sources;
}

export const STATIC_REASON =
  "Static report: this file was exported without an API. Run `hc-valuation run` to serve the dashboard and record decisions.";

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${url} → ${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j && j.detail) {
        // FastAPI's detail is a string, or an object the publish gate shapes as {message, outstanding, ...}
        detail = typeof j.detail === "string" ? j.detail : typeof j.detail?.message === "string" ? j.detail.message : JSON.stringify(j.detail);
      }
    } catch {
      /* body not JSON */
    }
    throw new Error(detail);
  }
  return (await r.json()) as T;
}

/** Never throws: a server that predates /api/sources, or a failed fetch, is "no references". */
async function loadSources(): Promise<Sources | undefined> {
  try {
    const s = await getJson<Sources>("/api/sources");
    return s && s.workbook && s.sheets ? s : undefined;
  } catch {
    return undefined;
  }
}

export class NoWorkbookError extends Error {}

export async function loadRun(): Promise<Loaded> {
  if (window.__HC_RUN__) return { run: window.__HC_RUN__, mode: "static", sources: window.__HC_SOURCES__ };
  const r = await fetch("/api/run", { headers: { Accept: "application/json" } });
  if (r.status === 404) throw new NoWorkbookError("No workbook loaded yet.");
  if (!r.ok) throw new Error(`/api/run → ${r.status} ${r.statusText}`);
  const run = (await r.json()) as ValuationRun;
  const sources = await loadSources();
  return { run, mode: "served", sources };
}

/** Start an upload; the server answers with a job to poll. */
export async function uploadWorkbook(file: File): Promise<{ id: string; total: number; stages: string[] }> {
  const body = new FormData();
  body.append("file", file, file.name);
  const r = await fetch("/api/upload", { method: "POST", body });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : j.detail?.message ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return (await r.json()) as { id: string; total: number; stages: string[] };
}

export async function uploadStatus(id: string): Promise<UploadJob> {
  return getJson<UploadJob>(`/api/upload/${encodeURIComponent(id)}`);
}

export const NO_MARKET_REASON =
  "No market data: neither /api/market answered nor was window.__HC_MARKET__ inlined into this file.";

/** The sector comps report (docs/market-feed.md §3). Served: GET /api/market; static: the
    object `hc-valuation build` inlines as window.__HC_MARKET__. An export made before the
    market feed existed has neither, which the view explains rather than rendering blank. */
export async function loadMarket(mode: Mode): Promise<MarketReport> {
  if (mode === "static" || window.__HC_RUN__) {
    if (window.__HC_MARKET__) return window.__HC_MARKET__;
    throw new Error(NO_MARKET_REASON);
  }
  return getJson<MarketReport>("/api/market");
}

export const NO_HISTORY_REASON =
  "No mark history: neither /api/history answered nor was window.__HC_HISTORY__ inlined into this file.";

/** The per-company quarter-over-quarter archive (api/history.py). Served: GET /api/history;
    static: the object `hc-valuation build` inlines as window.__HC_HISTORY__. Reloaded with the
    run, because an override moves this quarter's live point. */
export async function loadHistory(mode: Mode): Promise<MarkHistory> {
  if (mode === "static" || window.__HC_RUN__) {
    if (window.__HC_HISTORY__) return window.__HC_HISTORY__;
    throw new Error(NO_HISTORY_REASON);
  }
  return getJson<MarkHistory>("/api/history");
}

/** Vendor context beside a position (api/signals.py). Never throws: no feed = no card. */
export async function loadSignals(mode: Mode): Promise<Signals | undefined> {
  if (mode === "static" || window.__HC_RUN__) return window.__HC_SIGNALS__;
  try {
    return await getJson<Signals>("/api/signals");
  } catch {
    return undefined;
  }
}

/** The two bullets behind every rule (rules/rationale.yaml). Never throws: an older server
    or an export without it just means the Rules tab explains itself as unavailable. */
export async function loadRationale(mode: Mode): Promise<Rationale | undefined> {
  if (mode === "static" || window.__HC_RUN__) return window.__HC_RATIONALE__;
  try {
    return await getJson<Rationale>("/api/rationale");
  } catch {
    return undefined;
  }
}

/** Identifies the run the server currently holds — run id plus generation time, because a
    ledger change re-runs without changing the id — for the self-refreshing page
    (`hc-valuation run --watch`). */
export async function currentRunStamp(): Promise<string | null> {
  try {
    const h = await getJson<{ run_id: string; generated_at: string }>("/api/health");
    return h.run_id ? `${h.run_id}@${h.generated_at}` : null;
  } catch {
    return null;
  }
}

export async function loadProposals(mode: Mode): Promise<TreatmentProposal[]> {
  if (mode === "static") return window.__HC_PROPOSALS__ ?? [];
  try {
    const data = await getJson<TreatmentProposal[] | { proposals: TreatmentProposal[] }>("/api/proposals");
    return Array.isArray(data) ? data : data.proposals ?? [];
  } catch (e) {
    // A 404 means the server predates E-09; treat as "none" rather than an error.
    if (String(e).includes("404")) return [];
    throw e;
  }
}

export function proposalId(p: TreatmentProposal): string {
  return p.proposal_id ?? p.id ?? p.event_signature;
}

export async function decideProposal(id: string, decision: ProposalDecision): Promise<unknown> {
  return postJson(`/api/proposals/${encodeURIComponent(id)}/decision`, decision);
}

export async function postOverride(req: OverrideRequest): Promise<unknown> {
  return postJson("/api/overrides", req);
}

/** Freeze the current booked marks as the executive snapshot for this quarter. */
export async function publishRun(approver: string, note: string): Promise<PublishRecord> {
  return postJson<PublishRecord>("/api/publish", { approver, note });
}

/** Every quarter released to executives, newest first. A server without the publish
    gate (404) is "nothing published" rather than an error. */
export async function fetchPublished(): Promise<PublishRecord[]> {
  try {
    const data = await getJson<PublishRecord[]>("/api/published");
    return Array.isArray(data) ? data : [];
  } catch (e) {
    if (String(e).includes("404")) return [];
    throw e;
  }
}

/** The workbooks the server can switch between. A server without the route (404) offers none. */
export async function fetchWorkbooks(): Promise<WorkbookProfile[]> {
  try {
    const data = await getJson<{ workbooks: WorkbookProfile[] }>("/api/workbooks");
    return Array.isArray(data?.workbooks) ? data.workbooks : [];
  } catch (e) {
    if (String(e).includes("404")) return [];
    throw e;
  }
}

/** Switch the served run to another workbook (its quarter's policy and its own ledger come with it).
    The server recomputes and answers with the new run id; the page then reloads the run. */
export async function selectWorkbook(id: string): Promise<{ run_id: string; quarter: string }> {
  return postJson("/api/workbook", { id });
}
