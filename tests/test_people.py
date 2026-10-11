"""MP and peer pages, Your MP by postcode, and the people API."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from hansard.people import People, slug
from tests.conftest import BENN, CAMERON

from .test_api import make_app


@pytest.fixture(scope="module")
def people(indexed_settings):
    from hansard.reference.profiles import ProfileResolver

    return People(indexed_settings, ProfileResolver(indexed_settings.reference_dir), today=date(2026, 10, 10))


def test_page_has_roles_seats_and_majorities(people):
    page = people.page(BENN)
    assert page["name"] == "Hilary Benn" and page["number"] == 10669 and page["slug"] == "hilary-benn"
    assert page["status"].startswith("MP for Leeds South")
    leeds_central = next(s for s in page["seats"] if s["constituency"] == "Leeds Central" and s["results"])
    assert leeds_central["results"][0]["election"] == "2019 general election"
    assert any("Northern Ireland" in o["title"] for o in page["offices"])


def test_former_mp_now_a_peer(people):
    page = people.page(CAMERON)
    assert page["name"] == "Lord Cameron of Chipping Norton" and "David Cameron" in page["other_names"]
    assert any(m["house"] == "lords" for m in page["memberships"])


def test_contributions_and_voting_record(people):
    pid = people.resolve(10669)
    assert pid == BENN
    contributions = people.contributions(pid)
    assert all(c["date"] and c["twfy_url"] for c in contributions)
    voting = people.voting(BENN)
    assert voting is None or (voting["votes"] >= voting["rebellions"] >= 0 and "free votes" in voting["method"])


def test_search_and_slug(people):
    found = people.search("benn")
    assert any(p["number"] == 10669 for p in found)
    assert slug("Lord Cameron of Chipping Norton") == "lord-cameron-of-chipping-norton"


def test_postcode_finds_the_mp(people):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["searchText"] == "LS11 5DR"
        return httpx.Response(200, json={"items": [{"value": {"id": 4138, "name": "Leeds South", "currentRepresentation":
                                                              {"member": {"value": {"id": 413, "nameDisplayAs": "Hilary Benn"}}}}}]})

    found = people.by_postcode("ls115dr", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert found == {"postcode": "LS11 5DR", "constituency": "Leeds South", "name": "Hilary Benn", "number": 10669,
                     "slug": "hilary-benn"}
    with pytest.raises(ValueError):
        people.by_postcode("not a postcode")


def test_people_api_and_page(indexed_settings, tmp_path):
    app, _, _ = make_app(indexed_settings, tmp_path, auth=False)
    client = TestClient(app)
    body = client.get("/api/people/10669").json()
    assert body["name"] == "Hilary Benn" and "contributions" in body and "voting" in body
    assert client.get("/api/people/99999999").status_code == 404
    assert any(p["number"] == 10669 for p in client.get("/api/people?q=benn").json()["people"])
    assert client.get("/api/postcode/xyz").status_code == 400
    page = client.get("/people/10669/hilary-benn")
    assert page.status_code == 200 and "<title>Hilary Benn — Where They Stand</title>" in page.text
    assert 'content="noindex"' not in page.text  # member pages are for search engines
    assert "/people/10669/hilary-benn" in client.get("/sitemap-people.xml").text
