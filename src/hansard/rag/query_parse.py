"""Turn a plain-English question into structured, user-editable search filters.

This is the only model-driven step before retrieval. Its output is shown in
the UI as filter chips the user can remove or change; retrieval itself is
deterministic. Without an API key, :func:`parse_offline` applies simple rules.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from hansard.engine import Filters
from hansard.reference.portfolios import PORTFOLIOS, portfolios_for_query

log = logging.getLogger(__name__)

ITL1_REGIONS = [
    "North East", "North West", "Yorkshire and The Humber", "East Midlands", "West Midlands",
    "East of England", "London", "South East", "South West", "Scotland", "Wales", "Northern Ireland",
]
Office = Literal["gov", "shadow", "chair", "backbench"]
House = Literal["commons", "lords"]


class ParsedQuery(BaseModel):
    """Schema the model fills in (structured output)."""

    search_text: str = Field(description="Keywords for retrieval in UK parliamentary vocabulary")
    date_from: str | None = Field(description="YYYY-MM-DD or null")
    date_to: str | None = Field(description="YYYY-MM-DD or null")
    houses: list[House]
    regions: list[str]
    parties: list[str]
    speakers: list[str]
    offices: list[Office]
    portfolios: list[str]
    wants_votes: bool
    interpretation: str = Field(description="One sentence: how the question was interpreted")


@dataclass
class QueryPlan:
    question: str
    search_text: str
    filters: Filters
    portfolios: list[str] = field(default_factory=list)
    wants_votes: bool = False
    speakers: list[dict[str, str]] = field(default_factory=list)  # resolved {"person_id", "name"}
    unresolved_speakers: list[str] = field(default_factory=list)
    interpretation: str = ""
    parser: str = "offline"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "search_text": self.search_text,
            "filters": self.filters.as_dict(),
            "portfolios": self.portfolios,
            "wants_votes": self.wants_votes,
            "speakers": self.speakers,
            "unresolved_speakers": self.unresolved_speakers,
            "interpretation": self.interpretation,
            "parser": self.parser,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> QueryPlan:
        f = d.get("filters") or {}
        filters = Filters(
            date_from=_iso(f.get("date_from")), date_to=_iso(f.get("date_to")),
            houses=list(f.get("houses") or []), regions=list(f.get("regions") or []),
            parties=list(f.get("parties") or []), person_ids=list(f.get("person_ids") or []),
            offices=list(f.get("offices") or []), record_types=list(f.get("record_types") or []),
        )
        return cls(question=d.get("question", ""), search_text=d.get("search_text") or d.get("question", ""),
                   filters=filters, portfolios=list(d.get("portfolios") or []),
                   wants_votes=bool(d.get("wants_votes")), speakers=list(d.get("speakers") or []),
                   interpretation=d.get("interpretation", ""), parser=d.get("parser", "edited"))


def _iso(v: Any) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- offline rules

_YEAR = r"(19\d\d|20\d\d)"


def _dates(q: str, today: date) -> tuple[date | None, date | None]:
    ql = q.lower()
    if m := re.search(rf"between {_YEAR} and {_YEAR}", ql) or re.search(rf"{_YEAR}\s*(?:-|–|to|until)\s*{_YEAR}", ql):
        a, b = sorted(int(x) for x in m.groups())
        return date(a, 1, 1), date(b, 12, 31)
    if m := re.search(rf"(?:since|after|from) {_YEAR}", ql):
        return date(int(m.group(1)), 1, 1), None
    if m := re.search(rf"before {_YEAR}", ql):
        return None, date(int(m.group(1)) - 1, 12, 31)
    if m := re.search(rf"\bin {_YEAR}\b", ql):
        y = int(m.group(1))
        return date(y, 1, 1), date(y, 12, 31)
    if "last year" in ql:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if "this year" in ql:
        return date(today.year, 1, 1), None
    return None, None


_FILTER_WORDS = set(["how", "have", "has", "had", "did", "do", "does", "what", "which", "who", "whom", "whose", "when", "where", "why", "is", "are", "was", "were", "be", "been", "being", "the", "a", "an", "of", "to", "in", "on", "for", "by", "with", "about", "from", "at", "as", "and", "or", "not", "any", "all", "this", "that", "these", "those", "there", "their", "they", "them", "it", "its", "into", "over", "under", "between", "since", "before", "after", "during", "until", "than", "then", "so", "such", "said", "say", "says", "saying", "stated", "mps", "mp", "members", "member", "ministers", "minister", "government", "governments", "lords", "lord", "peers", "peer", "commons", "house", "parliament", "parliamentary", "shadow", "backbench", "backbenchers", "backbencher", "chairs", "chair", "committee", "committees", "northern", "southern", "midlands", "north", "south", "east", "west", "party", "parties", "labour", "conservative", "conservatives", "tory", "tories", "liberal", "democrat", "democrats", "snp", "year", "years", "last", "this"])


def topic_words(question: str) -> str:
    """Retrieval words: drop question words, filter words and years (they become filters)."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", question)
    keep = [w for w in words if w.lower() not in _FILTER_WORDS and not re.fullmatch(r"(19|20)\d\d", w)]
    return " ".join(keep)


def parse_offline(question: str, region_groups: dict[str, list[str]], today: date | None = None) -> QueryPlan:
    today = today or date.today()
    ql = question.lower()
    date_from, date_to = _dates(question, today)
    regions: list[str] = []
    for group, members in region_groups.items():
        stem = group.rstrip("s").replace("_", " ")
        if re.search(rf"\b{re.escape(stem)}", ql):
            regions.extend(members)
    for r in ITL1_REGIONS:
        if r.lower() in ql and r not in regions:
            regions.append(r)
    houses: list[str] = []
    if re.search(r"\blords\b|\bpeers?\b", ql):
        houses.append("lords")
    if re.search(r"\bmps\b|\bcommons\b", ql) or regions:
        houses.append("commons")
    offices: list[str] = []
    if re.search(r"\bshadow\b", ql):
        offices.append("shadow")
    elif re.search(r"\bministers?\b|\bgovernment\b", ql):
        offices.append("gov")
    if re.search(r"committee chairs?|chairs? of", ql):
        offices.append("chair")
    if re.search(r"backbench", ql):
        offices.append("backbench")
    wants_votes = bool(re.search(r"\bvot(e|ed|es|ing)\b|dissent|rebel|divisions?\b", ql))
    return QueryPlan(
        question=question,
        search_text=topic_words(question) or question,
        filters=Filters(date_from=date_from, date_to=date_to, houses=sorted(set(houses)) if len(set(houses)) == 1 else [],
                        regions=regions, offices=offices),
        portfolios=list(portfolios_for_query(question)),
        wants_votes=wants_votes,
        interpretation="Interpreted with offline rules (no language model).",
        parser="offline",
    )


# --------------------------------------------------------------------------- model-based


def system_prompt(region_groups: dict[str, list[str]], parties: list[tuple[str, str]], today: date) -> str:
    groups = "\n".join(f"- {k}: {', '.join(v)}" for k, v in region_groups.items())
    ports = "\n".join(f"- {k}: {v}" for k, v in PORTFOLIOS.items())
    party_list = ", ".join(f"{pid} ({name})" for pid, name in parties)
    return f"""You convert research questions about the UK Parliament into search filters for a Hansard search engine.
Today's date is {today.isoformat()}. The archive covers May 2010 to today.

Rules:
- Only set a filter when the question clearly asks for it. Never invent constraints.
- search_text: the topic, rewritten in the vocabulary used in Hansard. Translate non-UK or informal terms
  (e.g. "zoning" -> "planning, land use", "cops" -> "police") and add close UK synonyms. Leave out words that
  only express filters (dates, regions, party, "ministers").
- date_from/date_to: ISO dates for explicit or clearly implied periods ("between 2018 and 2022" ->
  2018-01-01 to 2022-12-31; "since the 2024 election" -> 2024-07-04).
- houses: "commons" for MPs/House of Commons/constituencies, "lords" for peers/House of Lords.
- regions: ITL1 regions for questions about where MPs' seats are. Named groups:
{groups}
  Region filters apply to MPs only (peers have no constituency), so also set houses to ["commons"].
- parties: party ids from this list: {party_list}
- speakers: full names of specific people the question asks about, as written.
- offices: "gov" for government ministers, "shadow" for opposition frontbenchers, "chair" for select committee
  chairs, "backbench" for backbenchers - only when the question restricts who is speaking.
- portfolios: the policy areas the question is about (used to boost relevant ministers, not to filter):
{ports}
- wants_votes: true if the question is about how members voted, rebellions, dissent or divisions.
- interpretation: one plain sentence describing the filters you chose."""


def parse_with_model(client, settings, question: str, history: list[dict[str, str]] | None,
                     parties: list[tuple[str, str]], today: date | None = None) -> tuple[QueryPlan, Any]:
    today = today or date.today()
    convo = ""
    if history:
        convo = "Earlier questions in this conversation (for resolving references like 'what about the Lords?'):\n"
        convo += "\n".join(f"- {h['question']}" for h in history[-4:]) + "\n\n"
    resp = client.messages.parse(
        model=settings.answer.get("model", "claude-opus-5-5"),
        max_tokens=2000,
        system=system_prompt(settings.regions, parties, today),
        messages=[{"role": "user", "content": f"{convo}Question: {question}"}],
        output_config={"effort": settings.answer.get("query_parse_effort", "low")},
        output_format=ParsedQuery,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"query parser returned no output (stop_reason={resp.stop_reason})")
    p: ParsedQuery = resp.parsed_output
    known_ports = set(PORTFOLIOS)
    known_parties = {pid for pid, _ in parties}
    plan = QueryPlan(
        question=question,
        search_text=p.search_text.strip() or question,
        filters=Filters(
            date_from=_iso(p.date_from), date_to=_iso(p.date_to), houses=sorted(set(p.houses)),
            regions=[r for r in p.regions if r in ITL1_REGIONS],
            parties=[x for x in p.parties if x in known_parties], offices=sorted(set(p.offices)),
        ),
        portfolios=[x for x in p.portfolios if x in known_ports],
        wants_votes=p.wants_votes,
        interpretation=p.interpretation,
        parser="model",
    )
    plan.unresolved_speakers = list(p.speakers)
    return plan, resp.usage


def resolve_speakers(resolver_con, names: list[str], f: Filters) -> tuple[list[dict[str, str]], list[str]]:
    """Map names the user mentioned to person ids, preferring people active in the date range."""
    found, missing = [], []
    for name in names:
        rows = resolver_con.execute(
            """SELECT n.person_id, n.name, max(n."end") AS last_end FROM ref_names n
               WHERE lower(n.name) = lower(?) OR lower(n.name) LIKE '%' || lower(?) || '%'
               GROUP BY ALL ORDER BY (lower(n.name) = lower(?)) DESC, last_end DESC LIMIT 5""",
            [name, name, name]).fetchall()
        if not rows:
            missing.append(name)
            continue
        if f.date_from:
            rows.sort(key=lambda r: r[2] >= f.date_from, reverse=True)
        found.append({"person_id": rows[0][0], "name": rows[0][1], "query": name})
    return found, missing


def plan_json(plan: QueryPlan) -> str:
    return json.dumps(plan.to_dict(), default=str)
