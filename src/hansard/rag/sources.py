"""Turn ranked records and division summaries into numbered, citable sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from hansard.rank.evidence import GROUPS, seat_type_label, speaker_group
from hansard.votes import division_text


@dataclass
class Source:
    n: int                      # 1-based number shown as [Source n]
    kind: str                   # "record" | "division"
    title: str
    url: str
    blocks: list[str]           # citable text, verbatim from the record
    meta: dict[str, Any] = field(default_factory=dict)

    def search_result(self) -> dict[str, Any]:
        return {
            "type": "search_result",
            "source": self.url,
            "title": self.title,
            "content": [{"type": "text", "text": b} for b in self.blocks],
            "citations": {"enabled": True},
        }

    def card(self) -> dict[str, Any]:
        return {"n": self.n, "kind": self.kind, "title": self.title, "url": self.url, **self.meta}


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def speaker_label(r: dict[str, Any]) -> str:
    """e.g. 'Hilary Benn (Labour; MP for Leeds Central, city seat (West Yorkshire urban area, 1.9m people),
    Yorkshire and The Humber; role on this date: Chair, Exiting the European Union Committee)'."""
    sp = r.get("speaker") or {}
    name = sp.get("name") or r.get("speaker_name_raw") or "Unattributed"
    bits = []
    if sp.get("party"):
        bits.append(sp["party"])
    if sp.get("constituency"):
        seat = [f"MP for {sp['constituency']}"]
        if sp.get("settlement"):
            seat.append(seat_type_label(sp))
        if sp.get("region"):
            seat.append(sp["region"])
        bits.append(", ".join(seat))
    elif sp.get("house") == "lords":
        bits.append("member of the House of Lords")
    if sp.get("person_id"):
        roles = [o["title"] for o in sp.get("offices", []) if o.get("kind") in ("gov", "shadow", "chair")]
        bits.append("role on this date: " + ("; ".join(roles) if roles else "backbencher"))
    return f"{name} ({'; '.join(bits)})" if bits else name


def record_source(n: int, r: dict[str, Any]) -> Source:
    ref = f"col. {r['colnum']}" if r.get("colnum") else (f"UIN {r['uin']}" if r.get("uin") else "")
    heading = r.get("heading") or r.get("minor_heading") or r.get("major_heading") or ""
    kind_label = {"question": "Written question", "answer": "Written answer", "statement": "Written statement"}.get(
        r["record_type"], r["chamber"])
    title = " — ".join(x for x in (speaker_label(r), f"{kind_label}, {r['chamber']}" if kind_label != r["chamber"]
                                   else r["chamber"], _fmt_date(r["date"]), ref, heading) if x)
    blocks = [p for p in r["text"].split("\n\n") if p.strip()]
    if r.get("context"):
        blocks = [f"Question asked: {r['context']}", *blocks]
    url = r.get("official_url") or r["twfy_url"]
    meta = {
        "record_id": r["record_id"],
        "date": r["date"],
        "chamber": r["chamber"],
        "record_type": r["record_type"],
        "heading": heading,
        "colnum": r.get("colnum"),
        "uin": r.get("uin"),
        "time": r.get("time"),
        "official_url": r.get("official_url"),
        "url_kind": r.get("url_kind"),
        "twfy_url": r["twfy_url"],
        "speaker": r.get("speaker"),
        "speaker_name_raw": r.get("speaker_name_raw"),
        "group": GROUPS[speaker_group(r.get("speaker"))],
        "text": r["text"],
        "context": r.get("context"),
        "ranking": r.get("ranking"),
    }
    return Source(n, "record", title, url, blocks, meta)


def division_source(n: int, d: dict[str, Any]) -> Source:
    house = "House of Commons" if d["house"] == "commons" else "House of Lords"
    title = f"Division {d['number']}, {house}, {_fmt_date(d['date'])} — " + " — ".join(
        x for x in (d.get("major_heading"), d.get("minor_heading")) if x)
    blocks = division_text(d)
    url = d.get("official_url") or d["twfy_url"]
    meta = {**d, "chamber": house, "text": "\n\n".join(blocks)}
    return Source(n, "division", title, url, blocks, meta)


def build_sources(records: list[dict[str, Any]], divisions: list[dict[str, Any]]) -> list[Source]:
    out = [record_source(i, r) for i, r in enumerate(records, 1)]
    out += [division_source(len(out) + i, d) for i, d in enumerate(divisions, 1)]
    return out
