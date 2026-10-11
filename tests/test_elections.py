"""Election results, majorities at the time and now, first terms: data, matching, filters and grouping."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from hansard.engine import Engine, Filters
from hansard.rag.query_parse import QueryPlan, parse_offline
from hansard.rag.sources import group_label, speaker_label
from hansard.sources.elections import (
    commons_member_ids,
    first_term,
    general_elections,
    majority_band,
    refresh_elections,
)
from tests.conftest import BENN, CAMERON, MEMBERS


def test_majority_bands():
    assert [majority_band(x) for x in (0.9, 9.99, 10, 19.9, 20, 49.7)] == [
        "marginal", "marginal", "middle", "middle", "safe", "safe"]
    assert majority_band(None) is None


def test_first_term_lasts_until_the_next_general_election():
    ge = general_elections()
    assert first_term(date(2019, 12, 12), date(2024, 7, 3), ge) is True
    assert first_term(date(2019, 12, 12), date(2024, 7, 4), ge) is False   # re-elected (or not) on this day
    assert first_term(date(2021, 7, 2), date(2023, 1, 1), ge) is True      # by-election entrant
    assert first_term(date(1999, 6, 10), date(2018, 1, 1), ge) is False
    assert first_term(None, date(2018, 1, 1), ge) is None


def test_majority_then_and_now_from_real_results(resolver):
    cameron = resolver.profile(CAMERON, date(2012, 6, 1)).to_dict()
    assert cameron["majority_then"] == {"majority": 22740, "pct": 39.4, "band": "safe",
                                        "election": "2010 general election", "date": "2010-05-06"}
    assert cameron["first_term"] is False and cameron.get("majority_now") is None  # no longer an MP
    benn = resolver.profile(BENN, date(2018, 3, 1)).to_dict()
    assert benn["majority_then"]["election"] == "2017 general election"
    assert benn["majority_now"]["constituency"] == "Leeds South"
    lord = resolver.profile(CAMERON, date(2024, 2, 1)).to_dict()
    assert "majority_then" not in lord and "first_term" not in lord  # a peer: no seat facts


def test_labels_mention_majority_and_term_only_when_asked(resolver):
    rec = {"speaker": resolver.profile(BENN, date(2018, 3, 1)).to_dict()}
    assert "majority" not in speaker_label(rec)
    label = speaker_label(rec, {"majority", "tenure"})
    assert "majority 23,698 (49.7%) at the 2017 general election" in label and "re-elected MP" in label
    assert group_label(rec["speaker"], "majority") == "Safe (majority over 20%)"
    assert group_label(rec["speaker"], "tenure") == "Re-elected MPs"


def test_offline_parser_reads_new_mps_and_marginal_seats():
    assert parse_offline("What have new MPs said about housing?", {}).filters.tenure == ["first-term"]
    assert parse_offline("How have MPs in marginal seats talked about immigration?", {}).filters.majority_bands == [
        "marginal"]
    both = parse_offline("How do MPs in marginal and safe seats differ on onshore wind?", {})
    assert both.group_by == "majority" and both.filters.majority_bands == []
    assert parse_offline("What have MPs said about safe standing at football?", {}).filters.majority_bands == []
    again = QueryPlan.from_dict({"filters": {"tenure": ["first-term", "x"], "majority_bands": ["safe", "y"]},
                                 "group_by": "majority"})
    assert again.filters.tenure == ["first-term"] and again.filters.majority_bands == ["safe"]
    assert again.group_by == "majority"


def test_member_ids_come_from_commons_memberships_since_2010():
    ids = commons_member_ids(MEMBERS / "people.json")
    assert "1467" in ids and "413" in ids  # Cameron, Benn


def test_refresh_keeps_the_old_copy_when_the_api_fails(tmp_path):
    cache = tmp_path / "elections.json"
    bio = {"value": {"representations": [{"house": 1, "id": 7, "name": "Seat", "startDate": "2019-12-12T00:00:00",
                                          "endDate": None}]}}
    res = {"value": [{"electionDate": "2019-12-12T00:00:00", "electionTitle": "2019 General Election",
                      "isGeneralElection": True, "isNotional": False, "majority": 100, "turnout": 1000,
                      "electorate": 2000, "result": "Lab Hold", "winningParty": {"name": "Labour"}},
                     {"electionDate": "2019-12-12T00:00:00", "isNotional": True, "majority": 5}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bio if "Biography" in request.url.path else res)

    ok = refresh_elections(cache, ["1"], client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert ok["status"] == "updated" and ok["results"] == 1  # the notional result is ignored
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert refresh_elections(cache, ["1"], force=True, client=down)["status"] == "failed"
    assert '"majority": 100' in cache.read_text()


@pytest.fixture(scope="module")
def engine(indexed_settings):
    return Engine(indexed_settings, today=date(2026, 10, 10))


def test_majority_and_tenure_filters_check_the_day(engine):
    safe = engine.search("the", Filters(majority_bands=["safe"]), limit=200)
    assert safe.records and all(r["speaker"]["majority_band"] == "safe" for r in safe.records)
    first = engine.search("the", Filters(tenure=["first-term"]), limit=200)
    assert all(r["speaker"]["first_term"] is True for r in first.records)
    returning = engine.search("the", Filters(tenure=["returning"]), limit=200)
    assert returning.records and all(r["speaker"]["first_term"] is False for r in returning.records)
