import type { ExecView } from "../types";
import { Provenance } from "./Masthead";

export function Footer({ view }: { view: ExecView }) {
  const m = view.meta;
  const items: [string, string][] = [
    ["Run", m.run_id],
    ["Input", `${m.input_file} · sha256 ${m.input_sha256.slice(0, 12)}`],
    ["Policy", m.policy_version],
    ["Engine", m.engine_version],
    ["Market data", m.market_data_source],
  ];
  return (
    <footer className="border-t border-hair pt-6 pb-14 text-[12px] text-muted">
      <Provenance view={view} className="mb-2" />
      <div className="flex flex-wrap gap-x-6 gap-y-1.5">
        {items.map(([k, v]) => (
          <span key={k}>
            {k} <span className="num text-ink2">{v}</span>
          </span>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-4">
        <span>Prepared by HC Finance from the valuation engine; synthetic data for the September 2026 assessment.</span>
        <a href="/" className="whitespace-nowrap">Back-office review →</a>
      </div>
    </footer>
  );
}
