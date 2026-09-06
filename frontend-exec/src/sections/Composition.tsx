import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CompositionSlice, ExecView } from "../types";
import { Section } from "../components/ui";
import { money, pct, plural } from "../lib/format";

function SliceTip({ active, payload, word }: { active?: boolean; payload?: { payload: CompositionSlice }[]; word?: string }) {
  if (!active || !payload?.length) return null;
  const s = payload[0].payload;
  return (
    <div className="tip">
      <div className="font-medium text-ink">{s.name}</div>
      <div className="num text-ink text-[14px] font-semibold mt-0.5">{money(s.nav, 2)}</div>
      <div className="text-muted">{pct(s.share)} of {word ?? "booked"} NAV · {plural(s.count, "position")}</div>
    </div>
  );
}

function SliceChart({ title, rows, word }: { title: string; rows: CompositionSlice[]; word: string }) {
  const max = Math.max(1, ...rows.map((r) => r.nav));
  return (
    <div className="frame px-4 pt-3.5 pb-3">
      <div className="flex items-baseline justify-between">
        <div className="text-[13px] font-medium text-ink">{title}</div>
        <div className="text-[11px] text-muted">{word} NAV, largest first · label = share</div>
      </div>
      <div className="mt-1">
        <ResponsiveContainer width="100%" height={rows.length * 26 + 16}>
          <BarChart data={rows} layout="vertical" margin={{ top: 6, right: 96, bottom: 0, left: 0 }} barCategoryGap={6}>
            <XAxis type="number" domain={[0, max]} hide />
            <YAxis type="category" dataKey="name" width={124} axisLine={false} tickLine={false} interval={0} tick={{ className: "cat", fill: "var(--ink-2)", fontSize: 12 }} />
            <Tooltip content={<SliceTip word={word} />} cursor={{ fill: "var(--accent-wash)" }} />
            <Bar dataKey="nav" fill="var(--series-1)" barSize={14} radius={[0, 3, 3, 0]} isAnimationActive={false}>
              <LabelList
                dataKey="share"
                position="right"
                offset={8}
                className="num"
                fill="var(--ink-2)"
                fontSize={11.5}
                formatter={(v: number) => pct(v)}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function Composition({ view }: { view: ExecView }) {
  const c = view.composition;
  const h = view.headline;
  const hier = view.hierarchy;
  const total = Object.values(hier).reduce((s, v) => s + v.nav, 0) || h.booked_nav;
  const l1 = hier.level1 ?? { count: 0, nav: 0 };
  const l3 = hier.level3 ?? { count: 0, nav: 0 };
  const l2 = hier.level2;
  // "Booked" is reserved for a final release; while the book is proposed the numbers are the proposal.
  const word = view.meta.status === "final" ? "booked" : "proposed";

  return (
    <Section
      id="composition"
      eyebrow="Portfolio composition"
      title={`Where the ${word} NAV sits`}
      aside={
        <>
          Active positions only. Sector and stage follow the workbook's own labels.
        </>
      }
    >
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-7 max-[1180px]:col-span-12"><SliceChart title="By sector" rows={c.by_sector} word={word} /></div>
        <div className="col-span-5 max-[1180px]:col-span-12 flex flex-col gap-3">
          <SliceChart title="By stage" rows={c.by_stage} word={word} />
          <div className="frame px-4 pt-3.5 pb-4 flex flex-col gap-3">
            <div>
              <div className="text-[13px] font-medium text-ink mb-1.5">Fair-value hierarchy</div>
              <div className="flex h-2 rounded-[3px] overflow-hidden gap-[2px]" aria-hidden>
                <div style={{ width: `${(l1.nav / total) * 100}%`, background: "var(--up-mark)", minWidth: l1.nav > 0 ? 3 : 0 }} />
                {l2 && <div style={{ width: `${(l2.nav / total) * 100}%`, background: "var(--series-2)" }} />}
                <div style={{ width: `${(l3.nav / total) * 100}%`, background: "var(--series-1)" }} />
              </div>
              <div className="flex justify-between gap-4 mt-1.5 text-[12px] text-ink2">
                <span><span className="inline-block w-2 h-2 rounded-[2px] mr-1.5 align-middle" style={{ background: "var(--up-mark)" }} />Level 1 · {plural(l1.count, "position")} · <span className="num text-ink">{money(l1.nav, 1)}</span> ({pct(l1.nav / total)})</span>
                <span className="text-right"><span className="inline-block w-2 h-2 rounded-[2px] mr-1.5 align-middle" style={{ background: "var(--series-1)" }} />Level 3 · {plural(l3.count, "position")} · <span className="num text-ink">{money(l3.nav, 1)}</span> ({pct(l3.nav / total)})</span>
              </div>
            </div>
            <div className="border-t border-hair pt-3 flex items-baseline justify-between gap-4">
              <div className="text-[13px] font-medium text-ink">Top-10 concentration</div>
              <div className="text-[12px] text-ink2">
                <span className="display text-[20px] font-semibold text-ink mr-1.5">{pct(h.top10_concentration)}</span>
                of {word} NAV in the ten largest positions
              </div>
            </div>
            <div className="border-t border-hair pt-3">
              <div className="text-[13px] font-medium text-ink mb-1.5">By fund</div>
              <div className="flex h-2 rounded-[3px] overflow-hidden gap-[2px]" aria-hidden>
                {c.by_fund.map((f, i) => (
                  <div key={f.name} style={{ width: `${f.share * 100}%`, background: "var(--series-1)", opacity: 1 - i * 0.28 }} />
                ))}
              </div>
              <div className="flex flex-wrap gap-x-5 gap-y-1 mt-1.5 text-[12px] text-ink2">
                {c.by_fund.map((f, i) => (
                  <span key={f.name}>
                    <span className="inline-block w-2 h-2 rounded-[2px] mr-1.5 align-middle" style={{ background: "var(--series-1)", opacity: 1 - i * 0.28 }} />
                    {f.name} <span className="num text-ink">{money(f.nav, 1)}</span> ({pct(f.share)})
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </Section>
  );
}
