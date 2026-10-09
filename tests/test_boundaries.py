"""Boundary invariance: 2010-2024 and post-2024 seats both resolve to ITL1 regions."""

from collections import Counter
from datetime import date

from hansard.reference.build import load_constituencies, normalise_place

from .conftest import BENN, CAMERON, GEO_CSV

ITL1 = {
    "North East", "North West", "Yorkshire and The Humber", "East Midlands", "West Midlands",
    "East of England", "London", "South East", "South West", "Scotland", "Wales", "Northern Ireland",
}


def seats():
    return load_constituencies(GEO_CSV)


def test_both_boundary_sets_are_complete():
    counts = Counter(s["boundary_set"] for s in seats())
    assert counts == {"2010": 650, "2024": 650}
    assert len({(s["gss_code"], s["boundary_set"]) for s in seats()}) == 1300
    # Five unchanged Scottish seats keep their ONS code across the 2024 review.
    shared = {s["gss_code"] for s in seats() if s["boundary_set"] == "2010"} & {
        s["gss_code"] for s in seats() if s["boundary_set"] == "2024"}
    assert len(shared) == 5 and all(code.startswith("S14") for code in shared)


def test_every_seat_has_an_itl1_region_and_valid_interval():
    for s in seats():
        assert s["region"] in ITL1, s
        assert s["valid_from"] <= s["valid_to"]
    by_set = {}
    for s in seats():
        by_set.setdefault(s["boundary_set"], set()).add((s["valid_from"], s["valid_to"]))
    assert by_set["2010"] == {(date(2010, 5, 6), date(2024, 7, 3))}
    assert by_set["2024"] == {(date(2024, 7, 4), date(9999, 12, 31))}


def test_abolished_and_successor_seats_resolve_to_the_same_region():
    idx = {(normalise_place(s["name"]), s["boundary_set"]): s for s in seats()}
    assert idx[("wakefield", "2010")]["region"] == "Yorkshire and The Humber"
    assert idx[("wakefield and rothwell", "2024")]["region"] == "Yorkshire and The Humber"
    assert ("wakefield", "2024") not in idx  # abolished in 2024


def test_nations_resolve_to_themselves():
    regions = {(s["nation"], s["region"]) for s in seats() if s["nation"] != "England"}
    assert regions == {("Scotland", "Scotland"), ("Wales", "Wales"), ("Northern Ireland", "Northern Ireland")}
    counts = Counter((s["boundary_set"], s["nation"]) for s in seats())
    assert counts[("2010", "Scotland")] == 59 and counts[("2024", "Scotland")] == 57
    assert counts[("2010", "Wales")] == 40 and counts[("2024", "Wales")] == 32
    assert counts[("2010", "Northern Ireland")] == 18 == counts[("2024", "Northern Ireland")]


def test_members_resolve_to_regions_across_the_2024_change(resolver):
    old = resolver.profile(BENN, date(2015, 10, 14))
    new = resolver.profile(BENN, date(2025, 3, 1))
    assert old.gss_code != new.gss_code
    assert old.region == new.region == "Yorkshire and The Humber"
    assert resolver.profile(CAMERON, date(2012, 3, 1)).region == "South East"


def test_all_fixture_commons_memberships_since_2010_have_regions(reference):
    ref, _ = reference
    missing = [m for m in ref.memberships
               if m["house"] == "commons" and m["end"] >= date(2010, 5, 6) and not m["region"]]
    assert missing == []
    assert ref.stats["unmatched_seats_since_2010"] == []


def test_name_normalisation():
    assert normalise_place("Airdrie & Shotts") == normalise_place("Airdrie and Shotts")
    assert normalise_place("Aldridge - Brownhills") == normalise_place("Aldridge-Brownhills")
    assert normalise_place("Ynys Môn") == "ynys mon"
