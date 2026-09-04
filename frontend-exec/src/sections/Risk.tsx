import type { ExecView, RiskRow } from "../types";
import { Section, Empty } from "../components/ui";
import { money, plural } from "../lib/format";

function RiskList({
  title,
  threshold,
  rows,
  metric,
}: {
  title: string;
  threshold: string;
  rows: RiskRow[];
  metric: (r: RiskRow) => { value: string; label: string };
}) {
  const total = rows.reduce((s, r) => s + r.booked, 0);
  return (
    <div className="frame flex flex-col">
      <div className="px-4 pt-3.5 pb-2.5 border-b border-hair">
        <div className="flex items-baseline justify-between gap-3">
          <div className="text-[13px] font-medium text-ink">{title}</div>
          <div className="text-[11px] text-muted">{threshold}</div>
        </div>
        <div className="text-[12px] text-ink2 mt-0.5">
          {plural(rows.length, "position")} · <span className="num text-ink">{money(total, 1)}</span> booked
        </div>
      </div>
      {rows.length === 0 ? (
        <Empty>Nothing on this list.</Empty>
      ) : (
        <ul>
          {rows.map((r) => {
            const m = metric(r);
            return (
              <li key={r.company} className="px-4 py-2.5 border-b border-hair last:border-b-0 flex gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-ink font-medium">{r.company} <span className="text-muted font-normal text-[11.5px]">{r.fund}</span></span>
                    <span className="num text-ink2 text-[12.5px] whitespace-nowrap">{money(r.booked, 1)}</span>
                  </div>
                  <div className="text-[12px] text-ink2 leading-snug mt-0.5" title={r.detail}>{firstSentence(r.detail)}</div>
                </div>
                <div className="w-[62px] shrink-0 text-right pt-0.5">
                  <div className="num text-[15px] font-semibold text-ink leading-none">{m.value}</div>
                  <div className="text-[10.5px] text-muted mt-1">{m.label}</div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** The engine's message is a paragraph; the list shows its first sentence (the evidence), the rest on hover. */
function firstSentence(s: string): string {
  const m = /^(.+?[.!?])(\s|$)/.exec(s);
  return m ? m[1] : s;
}

const n = (v: unknown, d: number) => (typeof v === "number" ? v.toFixed(d) : "—");

export function Risk({ view }: { view: ExecView }) {
  const r = view.risk_watch;
  return (
    <Section
      id="risk"
      eyebrow="Risk watch"
      title="Positions the engine is watching"
      aside={<>Raised from the operating data in the workbook; each item is already on the review queue. Marks stand until the committee acts.</>}
    >
      <div className="grid grid-cols-3 gap-3 max-[1180px]:grid-cols-1 items-start">
        <RiskList
          title="Short runway"
          threshold="under 6 months of cash"
          rows={r.short_runway}
          metric={(x) => ({ value: n(x.evidence.runway_months_aged, 1), label: "months" })}
        />
        <RiskList
          title="Revenue contracting"
          threshold="ARR growth below −15%"
          rows={r.arr_contraction}
          metric={(x) => ({ value: typeof x.evidence.arr_growth === "number" ? `−${Math.abs(x.evidence.arr_growth * 100).toFixed(0)}%` : "—", label: "YoY" })}
        />
        <RiskList
          title="Stale marks"
          threshold="last priced over 48 months ago"
          rows={r.stale_marks}
          metric={(x) => ({ value: n(x.evidence.months, 0), label: "months" })}
        />
      </div>
    </Section>
  );
}
