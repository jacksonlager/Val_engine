import { useEffect, useRef, useState } from "react";
import type { BridgeBar } from "../types";
import { money, signed, signedMoney, plural } from "../lib/format";

type Step =
  | { kind: "total"; label: string; value: number; sub?: string }
  | { kind: "delta"; label: string; bar: BridgeBar; start: number; end: number };

const M = { top: 28, right: 12, bottom: 44, left: 56 };
const BAR = 24;

function niceStep(range: number): number {
  const candidates = [5, 10, 20, 25, 50, 100, 200, 250, 500];
  for (const c of candidates) if (range / c <= 6) return c;
  return 1000;
}

function useSize<T extends HTMLElement>(): [React.RefObject<T>, number, number] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState<[number, number]>([0, 0]);
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const read = () => setSize([el.clientWidth, el.clientHeight]);
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size[0], size[1]];
}

function wrapLabel(s: string, max = 15): string[] {
  if (s.length <= max) return [s];
  const words = s.split(" ");
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > max && cur) {
      lines.push(cur);
      cur = w;
    } else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur);
  return lines.slice(0, 2);
}

export function Waterfall({
  prior,
  booked,
  bridge,
  priorLabel,
  bookedLabel,
}: {
  prior: number;
  booked: number;
  bridge: BridgeBar[];
  priorLabel: string;
  bookedLabel: string;
}) {
  const [ref, width, measuredH] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = Math.max(320, measuredH);

  const steps: Step[] = [{ kind: "total", label: priorLabel, value: prior }];
  let run = prior;
  for (const b of bridge) {
    steps.push({ kind: "delta", label: b.label, bar: b, start: run, end: run + b.delta });
    run += b.delta;
  }
  steps.push({ kind: "total", label: bookedLabel, value: booked });

  const levels = [prior, booked, ...bridge.map((b) => b.running_total)];
  const lo = Math.min(...levels), hi = Math.max(...levels);
  const span = Math.max(hi - lo, 1);
  const step = niceStep(span * 1.6);
  const floor = Math.floor((lo - span * 0.22) / step) * step;
  const ceil = Math.ceil((hi + span * 0.12) / step) * step;
  const ticks: number[] = [];
  for (let t = floor; t <= ceil + 1e-9; t += step) ticks.push(t);

  const plotW = Math.max(width - M.left - M.right, 0);
  const plotH = height - M.top - M.bottom;
  const y = (v: number) => M.top + ((ceil - v) / (ceil - floor)) * plotH;
  const slot = steps.length ? plotW / steps.length : 0;
  const cx = (i: number) => M.left + slot * i + slot / 2;

  const active = hover != null ? steps[hover] : null;
  const TIP_W = 260;
  const tipLeft = hover != null ? (cx(hover) + BAR / 2 + 14 + TIP_W <= width ? cx(hover) + BAR / 2 + 14 : Math.max(0, cx(hover) - BAR / 2 - 14 - TIP_W)) : 0;

  return (
    <div ref={ref} className="relative w-full flex-1 min-h-[320px]">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Bridge from prior NAV to booked NAV by driver">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
              <text x={M.left - 8} y={y(t) + 3.5} textAnchor="end" className="num" fontSize={11} fill="var(--muted)">
                {t.toLocaleString("en-US")}
              </text>
            </g>
          ))}
          {/* axis-break mark: the scale starts near the floor, not at zero */}
          <g stroke="var(--axis)" strokeWidth={1.5} fill="none">
            <path d={`M ${M.left - 3} ${M.top + plotH + 2} l 6 -5 l -6 -5 l 6 -5`} />
          </g>
          {steps.map((s, i) => {
            const x = cx(i) - BAR / 2;
            let top: number, bottom: number, fill: string, rTop: boolean;
            if (s.kind === "total") {
              top = y(s.value); bottom = y(floor); fill = "var(--neutral-mark)"; rTop = true;
            } else {
              const up = s.end >= s.start;
              top = y(Math.max(s.start, s.end)); bottom = y(Math.min(s.start, s.end));
              fill = s.bar.kind === "realized" ? "var(--realized-mark)" : up ? "var(--up-mark)" : "var(--down-mark)"; rTop = up;
            }
            const h = Math.max(bottom - top, 1.5);
            const r = Math.min(4, h / 2);
            const path = rTop
              ? `M ${x} ${bottom} V ${top + r} Q ${x} ${top} ${x + r} ${top} H ${x + BAR - r} Q ${x + BAR} ${top} ${x + BAR} ${top + r} V ${bottom} Z`
              : `M ${x} ${top} V ${bottom - r} Q ${x} ${bottom} ${x + r} ${bottom} H ${x + BAR - r} Q ${x + BAR} ${bottom} ${x + BAR} ${bottom - r} V ${top} Z`;
            const next = steps[i + 1];
            const level = s.kind === "total" ? s.value : s.end;
            const valueText = s.kind === "total" ? money(s.value, 1) : signed(s.bar.delta, 1);
            const labelUp = s.kind === "total" || s.end >= s.start;
            const lines = wrapLabel(s.label, Math.max(8, Math.floor((slot - 4) / 6.2)));
            const dim = hover != null && hover !== i;
            return (
              <g
                key={i}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                style={{ cursor: "default", outline: "none" }}
              >
                <rect x={M.left + slot * i} y={M.top} width={slot} height={plotH} fill="transparent" />
                <path d={path} fill={fill} opacity={dim ? 0.45 : 1} />
                {next && (
                  <line
                    x1={x + BAR} x2={cx(i + 1) - BAR / 2} y1={y(level)} y2={y(level)}
                    stroke="var(--axis)" strokeWidth={1}
                  />
                )}
                <text
                  x={cx(i)} y={labelUp ? top - 7 : bottom + 14} textAnchor="middle" className="num" fontSize={11.5}
                  fill={s.kind === "total" ? "var(--ink)" : "var(--ink-2)"} fontWeight={s.kind === "total" ? 600 : 500}
                >
                  {valueText}
                </text>
                <text x={cx(i)} y={height - M.bottom + 16} textAnchor="middle" fontSize={11.5} fill="var(--ink-2)">
                  {lines.map((l, k) => (
                    <tspan key={k} x={cx(i)} dy={k === 0 ? 0 : 13}>{l}</tspan>
                  ))}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {active && (
        <div className="tip absolute pointer-events-none z-10" style={{ left: tipLeft, top: M.top, width: TIP_W }}>
          {active.kind === "total" ? (
            <>
              <div className="font-medium text-ink">{active.label}</div>
              <div className="num text-ink mt-1 text-[14px] font-semibold">{money(active.value, 2)}</div>
            </>
          ) : (
            <>
              <div className="flex items-baseline justify-between gap-4">
                <span className="font-medium text-ink">{active.label}</span>
                <span className={`num font-semibold text-[14px] ${active.bar.kind === "realized" ? "realized" : active.bar.delta >= 0 ? "up" : "down"}`}>{signedMoney(active.bar.delta, 2)}</span>
              </div>
              <div className="text-muted mt-0.5">{active.bar.note}</div>
              <div className="text-muted mt-0.5">{plural(active.bar.count, "position")} · running {money(active.bar.running_total, 1)}</div>
              <ul className="mt-2 border-t border-hair pt-2 space-y-0.5">
                {active.bar.companies.slice(0, 8).map((c) => (
                  <li key={c.company} className="flex justify-between gap-4">
                    <span className="text-ink2">{c.company}</span>
                    <span className={`num ${c.delta >= 0 ? "up" : "down"}`}>{signed(c.delta, 2)}</span>
                  </li>
                ))}
                {active.bar.companies.length > 8 && (
                  <li className="text-muted">and {active.bar.companies.length - 8} more</li>
                )}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
