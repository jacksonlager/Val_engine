import type { ExecView } from "../types";

export type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; view: ExecView }
  | { kind: "empty" }
  | { kind: "error"; message: string };

/** The single-file report inlines the payload as window.__HC_EXEC__; the served site fetches it. */
export async function loadView(): Promise<LoadState> {
  if (window.__HC_EXEC__) return { kind: "ready", view: window.__HC_EXEC__ };
  try {
    const res = await fetch("/api/exec", { headers: { Accept: "application/json" } });
    if (res.status === 404) return { kind: "empty" };
    if (!res.ok) return { kind: "error", message: `The valuation service answered ${res.status}.` };
    const view = (await res.json()) as ExecView;
    return { kind: "ready", view };
  } catch (e) {
    return { kind: "error", message: e instanceof Error ? e.message : "Could not reach the valuation service." };
  }
}
