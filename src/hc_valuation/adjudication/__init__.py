"""E-09 — novel-case adjudication. Runs OUTSIDE the engine, after a run, on M-999 blocks.

    adjudicate_run(run, feed, cfg, paths) -> list[TreatmentProposal]

For every company the engine blocked with M-999 this builds a context packet, looks the
event signature up in the proposal cache (`paths.proposals_dir/<proposal_id>.json`, where
the id is sha(signature | catalogue version) and the catalogue version embeds the policy
version), asks the configured proposer only when nothing is cached, persists the draft
and returns it. The run itself is never modified: a proposal sits *beside* a blocked
position until a named person acts on it (`promote.record_decision`).

With `adjudication.enabled: false` this returns nothing and M-999 blocks exactly as before.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import RuleConfig
from ..engine.inputs import ActivityFeed, Position
from ..engine.models import ValuationRun
from ..engine.run import build_registry
from .proposer import ContextPacket, Proposer, build_packet, make_proposer
from .schema import TreatmentProposal, catalogue_version_for, make_proposal_id, validation_scope

if TYPE_CHECKING:  # pragma: no cover
    from ..pipeline import RunPaths

log = logging.getLogger(__name__)

NOVEL_RULE_ID = "M-999"
POLICY_MARKDOWN = Path("docs") / "valuation-policy.md"


def proposal_path(proposals_dir: Path, proposal_id: str) -> Path:
    return Path(proposals_dir) / f"{proposal_id}.json"


def load_proposal(path: Path, cfg: RuleConfig | None = None) -> TreatmentProposal:
    registry = build_registry(cfg) if cfg else None
    with validation_scope(cfg, registry):
        return TreatmentProposal.from_json(Path(path).read_text(encoding="utf-8"))


def save_proposal(path: Path, proposal: TreatmentProposal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proposal.to_json() + "\n", encoding="utf-8")


def novel_events(run: ValuationRun, feed: ActivityFeed) -> list[tuple[str, str, int]]:
    """(company, signature, row_index) for every M-999 flag, matched back to its feed row."""
    out: list[tuple[str, str, int]] = []
    by_company = feed.by_company()
    for c in run.companies:
        for f in c.flags:
            if f.rule_id != NOVEL_RULE_ID:
                continue
            sig = str(f.evidence.get("signature", ""))
            rows = [e for e in by_company.get(c.company, []) if e.signature == sig] or \
                   [e for e in by_company.get(c.company, []) if not e.known]
            for e in rows:
                out.append((c.company, e.signature, e.row_index))
    # one proposal per (company, signature): the same novel treatment on two rows is one decision
    seen: set[tuple[str, str]] = set()
    uniq = []
    for company, sig, row in out:
        if (company, sig) not in seen:
            seen.add((company, sig))
            uniq.append((company, sig, row))
    return uniq


def _positions(paths: "RunPaths", cfg: RuleConfig) -> dict[str, Position]:
    """The prior-close Position rows, for the packet. The run carries the results, not the
    inputs, so re-read the workbook; a missing file just leaves the packet without them."""
    try:
        from ..ingest.reader import read_workbook
        snapshot, _ = read_workbook(paths.workbook, cfg)
        return snapshot.by_company()
    except Exception as ex:  # noqa: BLE001 — the packet is richer with positions, valid without
        log.warning("could not re-read positions for adjudication packets (%s)", ex)
        return {}


def adjudicate_run(run: ValuationRun, feed: ActivityFeed, cfg: RuleConfig, paths: "RunPaths",
                   proposer: Proposer | None = None) -> list[TreatmentProposal]:
    if not cfg.adjudication.enabled:
        return []
    registry = build_registry(cfg)
    catalogue_version = catalogue_version_for(cfg.policy_version, registry)
    proposer = proposer or make_proposer(cfg)
    policy_md = Path(paths.root) / POLICY_MARKDOWN
    results = run.by_company()
    events = {(e.company, e.row_index): e for e in feed.events}
    positions = _positions(paths, cfg)
    proposals: list[TreatmentProposal] = []

    with validation_scope(cfg, registry):
        for company, signature, row_index in novel_events(run, feed):
            pid = make_proposal_id(signature, catalogue_version)
            path = proposal_path(paths.proposals_dir, pid)
            if cfg.adjudication.cache_proposals and path.exists():
                try:
                    cached = TreatmentProposal.from_json(path.read_text(encoding="utf-8"))
                    # A pending draft the stub wrote while no model was reachable is replaced once one is: the
                    # stub's briefing is generic by construction. A decided proposal is never rewritten.
                    stale_stub = (cached.status == "pending" and cached.provenance.model.startswith("stub")
                                  and getattr(proposer, "name", "") == "claude" and getattr(proposer, "available", False))
                    if not stale_stub:
                        proposals.append(cached)
                        continue
                except Exception as ex:  # noqa: BLE001 — a corrupt cache file is re-proposed, not fatal
                    log.warning("cached proposal %s unreadable (%s); re-proposing", path.name, ex)
            event = events[(company, row_index)]
            packet: ContextPacket = build_packet(event, positions.get(company), results[company], cfg, registry, policy_md)
            try:
                proposal = proposer.propose(packet)
            except Exception as ex:  # noqa: BLE001 — adjudication is assist, never a dependency
                log.warning("proposer %s failed for %s (%s); position stays blocked under M-999", proposer.name, company, ex)
                continue
            save_proposal(path, proposal)
            proposals.append(proposal)
    return proposals


__all__ = ["TreatmentProposal", "adjudicate_run", "load_proposal", "novel_events", "proposal_path", "save_proposal"]
