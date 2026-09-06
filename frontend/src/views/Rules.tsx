// The Rules tab: how a position gets its label, why every rule exists and why it carries its
// severity (rules/rationale.yaml, tagged by whether the brief named it), and the exact reasons
// behind every flagged company in this run — the page an auditor reads before the queue.
import { useMemo, useState } from "react";
import type { CompanyResult, Disposition, RuleRationale, ValuationRun } from "../types";
import { useRationale } from "../lib/rationale";
import { musd } from "../lib/format";
import { DispChip, EscalatedChip, escalatedReviewFamilies } from "../components/ui";

const DISP_ORDER: Record<Disposition, number> = { BLOCK: 0, REVIEW: 1, MONITOR: 2, CLEAR: 3 };

/** Which check in disposition() decided this position, in the reviewer's words. */
export function whyDisposition(c: CompanyResult): string {
  const addressed = new Set(c.override?.rule_ids_addressed ?? []);
  const blocks = c.flags.filter((f) => f.severity === "BLOCK" && !addressed.has(f.rule_id));
  const families = [...new Set(c.flags.filter((f) => f.severity === "REVIEW" && !addressed.has(f.rule_id)).map((f) => f.family))].sort();
  const terminal = c.status_after !== "Active";
  if (blocks.length) return `BLOCK flag on the position (${blocks.map((f) => f.rule_id).join(", ")})`;
  if (terminal && families.length === 0 && !c.flags.some((f) => f.severity === "MONITOR")) return "terminal, nothing left to check";
  if (families.length >= 2 && !c.override) return `escalated — ${families.length} REVIEW families (${families.join(" + ")})`;
  if (families.length) return `one REVIEW family (${families[0]})`;
  if (c.override) return "overridden — the decision stays visible";
  if (c.flags.some((f) => f.severity === "MONITOR")) return "MONITOR flags only";
  return "no flag fired";
}

function SourceTag({ r }: { r: RuleRationale }) {
  return r.source === "brief" ? (
    <span className="rtag rtag-brief" title={`The brief names this exception: “${r.brief_text}”`}>
      in the brief
    </span>
  ) : (
    <span className="rtag rtag-ours" title="A rule we added; the two bullets are its defence">
      our call
    </span>
  );
}

export function RuleCard({ r, count }: { r: RuleRationale; count?: number }) {
  return (
    <div className="card p-3 flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="mono font-medium text-[12.5px]">{r.id}</span>
        <span className="font-semibold text-[13px]">{r.name}</span>
        {r.severity.map((s) => (
          <DispChip key={s} d={s} />
        ))}
        <span className="ml-auto flex items-center gap-2">
          {count !== undefined && count > 0 && (
            <span className="text-[11px] text-muted mono" title="Positions carrying this flag in the current run">
              ×{count}
            </span>
          )}
          <SourceTag r={r} />
        </span>
      </div>
      <div className="mono text-[10.5px] text-muted">
        family {r.family} · reads {r.reads}
      </div>
      <ul className="flag-points m-0">
        <li>
          <b>Why it is a flag.</b> {r.why_flag}
        </li>
        <li>
          <b>Why this severity.</b> {r.why_severity}
        </li>
      </ul>
    </div>
  );
}

const STEPS: { q: string; a: string; d: Disposition }[] = [
  { q: "Any BLOCK flag no override has addressed?", a: "The engine has a number but will not book it until a named person decides.", d: "BLOCK" },
  { q: "Terminal (exited, written off) with no REVIEW and no MONITOR left?", a: "Nothing left to check on a company that no longer exists.", d: "CLEAR" },
  { q: "REVIEW flags from two or more different families?", a: "Two independent reasons to doubt one number compound to a committee decision (escalation).", d: "BLOCK" },
  { q: "Any REVIEW flag?", a: "The number stands; a human confirms it.", d: "REVIEW" },
  { q: "Any MONITOR flag, or an override on file?", a: "Booked. Visible on the queue, nothing to decide.", d: "MONITOR" },
  { q: "Otherwise", a: "Booked, no flags.", d: "CLEAR" },
];

export function RulesView({ run, gotoCompany }: { run: ValuationRun; gotoCompany: (n: string) => void }) {
  const rationale = useRationale();
  const [source, setSource] = useState<"" | "brief" | "policy">("");
  const [onlyFired, setOnlyFired] = useState(false);
  const [q, setQ] = useState("");

  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    run.companies.forEach((c) => c.flags.forEach((f) => (m[f.rule_id] = (m[f.rule_id] ?? 0) + 1)));
    return m;
  }, [run]);

  const flagged = useMemo(
    () =>
      run.companies
        .filter((c) => c.disposition !== "CLEAR")
        .filter((c) => !q || `${c.company} ${c.flags.map((f) => f.rule_id).join(" ")}`.toLowerCase().includes(q.toLowerCase()))
        .slice()
        .sort((a, b) => DISP_ORDER[a.disposition] - DISP_ORDER[b.disposition] || a.company.localeCompare(b.company)),
    [run, q],
  );

  if (!rationale)
    return (
      <div className="card p-4 text-[12.5px] text-ink2">
        No rule rationale is available: neither <span className="mono">/api/rationale</span> answered nor was{" "}
        <span className="mono">window.__HC_RATIONALE__</span> inlined into this file. Re-run <span className="mono">hc-valuation run</span> or{" "}
        <span className="mono">hc-valuation build</span> from a tree that has <span className="mono">rules/rationale.yaml</span>.
      </div>
    );

  const groups = rationale.groups.map((g) => ({
    ...g,
    rules: rationale.rules.filter((r) => r.family === g.key && (!source || r.source === source) && (!onlyFired || (counts[r.id] ?? 0) > 0)),
  }));
  const briefCount = rationale.rules.filter((r) => r.source === "brief").length;

  return (
    <div className="space-y-4">
      {/* ------------------------------------------------------------ the filter */}
      <section>
        <div className="flex items-baseline gap-3 mb-2">
          <h2 className="text-[14px] font-semibold m-0">How a position gets its label</h2>
          <span className="text-[11.5px] text-muted">
            <span className="mono">disposition()</span> · six checks in order, the first that matches wins · policy{" "}
            <span className="mono">{run.manifest.policy_version}</span>
          </span>
        </div>
        <div className="card p-0 overflow-hidden">
          <ol className="m-0 p-0 list-none">
            {STEPS.map((s, i) => (
              <li key={i} className="grid grid-cols-[28px_1fr_auto] items-baseline gap-3 px-3 py-2 border-b border-hairline last:border-b-0 text-[12.5px]">
                <span className="mono text-[11px] text-muted">{String(i + 1).padStart(2, "0")}</span>
                <span>
                  <span className="font-medium">{s.q}</span> <span className="text-ink2">{s.a}</span>
                </span>
                <DispChip d={s.d} />
              </li>
            ))}
          </ol>
        </div>
        <p className="text-[11.5px] text-muted mt-2 mb-0 leading-snug max-w-[92ch]">
          A flag is a rule id, a severity and a <b>family</b>; the family is what step 3 counts. Two REVIEWs from the same family (a stale round and
          a stale-round screen) stay REVIEW; two from different families (stale + shrinking ARR) compound to BLOCK. A terminal position drops its
          carry-side screens — staleness, growth, runway, multiples mean nothing for a company that no longer exists — but keeps every BLOCK and
          every event-driven flag. An override names the flags it resolves; those stop waiting, the rest still count.
        </p>
      </section>

      {/* ------------------------------------------------------------ the rules */}
      <section>
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <h2 className="text-[14px] font-semibold m-0 mr-2">Why each rule exists, and why that severity</h2>
          <select className="select" value={source} onChange={(e) => setSource(e.target.value as "" | "brief" | "policy")}>
            <option value="">Brief and our call</option>
            <option value="brief">In the brief ({briefCount})</option>
            <option value="policy">Our call ({rationale.rules.length - briefCount})</option>
          </select>
          <label className="flex items-center gap-1.5 text-[12px] cursor-pointer">
            <input type="checkbox" checked={onlyFired} onChange={(e) => setOnlyFired(e.target.checked)} /> only rules that fired this quarter
          </label>
          <span className="text-[11px] text-muted ml-auto max-w-[60ch] text-right leading-snug">
            <span className="rtag rtag-brief">in the brief</span> = one of the five exceptions the assessment names. <span className="rtag rtag-ours">our call</span> = a
            rule we added and must defend. Severity test: <i>could a reviewer change the booked number?</i>
          </span>
        </div>
        <div className="space-y-4">
          {groups
            .filter((g) => g.rules.length > 0)
            .map((g) => (
              <div key={g.key}>
                <div className="flex items-baseline gap-2 mb-1.5">
                  <h3 className="text-[12.5px] font-semibold m-0">{g.title}</h3>
                  <span className="mono text-[10.5px] text-muted">family {g.key}</span>
                  {g.brief_text && <span className="text-[11px] text-muted italic">— “{g.brief_text}”</span>}
                </div>
                <div className="grid grid-cols-2 gap-2 max-[1100px]:grid-cols-1">
                  {g.rules.map((r) => (
                    <RuleCard key={r.id} r={r} count={counts[r.id]} />
                  ))}
                </div>
              </div>
            ))}
        </div>
      </section>

      {/* ------------------------------------------------------------ the companies */}
      <section>
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <h2 className="text-[14px] font-semibold m-0 mr-2">Every flagged company, and exactly why</h2>
          <input className="input w-[240px]" placeholder="Filter by company or rule id…" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="text-[11px] text-muted ml-auto">
            {flagged.length} of {run.companies.length} positions carry a flag · {run.companies.length - run.companies.filter((c) => c.disposition !== "CLEAR").length} CLEAR
          </span>
        </div>
        <div className="card dtable-wrap">
          <table className="dtable text-[12px]">
            <thead>
              <tr>
                <th>Company</th>
                <th>Disposition · which check decided it</th>
                <th>Flags · the engine's reason</th>
              </tr>
            </thead>
            <tbody>
              {flagged.map((c) => {
                const n = escalatedReviewFamilies(c);
                return (
                  <tr key={c.company} className="row" onClick={() => gotoCompany(c.company)} title="Open in Companies">
                    <td className="align-top">
                      <div className="font-medium">{c.company}</div>
                      <div className="mono text-[10.5px] text-muted">
                        {[...new Set(c.steps.map((s) => s.rule_id))].join(", ")} · {musd(c.prior_mark)} → {musd(c.proposed_mark)}
                      </div>
                    </td>
                    <td className="align-top">
                      <span className="inline-flex items-center gap-1">
                        <DispChip d={c.disposition} />
                        <EscalatedChip n={n} short />
                      </span>
                      <div className="text-[11px] text-muted mt-0.5 whitespace-normal max-w-[260px]">{whyDisposition(c)}</div>
                    </td>
                    <td className="align-top whitespace-normal min-w-[420px]">
                      {c.flags.map((f) => (
                        <div key={f.rule_id} className="flex items-baseline gap-2 py-0.5">
                          <span className={`chip disp-${f.severity} shrink-0`}>
                            <span className="mono">{f.rule_id}</span>
                          </span>
                          <span className="text-ink2 leading-snug">{firstSentence(f.message)}</span>
                        </div>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function firstSentence(m: string): string {
  const s = m.replace(/\*\*/g, "").trim().split(/(?<=[.!?])\s/)[0];
  return s.length > 180 ? s.slice(0, 177).replace(/\s\S*$/, "") + "…" : s;
}
