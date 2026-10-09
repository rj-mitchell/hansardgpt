"""Composite soft ranking: boosts re-order results but never drop strong matches."""

from datetime import date

import pytest

from hansard.rank.composite import Candidate, RankParams, rank, recency_factor

TODAY = date(2026, 10, 1)


def params(**kw):
    return RankParams(today=TODAY, **kw)


def ids(scored):
    return [s.candidate.record_id for s in scored]


def test_no_decay_means_pure_relevance_order():
    cands = [Candidate("old-strong", date(2011, 1, 1), bm25=9.0), Candidate("new-weak", date(2026, 9, 1), bm25=3.0),
             Candidate("mid", date(2018, 1, 1), bm25=6.0)]
    assert ids(rank(cands, set(), params(recency=0.0, role_weight=1.0))) == ["old-strong", "mid", "new-weak"]


def test_decay_prefers_recent_when_relevance_is_similar():
    cands = [Candidate("old", date(2012, 1, 1), bm25=8.0), Candidate("new", date(2026, 6, 1), bm25=7.5)]
    assert ids(rank(cands, set(), params(recency=0.5, role_weight=1.0))) == ["new", "old"]


def test_aggressive_decay_never_drops_a_much_stronger_old_match():
    old = Candidate("old-strong", date(2010, 6, 1), bm25=10.0, cosine=0.8)
    new = [Candidate(f"new-weak-{i}", date(2026, 9, 1), bm25=2.0, cosine=0.2) for i in range(5)]
    scored = rank([old, *new], set(), params(recency=1.0, role_weight=1.0))
    assert len(scored) == 6  # nothing is excluded
    assert ids(scored)[0] == "old-strong"
    # The floor is what keeps it: a 16-year-old record keeps 35% of its weight.
    assert recency_factor(date(2010, 6, 1), params(recency=1.0)) == pytest.approx(0.35, abs=0.01)


def test_recency_factor_properties():
    p = params(recency=0.5)  # half-life 4 years
    assert recency_factor(TODAY, p) == pytest.approx(1.0)
    four_years = date(2022, 10, 1)
    assert recency_factor(four_years, p) == pytest.approx(0.35 + 0.65 * 0.5, abs=0.005)
    assert recency_factor(date(2012, 1, 1), params(recency=0.0)) == 1.0


def test_role_weight_one_leaves_ranking_unchanged():
    cands = [Candidate("minister", date(2020, 1, 1), bm25=5.0, is_gov=True, gov_portfolios=["transport"]),
             Candidate("backbencher", date(2020, 1, 1), bm25=6.0)]
    assert ids(rank(cands, {"transport"}, params(recency=0.0, role_weight=1.0))) == ["backbencher", "minister"]


def test_authority_order_at_equal_relevance():
    d = date(2020, 1, 1)
    cands = [
        Candidate("backbencher", d, bm25=5.0),
        Candidate("other-minister", d, bm25=5.0, is_gov=True, gov_portfolios=["health"]),
        Candidate("transport-minister", d, bm25=5.0, is_gov=True, gov_portfolios=["transport"]),
        Candidate("shadow-transport", d, bm25=5.0, is_shadow=True, shadow_portfolios=["transport"]),
        Candidate("transport-chair", d, bm25=5.0, is_chair=True, chair_portfolios=["transport"]),
    ]
    scored = rank(cands, {"transport"}, params(recency=0.0, role_weight=2.0))
    by = {s.candidate.record_id: s for s in scored}
    assert by["transport-minister"].authority == by["transport-chair"].authority == 2.0
    assert by["shadow-transport"].authority == pytest.approx(1.6)
    assert by["other-minister"].authority == pytest.approx(1.5)
    assert by["backbencher"].authority == 1.0
    assert ids(scored)[-1] == "backbencher"


def test_highly_relevant_backbencher_stays_on_top_against_weak_minister():
    d = date(2024, 1, 1)
    cands = [Candidate("backbencher", d, bm25=10.0, cosine=0.9),
             Candidate("minister", d, bm25=3.0, cosine=0.3, is_gov=True, gov_portfolios=["transport"])]
    assert ids(rank(cands, {"transport"}, params(recency=0.0, role_weight=2.0)))[0] == "backbencher"


def test_hybrid_relevance_combines_keyword_and_semantic():
    d = date(2024, 1, 1)
    cands = [Candidate("kw-only", d, bm25=10.0), Candidate("sem-only", d, cosine=0.8),
             Candidate("both", d, bm25=8.0, cosine=0.7)]
    scored = rank(cands, set(), params(recency=0.0, role_weight=1.0))
    assert ids(scored)[0] == "both"
    rel = {s.candidate.record_id: s.relevance for s in scored}
    assert rel["kw-only"] == pytest.approx(0.5) and rel["sem-only"] == pytest.approx(0.5)


def test_sliders_are_clamped():
    p = RankParams.from_settings({"default_recency": 3, "default_role_weight": 9})
    assert p.recency == 1.0 and p.role_weight == 2.0
