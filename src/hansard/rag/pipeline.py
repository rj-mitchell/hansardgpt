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
from hansard.rag.british import britishise_segments, to_british
from hansard.rag.neutral import flag_loaded
from hansard.rag.prompts import NO_RECORDS
from hansard.rag.query_parse import QueryPlan, parse_offline, parse_with_model, resolve_speakers
from hansard.rag.sources import build_sources
from hansard.rag.verify import check_quotes, verify
from hansard.sources.demographics import AGE_BAND_LABEL, GENDER_LABEL
from hansard.sources.elections import MAJORITY_BAND_LABEL, TENURE_LABEL
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
    compare: list[dict[str, Any]] = field(default_factory=list)  # sides to compare, from the Compare page


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
    if f.genders:
        bits.append("speakers: " + " and ".join(GENDER_LABEL[g] for g in f.genders))
    if f.age_bands:
        bits.append("speakers aged " + ", ".join(AGE_BAND_LABEL[b] for b in f.age_bands) + " on the day")
    if f.tenure:
        bits.append("speakers: " + " and ".join(TENURE_LABEL[t] for t in f.tenure) + " (on the day)")
    if f.majority_bands:
        bits.append("MPs in seats that were " + ", ".join(MAJORITY_BAND_LABEL[b] for b in f.majority_bands)
                    + " at the time")
    if not scope.written:
        bits.append("written answers/statements excluded")
    if not scope.pbc:
        bits.append("Public Bill Committees excluded")
    if plan.compare:
        bits.append("comparing " + " and ".join(s["label"] for s in plan.compare) + ", each searched separately")
    return "; ".join(bits)


def plan_facets(plan: QueryPlan) -> set[str]:
    """Speaker facts the question is about (gender, age, first term, majority): only these are given to the model."""
    f = plan.filters
    out = {plan.group_by} - {"role"}
    for facet, active in (("gender", f.genders), ("age", f.age_bands), ("tenure", f.tenure),
                          ("majority", f.majority_bands)):
        if active:
            out.add(facet)
    return out


def rerank_query(plan: QueryPlan, how: str | None) -> str:
    """What the re-ranker compares passages with: the question as asked, the search keywords, or both
    (the keywords carry the topic of a follow-up such as "what about the Lords?")."""
    if how == "keywords":
        return plan.search_text
    if how == "question":
        return plan.question
    return f"{plan.question} ({plan.search_text})"


class Pipeline:
    def __init__(self, settings: Settings, engine: Engine | None = None, client=None, today: date | None = None):
        self.settings = settings
        self.engine = engine or Engine(settings, today=today)
        self.votes = VoteFinder(settings, self.engine.con)
        self._client = client
        self.today = today
        self._edms = None

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
                plan.interpretation = to_british(plan.interpretation)
                from hansard.rag.answer import usage_dict

                usage = usage_dict(u)
            except Exception as exc:
                log.warning("model query parsing failed (%s); using offline rules", exc)
                plan = parse_offline(req.question, self.settings.regions, self.today)
                plan.parse_error = f"{type(exc).__name__}: {exc}"
        else:
            plan = parse_offline(req.question, self.settings.regions, self.today)
        if plan.unresolved_speakers:
            plan.speakers, plan.unresolved_speakers = resolve_speakers(
                self.engine.resolver.con, plan.unresolved_speakers, plan.filters)
            plan.filters.person_ids = [s["person_id"] for s in plan.speakers]
        self._set_comparison(plan, req)
        return plan, usage

    def person_name(self, person_id: str) -> str | None:
        row = self.engine.resolver.con.execute("SELECT latest_name FROM ref_persons WHERE person_id = ?",
                                               [person_id]).fetchone()
        return row[0] if row else None

    def _set_comparison(self, plan: QueryPlan, req: AskRequest) -> None:
        """Sides from the Compare page, or from a question that asks to compare named members or parties."""
        from hansard.compare import resolve_sides, sides_from_question

        names = dict(self.parties())
        sides = (resolve_sides(req.compare, names, self.person_name) if req.compare
                 else sides_from_question(plan.question, plan.filters, plan.speakers, names))
        if not sides:
            return
        plan.compare = sides
        kinds = {s["kind"] for s in sides}
        # each side brings its own filter; the question's other filters (dates, House, roles) still apply to both
        if "party" in kinds:
            plan.filters.parties = []
        if "person" in kinds:
            plan.filters.person_ids = []
        if "nation" in kinds:
            plan.filters.regions = []
        plan.group_by = "role"
        plan.interpretation = (plan.interpretation + " " if plan.interpretation else "") + \
            "Comparing " + " and ".join(s["label"] for s in sides) + ", each searched separately."

    def find(self, plan: QueryPlan, req: AskRequest):
        """The evidence for a plan: (search result, divisions, numbered sources). Free: no model call."""
        limit = int(self.settings.answer.get(
            "comprehensive_sources" if req.mode == "comprehensive" else "summary_sources", 12))
        rq = rerank_query(plan, self.settings.ranking.get("rerank_query"))
        if plan.compare:
            result = self._compare_search(plan, req, limit, rq)
        else:
            result = self.engine.search(plan.search_text, plan.filters, req.scope, plan.portfolios,
                                        req.recency, req.role_weight, limit, diversify=True, group_by=plan.group_by,
                                        rerank_query=rq)
        divisions = []
        if req.scope.votes and (plan.wants_votes or not result.records):
            divisions = self.votes.find(plan.search_text, plan.filters, limit=4)
        edms = self.find_edms(plan, req) if getattr(req.scope, "edms", True) else []
        return result, divisions, build_sources(result.records, divisions, plan_facets(plan), plan.group_by, edms)

    def find_edms(self, plan: QueryPlan, req: AskRequest) -> list[dict[str, Any]]:
        """A few early day motions on the subject, with signatures counted by party on the day (when collected)."""
        if plan.speakers or plan.filters.person_ids or plan.compare:
            return []  # questions about particular members or sides: their own words and votes come first
        from hansard.people import members_by_parliament_id
        from hansard.sources.edms import EdmStore
        from hansard.sync import edms_path
        from hansard.votes import keywords

        path = edms_path(self.settings)
        if not path.exists():
            return []
        try:
            if self._edms is None:
                self._edms = EdmStore(path)
            found = self._edms.relevant(keywords(plan.search_text),
                                        date_from=plan.filters.date_from and plan.filters.date_from.isoformat(),
                                        date_to=plan.filters.date_to and plan.filters.date_to.isoformat(),
                                        limit=3 if req.mode == "comprehensive" else 2)
            pairs = [(s["mnis"], s["signed"]) for e in found for s in e["sponsors"]]
            pairs += [(e["primary_mnis"], e["date_tabled"]) for e in found if e["primary_mnis"]]
            members = members_by_parliament_id(self.engine.con, pairs)
        except Exception:  # never let motions break a briefing
            log.exception("early day motions unavailable")
            return []
        for e in found:
            counts: dict[str, int] = {}
            for s in e["sponsors"]:
                if not s["withdrawn"]:
                    party = (members.get((s["mnis"], s["signed"])) or {}).get("party") or s["party"] or "Unknown"
                    counts[party] = counts.get(party, 0) + 1
            e["party_counts"] = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
            m = members.get((e["primary_mnis"], e["date_tabled"])) or {}
            e["sponsor"] = {"name": m.get("name") or e["primary_name"], "party": m.get("party") or e["primary_party"],
                            "number": m.get("number"), "slug": m.get("slug")}
        return found

    def _compare_search(self, plan: QueryPlan, req: AskRequest, limit: int, rq: str):
        """One search per side, each with an equal share of the sources."""
        from dataclasses import replace

        from hansard.compare import side_filters

        share = max(4, -(-limit // len(plan.compare)))
        results = []
        for side in plan.compare:
            res = self.engine.search(plan.search_text, side_filters(plan.filters, side), req.scope, plan.portfolios,
                                     req.recency, req.role_weight, share, diversify=True, group_by="role",
                                     rerank_query=rq)
            for r in res.records:
                r["compare_side"] = side["label"]
            results.append(res)
        records = [r for res in results for r in res.records]
        from hansard.rank.evidence import evidence_summary

        return replace(results[0], records=records, scored=[x for res in results for x in res.scored],
                       no_records=all(res.no_records for res in results),
                       candidates=sum(res.candidates for res in results), evidence=evidence_summary(records))

    def run(self, req: AskRequest) -> Iterator[dict[str, Any]]:
        plan, parse_usage = self.make_plan(req)
        ev: dict[str, Any] = {"type": "plan", "plan": plan.to_dict(), "usage": parse_usage}
        if plan.parse_error:
            ev["parse_error"] = plan.parse_error  # for the operator's failure log; removed before reaching readers
        yield ev

        result, divisions, sources = self.find(plan, req)
        from hansard.devolution import notes_for
        from hansard.rank.evidence import evidence_summary

        yield {"type": "sources", "sources": [s.card() for s in sources], "candidates": result.candidates,
               "semantic": result.semantic_available,
               "evidence": {**evidence_summary(result.records, divisions), "devolution": notes_for(plan.question),
                            "edms": sum(1 for s in sources if s.kind == "edm")}}

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
                req.question, sources, req.mode, plan_note(plan, req.scope), req.history, self.today,
                group_by=plan.group_by, compare=plan.compare):
            if ev["type"] == "final":
                final = ev
            else:
                yield ev
        if final is None or final["stop_reason"] == "refusal":
            yield {"type": "error", "message": "The model declined to answer this question."}
            return
        report = verify(final["blocks"], sources)
        britishise_segments(report.segments)  # the model's own words only; quotations stay verbatim
        flag_loaded(report.segments)          # judgemental words in its own voice are highlighted, not hidden
        check_quotes(report, sources)         # quotations not found word for word in their sources are marked
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
