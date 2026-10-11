"""Balanced evidence selection for synthesis, and party expansion."""

from datetime import date

from hansard.embed.base import HashingEmbedder
from hansard.engine import Engine
from hansard.rank.composite import Candidate, Scored
from hansard.rank.evidence import GROUPS, evidence_summary, select_evidence, speaker_group


def scored(rid, score, rel=None):
    return Scored(Candidate(rid, date(2024, 1, 1)), rel if rel is not None else score, 1, 1, 0, "", score)


def prof(pid, house="commons", settlement=None, kind=None):
    from hansard.reference.profiles import SpeakerProfile

    offices = [{"kind": kind, "display_name": "x", "role": "x"}] if kind else []
    return SpeakerProfile(person_id=pid, on=date(2024, 1, 1), name=pid, house=house, settlement=settlement,
                          offices=offices)


def test_speaker_groups():
    assert speaker_group(prof("a", kind="gov")) == "gov"
    assert speaker_group(prof("a", kind="shadow")) == "shadow"
    assert speaker_group(prof("a", settlement="rural")) == "rural"
    assert speaker_group(prof("a", house="lords")) == "lords"
    assert speaker_group(None) == "other"


def test_selection_spreads_across_groups_and_caps_each_speaker():
    # One minister dominates the raw ranking; rural and city backbenchers rank lower.
    pool = [scored(f"min{i}", 1.0 - i * 0.01) for i in range(6)]
    pool += [scored("city1", 0.80), scored("city2", 0.79), scored("rural1", 0.70), scored("rural2", 0.69)]
    profiles = {f"min{i}": prof("minister", kind="gov") for i in range(6)}
    profiles |= {"city1": prof("c1", settlement="city"), "city2": prof("c2", settlement="city"),
                 "rural1": prof("r1", settlement="rural"), "rural2": prof("r2", settlement="rural")}
    chosen = [s.candidate.record_id for s in select_evidence(pool, profiles, k=6, max_per_speaker=2)]
    assert sum(1 for c in chosen if c.startswith("min")) == 2  # per-speaker cap
    assert {"city1", "city2", "rural1", "rural2"} <= set(chosen)


def test_selection_does_not_pull_in_irrelevant_records_for_balance():
    pool = [scored("strong", 1.0, rel=1.0), scored("weak-rural", 0.1, rel=0.1)]
    profiles = {"strong": prof("a", kind="gov"), "weak-rural": prof("b", settlement="rural")}
    chosen = [s.candidate.record_id for s in select_evidence(pool, profiles, k=5, min_relevance_ratio=0.25)]
    assert chosen == ["strong"]


def test_evidence_summary_counts():
    recs = [{"record_id": "1", "date": "2020-01-01", "speaker": {"person_id": "a", "house": "commons",
             "settlement": "city", "party": "Labour", "offices": []}},
            {"record_id": "2", "date": "2024-05-01", "speaker": {"person_id": "b", "house": "commons",
             "settlement": "rural", "party": "Conservative", "offices": [{"kind": "gov"}]}}]
    s = evidence_summary(recs)
    assert s["records"] == 2 and s["speakers"] == 2
    assert s["groups"] == {GROUPS["city"]: 1, GROUPS["gov"]: 1}
    assert s["seat_types"] == {"city": 1, "rural": 1} and s["date_from"] == "2020-01-01"


def test_labour_includes_labour_cooperative(indexed_settings):
    e = Engine(indexed_settings, embedder=HashingEmbedder(64))
    assert set(e.expand_parties(["labour"])) >= {"labour", "labourco-operative"}
    assert e.expand_parties(["conservative"]) == ["conservative"]


def test_seat_type_labels_say_how_big_the_urban_area_is():
    from hansard.rank.evidence import seat_type_label

    assert seat_type_label({"settlement": "city", "urban_area": "Greater Manchester", "urban_area_pop": 2_776_363}) \
        == "city seat (Greater Manchester urban area, 2.8m people)"
    assert seat_type_label({"settlement": "city", "urban_area": "Milton Keynes", "urban_area_pop": 195_063}) \
        == "city seat (Milton Keynes urban area, 195,000 people)"
    assert seat_type_label({"settlement": "city", "urban_area": "Belfast", "urban_area_pop": None}) \
        == "city seat (Belfast urban area)"
    assert seat_type_label({"settlement": "town", "urban_area": "Wigan", "urban_area_pop": 172_345}) \
        == "town seat (urban area of 172,000)"
    assert seat_type_label({"settlement": "rural", "urban_area_pop": 11_087}) == "rural seat"
    assert seat_type_label({"settlement": None}) is None


def test_one_sided_evidence_is_flagged():
    from collections import Counter

    from hansard.rank.evidence import imbalance

    assert imbalance(Counter({"Labour": 8, "Conservative": 2}), 10) == {"party": "Labour", "count": 8, "total": 10}
    assert imbalance(Counter({"Labour": 6, "Conservative": 4}), 10) is None
    assert imbalance(Counter({"Labour": 3}), 3) is None  # too few to say
