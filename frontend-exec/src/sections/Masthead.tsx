import type { ExecView } from "../types";
import { dateTime, longDate, plural } from "../lib/format";

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
] as const;

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
    <header className="sticky top-0 z-20 border-b border-hair" style={{ background: "color-mix(in srgb, var(--ground) 88%, transparent)", backdropFilter: "blur(10px)" }}>
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
  return (
    <div id="top" className="pt-12 pb-10">
      <div className="eyebrow mb-3">{m.firm} · Investment committee pre-read</div>
      <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-4">
        <div>
          <h1 className="display text-[44px] font-bold leading-[1.02] tracking-[-0.025em] text-ink">
            {m.quarter} valuation
          </h1>
          <div className="mt-3 text-[15px] text-ink2">
            Marks proposed as at <span className="text-ink font-medium">{longDate(m.measurement_date)}</span>, moved from the{" "}
            {longDate(m.prior_close)} close. Booked marks shown, after any committee override.
          </div>
        </div>
        <div className="flex flex-col items-start gap-2 text-[12px] text-muted">
          <StatusBadge view={view} />
          <div>
            Published {dateTime(m.published_at)}
            {m.published_by ? ` by ${m.published_by}` : ""}
            {m.note ? <span> · “{m.note}”</span> : null}
          </div>
        </div>
      </div>
    </div>
  );
}
