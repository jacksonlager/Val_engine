import { useEffect, useState, type ReactNode } from "react";
import type { CompanyResult, Disposition, Flag, Severity } from "../types";
import { musd, signClass, signed } from "../lib/format";
import { dispositionLabel, familyLabel, severityShort, readinessClass } from "../lib/labels";
import { READINESS_HINT } from "../types";

export function DispChip({ d, className = "" }: { d: Disposition | Severity; className?: string }) {
  return <span className={`chip disp-${d} ${className}`}>{dispositionLabel(d)}</span>;
}

/** A position's readiness — Blocked / Needs Review / Ready — the one status a position carries. */
export function ReadinessChip({ r, className = "" }: { r: string; className?: string }) {
  return (
    <span className={`chip ${readinessClass(r)} ${className}`} title={(READINESS_HINT as Record<string, string>)[r] ?? ""}>
      {r}
    </span>
  );
}

export const ESCALATION_HINT =
  "Two or more findings that each need review, in different areas of the policy, together block approval.";

/**
 * A BLOCK with no BLOCK-severity flag got there by escalation: policy
 * `exceptions.escalation.review_rules_to_block` (default 2) compounds REVIEW findings from
 * distinct families. Returns that family count, or 0 when the disposition is not escalated.
 */
export function escalatedReviewFamilies(c: Pick<CompanyResult, "disposition" | "flags">): number {
  if (c.disposition !== "BLOCK") return 0;
  if (c.flags.some((f) => f.severity === "BLOCK")) return 0;
  return new Set(c.flags.filter((f) => f.severity === "REVIEW").map((f) => f.family)).size;
}

/** "2 review findings combined" — sits beside the blocking chip so the reader knows no single
    rule blocked this position. */
export function EscalatedChip({ n, className = "", short = false }: { n: number; className?: string; short?: boolean }) {
  if (n <= 0) return null;
  const long = `${n} review finding${n === 1 ? "" : "s"} combined`;
  return (
    <span className={`chip no-dot escalated disp-BLOCK hint ${className}`} title={`${long}. ${ESCALATION_HINT}`}>
      {short ? `${n} reviews` : long}
    </span>
  );
}

/** Rule-id chip: severity color, mono rule id, action + message as native tooltip. */
export function FlagChip({ f }: { f: Flag }) {
  const title = `${familyLabel(f.family)} · ${severityShort(f.severity)}\n${f.action ? `${f.action}\n\n` : ""}${f.message}`;
  return (
    <span className={`chip disp-${f.severity} hint`} title={title}>
      <span className="mono">{f.rule_id}</span>
    </span>
  );
}

function copyIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden focusable="false" className="flex-none">
      <rect x="0.75" y="0.75" width="7" height="7" rx="1.25" fill="none" stroke="currentColor" strokeWidth="1.1" />
      <path d="M4.25 4.25h6a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-5a1 1 0 0 1-1-1z" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  );
}

/**
 * Copy-to-clipboard chip. A spreadsheet reference is not a link — Chrome and Safari refuse
 * to navigate from http to file://, so a link here would silently do nothing. Copying is the
 * honest affordance. Falls back to execCommand, then silently does nothing.
 */
export function CopyRef({
  text,
  label,
  title,
  mono = true,
}: {
  text: string;
  label?: ReactNode;
  title?: string;
  mono?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(t);
  }, [copied]);

  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        return;
      }
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      if (ok) setCopied(true);
    } catch {
      /* no clipboard in this context — stay quiet rather than shout an error */
    }
  };

  return (
    <button
      type="button"
      className="copyref"
      data-copied={copied ? "true" : undefined}
      title={title ?? `Copy ${text}`}
      aria-label={`Copy ${text}`}
      onClick={(e) => {
        e.stopPropagation();
        void copy();
      }}
    >
      <span className={mono ? "mono" : undefined}>{label ?? text}</span>
      {copyIcon()}
      {/* absolutely positioned so confirming a copy never reflows the row */}
      {copied && <span className="copied">copied</span>}
    </button>
  );
}

export function Delta({ v, decimals = 2, suffix = "" }: { v: number | null; decimals?: number; suffix?: string }) {
  return (
    <span className={`num ${signClass(v)}`}>
      {signed(v, decimals)}
      {v === null ? "" : suffix}
    </span>
  );
}

export function Arrow() {
  return <span className="text-muted mx-1">→</span>;
}

/** prior → proposed → booked, booked emphasised when it differs from proposed. */
export function MarkTriple({
  prior,
  proposed,
  booked,
  decimals = 2,
}: {
  prior: number;
  proposed: number;
  booked: number;
  decimals?: number;
}) {
  const overridden = Math.abs(booked - proposed) > 1e-6;
  return (
    <span className="num whitespace-nowrap">
      <span className="text-ink2">{musd(prior, decimals)}</span>
      <Arrow />
      <span>{musd(proposed, decimals)}</span>
      <Arrow />
      <span
        className={overridden ? "font-semibold underline decoration-dotted underline-offset-2" : "text-ink2"}
        title={
          overridden
            ? "The booked mark differs from the proposal: a committee override is on record (ledger reference E-01)."
            : "The booked mark is the proposal, unchanged."
        }
      >
        {musd(booked, decimals)}
      </span>
    </span>
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between mb-2">
      <h2 className="text-[13px] font-semibold tracking-tight">{children}</h2>
      {right && <div className="text-[11px] text-muted">{right}</div>}
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <div className="text-[11px] uppercase tracking-wider text-muted mb-0.5">{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="card p-6 text-center text-muted text-[12px]">{children}</div>;
}

export function KV({ k, v, mono = false }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3 py-0.5 border-b border-hair last:border-0">
      <span className="text-muted">{k}</span>
      <span className={`${mono ? "mono" : "num"} text-right`}>{v}</span>
    </div>
  );
}

export function Modal({ title, onClose, children, className = "" }: { title: string; onClose: () => void; children: ReactNode; className?: string }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${className}`.trim()} role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold text-[14px]">{title}</h3>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block mb-3">
      <div className="text-[11px] text-muted mb-1">{label}</div>
      {children}
    </label>
  );
}

/** Button that is disabled with a reason in static mode. */
export function WriteButton({
  disabledReason,
  className = "btn",
  onClick,
  children,
  title,
}: {
  disabledReason?: string | null;
  className?: string;
  onClick: () => void;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span title={disabledReason ?? title} className="inline-block">
      <button className={className} disabled={!!disabledReason} onClick={onClick} title={disabledReason ?? title}>
        {children}
      </button>
    </span>
  );
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, set] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    set((s) => ({ ...s, loading: true }));
    fn().then(
      (data) => alive && set({ data, loading: false }),
      (e) => alive && set({ error: String(e?.message ?? e), loading: false }),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, refetch: () => setTick((t) => t + 1) };
}
