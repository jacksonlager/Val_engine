"""The one contract that matters.

    run_valuation(portfolio, activity, market, overrides, config) -> ValuationRun

Pure. No file reads, no network, no clock — the measurement date comes from config and
`generated_at` is supplied by the caller. Market data arrives already fetched. That
purity is what makes the determinism test possible and lets a real connector replace a
stub without the engine noticing.

Refused rows. An activity row carrying a blocking validation issue (X-902 / X-903 / X-905
outside the grace period / X-914 / X-920 …) is *recorded* against its position — an M-000
"recorded but not applied" step and an X-900 BLOCK flag — and never dispatched to a marking
rule. Four consequences follow from "a refused row is not evidence of anything":

* it never supersedes another row: an announced acquisition followed by a closing (or
  termination) row that was refused stays announced — M-050 applies, the pending item stays
  open, the refused close is recorded and the position blocks until the row is corrected;
* it never closes a position: proceeds on a refused exit are not realized;
* a listed position (Stage = Public) whose only rows were refused is still worth its close —
  M-041 runs on the carry side, and the refusal blocks on top of it;
* the one exception is a row whose event type has no real handler (M-999): it is dispatched
  so M-999 blocks and the adjudication proposal is raised.

A *Portfolio* row carrying a blocking issue (X-903 ownership out of range, X-904 unreconciled
prior mark, X-906 duplicate, X-921 latest round after the measurement date, an uncoercible cell)
blocks its position the same way: the mark is rolled as usual — the book is never silently
edited — and an X-900 BLOCK says which cell to fix.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time

from ..config import RuleConfig
from . import declarative, marking, precedence
from .exceptions import assess_carry_side, disposition, screen_notes
from .inputs import ActivityFeed, Event, EventType, PortfolioSnapshot, Position, Status
from .models import (
    CompanyResult, MarketData, OpenItem, OverrideLedger, RunManifest, Severity, ValidationIssue, ValuationRun,
)
from .open_items import RESOLVES, carry_prior_items
from .overrides import apply_override
from .registry import BUILTIN, Registry
from .rollup import fund_rollups, portfolio_totals, sensitivity
from .state import Suggest, Working

ENGINE_VERSION = "0.1.0"


def build_registry(config: RuleConfig) -> Registry:
    reg = BUILTIN.copy()
    declarative.register_custom_rules(reg, config)
    return reg


LISTED_STAGE = "public"


def is_listed(p: Position) -> bool:
    """A position the book already carries as a public security (M-041 applies on the carry side)."""
    return p.stage.strip().lower() == LISTED_STAGE


def _dispatch(w: Working, e: Event, registry: Registry, config: RuleConfig, market: MarketData, md: date) -> None:
    found = registry.handler_for(e.event_type, md)
    if found is None:  # pragma: no cover - M-999 is always registered
        raise RuntimeError(f"no handler and no fallback for event type {e.event_type!r}")
    _meta, fn = found
    fn(w, e, config, market)


def _blocked_rows(validation: tuple[ValidationIssue, ...], sheet: str) -> dict[int, list[ValidationIssue]]:
    """Rows of `sheet` that ingest refused: a blocking issue anchored to a row. On the activity
    sheet such a row is *recorded* against its position but never dispatched — a rule handed a
    cell it could not trust (a missing post-money, 150% ownership, a euro figure) would either
    crash or, worse, book a number. On the Portfolio sheet the position it describes blocks."""
    out: dict[int, list[ValidationIssue]] = {}
    for v in validation:
        if v.blocking and v.severity == Severity.BLOCK and v.row_index is not None and v.sheet == sheet:
            out.setdefault(v.row_index, []).append(v)
    return out


def _refused(e: Event, blocked: dict[int, list[ValidationIssue]], registry: Registry, md: date) -> list[ValidationIssue]:
    """The issues that stop this row from being applied, or [] when it may be dispatched.

    An unrecognised or ambiguous event type (X-909 / X-914 on the Event column) is *not* a
    reason to hold the row back: its handler is M-999, which blocks the position and raises
    the adjudication proposal (E-09). Refusing it here would hide the new event from the
    people who have to decide what it means."""
    issues = blocked.get(e.row_index, [])
    if not issues:
        return []
    found = registry.handler_for(e.event_type, md)
    if found is not None and found[0].rule_id == marking.UNKNOWN_RULE_ID:
        return []
    return issues


def _refuse(w: Working, e: Event, issues: list[ValidationIssue]) -> None:
    """Record a refused row on the position and block it. Nothing about the mark changes."""
    ids = sorted({v.rule_id for v in issues})
    why = "; ".join(f"{v.rule_id}: {v.message}" for v in issues)
    w.step("M-000", marking.V, {"refused_event": e.event_type, "row_index": e.row_index, "validation": ids},
           w.proposed_mark, w.proposed_mark,
           f"{e.event_type} on {e.date.isoformat()} recorded but not applied: the row failed validation ({why}). "
           "The mark is carried unchanged.", e)
    w.flag("X-900", "data", Severity.BLOCK,
           f"Row {e.row_index} of the activity tab ({e.event_type}) could not be applied: {why}. The engine will not "
           "book a number from a cell it could not read, so the prior mark is carried until the workbook is corrected.",
           points=(f"Activity row **{e.row_index}** ({e.event_type}) **could not be applied**: {why}.",
                   "The engine **will not book a number from a cell it could not read**.",
                   "The **prior mark is carried** until the workbook is corrected."),
           suggestions=(
               Suggest("hold_prior", "Hold the prior mark; correct the cell and rerun.", ("The engine will not book a number from a cell it could not read.", "Rerunning after the fix clears this without an override."), "prior"),
           ),
           action=f"Correct the cell(s) named in {', '.join(ids)} on row {e.row_index} of the activity tab and rerun.",
           sheet="activity", row_index=e.row_index, validation=ids)


def _refuse_book_row(w: Working, p: Position, issues: list[ValidationIssue]) -> None:
    """The position's own Portfolio row failed a blocking check. The roll proceeds on what the
    book says — nothing is edited or guessed — but the number cannot be booked until the row is
    fixed, so the position blocks and the flag names the cell."""
    ids = sorted({v.rule_id for v in issues})
    why = "; ".join(f"{v.rule_id}: {v.message}" for v in issues)
    w.flag("X-900", "data", Severity.BLOCK,
           f"Row {p.row_index} of the Portfolio tab ({p.company}) failed validation: {why}. The position is rolled on the "
           "figures the book carries, but a mark that starts from a row the engine could not reconcile cannot be booked "
           "until the book is corrected.",
           points=(f"Portfolio row **{p.row_index}** ({p.company}) **failed validation**: {why}.",
                   "The position is rolled on the figures the book carries.",
                   "A mark starting from an **unreconciled row cannot be booked**."),
           suggestions=(
               Suggest("hold_prior", "Hold the prior mark; correct the cell and rerun.", ("A mark starting from an unreconciled row cannot be booked.", "Rerunning after the fix clears this without an override."), "prior"),
           ),
           action=f"Correct the cell(s) named in {', '.join(ids)} on row {p.row_index} of the Portfolio tab and rerun.",
           sheet="portfolio", row_index=p.row_index, validation=ids)


def _positions_to_roll(portfolio: PortfolioSnapshot, activity: ActivityFeed) -> list[Position]:
    """The book, plus one synthesised zero position per `New Investment` naming a company the
    book does not have (M-014). Appended after the book in activity order, so the run is a
    pure function of the two inputs."""
    positions = list(portfolio.positions)
    book = portfolio.by_company()
    known_sectors = {p.sector for p in portfolio.positions}
    seen: set[str] = set()
    for e in activity.events:
        if e.event_type == EventType.NEW_INVESTMENT.value and e.company not in book and e.company not in seen:
            positions.append(marking.synthesise_position(e, known_sectors))
            seen.add(e.company)
    return positions


def run_valuation(
    portfolio: PortfolioSnapshot,
    activity: ActivityFeed,
    market: MarketData,
    overrides: OverrideLedger,
    config: RuleConfig,
    *,
    validation: tuple[ValidationIssue, ...] = (),
    prior_open_items: tuple[OpenItem, ...] = (),
    input_sha256: str = "",
    input_file: str = "",
    generated_at: datetime | None = None,
    market_data_source: str = "none",
) -> ValuationRun:
    md = config.quarter.measurement_date
    quarter = config.quarter.label
    registry = build_registry(config)
    events_by = activity.by_company()
    blocked = _blocked_rows(validation, activity.sheet_name)
    blocked_book = _blocked_rows(validation, portfolio.sheet_name) if portfolio.sheet_name != activity.sheet_name else {}
    results: list[CompanyResult] = []

    for p in _positions_to_roll(portfolio, activity):
        w = Working.from_position(p, quarter, activity.sheet_name)
        listed = is_listed(p) and p.status == Status.ACTIVE
        if listed:
            w.listed, w.fv_level = True, 1
        evs = precedence.ordered(events_by.get(p.company, []))
        # A refused row is not evidence: it neither supersedes nor is superseded by anything.
        live = [e for e in evs if not _refused(e, blocked, registry, md)]
        resolved: set = set()
        if not p.extra.get("synthesised") and p.row_index in blocked_book:
            _refuse_book_row(w, p, blocked_book[p.row_index])

        if p.status != Status.ACTIVE:
            w.step("M-000", marking.V, {"status": p.status.value, "realized": p.realized}, 0.0, 0.0,
                   f"Already {p.status.value} at the prior close; carried at zero with ${p.realized:.1f}M cumulative realized.")
            # Activity on a terminal company is an X-907 validation issue and is not applied — except cash
            # arriving after the exit (a distribution, a note repaid), which moves realized and nothing else.
            applied = []
            for e in (x for x in evs if x.event_type in precedence.ALLOWED_AFTER_TERMINAL):
                if refused := _refused(e, blocked, registry, md):
                    _refuse(w, e, refused)
                    continue
                _dispatch(w, e, registry, config, market, md)
                applied.append(e)
            if applied:
                screen_notes(w, applied, config)
        elif evs:
            applied = []
            for e in evs:
                if w.terminal and e.event_type not in precedence.ALLOWED_AFTER_TERMINAL:
                    w.step("M-000", marking.V, {"suppressed_event": e.event_type, "row_index": e.row_index},
                           w.proposed_mark, w.proposed_mark,
                           f"{e.event_type} on {e.date.isoformat()} recorded but not applied: the position closed earlier in the quarter.", e)
                    continue
                if refused := _refused(e, blocked, registry, md):
                    _refuse(w, e, refused)
                    continue
                why = precedence.superseded(e, live)
                if why:
                    w.step("M-000", marking.V, {"skipped_event": e.event_type, "row_index": e.row_index},
                           w.proposed_mark, w.proposed_mark, f"{e.event_type} skipped: {why}.", e)
                    continue
                _dispatch(w, e, registry, config, market, md)
                applied.append(e)
                resolved |= RESOLVES.get(e.event_type, set())
            if listed and not w.terminal and "M-040" not in w.applied_rules:
                # A public security is worth its close whatever else happened this quarter: a dividend, a
                # secondary or a refused row does not turn last quarter's number into a fair value.
                marking.listed_carry(w, config, market)
            elif not applied:   # every row refused or skipped: the position is carried as if the quarter were quiet
                marking.apply_carry(w, reason="No activity could be applied this quarter")
            screen_notes(w, evs, config)   # note language is screened even on rows that were not applied
        elif listed:
            marking.listed_carry(w, config, market)   # M-041: a public security is worth its close, not its history
        else:
            marking.apply_carry(w)

        carry_prior_items(w, list(prior_open_items), config, resolved)
        assess_carry_side(w, config, market)
        marking.calibrate_stale(w, config, market)

        booked, override = apply_override(w, overrides, quarter, config.tolerances.prior_mark_reconciliation_musd)
        disp = disposition(w.flags, w.terminal, config,
                           addressed=set(override.rule_ids_addressed) if override else None,
                           overridden=override is not None)
        realized_cum = p.realized + w.realized_quarter
        invested_after = w.invested
        # Suggestions get their numbers only now, when the proposal is final; then a terminal position
        # drops its carry-side noise but never a BLOCK: an exit with no proceeds must surface.
        final_flags = w.resolved_flags(w.proposed_mark, p.prior_mark, invested_after)
        flags = tuple(f for f in final_flags if f.severity == Severity.BLOCK) if w.terminal else tuple(final_flags)
        aged_runway = (p.runway_months - config.metrics.reporting_lag_months) if p.runway_months is not None else None
        implied_mult = (w.latest_post / p.arr) if (p.arr and p.arr >= config.exceptions.multiple.min_arr and w.latest_post and not w.terminal) else None

        results.append(CompanyResult(
            company=p.company, fund=p.fund, sector=p.sector, stage=w.stage,
            status_before=p.status, status_after=w.status, listed=w.listed,
            prior_mark=p.prior_mark, equity_mark=round(w.equity_mark, 6), note_at_cost=round(w.note_at_cost, 6),
            proposed_mark=round(w.proposed_mark, 6), booked_mark=round(booked, 6), override=override,
            ownership_before=p.ownership, ownership_after=w.ownership,
            invested_before=p.invested, invested_after=round(invested_after, 6),
            realized_quarter=round(w.realized_quarter, 6), realized_cumulative=round(realized_cum, 6),
            latest_post_money=w.latest_post, staleness_anchor=w.staleness_anchor, fv_level=w.fv_level,
            arr=p.arr, arr_growth=p.arr_growth,
            runway_months_aged=(round(aged_runway, 2) if aged_runway is not None else None),
            implied_multiple=(round(implied_mult, 2) if implied_mult else None),
            moic_after=(round((booked + realized_cum) / invested_after, 4) if invested_after else None),
            steps=tuple(w.steps), flags=flags, disposition=disp,
            open_items=tuple(w.open_items), alternative_marks={k: round(v, 6) for k, v in w.alternative_marks.items()},
        ))

    rollups = fund_rollups(results)
    totals = portfolio_totals(results)
    sens = sensitivity(results, config)
    all_open = tuple(item for c in results for item in c.open_items)

    gen = generated_at or datetime.combine(md, time.min)
    run_id = hashlib.sha256(f"{input_sha256}|{config.policy_version}|{ENGINE_VERSION}".encode()).hexdigest()[:12]
    manifest = RunManifest(
        run_id=run_id, input_sha256=input_sha256, input_file=input_file,
        policy_version=config.policy_version, engine_version=ENGINE_VERSION,
        quarter_label=quarter, measurement_date=md, prior_close=config.quarter.prior_close,
        generated_at=gen, adjudication_enabled=config.adjudication.enabled, market_data_source=market_data_source,
    )
    return ValuationRun(manifest=manifest, companies=tuple(results), rollups=tuple(rollups),
                        validation=tuple(validation), totals=totals, open_items=all_open, sensitivity=sens)
