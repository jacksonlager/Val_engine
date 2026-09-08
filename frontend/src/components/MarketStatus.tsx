// Where the market data came from and when: "Live data as of 8 Sep 2026". There is no Refresh
// button: the server refetches the live feed on start whenever the cache predates today, so the
// dashboard always opens on current data and this line simply says which day it is. A failed fetch
// keeps the data on file and says so; nothing here ever invents a number.
import { useEffect, useState } from "react";
import type { MarketStatus } from "../types";
import { loadMarketStatus } from "../lib/api";
import { shortDate } from "../lib/format";

export function MarketStatusButton({ refreshKey, compact = false }: { refreshKey: number; compact?: boolean }) {
  const [status, setStatus] = useState<MarketStatus | null>(null);

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

  return (
    <span className={`inline-flex items-center gap-1.5 ${compact ? "text-[11px]" : "text-[12px]"} text-ink2 whitespace-nowrap`}>
      <span title={live ? "Refetched automatically when the dashboard starts on a day the data has not been fetched" : undefined}>
        {label}
      </span>
    </span>
  );
}
