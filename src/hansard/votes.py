"""Division (vote) evidence: find relevant divisions and who rebelled.

A member *rebels* when they vote against the majority of their own party's
voting members in that division (the Public Whip definition). Party is the
member's party on the division date (so defections are handled), with
Labour/Co-operative counted as Labour. Speakers, Deputy Speakers, crossbench
and non-affiliated members have no whip and never count as rebels.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import duckdb

from hansard.config import Settings
from hansard.engine import Filters
from hansard.reference.profiles import attach_reference
from hansard.store.parquet import attach_store

_STOP = set(["a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for", "from", "had", "has", "have", "how", "i", "in", "into", "is", "it", "its", "me", "mps", "mp", "members", "member", "lords", "lord", "of", "on", "or", "our", "over", "parliament", "said", "say", "says", "the", "their", "them", "they", "this", "to", "vote", "voted", "votes", "voting", "was", "were", "what", "when", "where", "which", "who", "why", "will", "with", "between", "since", "during", "about", "against", "dissent", "dissented", "rebel", "rebels", "rebelled", "rebellion", "bill", "bills", "northern", "southern", "government", "ministers", "minister", "debate", "debates"])
_WORD = re.compile(r"[a-z][a-z0-9-]{2,}")


def keywords(text: str) -> list[str]:
    words = [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]
    return list(dict.fromkeys(words))[:8]


class VoteFinder:
    def __init__(self, settings: Settings, con: duckdb.DuckDBPyConnection | None = None):
        self.con = con or duckdb.connect()
        attach_reference(self.con, settings.reference_dir)
        self.available = {"divisions", "votes"} <= set(attach_store(self.con, settings.parquet_dir))

    def find(self, text: str, filters: Filters, limit: int = 4) -> list[dict[str, Any]]:
        kws = keywords(text)
        if not self.available or not kws:
            return []
        heading = "lower(coalesce(major_heading, '') || ' ' || coalesce(minor_heading, ''))"
        score = " + ".join(f"(CASE WHEN {heading} LIKE ? THEN 1 ELSE 0 END)" for _ in kws)
        where, params = ["1=1"], [f"%{k}%" for k in kws]
        if filters.date_from:
            where.append("date >= ?")
            params.append(filters.date_from)
        if filters.date_to:
            where.append("date <= ?")
            params.append(filters.date_to)
        if filters.houses:
            where.append(f"house IN ({', '.join('?' for _ in filters.houses)})")
            params.extend(filters.houses)
        need = 1 if len(kws) == 1 else 2
        rows = self.con.execute(
            f"""SELECT * FROM (SELECT d.*, ({score}) AS kw FROM divisions d WHERE {' AND '.join(where)})
                WHERE kw >= {need} ORDER BY kw DESC, date DESC, number DESC LIMIT {int(limit)}""",
            [*params[:len(kws)], *params[len(kws):]]).fetchall()
        cols = [d[0] for d in self.con.description]
        divisions = [dict(zip(cols, r, strict=True)) for r in rows]
        return [self.summarise(d, filters) for d in divisions]

    def summarise(self, div: dict[str, Any], filters: Filters) -> dict[str, Any]:
        rows = self.con.execute(
            """
            WITH v AS (
                SELECT v.vote, v.teller, coalesce(pid.person_id, v.xml_person_id) AS person_id, v.date
                FROM votes v LEFT JOIN ref_person_ids pid ON pid.xml_id = v.xml_person_id
                WHERE v.division_id = ?
            ),
            m AS (
                SELECT v.person_id, v.vote, v.teller,
                       arg_max(struct_pack(party_id := mm.party_id, party := mm.party_name,
                                           constituency := mm.constituency, region := mm.region), mm.start) AS mem
                FROM v LEFT JOIN ref_memberships mm
                  ON mm.person_id = v.person_id AND v.date BETWEEN mm.start AND mm."end"
                GROUP BY v.person_id, v.vote, v.teller
            ),
            g AS (
                SELECT m.*, p.whip_group,
                       (SELECT arg_max(n.name, n.start) FROM ref_names n
                         WHERE n.person_id = m.person_id AND ? BETWEEN n.start AND n."end") AS name
                FROM m LEFT JOIN ref_parties p ON p.party_id = m.mem.party_id
            ),
            maj AS (
                SELECT whip_group, mode(vote) AS majority, count(*) AS n
                FROM g WHERE whip_group IS NOT NULL GROUP BY whip_group
            )
            SELECT g.name, g.mem.party, g.mem.constituency, g.mem.region, g.vote, g.whip_group, maj.majority,
                   (g.whip_group IS NOT NULL AND maj.n >= 2 AND g.vote <> maj.majority) AS rebel
            FROM g LEFT JOIN maj USING (whip_group)
            """, [div["division_id"], div["date"]]).fetchall()
        voters = [dict(zip(["name", "party", "constituency", "region", "vote", "whip_group", "majority", "rebel"],
                           r, strict=True)) for r in rows]
        in_scope = [v for v in voters if (not filters.regions or v["region"] in filters.regions)
                    and (not filters.parties or (v["whip_group"] in filters.parties))]
        rebels = sorted((v for v in in_scope if v["rebel"]), key=lambda v: (v["party"] or "", v["name"] or ""))
        party_votes: dict[str, dict[str, int]] = {}
        for v in in_scope:
            p = party_votes.setdefault(v["party"] or "Unknown", {"aye": 0, "no": 0})
            if v["vote"] in p:
                p[v["vote"]] += 1
        return {
            **{k: div[k] for k in ("division_id", "house", "number", "major_heading", "minor_heading", "ayes", "noes",
                                   "official_url", "twfy_url", "colnum")},
            "date": div["date"].isoformat() if isinstance(div["date"], date) else div["date"],
            "scope_note": _scope_note(filters),
            "party_votes": party_votes,
            "rebels": rebels,
            "voters_in_scope": len(in_scope),
        }


def _scope_note(f: Filters) -> str:
    parts = []
    if f.regions:
        parts.append("members for seats in " + ", ".join(f.regions))
    if f.parties:
        parts.append("party: " + ", ".join(f.parties))
    return "; ".join(parts) or "all members"


def division_text(d: dict[str, Any]) -> list[str]:
    """Plain-text blocks describing a division, used as a citable source."""
    title = " — ".join(x for x in (d["major_heading"], d["minor_heading"]) if x)
    house = "House of Commons" if d["house"] == "commons" else "House of Lords"
    blocks = [f"{house} division {d['number']} on {d['date']}: {title}. "
              f"Result: Ayes {d['ayes']}, Noes {d['noes']}."]
    pv = "; ".join(f"{p}: {c['aye']} aye, {c['no']} no" for p, c in sorted(d["party_votes"].items()))
    if pv:
        blocks.append(f"Votes by party ({d['scope_note']}): {pv}.")
    if d["rebels"]:
        names = "; ".join(f"{r['name']} ({r['party']}, {r['constituency'] or 'Lords'}) voted {r['vote']} "
                          f"against the {r['party']} majority ({r['majority']})" for r in d["rebels"][:40])
        more = f" and {len(d['rebels']) - 40} more" if len(d["rebels"]) > 40 else ""
        blocks.append(f"Members voting against their own party's majority ({d['scope_note']}): {names}{more}.")
    else:
        blocks.append(f"No members ({d['scope_note']}) voted against their own party's majority.")
    return blocks
