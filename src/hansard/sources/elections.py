"""Election results for every MP's seat, from the UK Parliament Members API (Open Parliament Licence).

For each MP since 1997 (matched by UK Parliament ID, never by name) the API lists the constituencies they have
represented, with dates. For each of those constituencies it gives every general election and by-election result:
the majority, votes cast, electorate and outcome. From these the site works out an MP's majority at the time they
spoke (the result of the most recent election in their seat before that day) and now.

Cached in the data folder and refreshed weekly (by-elections happen); if the API cannot be reached, the previous
copy is kept.

The API has results from 2010 only. For the general elections of 1997, 2001 and 2005 the House of Commons Library's
results by constituency (CBP-8647, Open Parliament Licence) are used, kept in data_static/elections (see
scripts/hocl_election_results.py). They are attached to a seat by its name, for the elections in which an MP the
API lists sat for it. By-elections before 2010 are not included.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from hansard.config import STATIC_DIR
from hansard.sources.demographics import USER_AGENT

log = logging.getLogger(__name__)

API = "https://members-api.parliament.uk/api"
REFRESH = timedelta(days=7)
SOURCE = "UK Parliament Members API (constituency election results)"
LIBRARY_CSV = STATIC_DIR / "elections" / "general_elections_1997_2005.csv"
LIBRARY_SOURCE = "House of Commons Library, general election results by constituency (CBP-8647)"

# Majority as a share of votes cast: (key, label, upper bound, exclusive)
MAJORITY_BANDS = [
    ("marginal", "marginal (majority under 10%)", 10.0),
    ("middle", "majority 10% to 20%", 20.0),
    ("safe", "safe (majority over 20%)", 1000.0),
]
MAJORITY_BAND_LABEL = {k: label for k, label, _ in MAJORITY_BANDS}
TENURE_LABEL = {"first-term": "first-term MPs", "returning": "MPs re-elected at least once"}

# UK general elections since 1945. Later ones are also read from the results, so this never goes stale.
GENERAL_ELECTIONS = [date.fromisoformat(d) for d in (
    "1945-07-05", "1950-02-23", "1951-10-25", "1955-05-26", "1959-10-08", "1964-10-15", "1966-03-31",
    "1970-06-18", "1974-02-28", "1974-10-10", "1979-05-03", "1983-06-09", "1987-06-11", "1992-04-09",
    "1997-05-01", "2001-06-07", "2005-05-05", "2010-05-06", "2015-05-07", "2017-06-08", "2019-12-12",
    "2024-07-04")]


def _get(client: httpx.Client, path: str, tries: int = 3) -> Any:
    for attempt in range(tries):
        try:
            resp = client.get(f"{API}{path}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            if attempt == tries - 1:
                raise
            time.sleep(1 + attempt * 2)
    return None


def fetch_representations(client: httpx.Client, member_id: str) -> list[dict[str, Any]]:
    """The Commons seats a member has held: [{"id", "name", "start", "end"}]."""
    body = _get(client, f"/Members/{member_id}/Biography")
    reps = ((body or {}).get("value") or {}).get("representations") or []
    return [{"id": r["id"], "name": r["name"], "start": r["startDate"][:10],
             "end": (r.get("endDate") or "")[:10] or None} for r in reps if r.get("house") == 1 and r.get("id")]


def fetch_results(client: httpx.Client, constituency_id: int) -> list[dict[str, Any]]:
    """Every real (not notional) election result for a constituency, oldest first."""
    body = _get(client, f"/Location/Constituency/{constituency_id}/ElectionResults")
    out = []
    for r in (body or {}).get("value") or []:
        if r.get("isNotional"):
            continue
        out.append({"date": r["electionDate"][:10], "title": r.get("electionTitle"),
                    "general": bool(r.get("isGeneralElection")), "majority": r.get("majority"),
                    "votes": r.get("turnout"), "electorate": r.get("electorate"), "result": r.get("result"),
                    "party": ((r.get("winningParty") or {}).get("name"))})
    return sorted(out, key=lambda x: x["date"])


def refresh_elections(cache: Path, member_ids: list[str], *, force: bool = False, client: httpx.Client | None = None,
                      workers: int = 4) -> dict[str, Any]:
    """Update the cache if it is over a week old (or missing). Keeps the previous copy on any failure."""
    if cache.exists() and not force:
        try:
            old = json.loads(cache.read_text())
            fetched = datetime.fromisoformat(old["fetched_at"])
            # fresh unless a week old, or members are asked for that the copy never looked up (the record grew)
            if datetime.now(UTC) - fetched < REFRESH and set(member_ids) <= set(old.get("requested") or []):
                return {"status": "fresh"}
        except (OSError, ValueError, KeyError):
            pass
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            reps = dict(zip(member_ids, pool.map(lambda m: fetch_representations(client, m), member_ids),
                            strict=True))
            seat_ids = sorted({r["id"] for rs in reps.values() for r in rs})
            results = dict(zip([str(i) for i in seat_ids], pool.map(lambda c: fetch_results(client, c), seat_ids),
                               strict=True))
    except Exception as exc:  # network trouble: keep what we have
        log.warning("could not refresh election results (%s); keeping the previous copy", exc)
        return {"status": "failed", "error": repr(exc)}
    finally:
        if own:
            client.close()
    if not any(results.values()):
        return {"status": "failed", "error": "no results returned"}
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched_at": datetime.now(UTC).isoformat(timespec="seconds"), "source": SOURCE,
                               "requested": sorted(member_ids),
                               "representations": {k: v for k, v in reps.items() if v}, "results": results},
                              sort_keys=True))
    tmp.replace(cache)
    return {"status": "updated", "members": sum(1 for v in reps.values() if v), "seats": len(seat_ids),
            "results": sum(len(v) for v in results.values())}


def seat_key(name: str) -> str:
    """'LIVERPOOL, WEST DERBY', 'Liverpool West Derby' and 'Bedfordshire Mid' / 'Mid Bedfordshire' alike."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower().replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)  # "Richmond (Yorks)" is "RICHMOND" in the Library's file
    words = re.findall(r"[a-z]+", text)
    return " ".join(sorted(w for w in words if w != "and"))


def library_results(path: Path | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    """{(seat key, election date): result} from the Commons Library file (1997 to 2005)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        with open(path or LIBRARY_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[(seat_key(r["constituency"]), r["date"])] = {
                    "date": r["date"], "title": f"{r['year']} General Election", "general": True,
                    "majority": int(r["majority"]) if r["majority"] else None,
                    "votes": int(r["votes"]) if r["votes"] else None,
                    "electorate": int(r["electorate"]) if r["electorate"] else None,
                    "result": None, "party": r["winner"] if r["winner"] != "Other" else None, "source": LIBRARY_SOURCE}
    except OSError:
        pass
    return out


def add_library_results(representations: dict[str, list[dict[str, Any]]], results: dict[str, list[dict[str, Any]]],
                        library: dict[tuple[str, str], dict[str, Any]]) -> int:
    """Fill in the 1997, 2001 and 2005 general elections for seats the API has no result for then: each election
    in which one of the MPs listed sat for the seat, matched by the seat's name. Returns the number added."""
    spans: dict[str, list[tuple[str, str, str]]] = {}
    for seats in representations.values():
        for r in seats:
            spans.setdefault(str(r["id"]), []).append((r["start"], r["end"] or "9999-12-31", r["name"]))  # end: excl.
    dates = sorted({d for _, d in library})
    added = 0
    for cid, ss in spans.items():
        have = {r["date"] for r in results.get(cid, [])}
        for d in dates:
            if d in have:
                continue
            hit = next((library.get((seat_key(name), d)) for start, end, name in ss if start <= d < end
                        and (seat_key(name), d) in library), None)
            if hit:
                results.setdefault(cid, []).append(dict(hit))
                added += 1
        if cid in results:
            results[cid].sort(key=lambda x: x["date"])
    return added


def load_elections(cache: Path, library: Path | None = None) -> dict[str, Any]:
    if not cache.exists():
        return {"representations": {}, "results": {}}
    try:
        raw = json.loads(cache.read_text())
    except (OSError, ValueError):
        return {"representations": {}, "results": {}}
    reps, results = raw.get("representations", {}), raw.get("results", {})
    add_library_results(reps, results, library_results(library))
    return {"representations": reps, "results": results}


def commons_member_ids(people_json: Path, since: str = "1997-05-01") -> list[str]:
    """UK Parliament IDs of everyone who has sat in the Commons since ``since`` (from parlparse people.json)."""
    data = json.loads(Path(people_json).read_text(encoding="utf-8"))
    ids = {p["id"]: str(i["identifier"]) for p in data["persons"] for i in p.get("identifiers", [])
           if i.get("scheme") == "datadotparl_id"}
    out = {ids[m["person_id"]] for m in data.get("memberships", [])
           if m.get("post_id") and m.get("person_id") in ids and (m.get("end_date") or "9999") >= since}
    return sorted(out)


# --------------------------------------------------------------------------- calculations


def majority_band(pct: float | None) -> str | None:
    if pct is None:
        return None
    return next(k for k, _, upper in MAJORITY_BANDS if pct < upper)


def general_elections(results: dict[str, list[dict[str, Any]]] | None = None) -> list[date]:
    seen = set(GENERAL_ELECTIONS)
    for rs in (results or {}).values():
        seen.update(date.fromisoformat(r["date"]) for r in rs if r.get("general"))
    return sorted(seen)


def first_term(first_elected: date | None, on: date, elections: list[date]) -> bool | None:
    """True while an MP is still in the Parliament they were first elected to (including by-election entrants)."""
    if first_elected is None:
        return None
    return not any(first_elected < g <= on for g in elections)


def election_label(result: dict[str, Any]) -> str:
    year = result["date"][:4]
    return f"{year} general election" if result.get("general") else f"{year} by-election"
