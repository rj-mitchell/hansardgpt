"""Shareable briefings.

Every completed briefing is kept at an unguessable address (/b/<id>), with the sources and checks exactly as
they were shown, the date it was prepared and the most recent record it could draw on. A kept briefing is
also the record to consult if someone later questions what the site published. A briefing can be withdrawn
(after a complaint, for example); its address then says so instead of showing it.
"""

from __future__ import annotations

import html
import json
import re
import secrets
from datetime import date
from typing import Any

from hansard.store.state import StateDB, utcnow

# no 0/o or 1/l, so an address read aloud or retyped is not misread; 10 characters is about 50 bits
_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
ID_PATTERN = re.compile(r"^[a-km-z2-9]{10}$")


def new_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(10))


def store_briefing(state: StateDB, question: str, settings: dict[str, Any], events: list[dict[str, Any]],
                   records_up_to: str | None, model: str | None) -> dict[str, str]:
    """Keep a briefing; returns its id and creation time."""
    created = utcnow()
    with state.connect() as con:
        for _ in range(5):
            bid = new_id()
            try:
                con.execute("INSERT INTO briefings (id, created_at, question, settings, events, records_up_to, model) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (bid, created, question, json.dumps(settings, default=str),
                             json.dumps(events, default=str), records_up_to, model))
                return {"id": bid, "created_at": created}
            except Exception as exc:  # an id collision is astronomically unlikely; try another
                if "UNIQUE" not in str(exc):
                    raise
    raise RuntimeError("could not allocate a briefing id")


def get_briefing(state: StateDB, bid: str) -> dict[str, Any] | None:
    if not ID_PATTERN.match(bid):
        return None
    with state.connect() as con:
        row = con.execute("SELECT * FROM briefings WHERE id = ?", (bid,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["settings"] = json.loads(out["settings"])
    out["events"] = json.loads(out["events"])
    return out


def withdraw_briefing(state: StateDB, bid: str, reason: str) -> bool:
    with state.connect() as con:
        cur = con.execute("UPDATE briefings SET withdrawn_at = ?, withdrawn_reason = ? WHERE id = ?",
                          (utcnow(), reason, bid))
    return cur.rowcount > 0


def recent_briefings(state: StateDB, limit: int = 50) -> list[dict[str, Any]]:
    with state.connect() as con:
        rows = con.execute("SELECT id, created_at, question, withdrawn_at, withdrawn_reason FROM briefings "
                           "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def public_view(b: dict[str, Any]) -> dict[str, Any]:
    """What a reader of /b/<id> receives: the question, the evidence and the checked answer, nothing internal."""
    ev = {e["type"]: e for e in b["events"]}
    plan, sources, final = ev.get("plan", {}), ev.get("sources", {}), ev.get("final", {})
    return {
        "id": b["id"],
        "question": b["question"],
        "created_at": b["created_at"],
        "records_up_to": b["records_up_to"],
        "settings": b["settings"],
        "plan": plan.get("plan"),
        "sources": sources.get("sources", []),
        "candidates": sources.get("candidates"),
        "semantic": sources.get("semantic"),
        "evidence": sources.get("evidence"),
        "answer": final.get("answer"),
    }


_MD = [(re.compile(r"\s*\[Source \d+\]"), ""),
       (re.compile(r"^#+ .*$", re.M), ""),                                  # the briefing's own title line
       (re.compile(r"\*\*\s*(Headline|Summary|Briefing)\s*:?\s*\*\*\s*:?", re.I), ""),  # "**Headline:**" labels
       (re.compile(r"^\s*(Headline|Summary)\s*:?\s*$", re.M | re.I), ""),      # a label on its own line
       (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
       (re.compile(r"\s+"), " ")]


def summary_text(answer: dict[str, Any] | None, limit: int = 220) -> str:
    """The opening of a briefing as plain text, for link previews."""
    text = (answer or {}).get("markdown") or ""
    for pattern, repl in _MD:
        text = pattern.sub(repl, text)
    text = re.sub(r"^(Headline:?|Briefing:?)\s*", "", text.strip(), flags=re.I)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%B %Y')}"


_HEAD_TAGS = re.compile(
    r'\s*<(?:meta (?:property="og:[^"]+"|name="(?:twitter:[^"]+|description|robots)")[^>]*|link rel="canonical"[^>]*|'
    r'title>[^<]*</title)>', re.I)


def page_with_meta(index_html: str, *, title: str, description: str, url: str, image: str | None,
                   image_alt: str = "", noindex: bool = True) -> str:
    """The app's index.html with the page title and link-preview tags for one briefing."""
    e = html.escape
    tags = [f"<title>{e(title)}</title>",
            f'<meta name="description" content="{e(description)}" />',
            f'<link rel="canonical" href="{e(url)}" />',
            '<meta property="og:site_name" content="Where They Stand" />',
            '<meta property="og:type" content="article" />',
            '<meta property="og:locale" content="en_GB" />',
            f'<meta property="og:title" content="{e(title)}" />',
            f'<meta property="og:description" content="{e(description)}" />',
            f'<meta property="og:url" content="{e(url)}" />',
            '<meta name="twitter:card" content="summary_large_image" />']
    if image:
        tags += [f'<meta property="og:image" content="{e(image)}" />',
                 '<meta property="og:image:width" content="1200" />',
                 '<meta property="og:image:height" content="630" />',
                 f'<meta property="og:image:alt" content="{e(image_alt)}" />']
    if noindex:
        tags.append('<meta name="robots" content="noindex" />')
    stripped = _HEAD_TAGS.sub("", index_html)
    return stripped.replace("</head>", "    " + "\n    ".join(tags) + "\n  </head>", 1)
