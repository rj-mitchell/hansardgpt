"""Post-generation verification of a cited answer.

Claude's citations API returns, for each cited span, the exact ``cited_text``
and the index of the search result it came from. This module re-checks every
citation against our own copy of the source text and classifies every
uncited span, so the UI can show the reader exactly what is and is not
supported. Unsupported text is never silently passed off as sourced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from hansard.rag.prompts import NO_RECORDS
from hansard.rag.sources import Source

_WS = re.compile(r"\s+")
_CONNECTIVE_MAX = 60


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return _WS.sub(" ", text).strip().lower()


@dataclass
class Segment:
    text: str
    sources: list[int] = field(default_factory=list)       # 1-based source numbers
    cited: list[dict[str, Any]] = field(default_factory=list)
    status: str = "cited"                                   # cited | connective | unsupported | invalid

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "sources": self.sources, "cited": self.cited, "status": self.status}


@dataclass
class Verification:
    segments: list[Segment]
    no_records: bool
    citations_total: int
    citations_invalid: int
    unsupported_chars: int
    cited_chars: int

    @property
    def grounded_ratio(self) -> float:
        total = self.cited_chars + self.unsupported_chars
        return 1.0 if total == 0 else self.cited_chars / total

    def markdown(self) -> str:
        """Answer text with [Source n] markers after each cited span."""
        out = []
        for s in self.segments:
            out.append(s.text)
            if s.sources:
                out.append(" " + "".join(f"[Source {n}]" for n in s.sources))
        return "".join(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "markdown": self.markdown(),
            "no_records": self.no_records,
            "citations_total": self.citations_total,
            "citations_invalid": self.citations_invalid,
            "grounded_ratio": round(self.grounded_ratio, 3),
            "unsupported_segments": sum(1 for s in self.segments if s.status == "unsupported"),
        }


def _is_connective(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t.startswith("#") or t.endswith(":"):
        return True
    # bullet markers, joins between cited spans, short transitions
    stripped = re.sub(r"^[\s\-*•\d.)]+", "", t)
    return len(stripped) <= _CONNECTIVE_MAX and not re.search(r"\d{4}|£|%", stripped)


_LABEL = re.compile(r"^\s*(#+ .*|\*\*[^*]+\*\*:?)\s*$")
# statements about the evidence itself (what was or was not retrieved), not about what anyone said
_EVIDENCE_NOTE = re.compile(
    r"\b(records? (retrieved|supplied|shown)|(retrieved|supplied) (records|results|sources)|in the records|"
    r"no (division|voting) records|evidence (base|is|set)|gaps?\b|caveats?\b|cannot be (reported|attributed)|"
    r"(were|was) not relevant|been excluded)", re.I)
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s+\S")
_ATTRIBUTION_MAX = 220


def _classify_uncited(text: str, next_is_cited: bool) -> list[Segment]:
    """Split an uncited block into lines and label each one.

    * headings, bold group labels, bullets and joins are ``connective``;
    * the lead-in to a cited quotation ("- Keir Mather (Selby), 10 August 2026, said ") is ``connective``
      when the very next span is cited and the lead-in states nothing on its own;
    * notes about the evidence itself ("No division records were supplied") are ``connective``;
    * anything else (a claim with no citation) is ``unsupported``.
    """
    lines = text.splitlines(keepends=True)
    out: list[Segment] = []
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        body = re.sub(r"^[\s\-*•\d.)]+", "", line).strip()
        lead_in = (last and next_is_cited and len(body) <= _ATTRIBUTION_MAX
                   and not _SENTENCE_END.search(body.rstrip()) and not body.endswith("."))
        if (_is_connective(line) or _LABEL.match(line) or lead_in
                or (_EVIDENCE_NOTE.search(body) and not re.search(r"\bsaid\b|\bargued\b|\bclaimed\b", body))):
            status = "connective"
        else:
            status = "unsupported"
        if out and out[-1].status == status:
            out[-1].text += line
        else:
            out.append(Segment(line, status=status))
    return out or [Segment(text, status="connective")]


def verify(blocks: list[dict[str, Any]], sources: list[Source]) -> Verification:
    """``blocks``: text blocks as returned by the API (``text`` and optional ``citations``)."""
    by_index = {s.n - 1: s for s in sources}
    segments: list[Segment] = []
    total = invalid = 0
    for i, b in enumerate(blocks):
        text = b.get("text") or ""
        cites = b.get("citations") or []
        if not cites:
            next_is_cited = i + 1 < len(blocks) and bool(blocks[i + 1].get("citations"))
            segments.extend(_classify_uncited(text, next_is_cited))
            continue
        nums, kept = [], []
        for c in cites:
            total += 1
            idx = c.get("search_result_index", c.get("document_index"))
            src = by_index.get(idx)
            cited_text = c.get("cited_text") or ""
            if src is None or _norm(cited_text) not in _norm("\n\n".join(src.blocks)):
                invalid += 1
                continue
            if src.n not in nums:
                nums.append(src.n)
            kept.append({"source": src.n, "cited_text": cited_text})
        segments.append(Segment(text, nums, kept, "cited" if nums else "invalid"))
    full = "".join(s.text for s in segments).strip()
    unsupported = sum(len(s.text) for s in segments if s.status in ("unsupported", "invalid"))
    cited = sum(len(s.text) for s in segments if s.status == "cited")
    return Verification(segments, full.startswith(NO_RECORDS), total, invalid, unsupported, cited)
