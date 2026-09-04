import type { Decision, ExecView, Suggestion } from "../types";
import { Section, Chip, Delta, DeltaPct, Empty } from "../components/ui";
import { humanAltMark, money, num, plural } from "../lib/format";

/** `**bold**` in an engine point marks the words that carry the decision. */
function renderBold(text: string): React.ReactNode {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return parts.map((part, i) => (i % 2 === 1 ? <strong key={i} className="font-semibold text-ink">{part}</strong> : part));
}

/** The engine's suggested resolutions for one flag: label — the mark it would book. Read-only here;
    a reviewer accepts one in the back-office tool. */
function Suggestions({ items }: { items: Suggestion[] }) {
  return (
    <div className="mt-1 rounded-[4px] px-3 py-2" style={{ background: "var(--raised)" }}>
      <div className="eyebrow mb-1" style={{ fontSize: 10 }}>Suggested resolutions</div>
      <ul className="flex flex-col gap-1">
        {items.map((sg) => (
          <li key={sg.key} className="flex items-baseline justify-between gap-3 text-[12.5px] leading-snug">
            <span className="text-ink2" title={sg.reasons.join(" ")}>
              {sg.label}
              {sg.reasons.length > 0 && <span className="block text-[11px] text-muted">{sg.reasons.join(" · ")}</span>}
            </span>
            <span className="num text-ink font-medium whitespace-nowrap">{money(sg.booked, 2)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DecisionCard({ d, index }: { d: Decision; index: number }) {
  const alts = Object.entries(d.alternative_marks ?? {});
  return (
    <article className="frame relative overflow-hidden flex flex-col">
      <div className="absolute left-0 top-0 bottom-0 w-[3px]" style={{ background: "var(--block)" }} aria-hidden />
      <div className="pl-5 pr-4 pt-4 pb-4 flex flex-col gap-3 h-full">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="num text-[11px] text-muted">{String(index + 1).padStart(2, "0")}</span>
              <h3 className="text-[18px] font-semibold text-ink leading-tight">{d.company}</h3>
            </div>
            <div className="text-[12px] text-muted mt-0.5">
              {d.fund} · {d.sector} · {d.stage}
              {d.fv_level ? ` · Level ${d.fv_level}` : ""}
            </div>
          </div>
          <div className="text-right shrink-0">
            <div className="num text-[13px] text-ink2">
              {num(d.prior, 2)} <span className="text-muted">→</span> <span className="text-ink font-semibold">{num(d.booked, 2)}</span>
            </div>
            <div className="num text-[12px]">
              <Delta v={d.delta} /> <DeltaPct v={d.delta_pct} className="ml-1" />
            </div>
          </div>
        </div>
        <div className="text-[12px] text-ink2">{d.event}{d.overridden ? " · overridden by committee" : ""}</div>
        <ol className="flex flex-col gap-3">
          {d.actions.map((a, i) => (
            <li key={i} className="flex flex-col gap-1">
              <div className="text-[15px] leading-snug font-medium text-ink">{a.action}</div>
              {a.points && a.points.length > 0 ? (
                <ul className="text-[12.5px] leading-snug text-ink2 list-disc pl-4 space-y-0.5">
                  {a.points.map((p, k) => (
                    <li key={k}>{renderBold(p)}</li>
                  ))}
                </ul>
              ) : (
                <div className="text-[12.5px] leading-snug text-ink2">{a.message}</div>
              )}
              <div className="num text-[10.5px] text-muted uppercase tracking-[0.06em]">{a.rule_id} · {a.severity}</div>
              {a.suggestions && a.suggestions.length > 0 && <Suggestions items={a.suggestions} />}
            </li>
          ))}
        </ol>
        {alts.length > 0 && (
          <div className="mt-auto pt-3 border-t border-hair text-[12px] text-ink2 flex flex-wrap gap-x-4 gap-y-1">
            <span className="text-muted">Alternatives</span>
            {alts.map(([k, v]) => (
              <span key={k}>
                {humanAltMark(k)} <span className="num text-ink">{money(v, 2)}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

export function Decisions({ view }: { view: ExecView }) {
  const monitor = view.headline.dispositions.MONITOR ?? 0;
  return (
    <Section
      id="decisions"
      eyebrow="Exception queue"
      title={view.decisions.length ? `${plural(view.decisions.length, "position")} awaiting a committee decision` : "No positions await a committee decision"}
      aside={
        <>
          Ordered by size of movement. Each card states what the committee must decide, with the engine's reasoning beneath.
          A further {plural(view.reviews.length, "position")} are flagged for review and {monitor} are on monitor.
        </>
      }
    >
      {view.decisions.length === 0 ? (
        <Empty>Every mark has been confirmed by the back office and no committee decision is open.</Empty>
      ) : (
        <div className="grid grid-cols-2 gap-3 max-[1180px]:grid-cols-1">
          {view.decisions.map((d, i) => (
            <DecisionCard key={d.company} d={d} index={i} />
          ))}
        </div>
      )}

      <div className="mt-8 frame">
        <div className="px-4 pt-3.5 pb-2 flex items-baseline justify-between">
          <div className="text-[13px] font-medium text-ink flex items-center gap-2">
            <Chip d="REVIEW" /> Flagged for review
          </div>
          <div className="text-[11px] text-muted">{plural(view.reviews.length, "position")} · booked marks stand unless the committee acts · <Chip d="MONITOR" /> {monitor} on monitor</div>
        </div>
        {view.reviews.length === 0 ? (
          <Empty>Nothing is flagged for review.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Fund · sector</th>
                  <th className="r">Prior</th>
                  <th className="r">Booked</th>
                  <th className="r">Δ</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {view.reviews.map((r) => (
                  <tr key={r.company}>
                    <td className="text-ink font-medium whitespace-nowrap">{r.company}</td>
                    <td className="text-ink2 whitespace-nowrap">{r.fund} · {r.sector}</td>
                    <td className="r text-ink2">{num(r.prior)}</td>
                    <td className="r text-ink">{num(r.booked)}</td>
                    <td className="r"><Delta v={r.delta} /></td>
                    <td className="text-ink2">
                      {r.actions.length ? r.actions.map((a) => a.action).join(" ") : r.event}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Section>
  );
}
