"""Turn ranked records and division summaries into numbered, citable sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from hansard.rank.evidence import GROUPS, demographic_group, seat_type_label, speaker_group
from hansard.sources.demographics import AGE_BAND_LABEL
from hansard.sources.elections import MAJORITY_BAND_LABEL
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


def age_label(sp: dict[str, Any]) -> str | None:
    """'aged 54' or 'aged about 54' (only the year of birth is known), on the date of the record."""
    if sp.get("age") is None:
        return None
    return f"aged {'about ' if sp.get('age_approximate') else ''}{sp['age']}"


def _facets(facets: set[str] | bool) -> set[str]:
    return {"gender", "age"} if facets is True else (set(facets) if facets else set())


def majority_label(m: dict[str, Any] | None) -> str | None:
    """e.g. 'majority 4,937 (11.8%) at the 2019 general election'."""
    if not m:
        return None
    pct = f" ({m['pct']}%)" if m.get("pct") is not None else ""
    return f"majority {m['majority']:,}{pct} at the {m['election']}"


def speaker_label(r: dict[str, Any], facets: set[str] | bool = False) -> str:
    """e.g. 'Hilary Benn (Labour; MP for Leeds Central, city seat (West Yorkshire urban area, 1.9m people),
    Yorkshire and The Humber; role on this date: Chair, Exiting the European Union Committee)'.

    ``facets`` adds, only when the question is about them: gender, age on the date, first term, majority then.
    """
    facets = _facets(facets)
    sp = r.get("speaker") or {}
    name = sp.get("name") or r.get("speaker_name_raw") or "Unattributed"
    bits = []
    if sp.get("person_id"):
        if "gender" in facets:
            bits.append({"F": "woman", "M": "man"}.get(sp.get("gender") or "", "gender not known"))
        if "age" in facets:
            bits.append(age_label(sp) or "age not known")
        if "tenure" in facets and sp.get("house") == "commons":
            bits.append({True: "first-term MP", False: "re-elected MP"}.get(sp.get("first_term"),
                                                                            "first election not known"))
        if "majority" in facets and sp.get("house") == "commons":
            bits.append(majority_label(sp.get("majority_then")) or "majority not known")
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


def group_label(speaker: dict[str, Any] | None, group_by: str = "role") -> str:
    """The heading a source is listed under: the speaker's role group, or their gender, age, tenure or majority."""
    if group_by == "tenure":
        return {"first-term": "First-term MPs", "returning": "Re-elected MPs"}.get(
            demographic_group(speaker, "tenure"), "Peers and others")
    if group_by == "majority":
        band = demographic_group(speaker, "majority")
        return (MAJORITY_BAND_LABEL[band][0].upper() + MAJORITY_BAND_LABEL[band][1:] if band in MAJORITY_BAND_LABEL
                else "Majority not known")
    if group_by == "gender":
        return {"F": "Women", "M": "Men"}.get(demographic_group(speaker, "gender"), "Gender not known")
    if group_by == "age":
        band = demographic_group(speaker, "age")
        return f"Aged {AGE_BAND_LABEL[band]} on the day" if band in AGE_BAND_LABEL else "Age not known"
    return GROUPS[speaker_group(speaker)]


def record_source(n: int, r: dict[str, Any], facets: set[str] | bool = False, group_by: str = "role") -> Source:
    ref = f"col. {r['colnum']}" if r.get("colnum") else (f"UIN {r['uin']}" if r.get("uin") else "")
    heading = r.get("heading") or r.get("minor_heading") or r.get("major_heading") or ""
    kind_label = {"question": "Written question", "answer": "Written answer", "statement": "Written statement"}.get(
        r["record_type"], r["chamber"])
    title = " — ".join(x for x in (speaker_label(r, facets), f"{kind_label}, {r['chamber']}" if kind_label != r["chamber"]
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
        "group": group_label(r.get("speaker"), group_by),
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


def build_sources(records: list[dict[str, Any]], divisions: list[dict[str, Any]],
                  facets: set[str] | bool = False, group_by: str = "role") -> list[Source]:
    out = [record_source(i, r, facets, group_by) for i, r in enumerate(records, 1)]
    out += [division_source(len(out) + i, d) for i, d in enumerate(divisions, 1)]
    return out
