// Vendor context beside a position — the Foresight and AlphaSense slots of the data layer.
//
// Operating metrics as the monitoring vendor reports them, lined up against the workbook's
// own columns so a restatement is visible; and dated news / filing signals for the quarter.
// Both are context for the reviewer: nothing here is an input to a mark, and the card says
// so. Today both feeds are vendor-shaped stubs (the chip says which).
import type { CompanySignals } from "../types";
import { isoDate, musd, pct, signClass } from "../lib/format";
import { useHistory } from "../lib/history";
import { Label } from "./ui";

function fmt(key: string, v: number | string | null): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (key === "arrGrowthYoY" || key === "grossMargin") return pct(v, 0);
  if (key === "headcount") return String(Math.round(v));
  return musd(v, key === "netBurn" ? 2 : 1);
}

function SentimentChip({ s }: { s: number | null }) {
  if (s === null) return null;
  const cls = s > 0.15 ? "disp-CLEAR" : s < -0.15 ? "disp-BLOCK" : "disp-NONE";
  const word = s > 0.15 ? "positive" : s < -0.15 ? "negative" : "neutral";
  return <span className={`chip ${cls}`}>{word}</span>;
}

function MetricsBlock({ sig }: { sig: NonNullable<CompanySignals["metrics"]> }) {
  const material = sig.rows.filter((r) => r.material).length;
  return (
    <div className="mt-1">
      <div className="text-[11px] text-muted mb-1">
        Operating metrics · {sig.reporting_period ?? "—"} · {sig.source_document ?? "—"}
        {sig.confidence && <> · <span className="mono">{sig.confidence}</span></>}
        {material > 0 && <span className="chip disp-REVIEW ml-1.5">{material} gap{material === 1 ? "" : "s"} &gt;10% vs workbook</span>}
      </div>
      <table className="signals-tbl">
        <thead>
          <tr>
            <th />
            <th className="text-right">Vendor</th>
            <th className="text-right">Workbook</th>
            <th className="text-right">Gap</th>
          </tr>
        </thead>
        <tbody>
          {sig.rows.map((r) => (
            <tr key={r.key} className={r.material ? "material" : ""}>
              <td className="text-muted">{r.label}</td>
              <td className="num text-right">{fmt(r.key, r.vendor)}</td>
              <td className="num text-right">{fmt(r.key, r.workbook)}</td>
              <td className={`num text-right ${r.delta_pct !== null && r.material ? signClass(r.delta_pct) : "text-muted"}`}>
                {r.delta_pct === null ? "—" : pct(r.delta_pct, 0, true)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {Object.keys(sig.extra).length > 0 && (
        <div className="text-[11px] text-muted mt-1">
          Also reported:{" "}
          {Object.entries(sig.extra).map(([k, v]) => (
            <span key={k} className="mono mr-2">
              {k} {String(v)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function NewsBlock({ items }: { items: CompanySignals["news"] }) {
  return (
    <ul className="mt-1 space-y-1.5">
      {items.map((n, i) => (
        <li key={i} className="text-[12px] leading-snug">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="mono text-[11px] text-muted">{isoDate(n.published_at)}</span>
            <span className="text-[11px] text-muted">
              {n.source ?? "—"}
              {n.source_type ? ` · ${n.source_type}` : ""}
            </span>
            <SentimentChip s={n.sentiment} />
            {n.topics.map((t) => (
              <span key={t} className="chip disp-NONE">
                {t}
              </span>
            ))}
          </div>
          <div className="font-medium">{n.title}</div>
          {n.snippet && <div className="text-ink2">{n.snippet}</div>}
        </li>
      ))}
    </ul>
  );
}

export function VendorSignalsCard({ company }: { company: string }) {
  const { signals } = useHistory();
  const sig: CompanySignals | undefined = signals?.companies[company];
  const provM = signals?.providers.metrics;
  const provN = signals?.providers.news;
  return (
    <div className="card p-3">
      <div className="flex items-baseline justify-between gap-2">
        <Label>Vendor signals</Label>
        <span className="text-[10.5px] text-muted whitespace-nowrap">
          {provM ? (provM.live ? "live" : "stub feeds") : "—"} · context only, never a mark input
        </span>
      </div>
      {!signals && <p className="text-[12px] text-muted">No vendor feeds attached to this run.</p>}
      {signals && !sig && (
        <p className="text-[12px] text-muted leading-snug">
          Nothing from {provM?.name ?? "the metrics feed"} or {provN?.name ?? "the news feed"} for this company this quarter.
        </p>
      )}
      {sig?.metrics && <MetricsBlock sig={sig.metrics} />}
      {sig && sig.news.length > 0 && (
        <>
          <div className="text-[11px] text-muted mt-2">
            Signals since {isoDate(signals?.since)} · {provN?.name}
          </div>
          <NewsBlock items={sig.news} />
        </>
      )}
    </div>
  );
}
