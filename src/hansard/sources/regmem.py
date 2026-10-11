"""The Register of Members' Financial Interests, from TheyWorkForYou's copy of each edition (Open Parliament Licence).

MPs must register jobs and earnings, donations, gifts and hospitality, visits abroad, land and property,
shareholdings and some other interests. Each edition of the register is published as XML by TheyWorkForYou
(``pwdata/scrapedxml/regmem``), with every member identified by their parlparse person ID, so no matching by name
is needed. The site keeps the latest edition and shows each current MP's entries on their page, as registered.

Addresses are left out: the register publishes donors' addresses, but repeating private individuals' addresses adds
nothing to understanding a member's interests.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from lxml import etree

from hansard.sources.demographics import USER_AGENT

log = logging.getLogger(__name__)

BASE = "https://www.theyworkforyou.com/pwdata/scrapedxml/regmem/"
OFFICIAL = "https://www.parliament.uk/mps-lords-and-offices/standards-and-financial-interests/parliamentary-commissioner-for-standards/registers-of-interests/register-of-members-financial-interests/"
_FILE = re.compile(r'href="(regmem(\d{4}-\d{2}-\d{2})\.xml)"')
_SKIP = re.compile(r"address|identifier source|^is until further notice$", re.I)


def _text(el: etree._Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _item(div: etree._Element) -> dict[str, Any]:
    summary = div.find("./h4") if div.find("./h4") is not None else div.find("./h6")
    ul = div.find("./ul")
    details, registered, published = [], None, None
    for li in (ul if ul is not None else []):
        cls = li.get("class") or ""
        if cls == "interest-detail":
            name = _text(li.find("./span[@class='interest-detail-name']")).rstrip(": ")
            value = _text(li.find("./span[@class='interest-detail-value']"))
            if name and value and not _SKIP.search(name) and value != _text(summary) \
                    and value not in (v for _, v in details):  # "Donor Company Name" often repeats "Donor Name"
                details.append([name, value])
        elif cls == "registration-date":
            registered = _text(li).split(":", 1)[-1].strip()
        elif cls == "published-date":
            published = _text(li).split(":", 1)[-1].strip()
    children = [_item(c) for c in div.findall("./div[@class='interest-child-items']/div[@class='interest-item']")]
    return {"summary": _text(summary), "details": details, "registered": registered, "published": published,
            "children": children}


def _category_key(t: str) -> tuple[float, str]:
    try:
        return float(t), t
    except ValueError:
        return 99.0, t


def parse(xml: bytes) -> dict[str, Any]:
    """One edition: {"edition": date, "members": {person_id: {"name", "categories": [...]}}}."""
    root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, huge_tree=True))
    members: dict[str, Any] = {}
    edition = None
    for rm in root.iter("regmem"):
        pid = rm.get("personid")
        if not pid:
            continue
        edition = edition or rm.get("date")
        cats = []
        for cat in rm.findall("./category"):
            items = []
            for rec in cat.findall("./record"):
                for item in rec.findall("./item"):
                    for div in item.findall("./div[@class='interest-item']"):
                        items.append(_item(div))
                    if item.find("./div[@class='interest-item']") is None and _text(item):
                        items.append({"summary": _text(item), "details": [], "registered": None,
                                      "published": None, "children": []})  # older plain-text entries
            if items:
                cats.append({"type": cat.get("type") or "", "name": cat.get("name") or "", "items": items})
        cats.sort(key=lambda c: _category_key(c["type"]))
        members[pid] = {"name": rm.get("membername"), "categories": cats}
    return {"edition": edition, "members": members}


def latest_edition(client: httpx.Client) -> tuple[str, str] | None:
    """(file name, date) of the newest edition listed."""
    resp = client.get(BASE)
    resp.raise_for_status()
    found = sorted(_FILE.findall(resp.text), key=lambda x: x[1])
    return found[-1] if found else None


def refresh(path: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """Fetch the newest edition if it is newer than the copy on disk. Keeps the old copy on any failure."""
    path = Path(path)
    current = None
    if path.exists():
        try:
            current = json.loads(path.read_text()).get("edition")
        except (OSError, ValueError):
            current = None
    own = client is None
    client = client or httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    try:
        latest = latest_edition(client)
        if latest is None:
            return {"edition": current, "updated": False, "error": "no editions listed"}
        name, day = latest
        if current == day:
            return {"edition": day, "updated": False}
        resp = client.get(BASE + name)
        resp.raise_for_status()
        data = parse(resp.content)
        if not data["members"]:
            return {"edition": current, "updated": False, "error": f"{name}: no members found"}
        data["edition"] = day
        data["fetched"] = datetime.now(UTC).isoformat(timespec="seconds")
        data["source"] = BASE + name
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)
        return {"edition": day, "updated": True, "members": len(data["members"])}
    finally:
        if own:
            client.close()


class Register:
    """The latest edition on disk, reloaded when the file changes."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] | None = None
        self._mtime: float | None = None

    def _load(self) -> dict[str, Any]:
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime
            except OSError:
                return {}
            if self._data is None or mtime != self._mtime:
                try:
                    self._data, self._mtime = json.loads(self.path.read_text()), mtime
                except (OSError, ValueError):
                    return self._data or {}
            return self._data

    def for_person(self, person_id: str) -> dict[str, Any] | None:
        data = self._load()
        m = (data.get("members") or {}).get(person_id)
        if not data:
            return None
        return {"edition": data.get("edition"), "source": data.get("source"), "official": OFFICIAL,
                "categories": (m or {}).get("categories", []), "listed": m is not None}
