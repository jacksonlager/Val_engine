import type { ExecView } from "../types";
import { Tile } from "../components/ui";
import { dirClass, money, multiple, plural, shortDate, signedMoney, signedPct } from "../lib/format";

export function Headline({ view }: { view: ExecView }) {
  const h = view.headline;
  const d = h.dispositions;
  const dir = dirClass(h.net_movement);
  // "Booked" is reserved for a final release; a proposed release shows the proposal the committee is being asked to book.
  const navLabel = view.meta.status === "final" ? "Booked NAV" : "Proposed NAV";

  return (
    <section id="headline" className="pb-12">
      <div className="grid grid-cols-6 gap-3 max-[1180px]:grid-cols-3">
        <Tile
          label={`${navLabel} · ${shortDate(view.meta.measurement_date)}`}
          value={money(h.booked_nav, 1)}
          delta={
            <span className={`num font-semibold ${dir}`}>
              {signedMoney(h.net_movement, 1)} <span className="font-medium">{signedPct(h.net_movement_pct)}</span>
            </span>
          }
          foot={
            <>
              from {money(h.prior_nav, 1)} prior
              {Math.abs(h.override_adjustment) > 0.005 && <> · overrides {signedMoney(h.override_adjustment, 1)}</>}
            </>
          }
        />
        <Tile
          label="Realized this quarter"
          value={money(h.realized_quarter, 1)}
          foot={<>{money(h.realized_cumulative, 1)} cumulative distributions</>}
        />
        <Tile
          label="Written off"
          value={money(h.written_off, 1)}
          foot={<>shutdowns, at prior mark · {money(h.exited_at_prior_mark, 1)} exited, returning {money(h.exit_proceeds, 1)}</>}
        />
        <Tile
          label="Portfolio TVPI"
          value={multiple(h.tvpi)}
          foot={<>DPI {multiple(h.dpi)} · {money(h.invested, 1)} invested</>}
        />
        <Tile
          label="Active positions"
          value={String(h.active)}
          foot={<>of {h.positions} held · {plural(h.events, "event")} this quarter</>}
        />
        <Tile
          label="Awaiting committee decision"
          value={String(d.BLOCK ?? 0)}
          valueClass={(d.BLOCK ?? 0) > 0 ? "!text-[var(--block-text)]" : ""}
          foot={<>{d.REVIEW ?? 0} to review · {d.MONITOR ?? 0} monitored · {d.CLEAR ?? 0} clear</>}
        />
      </div>
    </section>
  );
}
