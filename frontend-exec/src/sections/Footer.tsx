import type { ExecView } from "../types";
import { marketSourceLabel } from "../lib/format";
import { Provenance } from "./Masthead";

export function Footer({ view }: { view: ExecView }) {
  const m = view.meta;
  // provenance a regulator reads: every value still on the page, none of it in machine words
  const items: [string, string, string?][] = [
    ["Run reference", m.run_id],
    ["Source workbook", m.input_file],
    ["File fingerprint", m.input_sha256.slice(0, 12), m.input_sha256],
    ["Policy version", m.policy_version],
    ["Engine version", m.engine_version],
    ["Market data", marketSourceLabel(m.market_data_source), m.market_data_source],
  ];
  return (
    <footer className="border-t border-hair pt-6 pb-14 text-[12px] text-muted">
      <Provenance view={view} className="mb-2" />
      <div className="flex flex-wrap gap-x-6 gap-y-1.5">
        {items.map(([k, v, full]) => (
          <span key={k} title={full}>
            {k} <span className="num text-ink2">{v}</span>
          </span>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-4">
        <span>Prepared by HC Finance from the valuation engine · {m.quarter} marks as of {m.measurement_date}.</span>
        <a href="/" className="whitespace-nowrap">Back-office review →</a>
      </div>
    </footer>
  );
}
