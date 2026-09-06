// The rule rationale, available to every component: the Rules view lists it, the flag detail
// panel shows the two bullets beside the flag it explains.
import { createContext, useContext, type ReactNode } from "react";
import type { Rationale, RuleRationale } from "../types";

const RationaleCtx = createContext<Rationale | undefined>(undefined);

export function RationaleProvider({ value, children }: { value: Rationale | undefined; children: ReactNode }) {
  return <RationaleCtx.Provider value={value}>{children}</RationaleCtx.Provider>;
}

export function useRationale(): Rationale | undefined {
  return useContext(RationaleCtx);
}

export function useRuleRationale(ruleId: string): RuleRationale | undefined {
  const r = useContext(RationaleCtx);
  return r?.rules.find((x) => x.id === ruleId);
}
