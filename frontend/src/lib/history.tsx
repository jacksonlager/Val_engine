// The per-company mark archive for the detail panel's history chart.
//
// Loaded once per run load (App) and handed down by context, like cell provenance: a
// server without /api/history, or an export made before the archive existed, simply
// means the card explains that instead of rendering an empty chart.
import { createContext, useContext, type ReactNode } from "react";
import type { MarkHistory } from "../types";

export interface HistoryState {
  data?: MarkHistory;
  error?: string;
}

const HistoryCtx = createContext<HistoryState>({});

export function HistoryProvider({ value, children }: { value: HistoryState; children: ReactNode }) {
  return <HistoryCtx.Provider value={value}>{children}</HistoryCtx.Provider>;
}

export function useHistory(): HistoryState {
  return useContext(HistoryCtx);
}
