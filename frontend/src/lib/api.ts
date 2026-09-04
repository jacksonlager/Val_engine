// Data loading. Two modes:
//   served  — the FastAPI app serves this bundle at '/' and exposes /api/*
//   static  — the run is inlined as window.__HC_RUN__ (hc-valuation build); no API,
//             so every write action is disabled with an explanation.
import type { OverrideRequest, ProposalDecision, PublishRecord, Sources, TreatmentProposal, ValuationRun } from "../types";

export type Mode = "served" | "static";

export interface Loaded {
  run: ValuationRun;
  mode: Mode;
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
      if (j && j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
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

export async function loadRun(): Promise<Loaded> {
  if (window.__HC_RUN__) return { run: window.__HC_RUN__, mode: "static", sources: window.__HC_SOURCES__ };
  const [run, sources] = await Promise.all([getJson<ValuationRun>("/api/run"), loadSources()]);
  return { run, mode: "served", sources };
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
