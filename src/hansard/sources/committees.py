"""Select committees: their inquiries, reports, the government's responses, and who gave oral evidence.

From the UK Parliament Committees API (Open Parliament Licence). Rebuilt about once a week into a small SQLite file
(data/committees.sqlite) with a full-text index of witnesses and their organisations, so the site can show each
committee's work and answer "which organisations does Parliament hear from?". About 150 requests, one at a time.
If the API cannot be reached the previous copy is kept.
"""

from __future__ import annotations

import html
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from hansard.sources.demographics import USER_AGENT

log = logging.getLogger(__name__)

API = "https://committees-api.parliament.uk/api"
SITE = "https://committees.parliament.uk"
REFRESH = timedelta(days=6)
PAGE = 500
PAUSE = 0.25
FIRST_YEAR = 2010  # the start of the site's archive
REPORT_TYPES = {1: "Report", 2: "Government response", 12: "Special report"}

_SCHEMA = """
CREATE TABLE committees (id INTEGER PRIMARY KEY, name TEXT, house TEXT, category TEXT, start TEXT, end TEXT,
                         parent_id INTEGER, departments TEXT, purpose TEXT);
CREATE TABLE inquiries (id INTEGER PRIMARY KEY, title TEXT, type TEXT, open TEXT, close TEXT);
CREATE TABLE inquiry_committees (inquiry_id INTEGER, committee_id INTEGER, PRIMARY KEY (inquiry_id, committee_id));
CREATE TABLE publications (id INTEGER PRIMARY KEY, type TEXT, title TEXT, date TEXT, committee_id INTEGER,
                           hc TEXT, hl TEXT, response_to INTEGER, document_id INTEGER);
CREATE TABLE publication_inquiries (publication_id INTEGER, inquiry_id INTEGER,
                                    PRIMARY KEY (publication_id, inquiry_id));
CREATE TABLE sessions (id INTEGER PRIMARY KEY, date TEXT);
CREATE TABLE session_committees (session_id INTEGER, committee_id INTEGER, PRIMARY KEY (session_id, committee_id));
CREATE TABLE session_inquiries (session_id INTEGER, inquiry_id INTEGER, PRIMARY KEY (session_id, inquiry_id));
CREATE TABLE witnesses (session_id INTEGER, name TEXT, organisation TEXT, role TEXT, mnis INTEGER);
CREATE INDEX witnesses_session ON witnesses (session_id);
CREATE INDEX witnesses_org ON witnesses (organisation COLLATE NOCASE);
CREATE INDEX publications_committee ON publications (committee_id, date);
CREATE INDEX inquiry_committees_committee ON inquiry_committees (committee_id);
CREATE INDEX session_committees_committee ON session_committees (committee_id);
CREATE VIRTUAL TABLE witness_text USING fts5(name, organisation, role, content='witnesses');
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _day(v: Any) -> str | None:
    return str(v)[:10] if v else None


def _plain(text: str | None, limit: int = 600) -> str | None:
    """The first paragraph of an HTML description, as plain text."""
    if not text:
        return None
    first = re.split(r"</p>", text, maxsplit=1, flags=re.I)[0]
    out = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", first)).split())
    out = re.sub(r" ([.,;:!?)])", r"\1", out)  # the space a closing tag left before punctuation
    return out[:limit] if out else None


def _pages(client: httpx.Client, path: str, params: dict[str, Any], sleep: Callable[[float], None]
           ) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    skip = 0
    while True:
        body = _get(client, path, {**params, "Skip": skip, "Take": PAGE}, sleep)
        items = (body or {}).get("items") or []
        out += items
        skip += PAGE
        total = (body or {}).get("totalResults")
        if len(items) < PAGE or (total is not None and skip >= total) or skip > 100000:
            return out


def _get(client: httpx.Client, path: str, params: dict[str, Any] | None, sleep: Callable[[float], None],
         tries: int = 4) -> Any:
    for attempt in range(tries):
        try:
            resp = client.get(f"{API}{path}", params=params)
            if resp.status_code == 429:
                if attempt == tries - 1:
                    resp.raise_for_status()
                retry = resp.headers.get("Retry-After", "")
                sleep(min(int(retry) if retry.isdigit() else 30 * (attempt + 1), 300))
                continue
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            body = resp.json()
            sleep(PAUSE)
            return body
        except (httpx.HTTPError, ValueError):
            if attempt == tries - 1:
                raise
            sleep(2 + attempt * 3)
    return None


def _previous_purposes(path: Path) -> dict[int, str | None]:
    """Committee remits from the last copy, so a weekly rebuild need not fetch each committee again."""
    if not path.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return {cid: purpose for cid, purpose in con.execute("SELECT id, purpose FROM committees") if purpose}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def build(path: Path, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep,
          details: bool = True) -> dict[str, Any]:
    """Fetch everything and write a fresh database (swapped in only when complete)."""
    own = client is None
    client = client or httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    try:
        committees = _pages(client, "/Committees", {"CommitteeStatus": "All"}, sleep)
        businesses = _pages(client, "/CommitteeBusiness", {}, sleep)
        # a year at a time: the service fails when asked to page thousands deep
        pubs, sessions = [], []
        for year in range(FIRST_YEAR, datetime.now(UTC).year + 1):
            window = {"StartDate": f"{year}-01-01", "EndDate": f"{year}-12-31"}
            pubs += _pages(client, "/Publications", {"PublicationTypeIds": list(REPORT_TYPES), **window}, sleep)
            sessions += _pages(client, "/OralEvidence", window, sleep)
        purposes = _previous_purposes(Path(path))
        if details:  # the remit of each current committee, from its own record (only those not known already)
            for c in committees:
                if not c.get("endDate") and c.get("id") and not purposes.get(c["id"]):
                    one = _get(client, f"/Committees/{c['id']}", None, sleep) or {}
                    purposes[c["id"]] = _plain(one.get("purpose"))
    finally:
        if own:
            client.close()
    if not committees or not sessions:
        raise ValueError("the committees API returned no committees or no evidence sessions")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(_SCHEMA)
        con.executemany("INSERT OR REPLACE INTO committees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (c["id"], c.get("name"), c.get("house"), (c.get("category") or {}).get("name"), _day(c.get("startDate")),
             _day(c.get("endDate")), (c.get("parentCommittee") or {}).get("id"),
             "; ".join(d.get("name", "") for d in c.get("scrutinisingDepartments") or []) or None,
             purposes.get(c["id"])) for c in committees if c.get("id")])
        con.executemany("INSERT OR REPLACE INTO inquiries VALUES (?, ?, ?, ?, ?)", [
            (b["id"], b.get("title"), (b.get("type") or {}).get("name"), _day(b.get("openDate")),
             _day(b.get("closeDate"))) for b in businesses if b.get("id")])
        for p in pubs:
            ptype = REPORT_TYPES.get((p.get("type") or {}).get("id"))
            if not ptype or not p.get("id"):
                continue
            docs = p.get("documents") or []
            con.execute("INSERT OR REPLACE INTO publications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                p["id"], ptype, p.get("description"), _day(p.get("publicationStartDate")),
                (p.get("committee") or {}).get("id"), p.get("hcNumber"), p.get("hlPaper"),
                p.get("responseToPublicationId"), docs[0].get("documentId") if docs else None))
            for b in p.get("businesses") or []:
                _business(con, b)
                con.execute("INSERT OR IGNORE INTO publication_inquiries VALUES (?, ?)", (p["id"], b["id"]))
                if (p.get("committee") or {}).get("id"):
                    con.execute("INSERT OR IGNORE INTO inquiry_committees VALUES (?, ?)", (b["id"], p["committee"]["id"]))
        n_witnesses = 0
        seen: set[int] = set()
        for s in sessions:
            if not s.get("id") or s["id"] in seen:
                continue
            seen.add(s["id"])
            con.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (s["id"], _day(s.get("meetingDate"))))
            cids = [c["id"] for c in s.get("committees") or [] if c.get("id")]
            for cid in cids:
                con.execute("INSERT OR IGNORE INTO session_committees VALUES (?, ?)", (s["id"], cid))
            for b in s.get("committeeBusinesses") or []:
                _business(con, b)
                con.execute("INSERT OR IGNORE INTO session_inquiries VALUES (?, ?)", (s["id"], b["id"]))
                for cid in cids:
                    con.execute("INSERT OR IGNORE INTO inquiry_committees VALUES (?, ?)", (b["id"], cid))
            for w in s.get("witnesses") or []:
                member = w.get("memberInfo") or {}
                orgs = w.get("organisations") or [{}]
                for o in orgs:  # one row per organisation a witness spoke for
                    con.execute("INSERT INTO witnesses VALUES (?, ?, ?, ?, ?)", (
                        s["id"], " ".join((w.get("name") or "").split()) or None,
                        " ".join((o.get("name") or "").split()) or None, o.get("role"), member.get("mnisId")))
                    n_witnesses += 1
        con.execute("INSERT INTO witness_text (witness_text) VALUES ('rebuild')")
        built = datetime.now(UTC).isoformat(timespec="seconds")
        con.executemany("INSERT INTO meta VALUES (?, ?)", [("built", built), ("source", API)])
        con.commit()
    finally:
        con.close()
    tmp.replace(path)
    return {"committees": len(committees), "inquiries": len(businesses), "publications": len(pubs),
            "sessions": len(seen), "witnesses": n_witnesses, "built": built}


def _business(con: sqlite3.Connection, b: dict[str, Any]) -> None:
    if b.get("id"):
        con.execute("INSERT OR IGNORE INTO inquiries VALUES (?, ?, ?, ?, ?)", (
            b["id"], b.get("title"), (b.get("type") or {}).get("name"), _day(b.get("openDate")),
            _day(b.get("closeDate"))))


def refresh(path: Path, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep,
            force: bool = False) -> dict[str, Any]:
    """Rebuild if the copy on disk is more than about a week old."""
    path = Path(path)
    if not force and path.exists():
        age = datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if age < REFRESH:
            return {"updated": False, "age_days": age.days}
    return {"updated": True, **build(path, client, sleep)}


# ---- reading, for the pages ---------------------------------------------------------------------------------
def links(kind: str, ident: int, extra: int | None = None) -> str:
    """Parliament's own page for a committee, inquiry, evidence session or publication."""
    if kind == "committee":
        return f"{SITE}/committee/{ident}/"
    if kind == "inquiry":
        return f"{SITE}/work/{ident}/"
    if kind == "session":
        return f"{SITE}/oralevidence/{ident}/html/"
    if extra:
        return f"{SITE}/publications/{ident}/documents/{extra}/default/"
    return f"{SITE}/publications/{ident}/"


class Committees:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()

    @contextmanager
    def connect(self):
        mtime = self.path.stat().st_mtime if self.path.exists() else None
        con, seen = getattr(self._local, "con", None), getattr(self._local, "mtime", None)
        if con is None or seen != mtime:  # a weekly rebuild swaps the file: reopen
            if con is not None:
                con.close()
            con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
            con.row_factory = sqlite3.Row
            self._local.con, self._local.mtime = con, mtime
        yield con

    def available(self) -> bool:
        return self.path.exists()

    def index(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("""
                SELECT c.id, c.name, c.house, c.category, c.departments,
                       (SELECT count(*) FROM inquiry_committees ic WHERE ic.committee_id = c.id) AS inquiries,
                       (SELECT count(*) FROM publications p WHERE p.committee_id = c.id AND p.type = 'Report') AS reports,
                       (SELECT max(s.date) FROM session_committees sc JOIN sessions s ON s.id = sc.session_id
                         WHERE sc.committee_id = c.id) AS last_session
                FROM committees c WHERE c.end IS NULL AND c.parent_id IS NULL
                ORDER BY c.house, c.name""").fetchall()
        return [dict(r) | {"url": links("committee", r["id"])} for r in rows]

    def committee(self, cid: int) -> dict[str, Any] | None:
        with self.connect() as con:
            c = con.execute("SELECT * FROM committees WHERE id = ?", (cid,)).fetchone()
            if c is None:
                return None
            inquiries = con.execute("""
                SELECT i.id, i.title, i.type, i.open, i.close,
                       (SELECT count(*) FROM session_inquiries si WHERE si.inquiry_id = i.id) AS sessions,
                       (SELECT count(*) FROM publication_inquiries pi JOIN publications p ON p.id = pi.publication_id
                         WHERE pi.inquiry_id = i.id AND p.type = 'Report') AS reports
                FROM inquiries i JOIN inquiry_committees ic ON ic.inquiry_id = i.id
                WHERE ic.committee_id = ? ORDER BY coalesce(i.open, '') DESC, i.id DESC LIMIT 200""", (cid,)).fetchall()
            subs = con.execute("SELECT id, name FROM committees WHERE parent_id = ? ORDER BY name", (cid,)).fetchall()
            orgs = con.execute("""
                SELECT w.organisation, count(DISTINCT w.session_id) AS n FROM witnesses w
                JOIN session_committees sc ON sc.session_id = w.session_id
                WHERE sc.committee_id = ? AND w.organisation IS NOT NULL
                GROUP BY w.organisation COLLATE NOCASE ORDER BY n DESC, w.organisation LIMIT 15""", (cid,)).fetchall()
        return {**dict(c), "url": links("committee", cid), "inquiries": [dict(i) for i in inquiries],
                "subcommittees": [dict(s) for s in subs], "top_organisations": [dict(o) for o in orgs]}

    def inquiry(self, iid: int) -> dict[str, Any] | None:
        with self.connect() as con:
            i = con.execute("SELECT * FROM inquiries WHERE id = ?", (iid,)).fetchone()
            if i is None:
                return None
            committees = con.execute("""SELECT c.id, c.name, c.house FROM committees c JOIN inquiry_committees ic
                                        ON ic.committee_id = c.id WHERE ic.inquiry_id = ?""", (iid,)).fetchall()
            pubs = con.execute("""SELECT p.* FROM publications p JOIN publication_inquiries pi ON pi.publication_id = p.id
                                  WHERE pi.inquiry_id = ? ORDER BY p.date""", (iid,)).fetchall()
            sessions = con.execute("""SELECT s.id, s.date FROM sessions s JOIN session_inquiries si ON si.session_id = s.id
                                      WHERE si.inquiry_id = ? ORDER BY s.date""", (iid,)).fetchall()
            witnesses = con.execute(f"""SELECT session_id, name, organisation, role, mnis FROM witnesses
                                       WHERE session_id IN ({','.join('?' for _ in sessions) or 'NULL'})""",
                                    [s["id"] for s in sessions]).fetchall()
        by_session: dict[int, list[dict[str, Any]]] = {}
        for w in witnesses:
            by_session.setdefault(w["session_id"], []).append(dict(w))
        reports = {p["id"]: p for p in pubs}
        out_pubs = []
        for p in pubs:
            d = dict(p) | {"url": links("publication", p["id"], p["document_id"])}
            parent = reports.get(p["response_to"]) if p["response_to"] else None
            if parent and parent["date"] and p["date"]:
                d["days_after_report"] = (datetime.fromisoformat(p["date"]) - datetime.fromisoformat(parent["date"])).days
            out_pubs.append(d)
        return {**dict(i), "url": links("inquiry", iid), "committees": [dict(c) for c in committees],
                "publications": out_pubs,
                "sessions": [{"id": s["id"], "date": s["date"], "url": links("session", s["id"]),
                              "witnesses": by_session.get(s["id"], [])} for s in sessions]}

    def witnesses(self, q: str, limit: int = 50) -> dict[str, Any]:
        """Organisations (and people) matching the words, with how often and by whom they were heard."""
        words = re.findall(r"[\w'’&-]+", q)[:8]
        if not words:
            return self.top_organisations()
        match = " ".join(f'"{w}"' for w in words)
        with self.connect() as con:
            rows = con.execute("""
                SELECT w.organisation, count(DISTINCT w.session_id) AS sessions, min(s.date) AS first, max(s.date) AS last,
                       group_concat(DISTINCT c.name) AS committees
                FROM witnesses w JOIN sessions s ON s.id = w.session_id
                LEFT JOIN session_committees sc ON sc.session_id = w.session_id
                LEFT JOIN committees c ON c.id = sc.committee_id
                WHERE w.rowid IN (SELECT rowid FROM witness_text WHERE witness_text MATCH ?)
                GROUP BY coalesce(w.organisation, w.name) COLLATE NOCASE
                ORDER BY sessions DESC LIMIT ?""", (match, limit)).fetchall()
            recent = con.execute("""
                SELECT s.id, s.date, w.name, w.organisation, w.role,
                       (SELECT group_concat(c.name, '; ') FROM session_committees sc JOIN committees c ON c.id = sc.committee_id
                         WHERE sc.session_id = s.id) AS committees,
                       (SELECT i.id FROM session_inquiries si JOIN inquiries i ON i.id = si.inquiry_id
                         WHERE si.session_id = s.id LIMIT 1) AS inquiry_id,
                       (SELECT i.title FROM session_inquiries si JOIN inquiries i ON i.id = si.inquiry_id
                         WHERE si.session_id = s.id LIMIT 1) AS inquiry
                FROM witnesses w JOIN sessions s ON s.id = w.session_id
                WHERE w.rowid IN (SELECT rowid FROM witness_text WHERE witness_text MATCH ?)
                ORDER BY s.date DESC LIMIT 40""", (match,)).fetchall()
        return {"query": q, "organisations": [dict(r) | {"committees": sorted(set((r["committees"] or "").split(",")) - {""})}
                                              for r in rows],
                "sessions": [dict(r) | {"url": links("session", r["id"])} for r in recent]}

    def top_organisations(self, since: str | None = None, limit: int = 30) -> dict[str, Any]:
        since = since or (datetime.now(UTC) - timedelta(days=365 * 2)).date().isoformat()
        with self.connect() as con:
            rows = con.execute("""
                SELECT w.organisation, count(DISTINCT w.session_id) AS sessions, min(s.date) AS first, max(s.date) AS last
                FROM witnesses w JOIN sessions s ON s.id = w.session_id
                WHERE w.organisation IS NOT NULL AND s.date >= ?
                GROUP BY w.organisation COLLATE NOCASE ORDER BY sessions DESC LIMIT ?""", (since, limit)).fetchall()
        return {"query": "", "since": since, "organisations": [dict(r) for r in rows], "sessions": []}

    def for_member(self, mnis: int, limit: int = 10) -> list[dict[str, Any]]:
        """Evidence sessions where a member of either House appeared as a witness (ministers, mostly)."""
        with self.connect() as con:
            rows = con.execute("""
                SELECT s.id, s.date, w.role,
                       (SELECT group_concat(c.name, '; ') FROM session_committees sc JOIN committees c ON c.id = sc.committee_id
                         WHERE sc.session_id = s.id) AS committees,
                       (SELECT i.title FROM session_inquiries si JOIN inquiries i ON i.id = si.inquiry_id
                         WHERE si.session_id = s.id LIMIT 1) AS inquiry
                FROM witnesses w JOIN sessions s ON s.id = w.session_id WHERE w.mnis = ?
                GROUP BY s.id ORDER BY s.date DESC LIMIT ?""", (mnis, limit)).fetchall()
        return [dict(r) | {"url": links("session", r["id"])} for r in rows]

    def stats(self) -> dict[str, Any]:
        with self.connect() as con:
            built = con.execute("SELECT value FROM meta WHERE key = 'built'").fetchone()
            n = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: S608 (fixed table names)
                 for t in ("committees", "inquiries", "publications", "sessions")}
        return {"built": built[0] if built else None, **n}
