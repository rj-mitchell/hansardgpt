"""Build normalised reference tables from parlparse ``members/`` and the geo lookup.

Outputs (Parquet, in ``settings.reference_dir``):

* ``persons``         one row per canonical person (redirects resolved), with gender and date of
                      birth where known (matched by UK Parliament ID; see ``sources.demographics``)
* ``person_ids``      every id that can appear in Hansard XML -> canonical person:
                      person ids (incl. redirected ones), Commons member ids and
                      Lords ids (incl. redirected memberships)
* ``names``           dated *Main* names (display only; never used for matching)
* ``memberships``     Westminster seat / peerage spells with party, constituency,
                      GSS code, region and nation
* ``offices``         government, shadow, parliamentary, whip and committee spells,
                      de-duplicated and interval-merged, with policy portfolios
* ``constituencies``  ONS constituency -> ITL1 region with validity intervals
* ``parties``         party id -> name and whip group (for rebellion analysis)
* ``representations`` the Commons seats each MP has held, by UK Parliament constituency id (Members API)
* ``election_results`` every general election and by-election result for those seats (Members API)

Identity is keyed only on ``uk.org.publicwhip/person/N``. Names, including
"Alternate" names such as "The Prime Minister", are never used to resolve who
spoke.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from hansard.dates import SENTINEL_END, parse_end, parse_start
from hansard.reference.portfolios import (
    KIND_CHAIR,
    KIND_MEMBER,
    classify_committee,
    classify_post,
)

COMMONS = "commons"
LORDS = "lords"
PERSON_PREFIX = "uk.org.publicwhip/person/"

# Parties whose members take the same whip, for rebellion analysis.
PARTY_GROUPS = {
    "labourco-operative": "labour",
    "labour": "labour",
}
NON_PARTISAN = {"speaker", "deputy-speaker", "presiding-officer", "crossbench", "non-affiliated",
                "independent", "none", "bishop", "other"}

# Committee display names that differ from the latest name parlparse stores
# under the committee id (ids carry the most recent name).
COMMITTEE_NAME_HISTORY: dict[str, list[tuple[date, date, str]]] = {
    "committee-on-the-future-relationship-with-the-european-union": [
        (date(2016, 7, 1), date(2020, 1, 26), "Exiting the European Union Committee"),
    ],
}


@dataclass
class ReferenceData:
    persons: list[dict[str, Any]] = field(default_factory=list)
    person_ids: list[dict[str, Any]] = field(default_factory=list)
    names: list[dict[str, Any]] = field(default_factory=list)
    memberships: list[dict[str, Any]] = field(default_factory=list)
    offices: list[dict[str, Any]] = field(default_factory=list)
    constituencies: list[dict[str, Any]] = field(default_factory=list)
    parties: list[dict[str, Any]] = field(default_factory=list)
    representations: list[dict[str, Any]] = field(default_factory=list)
    election_results: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- names


def normalise_place(name: str) -> str:
    """Normalise a constituency name for matching ("&" vs "and", punctuation, accents)."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"\bst\.?\b", "st", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def format_main_name(n: dict[str, Any]) -> str:
    """Display form of a parlparse Main name (Commons or Lords style)."""
    prefix = (n.get("honorific_prefix") or "").strip()
    lordname = (n.get("lordname") or "").strip()
    lordofname = (n.get("lordofname") or "").strip()
    if lordname or lordofname:
        parts = [prefix] if prefix else []
        if lordname:
            parts.append(lordname)
        text = " ".join(parts)
        if lordofname:
            text = f"{text} of {lordofname}" if text else lordofname
        return text.strip()
    given = (n.get("given_name") or "").strip()
    family = (n.get("family_name") or "").strip()
    base = " ".join(p for p in (given, family) if p) or (n.get("name") or "").strip()
    if prefix in {"Sir", "Dame"}:
        return f"{prefix} {base}"
    return base


# --------------------------------------------------------------------------- loaders


def _resolve_chain(mapping: dict[str, str], key: str) -> str:
    seen = set()
    while key in mapping and key not in seen:
        seen.add(key)
        key = mapping[key]
    return key


def election_tables(persons: list[dict[str, Any]], elections: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    by_mnis = {p["datadotparl_id"]: p["person_id"] for p in persons if p.get("datadotparl_id")}
    reps = []
    for mnis, seats in (elections.get("representations") or {}).items():
        person = by_mnis.get(str(mnis))
        if person is None:
            continue
        for r in seats:
            reps.append({"person_id": person, "constituency_id": int(r["id"]), "constituency_name": r["name"],
                         "start": date.fromisoformat(r["start"]),
                         "end": date.fromisoformat(r["end"]) if r.get("end") else SENTINEL_END})
    results = []
    for cid, rs in (elections.get("results") or {}).items():
        for r in rs:
            results.append({"constituency_id": int(cid), "election_date": date.fromisoformat(r["date"]),
                            "title": r.get("title"), "is_general": bool(r.get("general")),
                            "majority": r.get("majority"), "votes": r.get("votes"), "electorate": r.get("electorate"),
                            "result": r.get("result"), "party": r.get("party")})
    return reps, results


def load_constituencies(csv_path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(csv_path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "gss_code": r["gss_code"],
                "name": r["name"],
                "region": r["region"],
                "nation": r["nation"],
                "boundary_set": r["boundary_set"],
                "valid_from": date.fromisoformat(r["valid_from"]),
                "valid_to": date.fromisoformat(r["valid_to"]),
                "settlement": r.get("settlement") or None,
                "main_area": r.get("main_area") or None,
                "urban_area": r.get("urban_area") or None,
                "urban_area_pop": int(r["urban_area_pop"]) if r.get("urban_area_pop") else None,
            })
    return rows


def load_overrides(path: Path | None) -> dict[str, str]:
    """``config/overrides/constituency_names.csv``: parlparse name -> ONS name."""
    if not path or not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return {normalise_place(r["parlparse_name"]): normalise_place(r["ons_name"])
                for r in csv.DictReader(fh) if r.get("parlparse_name")}


def build_reference(
    members_dir: Path,
    geo_csv: Path,
    overrides_csv: Path | None = None,
    demographics: dict[str, dict[str, Any]] | None = None,
    elections: dict[str, Any] | None = None,
) -> ReferenceData:
    genders = (demographics or {}).get("genders", {})
    births = (demographics or {}).get("births", {})
    # members with a Wikidata item but no UK Parliament ID in ParlParse: Wikidata records the ID (P10428)
    mnis_by_qid = {b["qid"]: m for m, b in births.items() if b.get("qid")}
    people = json.loads((members_dir / "people.json").read_text(encoding="utf-8"))
    ref = ReferenceData()
    ref.constituencies = load_constituencies(geo_csv)

    # ---- persons, redirects and dated names
    person_redirect = {p["id"]: p["redirect"] for p in people["persons"] if "redirect" in p}
    for p in people["persons"]:
        if "redirect" in p:
            continue
        idents = {i["scheme"]: str(i["identifier"]) for i in p.get("identifiers", [])}
        mains = []
        for n in p.get("other_names", []):
            if n.get("note") != "Main":
                continue
            mains.append({
                "person_id": p["id"],
                "name": format_main_name(n),
                "start": parse_start(n.get("start_date")),
                "end": parse_end(n.get("end_date")),
            })
        mains.sort(key=lambda r: r["start"])
        ref.names.extend(mains)
        mnis = idents.get("datadotparl_id") or mnis_by_qid.get(idents.get("wikidata", ""))
        birth = births.get(mnis) if mnis else None
        ref.persons.append({
            "person_id": p["id"],
            "latest_name": mains[-1]["name"] if mains else p["id"],
            "datadotparl_id": mnis,
            "wikidata": idents.get("wikidata"),
            "gender": genders.get(mnis) if mnis else None,
            "birth_date": date.fromisoformat(birth["date"]) if birth else None,
            "birth_precision": birth["precision"] if birth else None,
        })
    known = {p["person_id"] for p in ref.persons}

    # ---- parties
    for org in people["organizations"]:
        if org.get("classification") == "party":
            ref.parties.append({
                "party_id": org["id"],
                "party_name": org.get("name", org["id"]),
                "whip_group": None if org["id"] in NON_PARTISAN else PARTY_GROUPS.get(org["id"], org["id"]),
            })
    party_names = {p["party_id"]: p["party_name"] for p in ref.parties}

    # ---- posts and seat -> GSS matching
    posts = {p["id"]: p for p in people["posts"]}
    overrides = load_overrides(overrides_csv)
    by_set: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    # A few unchanged seats (e.g. Orkney and Shetland) keep their GSS code across
    # boundary sets, so codes map to every entry and the one valid on the date wins.
    by_gss: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in ref.constituencies:
        by_set[c["boundary_set"]][normalise_place(c["name"])] = c
        by_gss[c["gss_code"]].append(c)

    def seat_for(post: dict[str, Any], on: date) -> dict[str, Any] | None:
        for ident in post.get("identifiers", []):
            if ident["scheme"] == "gss" and ident["identifier"] in by_gss:
                entries = by_gss[ident["identifier"]]
                return next((c for c in entries if c["valid_from"] <= on <= c["valid_to"]), entries[-1])
        bset = "2024" if on >= date(2024, 7, 4) else "2010" if on >= date(2010, 5, 6) else None
        if bset is None:
            return None
        names = [post["area"]["name"], *post["area"].get("other_names", [])]
        for raw in names:
            key = normalise_place(raw)
            key = overrides.get(key, key)
            if key in by_set[bset]:
                return by_set[bset][key]
        return None

    # ---- memberships
    member_redirect: dict[str, str] = {}
    member_person: dict[str, str] = {}
    unmatched_seats: set[str] = set()
    for m in people["memberships"]:
        if "redirect" in m:
            member_redirect[m["id"]] = m["redirect"]
            continue
        pid = _resolve_chain(person_redirect, m.get("person_id", ""))
        if pid not in known:
            continue
        member_person[m["id"]] = pid
        start, end = parse_start(m.get("start_date")), parse_end(m.get("end_date"))
        post = posts.get(m.get("post_id", ""))
        if m.get("organization_id") == "house-of-lords":
            house, constituency, seat = LORDS, None, None
        elif post and post.get("organization_id") == "house-of-commons":
            house, constituency = COMMONS, post["area"]["name"]
            # Seat set is decided by where the membership falls; memberships that
            # straddle the archive start resolve against the set in force then.
            on = max(start, date(2010, 5, 6))
            seat = seat_for(post, on) if end >= date(2010, 5, 6) else None
            if seat is None and end >= date(2010, 5, 6):
                unmatched_seats.add(constituency)
        else:
            continue  # devolved legislatures etc. are out of scope
        party = m.get("on_behalf_of_id")
        ref.memberships.append({
            "membership_id": m["id"],
            "person_id": pid,
            "house": house,
            "constituency": constituency,
            "gss_code": seat["gss_code"] if seat else None,
            "region": seat["region"] if seat else None,
            "nation": seat["nation"] if seat else None,
            "settlement": seat.get("settlement") if seat else None,
            "urban_area": seat.get("urban_area") if seat else None,
            "urban_area_pop": seat.get("urban_area_pop") if seat else None,
            "party_id": party,
            "party_name": party_names.get(party, party),
            "start": start,
            "end": end,
            "start_reason": m.get("start_reason"),
            "end_reason": m.get("end_reason"),
        })

    # ---- every id that may appear in XML -> canonical person
    for old, new in person_redirect.items():
        ref.person_ids.append({"xml_id": old, "person_id": _resolve_chain(person_redirect, new)})
    for pid in known:
        ref.person_ids.append({"xml_id": pid, "person_id": pid})
    for mid, pid in member_person.items():
        ref.person_ids.append({"xml_id": mid, "person_id": pid})
    for old in member_redirect:
        target = _resolve_chain(member_redirect, old)
        if target in member_person:
            ref.person_ids.append({"xml_id": old, "person_id": member_person[target]})

    # ---- offices
    ref.offices, office_stats = load_offices(members_dir, person_redirect, known)

    # ---- seats and election results (matched by UK Parliament ID)
    ref.representations, ref.election_results = election_tables(ref.persons, elections or {})

    recent = {m["person_id"] for m in ref.memberships if m["end"] >= date(2010, 5, 6)}
    recent_persons = [p for p in ref.persons if p["person_id"] in recent]
    ref.stats = {
        "persons": len(ref.persons),
        "members_since_2010": len(recent_persons),
        "with_gender_since_2010": sum(1 for p in recent_persons if p["gender"]),
        "with_birth_date_since_2010": sum(1 for p in recent_persons if p["birth_date"]),
        "mps_with_election_results": len({r["person_id"] for r in ref.representations}),
        "election_results": len(ref.election_results),
        "memberships": len(ref.memberships),
        "names": len(ref.names),
        "unmatched_seats_since_2010": sorted(unmatched_seats),
        **office_stats,
    }
    return ref


def load_offices(
    members_dir: Path, person_redirect: dict[str, str], known: set[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    files = [members_dir / "ministers-2010.json", members_dir / "posts" / "westminster-parliament-posts.json"]
    raw_rows: list[dict[str, Any]] = []
    org_names: dict[str, str] = {}
    for f in files:
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        for org in d.get("organizations", []):
            # later files (the posts scraper) carry fresher committee names
            org_names[org["id"]] = org.get("name", org["id"])
        raw_rows.extend(d.get("memberships", []))

    rows_in = len(raw_rows)
    exact: dict[tuple, dict[str, Any]] = {}
    for m in raw_rows:
        pid = _resolve_chain(person_redirect, m.get("person_id", ""))
        if pid not in known:
            continue
        source = m.get("source", "")
        role = (m.get("role") or "").strip()
        if source.endswith("/committee"):
            committee_id = m["organization_id"]
            committee_name = org_names.get(committee_id, committee_id)
            rc = classify_committee(committee_name, role)
        else:
            committee_id = committee_name = None
            rc = classify_post(source, role)
        key = (pid, rc.kind, role if rc.kind not in (KIND_CHAIR, KIND_MEMBER) else rc.kind, committee_id,
               parse_start(m.get("start_date")), parse_end(m.get("end_date")))
        if key in exact:
            exact[key]["source_ids"].append(m["id"])
            continue
        exact[key] = {
            "person_id": pid,
            "kind": rc.kind,
            "role": role or (rc.kind.replace("_", " ").title() if committee_id else ""),
            "portfolios": list(rc.portfolios),
            "committee_id": committee_id,
            "committee_name": committee_name,
            "source": source,
            "start": key[4],
            "end": key[5],
            "source_ids": [m["id"]],
        }
    deduped = list(exact.values())

    # Merge overlapping or adjacent spells of the same office.
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in deduped:
        groups[(r["person_id"], r["kind"], r["role"], r["committee_id"])].append(r)
    merged: list[dict[str, Any]] = []
    for spells in groups.values():
        spells.sort(key=lambda r: (r["start"], r["end"]))
        cur = dict(spells[0], source_ids=list(spells[0]["source_ids"]))
        for nxt in spells[1:]:
            if cur["end"] == SENTINEL_END or nxt["start"] <= cur["end"] + timedelta(days=1):
                cur["end"] = max(cur["end"], nxt["end"])
                cur["source_ids"].extend(nxt["source_ids"])
            else:
                merged.append(cur)
                cur = dict(nxt, source_ids=list(nxt["source_ids"]))
        merged.append(cur)
    for r in merged:
        r["display_name"] = office_display(r)
    stats = {"office_rows_in": rows_in, "office_rows_exact_dupes": rows_in - len(deduped),
             "office_rows_after_merge": len(merged)}
    return merged, stats


def office_display(office: dict[str, Any], on: date | None = None) -> str:
    """Human-readable office title, using the committee name in force on ``on``."""
    if office.get("committee_id"):
        name = office["committee_name"]
        for start, end, old in COMMITTEE_NAME_HISTORY.get(office["committee_id"], []):
            if on is not None and start <= on <= end:
                name = old
        prefix = "Chair, " if office["kind"] == KIND_CHAIR else "Member, "
        return prefix + name
    return office["role"]


# --------------------------------------------------------------------------- output

_SCHEMAS = {
    "persons": pa.schema([("person_id", pa.string()), ("latest_name", pa.string()),
                          ("datadotparl_id", pa.string()), ("wikidata", pa.string()),
                          ("gender", pa.string()), ("birth_date", pa.date32()), ("birth_precision", pa.string())]),
    "person_ids": pa.schema([("xml_id", pa.string()), ("person_id", pa.string())]),
    "names": pa.schema([("person_id", pa.string()), ("name", pa.string()),
                        ("start", pa.date32()), ("end", pa.date32())]),
    "memberships": pa.schema([
        ("membership_id", pa.string()), ("person_id", pa.string()), ("house", pa.string()),
        ("constituency", pa.string()), ("gss_code", pa.string()), ("region", pa.string()),
        ("nation", pa.string()), ("settlement", pa.string()), ("urban_area", pa.string()),
        ("urban_area_pop", pa.int32()), ("party_id", pa.string()), ("party_name", pa.string()),
        ("start", pa.date32()), ("end", pa.date32()), ("start_reason", pa.string()),
        ("end_reason", pa.string())]),
    "offices": pa.schema([
        ("person_id", pa.string()), ("kind", pa.string()), ("role", pa.string()),
        ("portfolios", pa.list_(pa.string())), ("committee_id", pa.string()),
        ("committee_name", pa.string()), ("source", pa.string()), ("start", pa.date32()),
        ("end", pa.date32()), ("source_ids", pa.list_(pa.string())), ("display_name", pa.string())]),
    "constituencies": pa.schema([
        ("gss_code", pa.string()), ("name", pa.string()), ("region", pa.string()),
        ("nation", pa.string()), ("boundary_set", pa.string()), ("valid_from", pa.date32()),
        ("valid_to", pa.date32()), ("settlement", pa.string()), ("main_area", pa.string()),
        ("urban_area", pa.string()), ("urban_area_pop", pa.int32())]),
    "parties": pa.schema([("party_id", pa.string()), ("party_name", pa.string()),
                          ("whip_group", pa.string())]),
    "representations": pa.schema([("person_id", pa.string()), ("constituency_id", pa.int32()),
                                  ("constituency_name", pa.string()), ("start", pa.date32()), ("end", pa.date32())]),
    "election_results": pa.schema([("constituency_id", pa.int32()), ("election_date", pa.date32()),
                                   ("title", pa.string()), ("is_general", pa.bool_()), ("majority", pa.int32()),
                                   ("votes", pa.int32()), ("electorate", pa.int32()), ("result", pa.string()),
                                   ("party", pa.string())]),
}


def write_reference(ref: ReferenceData, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, schema in _SCHEMAS.items():
        rows = getattr(ref, name)
        table = pa.Table.from_pylist(rows, schema=schema)
        tmp = out_dir / f".{name}.parquet.tmp"
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(out_dir / f"{name}.parquet")
    (out_dir / "stats.json").write_text(json.dumps(ref.stats, indent=2, default=str))


__all__ = [
    "COMMONS",
    "LORDS",
    "SENTINEL_END",
    "ReferenceData",
    "build_reference",
    "format_main_name",
    "normalise_place",
    "office_display",
    "write_reference",
]
