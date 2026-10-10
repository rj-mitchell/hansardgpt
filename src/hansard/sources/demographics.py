"""Gender and date of birth for MPs and peers, so a speaker's age on the day they spoke can be shown.

* Gender comes from the UK Parliament Members API, which records it as F or M.
* Date of birth comes from Wikidata (property P569), matched by the member's UK Parliament ID (P10428).
  Precision is kept: a year-only date gives an approximate age.

Members are matched to parlparse people by their UK Parliament ID ("datadotparl_id"), never by name. Both are
cached in one file in the data folder, each part with its own date, and refreshed weekly. If a service cannot be
reached, the previous copy of that part is kept and the site shows "not known" for anything missing.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

MEMBERS_API = "https://members-api.parliament.uk/api/Members/Search"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "WhereTheyStand/1.0 (https://github.com/rj-mitchell/hansardgpt; wheretheystanduk@gmail.com)"
REFRESH = timedelta(days=7)
SOURCES = {"gender": "UK Parliament Members API", "birth_date": "Wikidata (P569, matched by P10428)"}

# Wikidata time precision codes: 9 = year, 10 = month, 11 = day
PRECISION = {9: "year", 10: "month", 11: "day"}
WIKIDATA_QUERY = """
SELECT ?mnis ?dob ?precision WHERE {
  ?person wdt:P10428 ?mnis .
  ?person p:P569 ?stmt .
  ?stmt psv:P569 [ wikibase:timeValue ?dob ; wikibase:timePrecision ?precision ] .
  FILTER NOT EXISTS { ?stmt wikibase:rank wikibase:DeprecatedRank }
}
"""

# Age bands for filtering and grouping, by age on the date of the speech: (key, label, lowest age, highest age)
AGE_BANDS = [
    ("under-40", "under 40", 0, 39),
    ("40-54", "40 to 54", 40, 54),
    ("55-69", "55 to 69", 55, 69),
    ("70-plus", "70 and over", 70, 200),
]
AGE_BAND_LABEL = {k: label for k, label, _, _ in AGE_BANDS}
GENDER_LABEL = {"F": "women", "M": "men"}


def fetch_genders(client: httpx.Client, page_size: int = 20) -> dict[str, str]:
    """Every member of either House the Members API knows about: {Parliament member id: "F" | "M"}."""
    out: dict[str, str] = {}
    for house in (1, 2):
        skip, total = 0, None
        while total is None or skip < total:
            resp = client.get(MEMBERS_API, params={"House": house, "skip": skip, "take": page_size})
            resp.raise_for_status()
            body = resp.json()
            total = int(body.get("totalResults") or 0)
            items = body.get("items") or []
            for item in items:
                v = item.get("value") or {}
                if v.get("id") is not None and v.get("gender") in ("F", "M"):
                    out[str(v["id"])] = v["gender"]
            if not items:
                break
            skip += page_size
            time.sleep(0.05)  # be polite
    return out


def parse_births(body: dict[str, Any]) -> dict[str, dict[str, str]]:
    """SPARQL results -> {Parliament member id: {"date": "YYYY-MM-DD", "precision": "day" | "month" | "year"}}."""
    best: dict[str, dict[str, Any]] = {}
    for b in body["results"]["bindings"]:
        mnis = b["mnis"]["value"]
        precision = int(b["precision"]["value"])
        if precision not in PRECISION:
            continue
        value = b["dob"]["value"].lstrip("+")[:10]
        try:
            date.fromisoformat(value.replace("-00", "-01"))
        except ValueError:
            continue
        prev = best.get(mnis)
        if prev is None or precision > prev["p"]:  # prefer the most precise statement
            best[mnis] = {"date": value.replace("-00", "-01"), "precision": PRECISION[precision], "p": precision}
    return {k: {"date": v["date"], "precision": v["precision"]} for k, v in best.items()}


def fetch_births(timeout: float = 120) -> dict[str, dict[str, str]]:
    """Dates of birth from Wikidata. Uses the standard library: Wikidata's bot filter turns away some HTTP clients."""
    data = urllib.parse.urlencode({"query": WIKIDATA_QUERY}).encode()
    req = urllib.request.Request(WIKIDATA_SPARQL, data=data, headers={
        "User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
        return parse_births(json.loads(resp.read()))


def _read(cache: Path) -> dict[str, Any]:
    if not cache.exists():
        return {}
    try:
        return json.loads(cache.read_text())
    except (OSError, ValueError):
        return {}


def _stale(part: dict[str, Any] | None, now: datetime) -> bool:
    if not part or not part.get("fetched_at"):
        return True
    return now - datetime.fromisoformat(part["fetched_at"]) >= REFRESH


def refresh_demographics(cache: Path, *, force: bool = False, client: httpx.Client | None = None,
                         fetch_births_fn=fetch_births) -> dict[str, Any]:
    """Refresh whichever part is over a week old (or missing); keep the old copy of any part that fails.

    Returns {"status": "fresh" | "updated" | "partial" | "failed", ...}; "updated" and "partial" mean something
    changed and the reference tables should be rebuilt.
    """
    now = datetime.now(UTC)
    current = _read(cache)
    wanted = [k for k in ("genders", "births") if force or _stale(current.get(k), now)]
    if not wanted:
        return {"status": "fresh"}
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    errors: dict[str, str] = {}
    updated: list[str] = []
    try:
        for part in wanted:
            try:
                data = fetch_genders(client) if part == "genders" else fetch_births_fn()
            except Exception as exc:  # network trouble: carry on with what we have
                log.warning("could not refresh %s (%s); keeping the previous copy", part, exc)
                errors[part] = repr(exc)
                continue
            if not data:
                errors[part] = "empty response"
                continue
            current[part] = {"fetched_at": now.isoformat(timespec="seconds"), "data": data}
            updated.append(part)
            _write(cache, current)  # save each part as soon as it arrives
    finally:
        if own:
            client.close()
    status = "failed" if not updated else ("partial" if errors else "updated")
    return {"status": status, "updated": updated, "errors": errors,
            "genders": len((current.get("genders") or {}).get("data", {})),
            "births": len((current.get("births") or {}).get("data", {}))}


def _write(cache: Path, content: dict[str, Any]) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps({**content, "sources": SOURCES}, sort_keys=True))
    tmp.replace(cache)


def load_demographics(cache: Path) -> dict[str, dict[str, Any]]:
    """{"genders": {member id: "F"|"M"}, "births": {member id: {"date", "precision"}}} (empty if never fetched)."""
    raw = _read(cache)
    return {"genders": (raw.get("genders") or {}).get("data", {}),
            "births": (raw.get("births") or {}).get("data", {})}


# --------------------------------------------------------------------------- ages


def assumed_birth(birth_date: str | date | None, precision: str | None) -> date | None:
    """The date used for age calculations: the middle of the year or month when only that much is known."""
    if not birth_date:
        return None
    d = birth_date if isinstance(birth_date, date) else date.fromisoformat(str(birth_date)[:10])
    if precision == "year":
        return date(d.year, 7, 1)
    if precision == "month":
        return date(d.year, d.month, 15)
    return d


def age_on(birth: date | None, on: date) -> int | None:
    if birth is None:
        return None
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def age_band(age: int | None) -> str | None:
    if age is None:
        return None
    for key, _, lo, hi in AGE_BANDS:
        if lo <= age <= hi:
            return key
    return None


def band_dates(birth: date, band: str) -> tuple[date, date]:
    """The dates on which someone born on ``birth`` was in ``band`` (inclusive)."""
    _, _, lo, hi = next(b for b in AGE_BANDS if b[0] == band)

    def plus(years: int) -> date:
        try:
            return birth.replace(year=birth.year + years)
        except ValueError:  # born 29 February: a birthday in other years counts from 1 March, as in age_on
            return date(birth.year + years, 3, 1)

    return plus(lo), plus(hi + 1) - timedelta(days=1)
