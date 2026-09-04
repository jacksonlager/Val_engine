"""Flat row views over a `ValuationRun`.

Every export surface (xlsx, csv, the fallback HTML report) renders the same tables, so the
column choice lives here once. A `Table` is headers + rows + a per-column display kind;
writers decide how a kind becomes a number format or a CSS class.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..engine.models import ValuationRun

# Column kinds drive number formats in the workbook and alignment in HTML.
MUSD = "musd"        # $M, two decimals
PCT = "pct"          # ratio shown as percent, one decimal
MULT = "mult"        # multiple, two decimals with an x
NUM = "num"          # plain number
INT = "int"
TEXT = "text"
DATE = "date"


@dataclass
class Table:
    name: str
    headers: list[str]
    kinds: list[str]
    rows: list[list[Any]] = field(default_factory=list)


def _delta_pct(prior: float, proposed: float) -> float | None:
    return (proposed - prior) / prior if prior else None


def compact_json(obj: Any) -> str:
    """One-line JSON for audit inputs; deterministic key order so files diff cleanly."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


# ---------------------------------------------------------------------------- tables

def marks_table(run: ValuationRun) -> Table:
    t = Table(
        name="Marks",
        headers=[
            "Company", "Fund", "Sector", "Stage", "Status Before", "Status After", "FV Level",
            "Prior ($M)", "Equity ($M)", "Note at Cost ($M)", "Proposed ($M)", "Booked ($M)",
            "Delta ($M)", "Delta (%)", "Ownership Before", "Ownership After",
            "Invested Before ($M)", "Invested After ($M)", "Realized Q ($M)", "Realized Cum ($M)",
            "MOIC After (x)", "ARR ($M)", "ARR Growth", "Runway Aged (mo)", "Implied Multiple (x)",
            "Disposition", "Flags", "Override Approver",
        ],
        kinds=[
            TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INT,
            MUSD, MUSD, MUSD, MUSD, MUSD,
            MUSD, PCT, PCT, PCT,
            MUSD, MUSD, MUSD, MUSD,
            MULT, MUSD, PCT, NUM, MULT,
            TEXT, TEXT, TEXT,
        ],
    )
    for c in run.companies:
        t.rows.append([
            c.company, c.fund, c.sector, c.stage, c.status_before.value, c.status_after.value, c.fv_level,
            c.prior_mark, c.equity_mark, c.note_at_cost, c.proposed_mark, c.booked_mark,
            c.delta, _delta_pct(c.prior_mark, c.proposed_mark), c.ownership_before, c.ownership_after,
            c.invested_before, c.invested_after, c.realized_quarter, c.realized_cumulative,
            c.moic_after, c.arr, c.arr_growth, c.runway_months_aged, c.implied_multiple,
            c.disposition.value, ", ".join(f.rule_id for f in c.flags),
            c.override.approver if c.override else None,
        ])
    return t


def exceptions_table(run: ValuationRun) -> Table:
    t = Table(name="Exceptions",
              headers=["Company", "Disposition", "Rule", "Family", "Severity", "Message"],
              kinds=[TEXT, TEXT, TEXT, TEXT, TEXT, TEXT])
    for c in run.companies:
        for f in c.flags:
            t.rows.append([c.company, c.disposition.value, f.rule_id, f.family, f.severity.value, f.message])
    return t


def audit_table(run: ValuationRun) -> Table:
    t = Table(name="Audit Trail",
              headers=["Company", "Seq", "Rule", "Version", "Prior ($M)", "New ($M)", "Rationale",
                       "Evidence Sheet", "Evidence Row", "Event Type", "Event Date", "Inputs (JSON)"],
              kinds=[TEXT, INT, TEXT, TEXT, MUSD, MUSD, TEXT, TEXT, INT, TEXT, DATE, TEXT])
    for c in run.companies:
        for s in c.steps:
            ev = s.evidence
            t.rows.append([
                c.company, s.sequence, s.rule_id, s.rule_version, s.prior_value, s.new_value, s.rationale,
                ev.sheet if ev else None, ev.row_index if ev else None, ev.event_type if ev else None,
                ev.date.isoformat() if ev else None, compact_json(s.inputs),
            ])
    return t


def rollup_table(run: ValuationRun) -> Table:
    t = Table(name="Fund Rollup",
              headers=["Fund", "Companies", "Active", "Invested ($M)", "Prior NAV ($M)", "Proposed NAV ($M)",
                       "Booked NAV ($M)", "Realized Q ($M)", "Realized Cum ($M)", "TVPI (x)", "DPI (x)", "RVPI (x)",
                       "Top Positions"],
              kinds=[TEXT, INT, INT, MUSD, MUSD, MUSD, MUSD, MUSD, MUSD, MULT, MULT, MULT, TEXT])
    for r in run.rollups:
        t.rows.append([
            r.fund, r.companies, r.active, r.invested, r.prior_nav, r.proposed_nav, r.booked_nav,
            r.realized_quarter, r.realized_cumulative, r.tvpi, r.dpi, r.rvpi,
            "; ".join(f"{n} {s:.1%}" for n, s in r.top_positions),
        ])
    return t


def open_items_table(run: ValuationRun) -> Table:
    t = Table(name="Open Items",
              headers=["Company", "Kind", "Opened", "Opened Quarter", "Expected Resolution", "Amount ($M)",
                       "Detail", "Age (quarters)", "Escalated"],
              kinds=[TEXT, TEXT, DATE, TEXT, DATE, MUSD, TEXT, INT, TEXT])
    for o in run.open_items:
        t.rows.append([
            o.company, o.kind.value, o.opened.isoformat(), o.opened_quarter,
            o.expected_resolution.isoformat() if o.expected_resolution else None, o.amount_musd,
            o.detail, o.age_quarters, "yes" if o.escalated else "no",
        ])
    return t


def validation_table(run: ValuationRun) -> Table:
    t = Table(name="Validation",
              headers=["Rule", "Severity", "Blocking", "Sheet", "Row", "Company", "Message"],
              kinds=[TEXT, TEXT, TEXT, TEXT, INT, TEXT, TEXT])
    for v in run.validation:
        t.rows.append([v.rule_id, v.severity.value, "yes" if v.blocking else "no", v.sheet, v.row_index, v.company, v.message])
    return t


def alternatives_table(run: ValuationRun) -> Table:
    t = Table(name="Alternatives",
              headers=["Company", "Booked ($M)", "Alternative", "Value ($M)", "Vs Booked ($M)"],
              kinds=[TEXT, MUSD, TEXT, MUSD, MUSD])
    for c in run.companies:
        for name, val in sorted(c.alternative_marks.items()):
            t.rows.append([c.company, c.booked_mark, name, val, val - c.booked_mark])
    return t


def summary_rows(run: ValuationRun) -> list[tuple[str, Any, str]]:
    """(label, value, kind) triples for the Summary sheet and the report tiles."""
    m, t = run.manifest, run.totals
    rows: list[tuple[str, Any, str]] = [
        ("Quarter", m.quarter_label, TEXT),
        ("Measurement date", m.measurement_date.isoformat(), TEXT),
        ("Prior close", m.prior_close.isoformat(), TEXT),
        ("Policy version", m.policy_version, TEXT),
        ("Engine version", m.engine_version, TEXT),
        ("Run id", m.run_id, TEXT),
        ("Input file", m.input_file, TEXT),
        ("Input SHA-256", m.input_sha256, TEXT),
        ("Generated at", m.generated_at.isoformat(), TEXT),
        ("Market data source", m.market_data_source, TEXT),
        ("Adjudication enabled", "yes" if m.adjudication_enabled else "no", TEXT),
        ("", None, TEXT),
        ("Positions", t.positions, INT),
        ("Active after", t.active_after, INT),
        ("Prior NAV ($M)", t.prior_nav, MUSD),
        ("Proposed NAV ($M)", t.proposed_nav, MUSD),
        ("Booked NAV ($M)", t.booked_nav, MUSD),
        ("Net movement ($M)", t.net_movement, MUSD),
        ("Realized in quarter ($M)", t.realized_quarter, MUSD),
        ("Realized cumulative ($M)", t.realized_cumulative, MUSD),
        ("Written off ($M)", t.written_off, MUSD),
        ("Exited at prior mark ($M)", t.exited_at_prior_mark, MUSD),
        ("Level 1 positions", t.level1_positions, INT),
        ("Top-10 concentration", t.top10_concentration, PCT),
        ("", None, TEXT),
    ]
    for k, v in t.dispositions.items():
        rows.append((f"Disposition {k}", v, INT))
    rows.append(("", None, TEXT))
    for k, v in run.sensitivity.items():
        rows.append((f"Sensitivity {k}", v, MUSD))
    return rows


def all_tables(run: ValuationRun) -> list[Table]:
    return [
        marks_table(run), exceptions_table(run), audit_table(run), rollup_table(run),
        open_items_table(run), validation_table(run), alternatives_table(run),
    ]
