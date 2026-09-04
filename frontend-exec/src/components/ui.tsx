import type { ReactNode } from "react";
import { dirClass, signed, signedPct } from "../lib/format";
import type { Disposition } from "../types";

export function Section({
  id,
  eyebrow,
  title,
  aside,
  children,
}: {
  id: string;
  eyebrow: string;
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} className="border-t border-hair pt-8 pb-12">
      <div className="flex items-end justify-between gap-6 mb-6">
        <div>
          <div className="eyebrow mb-1">{eyebrow}</div>
          <h2 className="text-[22px] font-semibold leading-tight text-ink">{title}</h2>
        </div>
        {aside && <div className="text-[13px] text-ink2 text-right max-w-[52ch]">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export function Chip({ d }: { d: Disposition | string }) {
  return <span className={`chip chip-${d}`}>{d}</span>;
}

/** Signed delta in $M, coloured by direction. */
export function Delta({ v, d = 2, className = "" }: { v: number; d?: number; className?: string }) {
  return <span className={`num ${dirClass(v)} ${className}`}>{signed(v, d)}</span>;
}

export function DeltaPct({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  const cls = v == null ? "flat" : dirClass(v);
  return <span className={`num ${cls} ${className}`}>{signedPct(v)}</span>;
}

/** A single thin horizontal bar; width is a share of the track, hue is semantic or series. */
export function Bar({
  share,
  tone = "series",
  height = 8,
  align = "left",
  title,
}: {
  share: number;
  tone?: "series" | "up" | "down" | "neutral" | "realized";
  height?: number;
  align?: "left" | "right";
  title?: string;
}) {
  const color =
    tone === "up" ? "var(--up-mark)" : tone === "down" ? "var(--down-mark)" : tone === "neutral" ? "var(--neutral-mark)"
      : tone === "realized" ? "var(--realized-mark)" : "var(--series-1)";
  const w = Math.max(0, Math.min(1, share)) * 100;
  return (
    <div className="w-full" style={{ height }} title={title} aria-hidden>
      <div
        style={{
          height,
          width: `${w}%`,
          background: color,
          borderRadius: align === "left" ? "0 3px 3px 0" : "3px 0 0 3px",
          marginLeft: align === "right" ? "auto" : 0,
          minWidth: w > 0 ? 2 : 0,
        }}
      />
    </div>
  );
}

/** Stat tile per the dataviz contract: label, value (proportional figures), delta, footnote. */
export function Tile({
  label,
  value,
  valueClass = "",
  delta,
  foot,
}: {
  label: string;
  value: string;
  valueClass?: string;
  delta?: ReactNode;
  foot?: ReactNode;
}) {
  return (
    <div className="frame px-5 pt-4 pb-4 min-w-0">
      <div className="text-[12px] text-ink2 mb-2 whitespace-nowrap overflow-hidden text-ellipsis">{label}</div>
      <div className={`display text-[34px] font-semibold leading-none tracking-[-0.02em] text-ink ${valueClass}`}>{value}</div>
      {delta && <div className="mt-2 text-[14px] leading-tight">{delta}</div>}
      {foot && <div className="mt-1.5 text-[12px] text-muted leading-snug">{foot}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-[13px] text-muted py-6 text-center">{children}</div>;
}
