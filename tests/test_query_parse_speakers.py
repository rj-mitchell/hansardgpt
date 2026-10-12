"""Names in a question are matched to members: whole words, short first names, the right person for the dates."""

from __future__ import annotations

from datetime import date

from hansard.engine import Filters
from hansard.rag.query_parse import resolve_speakers

from .conftest import BENN, CAMERON


def test_names_resolve_by_whole_words_and_short_forms(resolver):
    found, missing = resolve_speakers(resolver.con, ["David Cameron", "Dave Cameron", "Benn", "Nobody Atall"], Filters())
    assert [f["person_id"] for f in found] == [CAMERON, CAMERON, BENN]
    assert missing == ["Nobody Atall"]


def test_the_member_who_sat_in_the_dates_asked_about_comes_first(resolver):
    found, _ = resolve_speakers(resolver.con, ["Cameron"], Filters(date_from=date(2011, 1, 1), date_to=date(2012, 1, 1)))
    assert found[0]["person_id"] == CAMERON
