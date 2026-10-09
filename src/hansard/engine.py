"""Deterministic retrieval: filters -> BM25 + vector candidates -> composite rank -> records.

Given the same index, query text, filters and slider values, results are
identical every time. The only non-deterministic step in the product, turning
a plain-English question into filters, happens before this (``rag.query_parse``)
and its output is shown to the user as editable chips.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import duckdb

from hansard.config import Settings
from hansard.embed.base import Embedder, get_embedder
from hansard.index.lance import SearchIndex, date_lit, sql_list, sql_str
from hansard.rank.composite import Candidate, RankParams, Scored, rank
from hansard.rank.evidence import evidence_summary, select_evidence
from hansard.reference.profiles import ProfileResolver
from hansard.store.parquet import read_partition_rows

log = logging.getLogger(__name__)

WRITTEN_SOURCES = {"wrans", "lordswrans", "wms", "lordswms"}
PBC_SOURCES = {"standing"}
ORAL_SOURCES = {"debates", "westminhall", "lordspages"}


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    houses: list[str] = field(default_factory=list)          # "commons", "lords"
    regions: list[str] = field(default_factory=list)         # ITL1 names
    parties: list[str] = field(default_factory=list)         # party ids, e.g. "labour"
    person_ids: list[str] = field(default_factory=list)
    offices: list[str] = field(default_factory=list)         # "gov", "shadow", "chair", "backbench"
    record_types: list[str] = field(default_factory=list)    # speech/question/answer/statement

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("date_from", "date_to"):
            d[k] = d[k].isoformat() if d[k] else None
        return d


@dataclass
class Scope:
    """Corpus scope toggles from the UI."""

    written: bool = True   # written answers and written ministerial statements
    pbc: bool = True       # Public Bill Committee debates
    votes: bool = True     # division (voting) records

    def sources(self) -> list[str]:
        s = set(ORAL_SOURCES)
        if self.written:
            s |= WRITTEN_SOURCES
        if self.pbc:
            s |= PBC_SOURCES
        return sorted(s)


@dataclass
class SearchResult:
    scored: list[Scored]
    records: list[dict[str, Any]]
    no_records: bool
    candidates: int
    semantic_available: bool
    where: str | None
    evidence: dict[str, Any] = field(default_factory=dict)


def build_where(filters: Filters, scope: Scope) -> str:
    clauses = [f"source IN ({', '.join(sql_str(s) for s in scope.sources())})"]
    if filters.date_from:
        clauses.append(f"date >= {date_lit(filters.date_from)}")
    if filters.date_to:
        clauses.append(f"date <= {date_lit(filters.date_to)}")
    if filters.houses:
        clauses.append(f"house IN ({', '.join(sql_str(h) for h in filters.houses)})")
    if filters.regions:
        clauses.append(f"region IN ({', '.join(sql_str(r) for r in filters.regions)})")
    if filters.parties:
        clauses.append(f"party_id IN ({', '.join(sql_str(p) for p in filters.parties)})")
    if filters.person_ids:
        clauses.append(f"person_id IN ({', '.join(sql_str(p) for p in filters.person_ids)})")
    if filters.record_types:
        clauses.append(f"record_type IN ({', '.join(sql_str(t) for t in filters.record_types)})")
    office = []
    for o in filters.offices:
        if o == "gov":
            office.append("is_gov = true")
        elif o == "shadow":
            office.append("is_shadow = true")
        elif o == "chair":
            office.append("is_chair = true")
        elif o == "backbench":
            office.append("(is_gov = false AND is_shadow = false AND is_chair = false)")
    if office:
        clauses.append("(" + " OR ".join(office) + ")")
    return " AND ".join(clauses)


class Engine:
    def __init__(self, settings: Settings, embedder: Embedder | None = None, today: date | None = None):
        self.settings = settings
        dim = int(settings.embedding.get("dim", 384))
        self.index = SearchIndex(settings.index_dir, dim)
        self.resolver = ProfileResolver(settings.reference_dir)
        self._embedder = embedder
        self.today = today
        self.con = duckdb.connect()
        self.con.execute("SET enable_object_cache = true")  # cache Parquet footers between queries

    @property
    def embedder(self) -> Embedder | None:
        if self._embedder is None:
            try:
                self._embedder = get_embedder(self.settings)
            except Exception as exc:  # semantic search degrades to keyword-only
                log.warning("embedder unavailable (%s); using keyword search only", exc)
                return None
        return self._embedder

    def expand_parties(self, parties: list[str]) -> list[str]:
        """'labour' also matches Labour/Co-operative members (same whip)."""
        if not parties:
            return []
        rows = self.resolver.con.execute(
            """SELECT party_id FROM ref_parties WHERE list_contains(?, party_id) OR whip_group IN
               (SELECT whip_group FROM ref_parties WHERE list_contains(?, party_id) AND whip_group IS NOT NULL)""",
            [parties, parties]).fetchall()
        return sorted({r[0] for r in rows} | set(parties))

    def search(self, query: str, filters: Filters | None = None, scope: Scope | None = None,
               portfolios: list[str] | None = None, recency: float | None = None,
               role_weight: float | None = None, limit: int = 12, diversify: bool = False) -> SearchResult:
        filters, scope = filters or Filters(), scope or Scope()
        r = self.settings.ranking
        if filters.parties:
            filters = Filters(**{**filters.__dict__, "parties": self.expand_parties(filters.parties)})
        where = build_where(filters, scope)
        bm = self.index.bm25(query, where, int(r.get("candidates_bm25", 300)))
        vec_hits: list[dict[str, Any]] = []
        semantic = self.index.stats()["vectors"] > 0 and self.embedder is not None
        if semantic:
            vec_hits = self.index.vector(self.embedder.embed_query(query), where,
                                         int(r.get("candidates_vector", 300)))

        cands: dict[str, Candidate] = {}

        def cand_for(hit: dict[str, Any]) -> Candidate:
            c = cands.get(hit["record_id"])
            if c is None:
                hit = dict(hit)
                c = Candidate(
                    record_id=hit["record_id"], date=hit["date"],
                    is_gov=bool(hit["is_gov"]), is_shadow=bool(hit["is_shadow"]), is_chair=bool(hit["is_chair"]),
                    gov_portfolios=list(hit["gov_portfolios"] or []),
                    shadow_portfolios=list(hit["shadow_portfolios"] or []),
                    chair_portfolios=list(hit["chair_portfolios"] or []),
                    data={"source": hit["source"], "source_key": hit["source_key"], "passages": {},
                          "person_id": hit.get("person_id")},
                )
                cands[hit["record_id"]] = c
            return c

        for h in bm:
            c = cand_for(h)
            c.data["passages"][h["passage_id"]] = {"text": h["text"], "heading": h["heading"]}
            if c.bm25 is None or h["_score"] > c.bm25:
                c.bm25 = float(h["_score"])
                c.best_passage_id = h["passage_id"]
        for h in vec_hits:
            c = cand_for(h)
            sim = 1.0 - float(h["_distance"])
            if c.cosine is None or sim > c.cosine:
                c.cosine = sim
                if c.bm25 is None:
                    c.best_passage_id = h["passage_id"]

        floor, ceiling = getattr(self.embedder, "similarity_range", (0.5, 0.85)) if semantic else (0.5, 0.85)
        params = RankParams.from_settings(
            r, recency=recency, role_weight=role_weight,
            semantic_floor=r.get("semantic_floor", floor), semantic_ceiling=r.get("semantic_ceiling", ceiling),
            **({"today": self.today} if self.today else {}))
        scored = rank(list(cands.values()), set(portfolios or []), params)
        best_cos = max((c.cosine or 0.0 for c in cands.values()), default=0.0)
        no_records = not scored or (semantic and best_cos < float(r.get("no_records_cosine", 0.0))
                                    and not any(c.bm25 for c in cands.values()))
        if diversify and scored:
            pool = scored[:max(limit * 8, 150)]
            profiles = self.resolver.profiles([(s.candidate.record_id, s.candidate.data.get("person_id"),
                                                s.candidate.date) for s in pool])
            top = select_evidence(pool, profiles, limit,
                                  max_per_speaker=int(r.get("max_per_speaker", 2)),
                                  min_relevance_ratio=float(r.get("min_relevance_ratio", 0.25)))
        else:
            top = scored[:limit]
        records = self.records_for(top) if top else []
        return SearchResult(top, records, no_records, len(cands), semantic, where, evidence_summary(records))

    # ---- full records for display / grounding ---------------------------------
    def records_for(self, scored: list[Scored]) -> list[dict[str, Any]]:
        by_part: dict[tuple[str, int], list[Scored]] = {}
        for s in scored:
            by_part.setdefault((s.candidate.data["source"], s.candidate.date.year), []).append(s)
        found: dict[tuple[str, str], dict[str, Any]] = {}
        for (source, year), items in by_part.items():
            ids = [s.candidate.record_id for s in items]
            keys = sorted({s.candidate.data["source_key"] for s in items})
            dates = sorted({s.candidate.date for s in items})
            # date and source_key predicates let DuckDB skip row groups of the date-sorted files
            where = (f"date BETWEEN DATE '{dates[0].isoformat()}' AND DATE '{dates[-1].isoformat()}' "
                     f"AND source_key IN {sql_list(keys)} AND record_id IN {sql_list(ids)}")
            for rec in read_partition_rows(self.con, self.settings.parquet_dir, "records", source, year, where):
                # the indexed copy: other files may hold older copies, and an ID can repeat within a file
                found.setdefault((rec["record_id"], rec["source_key"]), rec)
        rows = {s.candidate.record_id: found[key] for s in scored
                if (key := (s.candidate.record_id, s.candidate.data["source_key"])) in found}
        passages = {pid: p for s in scored for pid, p in s.candidate.data.get("passages", {}).items()}
        missing = [s.candidate.best_passage_id for s in scored
                   if s.candidate.best_passage_id and s.candidate.best_passage_id not in passages]
        passages.update(self.index.passages_for(missing))
        profiles = self.resolver.profiles([(rid, rows[rid]["xml_person_id"], rows[rid]["date"]) for rid in rows])
        out = []
        for s in scored:
            rec = rows.get(s.candidate.record_id)
            if rec is None:
                continue
            prof = profiles.get(s.candidate.record_id)
            passage = passages.get(s.candidate.best_passage_id or "", {})
            out.append({
                **{k: rec[k] for k in ("record_id", "source", "house", "chamber", "record_type", "time", "colnum",
                                       "uin", "major_heading", "minor_heading", "oral_heading", "bill", "text",
                                       "context", "official_url", "url_kind", "twfy_url", "speaker_name_raw")},
                "date": rec["date"].isoformat(),
                "heading": passage.get("heading") or rec.get("minor_heading") or rec.get("major_heading"),
                "excerpt": passage.get("text") or rec["text"][:1500],
                "speaker": prof.to_dict() if prof else None,
                "ranking": s.breakdown(),
            })
        return out
