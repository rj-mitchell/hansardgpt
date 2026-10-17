"""The lighter side of the record: what made the House laugh (Hansard marks it "[Laughter.]"), the same week in
earlier years, unparliamentary language, and early day motions you might not expect. Found in the record by plain
rules, with no AI and no commentary; every item links to where it was said."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import Any

from hansard.debates import debate_path

LAUGHTER = "[Laughter"
# Early day motions on the lighter side, found by whole words in their titles: food and drink prizes, birthdays and
# centenaries, animals, records and village life
EDM_WORDS = re.compile(
    r"\b(pies?|cakes?|cheeses?|crisps|chip shops?|fish and chips|pub of the year|pubs?|brass bands?|gnomes?|pigeons?|"
    r"ferrets?|tortoises?|owls?|biscuits?|scones?|pantomimes?|morris (?:men|dancers?|dancing)|bagpipes?|conkers?|"
    r"sausages?|pasties|pasty|doughnuts?|100th birthday|centenar\w+|world records?|birthday|bake off|"
    r"curry|curries|tea rooms?|ice cream|cats?|dogs?|ducks?|donkeys?|llamas?|alpacas?)\b", re.I)


def _sentences_before(text: str, at: int, limit: int = 320) -> str:
    """The sentence or two that drew the laugh: the text before the marker, from a sentence start."""
    before = text[:at].rstrip(" —-–").rstrip()
    start = max(before.rfind("\n", 0, len(before) - 1) + 1, 0)
    chunk = before[start:]
    if len(chunk) > limit:
        cut = chunk[-limit:]
        m = re.search(r"(?<=[.!?”\"])\s+[A-Z“\"]", cut)
        chunk = ("…" + cut[m.start() + 1:].lstrip()) if m else "…" + cut.split(" ", 1)[-1]
    return chunk.strip()


def _moment(row: dict[str, Any], marker: str) -> dict[str, Any] | None:
    text = row["text"] or ""
    at = text.find(marker)
    if at < 0:
        return None
    line = _sentences_before(text, at) if marker == LAUGHTER else _around(text, at)
    if len(line) < 20:
        return None
    d = row["date"]
    return {"date": d.isoformat(), "speaker": row["speaker_name_raw"], "person_id": row["person_id"],
            "heading": " — ".join(x for x in (row["major_heading"], row["minor_heading"]) if x) or None,
            "chamber": row["chamber"], "text": line, "twfy_url": row["twfy_url"],
            "debate_path": debate_path(row["source"], d, row["major_heading"], row["minor_heading"], row["bill"],
                                       row["record_id"])}


def _around(text: str, at: int, width: int = 160) -> str:
    lo, hi = max(at - width, 0), min(at + width, len(text))
    out = text[lo:hi].replace("\n", " ").strip()
    return ("…" if lo else "") + out + ("…" if hi < len(text) else "")


class Lighter:
    def __init__(self, con, today: date | None = None):
        self.con = con  # DuckDB with the records store and reference tables attached
        self.today = today or date.today()

    def _rows(self, where: str, params: list[Any], limit: int) -> list[dict[str, Any]]:
        rel = self.con.execute(f"""
            SELECT DISTINCT ON (r.record_id) r.record_id, r.date, r.source, r.chamber, r.major_heading,
                   r.minor_heading, r.bill, r.speaker_name_raw, r.text, r.twfy_url, p.person_id
            FROM records r LEFT JOIN ref_person_ids p ON p.xml_id = r.xml_person_id
            WHERE {where} ORDER BY r.record_id, r.date DESC""", params)
        cols = [c[0] for c in rel.description]
        rows = [dict(zip(cols, r, strict=True)) for r in rel.fetchall()]
        rows.sort(key=lambda r: (r["date"], r["record_id"]), reverse=True)
        return rows[:limit]

    def laughter(self, limit: int = 30) -> list[dict[str, Any]]:
        """The most recent moments the record marks as laughter, one per speaker per day."""
        since = self.today.year - 1
        rows = self._rows("r.year >= ? AND r.text LIKE '%[Laughter%' AND r.record_type = 'speech'", [since], 400)
        out, seen = [], set()
        for r in rows:
            m = _moment(r, LAUGHTER)
            if m and (m["date"], m["speaker"]) not in seen:
                seen.add((m["date"], m["speaker"]))
                out.append(m)
            if len(out) >= limit:
                break
        return out

    def on_this_day(self, limit: int = 12) -> list[dict[str, Any]]:
        """Laughter in the same week of earlier years, newest year first, at most two a year."""
        days = [(self.today + timedelta(days=k)).strftime("%m-%d") for k in range(-3, 4)]
        rows = self._rows("r.year < ? AND strftime(r.date, '%m-%d') IN (SELECT unnest(?)) "
                          "AND r.text LIKE '%[Laughter%' AND r.record_type = 'speech'",
                          [self.today.year, days], 600)
        out, per_year = [], {}
        for r in rows:
            m = _moment(r, LAUGHTER)
            year = r["date"].year
            if m and per_year.get(year, 0) < 2:
                per_year[year] = per_year.get(year, 0) + 1
                out.append(m)
            if len(out) >= limit:
                break
        return out

    def unparliamentary(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = self._rows("r.year >= ? AND lower(r.text) LIKE '%unparliamentary%' AND r.record_type = 'speech'",
                          [self.today.year - 3], 200)
        out = []
        for r in rows:
            text = r["text"] or ""
            at = text.lower().find("unparliamentary")
            m = _moment(r, text[at:at + 15]) if at >= 0 else None
            if m:
                out.append(m)
            if len(out) >= limit:
                break
        return out


def lighter_edms(path, limit: int = 20) -> list[dict[str, Any]]:
    """Early day motions whose titles are on the lighter side (by whole words), newest first."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute("SELECT id, uin, title, date_tabled, primary_name FROM edms "
                           "WHERE date_tabled >= date('now', '-3 years') ORDER BY date_tabled DESC").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [{"id": r[0], "uin": r[1], "title": r[2], "date": r[3], "tabled_by": r[4]}
            for r in rows if EDM_WORDS.search(r[2] or "")][:limit]
