import type { ExecView } from "../types";
import { longDate, plural } from "../lib/format";

export const NAV = [
  ["headline", "Headline"],
  ["bridge", "Bridge"],
  ["movers", "Movers"],
  ["decisions", "Decisions"],
  ["funds", "Funds"],
  ["composition", "Composition"],
  ["risk", "Risk watch"],
  ["sensitivity", "Sensitivity"],
  ["activity", "Activity"],
  ["marks", "All marks"],
] as const;

/** The one provenance line: measurement date, the run and when it was generated, the release.
    Used by the masthead and the footer so the report never shows two competing dates. */
export function Provenance({ view, className = "" }: { view: ExecView; className?: string }) {
  const m = view.meta;
  return (
    <div className={`text-[12px] text-muted ${className}`}>
      As of <span className="text-ink2">{longDate(m.measurement_date)}</span> (measurement date)
      {" · "}run <span className="num text-ink2">{m.run_id}</span> generated <span className="text-ink2">{longDate(m.generated_at)}</span>
      {" · "}published <span className="text-ink2">{longDate(m.published_at)}</span>
      {m.published_by ? <> by <span className="text-ink2">{m.published_by}</span></> : null}
    </div>
  );
}

function StatusBadge({ view, compact = false }: { view: ExecView; compact?: boolean }) {
  const proposed = view.meta.status === "proposed";
  const n = view.decisions.length;
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-[3px] font-semibold uppercase tracking-[0.08em] ${
        compact ? "h-6 px-2 text-[10.5px]" : "h-7 px-2.5 text-[11px]"
      }`}
      style={{
        color: proposed ? "var(--review-text)" : "var(--clear-text)",
        background: proposed ? "var(--review-wash)" : "var(--clear-wash)",
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: "currentColor" }} />
      {proposed ? "Proposed" : "Final"}
      {proposed && !compact && n > 0 && (
        <span className="normal-case tracking-normal font-medium text-ink2">
          · {plural(n, "position")} await a committee decision
        </span>
      )}
    </span>
  );
}

export function TopBar({ view }: { view: ExecView }) {
  return (
    <header className="sticky top-0 z-20 border-b border-hair" style={{ background: "var(--ground)" }}>
      <div className="max-w-page mx-auto px-8 h-12 flex items-center gap-6">
        <a href="#top" className="flex items-baseline gap-2 text-ink hover:no-underline shrink-0">
          <span className="display font-bold text-[14px] tracking-[-0.01em]">Human Capital</span>
          <span className="text-muted text-[12px]">{view.meta.quarter} valuation</span>
        </a>
        <nav className="flex items-center gap-1 ml-auto overflow-x-auto" aria-label="Sections">
          {NAV.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className="px-2.5 h-7 inline-flex items-center rounded-[3px] text-[12px] text-ink2 hover:text-ink hover:bg-raised hover:no-underline whitespace-nowrap"
            >
              {label}
            </a>
          ))}
        </nav>
        <StatusBadge view={view} compact />
      </div>
    </header>
  );
}

export function Masthead({ view }: { view: ExecView }) {
  const m = view.meta;
  const proposed = m.status !== "final";
  return (
    <div id="top" className="pt-12 pb-10">
      <div className="eyebrow mb-3">{m.firm} · Investment committee pre-read</div>
      <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-4">
        <div>
          <h1 className="display text-[44px] font-bold leading-[1.02] tracking-[-0.025em] text-ink">
            {m.quarter} valuation
          </h1>
          <div className="mt-3 text-[15px] text-ink2">
            {proposed ? "Proposed" : "Final"} marks as at <span className="text-ink font-medium">{longDate(m.measurement_date)}</span>, moved from the{" "}
            {longDate(m.prior_close)} close, shown after any committee override.
          </div>
          {proposed && (
            <div className="mt-2 text-[12.5px] text-muted max-w-[68ch]">
              A pre-read released before the committee sat: the review tool's own Publish stays locked until every decision and
              confirmation is recorded, so this snapshot was released deliberately as <span className="text-ink2">proposed</span>{" "}
              (from the command line) for the reading ahead of the meeting.
            </div>
          )}
        </div>
        <div className="flex flex-col items-start gap-2 text-[12px] text-muted">
          <StatusBadge view={view} />
          <Provenance view={view} />
          {m.note ? <div>“{m.note}”</div> : null}
        </div>
      </div>
    </div>
  );
}
