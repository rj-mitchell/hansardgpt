"""Registered interests that may relate to what a cited member said.

For each member quoted in a briefing, the entries in their register of interests (the Commons Register of Members'
Financial Interests, or the Register of Lords' Interests) that were registered before they spoke: ongoing interests
(jobs, directorships, shareholdings, land, unpaid roles) registered on or before the day, and one-off ones (gifts,
hospitality, visits, donations, single payments) registered in the twelve months before it. A small model then
judges, strictly, which of those concern the same subject as the contribution. It runs while the briefing is being
written, so it adds nothing to the wait.

The registers hold current interests (and, for MPs who have left, those in the last edition before they left), so
an interest ended before today is not seen: a contribution from years ago may have had relevant interests that are
not shown. Matches are worded as a connection only, never as a suggestion of influence or wrongdoing.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from hansard.people import person_number

log = logging.getLogger(__name__)

COMMONS_REGISTER = "Register of Members' Financial Interests"
LORDS_REGISTER = "Register of Lords' Interests"

# one-off entries (dated by when they were registered): relevant for a year, as the House's own rule on declaring has it
_ONE_OFF_COMMONS = re.compile(r"^(1\.1|2|3|4|5)\b")
_ONE_OFF_LORDS = re.compile(r"sponsorship|overseas visits|gifts", re.I)
_DETAILS = ("Organisation Name", "Organisation Description", "Job Title", "Employer", "Role, work or services",
            "Payer Name", "Payer Nature Of Business", "Donor Name", "Payment Description", "Purpose",
            "Property Description", "Land Use", "Miscellaneous Interest Type", "Location", "Country")


def _registered(item: dict[str, Any]) -> date | None:
    if item.get("registered_on"):
        try:
            return date.fromisoformat(item["registered_on"][:10])
        except ValueError:
            return None
    raw = (item.get("registered") or "").strip()
    for fmt in ("%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


_CEASED = re.compile(r"\binterest ceased\s+(\d{1,2}\s+\w+\s+\d{4})", re.I)


def _ended(item: dict[str, Any]) -> date | None:
    """When the interest ended, if the register says: "(interest ceased 30 April 2026)" in the Lords register, an
    end date in the Commons one."""
    m = _CEASED.search(item.get("summary") or "")
    raw = m.group(1) if m else (dict(item.get("details") or []).get("End Date") or "")
    for fmt in ("%d %B %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip()[:10] if fmt != "%d %B %Y" else raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _text(item: dict[str, Any]) -> str:
    details = dict(item.get("details") or [])
    bits = [item.get("summary") or ""] + [f"{k}: {details[k]}" for k in _DETAILS if details.get(k)]
    bits += [c.get("summary") or "" for c in item.get("children") or []]
    return " ".join(" — ".join(b for b in bits if b).split())[:400]


def held_on(categories: list[dict[str, Any]], on: date, lords: bool) -> list[dict[str, Any]]:
    """The register entries that applied on ``on``: see the module notes."""
    out = []
    for c in categories:
        label = f"{c.get('type') or ''} {c.get('name') or ''}".strip()
        one_off = bool(_ONE_OFF_LORDS.search(c.get("name") or "")) if lords else \
            bool(_ONE_OFF_COMMONS.match(str(c.get("type") or "")))
        for item in c.get("items") or []:
            when, ended = _registered(item), _ended(item)
            if when is None or when > on or (one_off and when < on - timedelta(days=365)) or (ended and ended < on):
                continue
            if re.match(r"^\s*no (registrable|registered|relevant)? ?interests?", item.get("summary") or "", re.I):
                continue
            out.append({"category": c.get("name") or label, "summary": " ".join((item.get("summary") or "").split()),
                        "text": _text(item), "registered": when.isoformat()})
    return out


class Match(BaseModel):
    contribution: int = Field(description="The contribution's number")
    interest: str = Field(description="The interest's label, e.g. 'A3'")
    connection: str = Field(description="One neutral sentence naming what links the interest to the contribution")


class Matches(BaseModel):
    matches: list[Match]


SYSTEM = """You check whether members of the UK Parliament had a registered interest that relates directly to what they
said in a particular contribution. You are given each member's register entries that applied on the day, and their
contributions.

An interest is relevant only if it concerns the same organisation, industry, profession, place or specific subject as
the contribution: for example a gift of hospitality from the Betting and Gaming Council and a speech on gambling
regulation; a paid role with an energy company and a speech on energy prices; owning farmland and a speech on
inheritance tax on farms; a directorship of a football club and a speech on football regulation; a trusteeship of a
charity and a speech on that charity's cause.

Not relevant: interests that share only a broad area (a theatre ticket and a speech on BBC funding), donations or
support for general political or constituency work, hospitality at unrelated events, family members employed in the
member's office, property that is only the member's home or rented out with no link to the subject, and anything you
are unsure about. When in doubt, leave it out: most contributions have no relevant interest.

Write each connection as one plain, neutral sentence describing the link only, for example "The register lists a
paid role as adviser to an energy supplier; the contribution concerned energy prices." Never suggest that the
interest influenced the member, that they should have declared it, or any wrongdoing or motive."""


def candidates(sources: list[Any], commons, lords) -> dict[str, Any]:
    """Members quoted in the briefing, their contributions, and the register entries that applied on each day."""
    people: dict[str, dict[str, Any]] = {}
    for s in sources:
        sp = s.meta.get("speaker") or {}
        pid, house = sp.get("person_id"), sp.get("house")
        if s.kind != "record" or not pid or house not in ("commons", "lords") or not s.meta.get("date"):
            continue
        on = date.fromisoformat(str(s.meta["date"])[:10])
        if pid not in people:
            if house == "commons":
                reg = commons.for_person(pid) if commons else None
                cats = (reg or {}).get("categories") or []
            else:
                reg = next((r for r in (lords.for_person(pid) if lords else []) if r["register"] == "lords"), None)
                cats = (reg or {}).get("categories") or []
            people[pid] = {"name": sp.get("name") or s.meta.get("speaker_name_raw") or "", "house": house,
                           "categories": cats, "contributions": []}
        held = held_on(people[pid]["categories"], on, house == "lords")
        if held:
            people[pid]["contributions"].append({"source": s.n, "date": on.isoformat(), "held": held,
                                                 "heading": s.meta.get("heading") or "",
                                                 "text": " ".join((s.meta.get("text") or "").split())[:900]})
    return {pid: p for pid, p in people.items() if p["contributions"]}


def prompt(question: str, people: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """The model's input, and each interest label's entry and member."""
    parts, labels = [f"The briefing's question: {question}"], {}
    for k, (pid, p) in enumerate(people.items()):
        letter = chr(ord("A") + k) if k < 26 else f"Z{k}"
        entries: dict[tuple[str, str], str] = {}
        for c in p["contributions"]:
            for h in c["held"]:
                key = (h["text"], h["registered"])
                if key not in entries:
                    entries[key] = f"{letter}{len(entries) + 1}"
                    labels[entries[key]] = {**h, "person_id": pid, "name": p["name"], "house": p["house"]}
        lines = [f"\nMember {letter}: {p['name']} ({'House of Lords' if p['house'] == 'lords' else 'MP'})",
                 "Register entries:"]
        lines += [f"  {label}: {text} (registered {when})" for (text, when), label in entries.items()]
        for c in p["contributions"]:
            mine = sorted({entries[(h['text'], h['registered'])] for h in c["held"]})
            lines.append(f"Contribution {c['source']} ({c['date']}, entries that applied: {', '.join(mine)}): "
                         f"{c['heading']}: {c['text']}")
        parts.append("\n".join(lines))
    return "\n".join(parts), labels


def check(client, model: str, question: str, sources: list[Any], commons, lords,
          effort: str = "low") -> tuple[list[dict[str, Any]], Any]:
    """Relevant registered interests for the briefing's sources, one entry per source, and the model's usage."""
    people = candidates(sources, commons, lords)
    if not people:
        return [], None
    text, labels = prompt(question, people)
    resp = client.messages.parse(model=model, max_tokens=2000, system=SYSTEM,
                                 messages=[{"role": "user", "content": text}],
                                 output_config={"effort": effort}, output_format=Matches)
    found = resp.parsed_output.matches if resp.parsed_output else []
    by_source: dict[int, dict[str, Any]] = {}
    for m in found:
        entry = labels.get(m.interest.strip())
        if entry is None or entry["person_id"] != pid_of(people, m.contribution):
            continue  # a label the model made up, or another member's entry
        if not any(h["text"] == entry["text"] and h["registered"] == entry["registered"]
                   for c in people[entry["person_id"]]["contributions"] if c["source"] == m.contribution
                   for h in c["held"]):
            continue  # an entry that did not apply on the day of this contribution
        number = person_number(entry["person_id"])
        flag = by_source.setdefault(m.contribution, {
            "source": m.contribution, "person_id": entry["person_id"], "name": entry["name"],
            "register": LORDS_REGISTER if entry["house"] == "lords" else COMMONS_REGISTER,
            "link": f"/people/{number}#h-interests" if number else None, "items": []})
        if not any(i["summary"] == entry["summary"] and i["registered"] == entry["registered"] for i in flag["items"]):
            flag["items"].append({"category": entry["category"], "summary": entry["summary"],
                                  "registered": entry["registered"], "connection": " ".join(m.connection.split())})
    return sorted(by_source.values(), key=lambda f: f["source"]), resp.usage


def pid_of(people: dict[str, Any], source: int) -> str | None:
    return next((pid for pid, p in people.items() for c in p["contributions"] if c["source"] == source), None)
