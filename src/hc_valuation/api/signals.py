"""Vendor signals beside a position — the Foresight and AlphaSense slots of the data layer.

The workbook is the marking input; these feeds are context a reviewer reads next to it. So
this module never touches a number: it takes what `CompanyMetricsProvider` (Foresight-shaped
operating metrics) and `NewsSignalProvider` (AlphaSense-shaped dated signals) return, lines
the metrics up against the workbook's own columns so a restatement is visible, and hands the
result to the review tool (`GET /api/signals`, inlined as `window.__HC_SIGNALS__`).

Payload:

    {
      "as_of": "2026-09-30",
      "providers": {
        "metrics": {"name": "Foresight-shaped stub", "source": "data/mock_responses/foresight/company_metrics.json", "live": false},
        "news":    {"name": "AlphaSense-shaped stub", "source": "data/mock_responses/alphasense/news_signals.json", "live": false}
      },
      "since": "2026-07-01",                      # news window: the quarter
      "companies": {
        "Fernwave": {
          "metrics": {
            "reporting_period": "2026-08", "source_document": "board_deck_2026_08.pdf", "confidence": "reported",
            "rows": [ {"key": "arr", "label": "ARR ($M)", "vendor": 81.4, "workbook": 78.0, "delta_pct": 0.0436, "material": false}, ... ],
            "extra": {"netRevenueRetention": 1.24}     # vendor fields the workbook has no column for
          } | null,
          "news": [ {"published_at": "...", "source_type": "news", "source": "TechWire", "sentiment": -0.2,
                     "relevance": 0.94, "title": "...", "snippet": "...", "topics": ["M&A"]} ]
        }
      }
    }

`material` marks a vendor/workbook gap beyond `MATERIAL_DRIFT` — shown, never acted on.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from ..connectors import company_metrics_provider, news_signal_provider
from ..engine.inputs import PortfolioSnapshot
from ..pipeline import PipelineResult

MATERIAL_DRIFT = 0.10   # a 10% gap between the vendor's number and the workbook's is worth a look

# vendor key -> (label, workbook attribute on Position, unit hint)
METRIC_ROWS: tuple[tuple[str, str, str], ...] = (
    ("arr", "ARR ($M)", "arr"),
    ("arrGrowthYoY", "ARR growth (YoY)", "arr_growth"),
    ("grossMargin", "Gross margin", "gross_margin"),
    ("netBurn", "Net burn ($M/mo)", "net_burn"),
    ("cash", "Cash ($M)", "cash"),
    ("headcount", "Headcount", "headcount"),
)


def _drift(vendor: Any, book: Any) -> tuple[float | None, bool]:
    try:
        v, b = float(vendor), float(book)
    except (TypeError, ValueError):
        return None, False
    if b == 0:
        return (None, v != 0)
    d = (v - b) / abs(b)
    return round(d, 4), abs(d) > MATERIAL_DRIFT


def metrics_for(company: str, snapshot: PortfolioSnapshot, provider: Any) -> dict[str, Any] | None:
    raw = provider.metrics(company)
    if not raw:
        return None
    pos = snapshot.by_company().get(company)
    m = raw.get("metrics") or {}
    rows = []
    for key, label, attr in METRIC_ROWS:
        if key not in m:
            continue
        book = getattr(pos, attr, None) if pos is not None else None
        delta, material = _drift(m[key], book) if book is not None else (None, False)
        rows.append({"key": key, "label": label, "vendor": m[key], "workbook": book, "delta_pct": delta, "material": material})
    known = {k for k, _, _ in METRIC_ROWS}
    return {
        "reporting_period": raw.get("reportingPeriod"),
        "source_document": raw.get("sourceDocument"),
        "confidence": raw.get("confidence"),
        "rows": rows,
        "extra": {k: v for k, v in m.items() if k not in known},
    }


def news_for(company: str, since: date, provider: Any) -> list[dict[str, Any]]:
    out = []
    for r in provider.signals(company, since):
        out.append({
            "published_at": r.get("publishedAt"), "source_type": r.get("sourceType"), "source": r.get("source"),
            "sentiment": r.get("sentiment"), "relevance": r.get("relevance"), "title": r.get("title"),
            "snippet": r.get("snippet"), "topics": list(r.get("topics") or []),
        })
    return out


def build_signals(result: PipelineResult) -> dict[str, Any]:
    """The `/api/signals` payload for every company the run knows about (see module docstring)."""
    from ..ingest.reader import read_workbook

    cfg, paths = result.config, result.paths
    snapshot, _feed = read_workbook(paths.workbook, cfg)
    root = Path(paths.root)
    metrics = company_metrics_provider(root)
    news = news_signal_provider(root)
    since = cfg.quarter.window_start

    companies: dict[str, Any] = {}
    for c in result.run.companies:
        m = metrics_for(c.company, snapshot, metrics)
        n = news_for(c.company, since, news)
        if m is None and not n:
            continue
        companies[c.company] = {"metrics": m, "news": n}

    return {
        "as_of": cfg.quarter.measurement_date.isoformat(),
        "since": since.isoformat(),
        "providers": {
            "metrics": {"name": "Foresight-shaped stub", "live": False,
                        "source": "data/mock_responses/foresight/company_metrics.json",
                        "protocol": "connectors.base.CompanyMetricsProvider"},
            "news": {"name": "AlphaSense-shaped stub", "live": False,
                     "source": "data/mock_responses/alphasense/news_signals.json",
                     "protocol": "connectors.base.NewsSignalProvider"},
        },
        "note": ("Context beside the position, never an input to a mark: the workbook stays the marking source. "
                 "A material vendor/workbook gap is shown so a restatement is caught, not booked."),
        "companies": companies,
    }
