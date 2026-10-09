"""End-to-end question answering: plan -> retrieve -> votes -> cite -> verify.

Events (all JSON-serialisable) are yielded so the API can stream them:

* ``plan``     the filters used (editable chips in the UI)
* ``sources``  numbered source cards (verbatim text, speaker on the date, links)
* ``text``     answer text as it streams
* ``final``    verified answer: segments with [Source n] markers, grounding report
* ``error``    something failed; nothing unsupported is shown
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from hansard.config import Settings
from hansard.engine import Engine, Filters, Scope
from hansard.rag.prompts import NO_RECORDS
from hansard.rag.query_parse import QueryPlan, parse_offline, parse_with_model, resolve_speakers
from hansard.rag.sources import build_sources
from hansard.rag.verify import verify
from hansard.votes import VoteFinder

log = logging.getLogger(__name__)


@dataclass
class AskRequest:
    question: str
    mode: str = "summary"                     # summary | comprehensive
    recency: float | None = None              # 0..1
    role_weight: float | None = None          # 1..2
    scope: Scope = field(default_factory=Scope)
    plan: dict[str, Any] | None = None        # edited plan from the UI (skips re-parsing)
    history: list[dict[str, str]] = field(default_factory=list)


def plan_note(plan: QueryPlan, scope: Scope) -> str:
    f = plan.filters
    bits = []
    if f.date_from or f.date_to:
        bits.append(f"dates {f.date_from or 'start'} to {f.date_to or 'today'}")
    if f.houses:
        bits.append("houses: " + ", ".join(f.houses))
    if f.regions:
        bits.append("MPs for seats in: " + ", ".join(f.regions))
    if f.parties:
        bits.append("parties: " + ", ".join(f.parties))
    if plan.speakers:
        bits.append("speakers: " + ", ".join(s["name"] for s in plan.speakers))
    if f.offices:
        bits.append("speaker roles: " + ", ".join(f.offices))
    if not scope.written:
        bits.append("written answers/statements excluded")
    if not scope.pbc:
        bits.append("Public Bill Committees excluded")
    return "; ".join(bits)


class Pipeline:
    def __init__(self, settings: Settings, engine: Engine | None = None, client=None, today: date | None = None):
        self.settings = settings
        self.engine = engine or Engine(settings, today=today)
        self.votes = VoteFinder(settings, self.engine.con)
        self._client = client
        self.today = today

    @property
    def client(self):
        if self._client is None:
            from hansard.rag.answer import make_client

            self._client = make_client()
        return self._client

    def has_model(self) -> bool:
        if self._client is not None:
            return True
        import os

        from hansard.rag.answer import api_key

        return bool(api_key() or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def parties(self) -> list[tuple[str, str]]:
        rows = self.engine.resolver.con.execute(
            """SELECT DISTINCT p.party_id, p.party_name FROM ref_parties p
               JOIN ref_memberships m ON m.party_id = p.party_id WHERE m."end" >= DATE '2010-05-06'
               ORDER BY 1""").fetchall()
        return [(r[0], r[1]) for r in rows]

    def make_plan(self, req: AskRequest) -> tuple[QueryPlan, dict[str, int] | None]:
        if req.plan:
            return QueryPlan.from_dict({"question": req.question, **req.plan}), None
        usage = None
        if self.has_model():
            try:
                plan, u = parse_with_model(self.client, self.settings, req.question, req.history, self.parties(),
                                           self.today)
                from hansard.rag.answer import usage_dict

                usage = usage_dict(u)
            except Exception as exc:
                log.warning("model query parsing failed (%s); using offline rules", exc)
                plan = parse_offline(req.question, self.settings.regions, self.today)
        else:
            plan = parse_offline(req.question, self.settings.regions, self.today)
        if plan.unresolved_speakers:
            plan.speakers, plan.unresolved_speakers = resolve_speakers(
                self.engine.resolver.con, plan.unresolved_speakers, plan.filters)
            plan.filters.person_ids = [s["person_id"] for s in plan.speakers]
        return plan, usage

    def run(self, req: AskRequest) -> Iterator[dict[str, Any]]:
        plan, parse_usage = self.make_plan(req)
        yield {"type": "plan", "plan": plan.to_dict(), "usage": parse_usage}

        limit = int(self.settings.answer.get(
            "comprehensive_sources" if req.mode == "comprehensive" else "summary_sources", 12))
        result = self.engine.search(plan.search_text, plan.filters, req.scope, plan.portfolios,
                                    req.recency, req.role_weight, limit, diversify=True)
        divisions = []
        if req.scope.votes and (plan.wants_votes or not result.records):
            divisions = self.votes.find(plan.search_text, plan.filters, limit=4)
        sources = build_sources(result.records, divisions)
        from hansard.rank.evidence import evidence_summary

        yield {"type": "sources", "sources": [s.card() for s in sources], "candidates": result.candidates,
               "semantic": result.semantic_available, "evidence": evidence_summary(result.records, divisions)}

        if not sources or (result.no_records and not divisions):
            yield {"type": "final", "answer": {"segments": [{"text": NO_RECORDS + " The archive contains no "
                   "records matching this question and these filters.", "sources": [], "cited": [],
                   "status": "connective"}], "markdown": NO_RECORDS, "no_records": True, "citations_total": 0,
                   "citations_invalid": 0, "grounded_ratio": 1.0, "unsupported_segments": 0}, "usage": None}
            return
        if not self.has_model():
            yield {"type": "final", "answer": None, "usage": None,
                   "note": "Showing the evidence set only (no Anthropic API key on the server)."}
            return

        from hansard.rag.answer import Answerer

        final = None
        for ev in Answerer(self.settings, self.client).stream(
                req.question, sources, req.mode, plan_note(plan, req.scope), req.history, self.today):
            if ev["type"] == "final":
                final = ev
            else:
                yield ev
        if final is None or final["stop_reason"] == "refusal":
            yield {"type": "error", "message": "The model declined to answer this question."}
            return
        report = verify(final["blocks"], sources)
        yield {"type": "final", "answer": report.to_dict(), "usage": final["usage"], "model": final["model"],
               "stop_reason": final["stop_reason"]}


def answer_once(pipeline: Pipeline, req: AskRequest) -> dict[str, Any]:
    """Run the pipeline to completion (CLI / tests)."""
    out: dict[str, Any] = {"text": ""}
    for ev in pipeline.run(req):
        if ev["type"] == "text":
            out["text"] += ev["text"]
        elif ev["type"] in ("plan", "sources", "final", "error"):
            out[ev["type"]] = ev
    return out


__all__ = ["AskRequest", "Filters", "Pipeline", "answer_once"]
