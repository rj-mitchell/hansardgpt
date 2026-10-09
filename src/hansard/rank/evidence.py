"""Choose a balanced evidence set for synthesis, and summarise it.

A briefing that says "ministers argued X, city MPs Y, rural MPs Z" needs
evidence from each of those groups, not the twelve highest-scoring speeches
(which are often six speeches by one minister). Selection is deterministic:

1. drop candidates far weaker than the best match (``min_relevance_ratio``);
2. cap contributions per speaker (``max_per_speaker``);
3. take the best remaining record from each speaker group in turn (groups
   ordered by their best score), then fill any remaining slots by score.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from hansard.rank.composite import Scored

GROUPS = {
    "gov": "Government ministers",
    "shadow": "Opposition frontbench",
    "chair": "Select committee chairs",
    "city": "Backbench MPs, city seats",
    "town": "Backbench MPs, town seats",
    "rural": "Backbench MPs, rural seats",
    "commons": "Backbench MPs",
    "lords": "Backbench peers",
    "other": "Other / unattributed",
}

SETTLEMENT_LABEL = {"city": "city seat", "town": "town seat", "rural": "rural seat"}


def speaker_group(profile: Any) -> str:
    """Group key for a speaker profile (``SpeakerProfile`` or its dict form)."""
    p = profile.to_dict() if hasattr(profile, "to_dict") else (profile or {})
    kinds = {o.get("kind") for o in p.get("offices") or []}
    if "gov" in kinds:
        return "gov"
    if "shadow" in kinds:
        return "shadow"
    if "chair" in kinds:
        return "chair"
    if p.get("house") == "lords":
        return "lords"
    if p.get("house") == "commons":
        return p.get("settlement") or "commons"
    return "other"


def select_evidence(scored: list[Scored], profiles: dict[str, Any], k: int, *, max_per_speaker: int = 2,
                    min_relevance_ratio: float = 0.25) -> list[Scored]:
    if not scored:
        return []
    best_rel = max(s.relevance for s in scored)
    pool = [s for s in scored if s.relevance >= best_rel * min_relevance_ratio]
    per_speaker: Counter[str] = Counter()
    groups: dict[str, list[Scored]] = defaultdict(list)
    for s in pool:  # already in score order
        groups[speaker_group(profiles.get(s.candidate.record_id))].append(s)
    order = sorted(groups, key=lambda g: -groups[g][0].score)
    chosen: list[Scored] = []
    taken: set[str] = set()

    def speaker(s: Scored) -> str:
        p = profiles.get(s.candidate.record_id)
        pid = getattr(p, "person_id", None) if p is not None else None
        return pid or s.candidate.record_id

    def take(s: Scored) -> bool:
        if s.candidate.record_id in taken or per_speaker[speaker(s)] >= max_per_speaker:
            return False
        chosen.append(s)
        taken.add(s.candidate.record_id)
        per_speaker[speaker(s)] += 1
        return True

    progress = True
    while len(chosen) < k and progress:
        progress = False
        for g in order:
            for s in groups[g]:
                if take(s):
                    progress = True
                    break
            if len(chosen) >= k:
                break
    for s in pool:  # fill by score if groups ran dry
        if len(chosen) >= k:
            break
        take(s)
    chosen.sort(key=lambda s: (-s.score, s.candidate.record_id))
    return chosen


def evidence_summary(records: list[dict[str, Any]], divisions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Deterministic description of the evidence base (shown in the UI, not model-written)."""
    groups: Counter[str] = Counter()
    parties: Counter[str] = Counter()
    settlements: Counter[str] = Counter()
    speakers: set[str] = set()
    dates = []
    for r in records:
        sp = r.get("speaker") or {}
        groups[GROUPS[speaker_group(sp)]] += 1
        if sp.get("party"):
            parties[sp["party"]] += 1
        if sp.get("settlement"):
            settlements[sp["settlement"]] += 1
        speakers.add(sp.get("person_id") or r.get("speaker_name_raw") or r["record_id"])
        dates.append(r["date"])
    return {
        "records": len(records),
        "speakers": len(speakers),
        "divisions": len(divisions or []),
        "date_from": min(dates) if dates else None,
        "date_to": max(dates) if dates else None,
        "groups": dict(groups.most_common()),
        "parties": dict(parties.most_common()),
        "seat_types": dict(settlements.most_common()),
    }
