"""Readable text in each page's HTML, for anything that reads pages without running their scripts: AI assistants,
search engines, readers with scripts off. It goes where the app later draws the page, so people see no difference.
Plain HTML only, every value escaped."""

from __future__ import annotations

import re
from html import escape as e
from typing import Any

from hansard.api.briefings import fmt_date

_ROOT = re.compile(r'(<div id="[\w-]+-root">)\s*<p class="muted">Loading…</p>\s*(</div>)')
_EMPTY_ROOT = '<div id="root"></div>'
MAX_ITEMS = 60


def with_text(page: str, fragment: str | None) -> str:
    """The page with ``fragment`` placed in its app root (replaced by the app when it starts)."""
    if not fragment:
        return page
    if _EMPTY_ROOT in page:
        return page.replace(_EMPTY_ROOT, f'<div id="root"><main class="thread prose">{fragment}</main></div>', 1)
    return _ROOT.sub(lambda m: m.group(1) + fragment + m.group(2), page, count=1)


def _link(href: str | None, text: str) -> str:
    return f'<a href="{e(href)}">{e(text)}</a>' if href else e(text)


def _inline(md: str) -> str:
    """Escaped text with **bold** kept."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", e(md))


def markdown_text(md: str) -> str:
    """Enough of a briefing's markdown for reading: headings, bold labels, bullets and paragraphs."""
    out, items = [], []
    for block in re.split(r"\n\s*\n", md.strip()):
        for line in block.splitlines():
            line = line.rstrip()
            if re.match(r"^\s*[-*•]\s+", line):
                items.append(f"<li>{_inline(re.sub(r'^\s*[-*•]\s+', '', line))}</li>")
                continue
            if items:
                out.append("<ul>" + "".join(items) + "</ul>")
                items = []
            if m := re.match(r"^(#{1,6})\s+(.*)", line):
                out.append(f"<h3>{_inline(m.group(2))}</h3>")
            elif line.strip():
                out.append(f"<p>{_inline(line.strip())}</p>")
    if items:
        out.append("<ul>" + "".join(items) + "</ul>")
    return "".join(out)


def briefing_text(view: dict[str, Any], heading: str | None = None) -> str:
    answer = view.get("answer") or {}
    parts = [f"<h1>{e(heading or view['question'])}</h1>"]
    if heading:
        parts.append(f"<p><em>{e(view['question'])}</em></p>")
    parts.append(f"<p>A briefing written by AI (Claude) from the Hansard records cited below, prepared "
                 f"{e(fmt_date(view['created_at'][:10]))}"
                 + (f" from records up to {e(fmt_date(view['records_up_to']))}" if view.get("records_up_to") else "")
                 + ". Check the sources before relying on it.</p>")
    if answer.get("markdown"):
        parts.append(markdown_text(answer["markdown"]))
    sources = view.get("sources") or []
    if sources:
        parts.append("<h2>Sources</h2><ol>")
        for s in sources[:MAX_ITEMS]:
            href = s.get("official_url") or s.get("twfy_url") or s.get("url")
            parts.append(f'<li value="{int(s.get("n") or 0)}">{_link(href, s.get("title") or "Source")}</li>')
        parts.append("</ol>")
    return "".join(parts)


def person_text(core: dict[str, Any], activity: dict[str, Any] | None) -> str:
    parts = [f"<h1>{e(core['name'])}</h1>", f"<p>{e(core.get('status') or '')}.</p>"]
    if core.get("memberships"):
        parts.append("<h2>Membership</h2><ul>")
        for m in reversed(core["memberships"]):
            what = f"MP for {m.get('constituency') or '—'}" if m["house"] == "commons" else "House of Lords"
            parts.append(f"<li>{e(what)}{', ' + e(m['party']) if m.get('party') else ''} "
                         f"({e(fmt_date(m['start']))} – {e(fmt_date(m['end'])) if m.get('end') else 'now'})</li>")
        parts.append("</ul>")
    if core.get("offices"):
        parts.append("<h2>Roles</h2><ul>")
        for o in core["offices"][:30]:
            parts.append(f"<li>{e(o['title'])} ({e(fmt_date(o['start']))} – "
                         f"{e(fmt_date(o['end'])) if o.get('end') else 'now'})</li>")
        parts.append("</ul>")
    for s in core.get("seats") or []:
        results = "; ".join(f"{r['election']}: majority {r['majority']:,}" + (f" ({r['pct']}%)" if r.get("pct") else "")
                            for r in s.get("results") or [] if r.get("majority") is not None)
        if results:
            parts.append(f"<p>{e(s['constituency'])}: {e(results)}.</p>")
    contributions = (activity or {}).get("contributions") or []
    if contributions:
        parts.append("<h2>Recent contributions</h2><ol>")
        for c in contributions:
            parts.append(f"<li><p>{e(fmt_date(c['date']))}, {e(c['chamber'])}"
                         + (f", {e(c['heading'])}" if c.get("heading") else "") + "</p>"
                         f"<p>{e(c['excerpt'])}</p><p>{_link(c.get('debate_path') or c.get('twfy_url'), 'Read in full')}</p></li>")
        parts.append("</ol>")
    voting = (activity or {}).get("voting")
    if voting and voting.get("votes"):
        parts.append(f"<h2>Voting record</h2><p>{voting['votes']:,} votes recorded, of which {voting['rebellions']:,} "
                     "were against the majority of their own party.</p>")
    return "".join(parts)


def bill_text(b: dict[str, Any]) -> str:
    parts = [f"<h1>{e(b['name'])}</h1>",
             f"<p>{b.get('contributions', 0):,} contributions in Parliament, {e(fmt_date(b['first']))} to "
             f"{e(fmt_date(b['last']))}.</p><h2>Sittings</h2><ul>"]
    for s in (b.get("sittings") or [])[:MAX_ITEMS]:
        stages = ", ".join(s.get("stages") or [])
        parts.append(f"<li>{e(fmt_date(s['date']))}, {'House of Lords' if s.get('house') == 'lords' else 'House of Commons'}"
                     f"{': ' + e(stages) if stages else ''} — {_link(s.get('path') or s.get('url'), 'read the debate')}</li>")
    parts.append("</ul>")
    return "".join(parts)


def debate_text(d: dict[str, Any]) -> str:
    parts = [f"<h1>{e(d['title'])}</h1>", f"<p>{e(d['chamber_name'])}, {e(fmt_date(d['date']))}"
             + (f", {e(d['department'])}" if d.get("department") else "") + ".</p>"]
    shown = 0
    for it in d.get("items") or []:
        if it.get("kind") == "heading":
            parts.append(f"<h2>{e(' '.join(it.get('paragraphs') or []) or it.get('text') or '')}</h2>")
            continue
        if it.get("kind") != "said":
            continue
        sp = it.get("speaker") or {}
        who = sp.get("name") or it.get("speaker_name_raw") or "A member"
        detail = ", ".join(x for x in (sp.get("party"), sp.get("constituency")) if x)
        body = "".join(f"<p>{e(p)}</p>" for p in it.get("paragraphs") or [])
        parts.append(f"<h3>{e(who)}{' (' + e(detail) + ')' if detail else ''}</h3>{body}")
        shown += 1
        if shown >= 200:
            parts.append(f"<p>{_link(d.get('official_url'), 'The rest of the debate is in Hansard')}.</p>")
            break
    return "".join(parts)


def week_text(w: dict[str, Any]) -> str:
    parts = [f"<h1>In Parliament, week of {e(fmt_date(w['start']))}</h1>"]
    for day in w.get("days") or []:
        parts.append(f"<h2>{e(fmt_date(day['date']))}</h2>")
        for ch in day.get("chambers") or []:
            parts.append(f"<h3>{e(ch['name'])}</h3><ul>")
            for deb in (ch.get("debates") or [])[:MAX_ITEMS]:
                kind = f" ({deb['kind']})" if deb.get("kind") else ""
                parts.append(f"<li>{_link(deb.get('path'), deb['title'])}{e(kind)}</li>")
            parts.append("</ul>")
    return "".join(parts)


def edm_text(m: dict[str, Any]) -> str:
    sponsor = m.get("sponsor") or {}
    parts = [f"<h1>{e(m['title'])}</h1>",
             f"<p>Early day motion {e(m.get('uin') or '')}, tabled {e(fmt_date(m['date_tabled']))}"
             + (f" by {e(sponsor['name'])}" + (f" ({e(sponsor['party'])})" if sponsor.get("party") else "")
                if sponsor.get("name") else "")
             + (f". Signed by {m['sponsors_count']} members" if m.get("sponsors_count") else "") + ".</p>"]
    if m.get("text"):
        parts.append(f"<blockquote><p>{e(m['text'])}</p></blockquote>")
    if m.get("party_counts"):
        parts.append("<p>Signatures by party: " + e(", ".join(f"{p} {n}" for p, n in m["party_counts"])) + ".</p>")
    return "".join(parts)
