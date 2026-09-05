"""The executive view-model: what a GP, CFO or investment committee needs from a run.

Derived entirely from a *published* `ValuationRun` — never the live one — so the numbers
on the executive dashboard are exactly the numbers the back office signed off. Every
aggregate here is computed in Python so it can be tested, and the executive front end
only renders.

Marks shown to executives are **booked** marks: the engine's proposal after any committee
override. The bridge from prior NAV runs through the engine's drivers first and then a
single "committee overrides" bar, so an executive can see both what the policy did and
where people departed from it.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..engine.inputs import Status
from ..engine.models import CompanyResult, Disposition, Severity, ValuationRun

# Which marking rule moved the mark decides the bridge bar it lands in. Order is the order
# the bars are drawn: value created first, value returned, value lost, then judgment.
DRIVERS: list[tuple[str, str, str]] = [
    # key, label, one-line meaning for a tooltip
    ("rounds_up", "New rounds", "Priced rounds and extensions that reset the mark upward"),
    ("new_investments", "New investments", "First checks into new positions, entered at cost"),
    ("ipo", "IPO / listing", "Positions that became listed, or already were, and are marked to the measurement-date market cap"),
    ("announced", "Announced deals", "Signed but unclosed acquisitions, probability-weighted; and deals that fell through, reverted"),
    ("notes", "Bridge notes", "HC's new money into convertible notes, carried at cost; notes repaid in cash"),
    ("secondary", "Secondary sales", "Partial sales and purchases; the stake held is re-marked at the last round"),
    ("adjustments", "Ownership adjustments", "Warrant exercises, pool expansions and cap-table restatements with no price event"),
    ("distributions", "Distributions", "Cash to HC with no change in the stake: dividends, escrow releases, earn-outs"),
    ("stock_exits", "Exits for stock", "Closed acquisitions paid in the acquirer's shares; the position continues"),
    ("rounds_down", "Down rounds & recaps", "Priced rounds below the prior post-money"),
    ("exits", "Exits realized", "Closed acquisitions: the mark goes to zero and cash comes back"),
    ("writeoffs", "Write-offs", "Shutdowns with little or no recovery"),
    ("impairments", "Chapter 11", "Reorganisations: the mark is held pending a recovery estimate"),
    ("overrides", "Committee overrides", "Where a person booked a different number from the engine's proposal"),
]
_DRIVER_LABEL = {k: v for k, v, _ in DRIVERS}
_DRIVER_NOTE = {k: n for k, _, n in DRIVERS}

# Bridge bars whose "mark-down" is cash coming back rather than value lost. They are drawn
# in their own hue so a realized exit never reads as a write-down.
REALIZED_DRIVERS = {"exits", "distributions"}

# The coarse movement categories a mover is presented under. Realized exits are kept apart
# from write-downs: the mark goes to zero because the cash arrived, not because value was lost.
MOVER_KINDS = ("round_up", "round_down", "realized", "written_off", "other")


def _driver_for(c: CompanyResult) -> str | None:
    """Classify the engine's movement (prior -> proposed) by the rule that produced it."""
    rules = {s.rule_id for s in c.steps}
    if "M-020" in rules:
        return "exits"
    if "M-024" in rules:
        return "stock_exits"
    if "M-021" in rules:
        return "writeoffs"
    if "M-040" in rules or "M-041" in rules:
        return "ipo"
    if "M-025" in rules:
        return "impairments"
    if "M-012" in rules:
        return "rounds_down"
    if "M-010" in rules or "M-011" in rules:
        return "rounds_up" if c.proposed_mark >= c.prior_mark else "rounds_down"
    if "M-014" in rules:
        return "new_investments"
    if "M-030" in rules or "M-031" in rules:
        return "secondary"
    if "M-013" in rules:
        return "adjustments"
    if "M-050" in rules or "M-051" in rules:
        return "announced"
    if "M-060" in rules or "M-061" in rules:
        return "notes"
    if "M-022" in rules:
        return "distributions"
    return None


def _event_label(c: CompanyResult) -> str:
    for s in c.steps:
        if s.evidence is not None and s.rule_id not in ("M-000",):
            detail = str(s.inputs.get("detail") or "")
            return f"{s.evidence.event_type}" + (f" · {detail}" if detail else "")
    return "No activity"


def _r(x: float, n: int = 2) -> float:
    return round(float(x), n)


def _pct(delta: float, base: float) -> float | None:
    return _r(delta / base, 4) if base else None


def _mover_kind(c: CompanyResult) -> str:
    """Coarse category for how a position moved, for the movers lists and the marks schedule.

    A closed acquisition with proceeds is *realized*, never a mark-down: the mark goes to zero
    because cash came back. Shutdowns are *written_off*. Priced rounds split by direction.
    """
    drv = _driver_for(c)
    if drv == "exits" or (c.status_after == Status.ACQUIRED and c.realized_quarter > 1e-9 and c.booked_mark <= 1e-9):
        return "realized"
    if drv == "writeoffs":
        return "written_off"
    if drv in ("rounds_up", "rounds_down"):
        return "round_up" if c.booked_mark >= c.prior_mark else "round_down"
    return "other"


def _mover_label(c: CompanyResult, kind: str) -> str:
    """Short caption for the movement, e.g. 'Realized $28.2M' or 'New round up'."""
    if kind == "realized":
        return f"Realized ${c.realized_quarter:,.1f}M"
    if kind == "written_off":
        return "Written off"
    if kind == "round_up":
        return "New round up"
    if kind == "round_down":
        return "New round down"
    drv = _driver_for(c)
    if drv:
        return _DRIVER_LABEL[drv]
    return "Committee override" if c.override is not None else "No activity"


def _suggestions(f) -> list[dict[str, Any]]:
    return [{"key": s.key, "label": s.label, "reasons": list(s.reasons), "booked": _r(s.booked)}
            for s in (getattr(f, "suggestions", ()) or ())]


def _recommendation(f: Any) -> dict[str, Any] | None:
    r = getattr(f, "recommendation", None)
    if r is None:
        return None
    return {"key": r.key, "label": r.label, "reasons": list(r.reasons), "booked": _r(r.booked), "source": r.source,
            "model": r.model, "rationale": r.rationale, "confidence": r.confidence}


def _actions(c: CompanyResult) -> list[dict[str, Any]]:
    return [{"rule_id": f.rule_id, "severity": f.severity.value, "action": f.action, "message": f.message,
             "points": list(getattr(f, "points", ()) or ()), "suggestions": _suggestions(f),
             "recommendation": _recommendation(f)}
            for f in c.flags if f.severity != Severity.MONITOR and f.action]


def _company_row(c: CompanyResult) -> dict[str, Any]:
    d = c.booked_mark - c.prior_mark
    kind = _mover_kind(c)
    return {
        "company": c.company, "fund": c.fund, "sector": c.sector, "stage": c.stage,
        "status": c.status_after.value, "fv_level": c.fv_level,
        "event": _event_label(c), "rule": next((s.rule_id for s in c.steps if s.rule_id != "M-000"), "M-000"),
        "prior": _r(c.prior_mark), "proposed": _r(c.proposed_mark), "booked": _r(c.booked_mark),
        "delta": _r(d), "delta_pct": _pct(d, c.prior_mark),
        "realized_quarter": _r(c.realized_quarter), "ownership": _r(c.ownership_after, 4),
        "disposition": c.disposition.value, "overridden": c.override is not None,
        "driver": _driver_for(c), "driver_kind": kind, "driver_label": _mover_label(c, kind),
    }


def _marks_schedule(cs: list[CompanyResult]) -> list[dict[str, Any]]:
    """Every position in the run, one row each: the full proposed-marks schedule.

    Default order is fund, then size of movement, so each fund's book reads largest change
    first; the front end may re-sort by any column.
    """
    return [_company_row(c) for c in sorted(cs, key=lambda c: (c.fund, -abs(c.booked_mark - c.prior_mark), c.company))]


def build_exec_view(run: ValuationRun, publish: dict[str, Any]) -> dict[str, Any]:
    cs = list(run.companies)
    t = run.totals

    # ---- bridge by driver (engine movement), then overrides as their own bar
    groups: dict[str, list[CompanyResult]] = defaultdict(list)
    for c in cs:
        k = _driver_for(c)
        if k and abs(c.proposed_mark - c.prior_mark) > 1e-9:
            groups[k].append(c)
    override_delta = sum(c.booked_mark - c.proposed_mark for c in cs)
    bridge: list[dict[str, Any]] = []
    running = t.prior_nav
    for key, label, note in DRIVERS:
        if key == "overrides":
            delta = override_delta
            members = [c for c in cs if c.override is not None]
        else:
            members = groups.get(key, [])
            delta = sum(c.proposed_mark - c.prior_mark for c in members)
        if abs(delta) < 1e-9 and not members:
            continue
        running += delta
        bridge.append({
            "key": key, "label": label, "note": note, "delta": _r(delta), "count": len(members),
            "kind": "realized" if key in REALIZED_DRIVERS else ("up" if delta >= 0 else "down"),
            "running_total": _r(running),
            "companies": sorted(({"company": c.company, "delta": _r((c.booked_mark if key == "overrides" else c.proposed_mark)
                                                                    - (c.proposed_mark if key == "overrides" else c.prior_mark))}
                                 for c in members), key=lambda x: -abs(x["delta"])),
        })

    # ---- movers (on booked marks)
    # Realized exits leave the mark-downs list: cash came back, so they are neither up nor down.
    moved = [c for c in cs if abs(c.booked_mark - c.prior_mark) > 1e-9]
    realized = sorted((c for c in moved if _mover_kind(c) == "realized"), key=lambda c: -c.realized_quarter)
    ups = sorted((c for c in moved if c.booked_mark > c.prior_mark and _mover_kind(c) != "realized"),
                 key=lambda c: -(c.booked_mark - c.prior_mark))
    downs = sorted((c for c in moved if c.booked_mark < c.prior_mark and _mover_kind(c) != "realized"),
                   key=lambda c: (c.booked_mark - c.prior_mark))

    # ---- composition (booked NAV, active positions only)
    def _comp(key):
        agg: dict[str, dict[str, float]] = defaultdict(lambda: {"nav": 0.0, "count": 0})
        for c in cs:
            if c.booked_mark > 0:
                agg[key(c)]["nav"] += c.booked_mark
                agg[key(c)]["count"] += 1
        total = sum(v["nav"] for v in agg.values()) or 1.0
        return sorted(({"name": k, "nav": _r(v["nav"]), "share": _r(v["nav"] / total, 4), "count": int(v["count"])}
                       for k, v in agg.items()), key=lambda x: -x["nav"])

    # ---- risk watch (active positions, from the flags the engine already raised)
    def _with_flag(rule_ids: set[str]):
        out = []
        for c in cs:
            for f in c.flags:
                if f.rule_id in rule_ids:
                    out.append({"company": c.company, "fund": c.fund, "booked": _r(c.booked_mark),
                                "detail": f.message, "evidence": f.evidence, "severity": f.severity.value})
                    break
        return sorted(out, key=lambda x: -x["booked"])

    risk = {
        "short_runway": _with_flag({"X-304"}),
        "arr_contraction": _with_flag({"X-302"}),
        "stale_marks": _with_flag({"X-202"}),
    }

    # ---- decisions: BLOCK positions with their actions; reviews compact
    decisions = [
        {**_company_row(c), "actions": _actions(c), "alternative_marks": {k: _r(v) for k, v in c.alternative_marks.items()}}
        for c in sorted((c for c in cs if c.disposition == Disposition.BLOCK), key=lambda c: -abs(c.booked_mark - c.prior_mark))
    ]
    reviews = [
        {**_company_row(c), "actions": _actions(c)}
        for c in sorted((c for c in cs if c.disposition == Disposition.REVIEW), key=lambda c: -c.booked_mark)
    ]

    # ---- fair value hierarchy
    hier: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "nav": 0.0})
    for c in cs:
        if c.booked_mark > 0 and c.fv_level:
            hier[f"level{c.fv_level}"]["count"] += 1
            hier[f"level{c.fv_level}"]["nav"] += c.booked_mark

    # The publish record is the authority on status (publish.py sets it at release time);
    # a snapshot without one falls back to whether any block is still open.
    status = publish.get("status") or ("final" if not decisions else "proposed")
    return {
        "meta": {
            "firm": "Human Capital",
            "quarter": run.manifest.quarter_label,
            "measurement_date": run.manifest.measurement_date.isoformat(),
            "prior_close": run.manifest.prior_close.isoformat(),
            "status": status,
            "published_at": publish.get("published_at"),
            "published_by": publish.get("published_by"),
            "note": publish.get("note", ""),
            "run_id": run.manifest.run_id,
            "policy_version": run.manifest.policy_version,
            "engine_version": run.manifest.engine_version,
            "input_file": run.manifest.input_file,
            "input_sha256": run.manifest.input_sha256,
            "market_data_source": run.manifest.market_data_source,
            "generated_at": run.manifest.generated_at.isoformat(),
        },
        "headline": {
            "prior_nav": _r(t.prior_nav), "proposed_nav": _r(t.proposed_nav), "booked_nav": _r(t.booked_nav),
            "net_movement": _r(t.booked_nav - t.prior_nav), "net_movement_pct": _pct(t.booked_nav - t.prior_nav, t.prior_nav),
            "override_adjustment": _r(override_delta),
            "realized_quarter": _r(t.realized_quarter), "realized_cumulative": _r(t.realized_cumulative),
            "written_off": _r(t.written_off),
            "exited_at_prior_mark": _r(t.exited_at_prior_mark),
            "exit_proceeds": _r(sum(c.realized_quarter for c in cs
                                    if c.status_before == Status.ACTIVE and c.status_after == Status.ACQUIRED)),
            "positions": t.positions, "active": t.active_after,
            "events": sum(1 for c in cs if any(s.evidence is not None for s in c.steps)),
            "level1_positions": t.level1_positions, "top10_concentration": _r(t.top10_concentration, 4),
            "dispositions": dict(t.dispositions),
            "invested": _r(sum(c.invested_after for c in cs)),
            "tvpi": _r((t.booked_nav + t.realized_cumulative) / max(sum(c.invested_after for c in cs), 1e-9), 4),
            "dpi": _r(t.realized_cumulative / max(sum(c.invested_after for c in cs), 1e-9), 4),
        },
        "bridge": bridge,
        "movers": {"up": [_company_row(c) for c in ups[:8]], "down": [_company_row(c) for c in downs[:8]],
                   "realized": [_company_row(c) for c in realized[:8]]},
        "marks": _marks_schedule(cs),
        "funds": [
            {"fund": r.fund, "companies": r.companies, "active": r.active, "invested": _r(r.invested),
             "prior_nav": _r(r.prior_nav), "booked_nav": _r(r.booked_nav), "delta": _r(r.booked_nav - r.prior_nav),
             "delta_pct": _pct(r.booked_nav - r.prior_nav, r.prior_nav),
             "realized_quarter": _r(r.realized_quarter), "realized_cumulative": _r(r.realized_cumulative),
             "tvpi": _r(r.tvpi, 4), "dpi": _r(r.dpi, 4), "rvpi": _r(r.rvpi, 4),
             "top_positions": [{"company": n, "share": _r(s, 4)} for n, s in r.top_positions]}
            for r in run.rollups
        ],
        "composition": {"by_sector": _comp(lambda c: c.sector), "by_stage": _comp(lambda c: c.stage), "by_fund": _comp(lambda c: c.fund)},
        "hierarchy": {k: {"count": int(v["count"]), "nav": _r(v["nav"])} for k, v in sorted(hier.items())},
        "decisions": decisions,
        "reviews": reviews,
        "risk_watch": risk,
        "sensitivity": {k: _r(v) for k, v in run.sensitivity.items()},
        "open_items": [
            {"company": o.company, "kind": o.kind.value, "opened": o.opened.isoformat(),
             "expected_resolution": o.expected_resolution.isoformat() if o.expected_resolution else None,
             "amount": o.amount_musd, "detail": o.detail, "escalated": o.escalated}
            for o in run.open_items
        ],
        "events": sorted((_company_row(c) for c in cs if any(s.evidence is not None for s in c.steps)),
                         key=lambda x: -abs(x["delta"])),
        "validation_issues": len([v for v in run.validation if v.blocking]),
    }
