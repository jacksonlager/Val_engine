// The Rules tab: how a position gets its status, drawn; three worked examples from this
// quarter's book, each expandable; and the rule catalogue — why every rule exists, why it
// carries its severity, and what in the workbook fires it (rules/rationale.yaml).
import { useMemo, useState } from "react";
import type { Disposition, RuleRationale, ValuationRun } from "../types";
import { useRationale } from "../lib/rationale";
import { DispChip } from "../components/ui";
import { ARAVINE_SVG, DRAYVENN_SVG, GRYPHONEL_SVG, TREE_SVG } from "../lib/trees";

export function RuleCard({ r, count }: { r: RuleRationale; count?: number }) {
  return (
    <div className="card p-3 flex flex-col gap-1.5" title={`Reads ${r.reads}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="mono font-medium text-[12.5px]">{r.id}</span>
        <span className="font-semibold text-[13px]">{r.name}</span>
        {r.severity.map((s) => (
          <DispChip key={s} d={s} />
        ))}
        {count !== undefined && count > 0 && (
          <span className="ml-auto text-[11px] text-muted mono" title="Positions carrying this flag in the current run">
            ×{count}
          </span>
        )}
      </div>
      <ul className="flag-points m-0">
        <li>
          <b>Flag.</b> {r.why_flag}
        </li>
        <li>
          <b>Severity.</b> {r.why_severity}
        </li>
        {/* The assessment's own wording for the exception, quoted rather than badged. */}
        {r.source === "brief" && r.brief_text && (
          <li>
            <b>Named in the brief.</b> “{r.brief_text}”
          </li>
        )}
      </ul>
      {/* The mechanical condition, last and quieter than the two judgments above it. */}
      {r.trigger && (
        <div className="text-[11.5px] text-muted leading-snug">
          <b className="font-semibold">Trigger.</b> {r.trigger}
        </div>
      )}
    </div>
  );
}

/** Three rows from this quarter's Activity tab through the same six questions, one ending at
    each status. Every figure on them is the engine's: M-040 80.30 → 110.07, M-050 3.50 → 4.66,
    M-010 6.90 → 13.88. Collapsed by default so the general tree above stays the subject. */
const EXAMPLES: { n: number; company: string; outcome: string; d: Disposition; why: string; svg: string }[] = [
  { n: 1, company: "Drayvenn", outcome: "Blocked", d: "BLOCK", why: "An IPO with no quarter-end close on file.", svg: DRAYVENN_SVG },
  { n: 2, company: "Gryphonel", outcome: "Needs Review", d: "REVIEW", why: "A signed acquisition that has not closed.", svg: GRYPHONEL_SVG },
  { n: 3, company: "Aravine", outcome: "Ready", d: "CLEAR", why: "A priced round led by a new investor.", svg: ARAVINE_SVG },
];

function Example({ e }: { e: (typeof EXAMPLES)[number] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card overflow-hidden">
      <button
        type="button"
        className="w-full flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 text-left"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="text-muted text-[11px] mono w-3 shrink-0" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
        <span className="font-semibold text-[13px]">
          Example {e.n}: {e.company}, {e.outcome}
        </span>
        <DispChip d={e.d} />
        <span className="text-[11.5px] text-muted">{e.why}</span>
      </button>
      {open && (
        <div className="px-3 pb-3">
          <div className="tree-fig" dangerouslySetInnerHTML={{ __html: e.svg }} />
        </div>
      )}
    </div>
  );
}

export function RulesView({ run }: { run: ValuationRun; gotoCompany: (n: string) => void }) {
  const rationale = useRationale();
  const [onlyFired, setOnlyFired] = useState(false);

  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    run.companies.forEach((c) => c.flags.forEach((f) => (m[f.rule_id] = (m[f.rule_id] ?? 0) + 1)));
    return m;
  }, [run]);

  const groups = (rationale?.groups ?? []).map((g) => ({
    ...g,
    rules: (rationale?.rules ?? []).filter((r) => r.family === g.key && (!onlyFired || (counts[r.id] ?? 0) > 0)),
  }));

  return (
    <div className="space-y-4">
      {/* ------------------------------------------------------------ how a status is reached */}
      <section>
        <div className="flex items-baseline gap-3 mb-2">
          <h2 className="text-[14px] font-semibold m-0">How a position gets its status</h2>
          <span className="text-[11.5px] text-muted">Six questions, in this order. Each leaf is a status on the queue.</span>
        </div>
        <div className="tree-fig" dangerouslySetInnerHTML={{ __html: TREE_SVG }} />
      </section>

      {/* ------------------------------------------------------------ the same tree, filled in */}
      <section>
        <div className="flex items-baseline gap-3 mb-2">
          <h2 className="text-[14px] font-semibold m-0">Three positions through the same tree</h2>
          <span className="text-[11.5px] text-muted">Real rows from this quarter, one ending at each status. Open one to see its path.</span>
        </div>
        <div className="space-y-2">
          {EXAMPLES.map((e) => (
            <Example key={e.n} e={e} />
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------ the rules */}
      <section>
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <h2 className="text-[14px] font-semibold m-0 mr-2">Flag glossary</h2>
          <label className="flex items-center gap-1.5 text-[12px] cursor-pointer">
            <input type="checkbox" checked={onlyFired} onChange={(e) => setOnlyFired(e.target.checked)} /> only rules that applied this quarter
          </label>
          <span className="text-[11px] text-muted ml-auto leading-snug">
            Severity test: <i>could a reviewer change the booked number?</i>
          </span>
        </div>
        {!rationale ? (
          <div className="card p-4 text-[12.5px] text-ink2">
            <p className="m-0">The rule catalogue did not load, so this page cannot show what each rule is for. Every other page in this run is unaffected.</p>
            <details className="mt-2">
              <summary className="text-[11.5px] text-muted cursor-pointer select-none">Technical details</summary>
              <p className="text-[11.5px] text-muted mt-1 mb-0 leading-snug">
                Neither <span className="mono">/api/rationale</span> answered nor was <span className="mono">window.__HC_RATIONALE__</span> inlined
                into this file. Re-run <span className="mono">hc-valuation run</span> or <span className="mono">hc-valuation build</span> from a tree
                that has <span className="mono">rules/rationale.yaml</span>.
              </p>
            </details>
          </div>
        ) : (
          <div className="space-y-4">
            {groups
              .filter((g) => g.rules.length > 0)
              .map((g) => (
                <div key={g.key}>
                  <h3 className="text-[12.5px] font-semibold m-0">{g.title}</h3>
                  {/* What the family is asking about, so the heading is not the only thing
                      orienting a reviewer who has never seen these ids before. */}
                  {g.description && <p className="text-[11.5px] text-muted m-0 mt-0.5 mb-1.5 leading-snug max-w-[80ch]">{g.description}</p>}
                  <div className="grid grid-cols-3 gap-2 max-[1240px]:grid-cols-2 max-[860px]:grid-cols-1">
                    {g.rules.map((r) => (
                      <RuleCard key={r.id} r={r} count={counts[r.id]} />
                    ))}
                  </div>
                </div>
              ))}
          </div>
        )}
      </section>
    </div>
  );
}
