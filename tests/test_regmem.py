"""The Register of Members' Financial Interests: parsing an edition, refreshing it, and the MP page."""

from __future__ import annotations

from pathlib import Path

import httpx

from hansard.sources.regmem import Register, parse, refresh

FIXTURE = Path(__file__).parent / "fixtures" / "regmem" / "regmem2026-09-21.xml"
BENN = "uk.org.publicwhip/person/10669"


def fake_twfy(calls: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/regmem/"):
            return httpx.Response(200, text='<a href="regmem2026-09-07.xml"></a> <a href="regmem2026-09-21.xml"></a>')
        return httpx.Response(200, content=FIXTURE.read_bytes())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_an_edition():
    d = parse(FIXTURE.read_bytes())
    assert d["edition"] == "2026-09-21" and set(d["members"]) >= {BENN}
    cats = d["members"][BENN]["categories"]
    types = [c["type"] for c in cats]
    assert types == sorted(types, key=float), "categories in the register's order"
    items = [i for c in cats for i in c["items"]]
    assert all(i["summary"] for i in items)
    assert any(i["children"] for i in items), "payments are kept under the job they were for"
    names = {n for i in items for n, _ in i["details"]} | {n for i in items for c in i["children"] for n, _ in c["details"]}
    assert not [n for n in names if "address" in n.lower()], "addresses are left out"


def test_refresh_only_when_there_is_a_new_edition(tmp_path):
    path = tmp_path / "regmem.json"
    calls: list[str] = []
    first = refresh(path, fake_twfy(calls))
    assert first["updated"] and first["edition"] == "2026-09-21"
    calls.clear()
    again = refresh(path, fake_twfy(calls))
    assert not again["updated"] and len(calls) == 1, "only the listing is fetched when nothing is new"
    reg = Register(path)
    assert reg.for_person(BENN)["listed"] and reg.for_person("uk.org.publicwhip/person/1")["listed"] is False
    assert Register(tmp_path / "missing.json").for_person(BENN) is None


def test_the_mp_page_shows_the_register(indexed_settings, tmp_path):
    from fastapi.testclient import TestClient

    from hansard.sync import regmem_path

    from .test_api import make_app

    path = regmem_path(indexed_settings)
    try:
        refresh(path, fake_twfy([]))
        app, _, _ = make_app(indexed_settings, tmp_path, auth=False)
        page = TestClient(app).get("/api/people/10669").json()
        assert page["interests"]["edition"] == "2026-09-21" and page["interests"]["categories"]
    finally:
        path.unlink(missing_ok=True)


def test_details_are_tidied():
    benn = parse(FIXTURE.read_bytes())["members"][BENN]["categories"]
    gift = benn[1]["items"][0]
    assert [n for n, _ in gift["details"]] == ["Payment Description", "Donor Name"], \
        "addresses and repeated values are left out"
    plain = parse(FIXTURE.read_bytes())["members"]["uk.org.publicwhip/person/10777"]["categories"][0]["items"][0]
    assert plain["summary"] == "Older-style entry written as plain text."
