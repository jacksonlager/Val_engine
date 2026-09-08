// Where the market data came from and when: "Live data as of 7 Sep 2026" with a Refresh button that
// refetches the feed over its cache and reruns the book. The fixture and synthetic data have nothing to
// refresh, so the button only appears for a live-priced workbook. A failed fetch keeps the data on file
// and says so; nothing here ever invents a number.
import { useEffect, useState } from "react";
import type { MarketStatus } from "../types";
import { loadMarketStatus, refreshMarket } from "../lib/api";
import { shortDate } from "../lib/format";

export function MarketStatusButton({ refreshKey, onRefreshed, compact = false }: { refreshKey: number; onRefreshed: () => void; compact?: boolean }) {
  const [status, setStatus] = useState<MarketStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    loadMarketStatus().then((s) => alive && setStatus(s), () => alive && setStatus(null));
    return () => {
      alive = false;
    };
  }, [refreshKey]);

  if (!status || !status.source) return null;
  const live = status.source.startsWith("live");
  const when = status.fetched_at ? shortDate(status.fetched_at) : null;
  const label = live
    ? when
      ? `Live data as of ${when}`
      : "Live data"
    : status.source.startsWith("synthetic")
      ? "Synthetic test data"
      : "Illustrative data";

  const go = async () => {
    if (busy) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await refreshMarket();
      setStatus(r.market);
      setNote(r.message);
      onRefreshed();
    } catch (e) {
      setNote(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className={`inline-flex items-center gap-1.5 ${compact ? "text-[11px]" : "text-[12px]"} text-ink2 whitespace-nowrap`}>
      <span title={status.fetched_at ? `Fetched ${status.fetched_at}` : undefined}>{label}</span>
      {status.refreshable && (
        <button className="btn btn-ghost px-2 py-0.5 text-[11px]" onClick={go} disabled={busy} title="Refetch the live feed now and rerun the book on it">
          {busy ? "Refreshing…" : "Refresh"}
        </button>
      )}
      {note && <span className="text-[11px] text-muted">{note}</span>}
    </span>
  );
}
