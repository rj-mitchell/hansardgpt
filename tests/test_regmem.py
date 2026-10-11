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


OLD = Path(__file__).parent / "fixtures" / "regmem" / "regmem2016-09-05.xml"
FORMER = "uk.org.publicwhip/person/99999"


def test_older_editions_are_read():
    cats = parse(OLD.read_bytes())["members"][FORMER]["categories"]
    visit = cats[0]["items"][0]
    assert visit["summary"] == "Name of donor: Example Foundation"
    assert ["Estimate of the probable value", "£1,500"] in visit["details"]
    assert not [n for n, _ in visit["details"] if "address" in n.lower()], "address lines are left out"
    assert cats[1]["items"][0] == {"summary": "Trustee of an example charity.", "details": [],
                                   "registered": "2 May 2015", "published": None, "children": []}


def test_former_members_get_the_last_edition_before_they_left(tmp_path):
    from hansard.sources.regmem import refresh_history

    files = {"regmem2016-09-05.xml": OLD.read_bytes(), "regmem2026-09-21.xml": FIXTURE.read_bytes()}
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[1]
        if not name:
            return httpx.Response(200, text=" ".join(f'<a href="{n}"></a>' for n in files))
        fetched.append(name)
        return httpx.Response(200, content=files[name])

    latest = tmp_path / "regmem.json"
    refresh(latest, httpx.Client(transport=httpx.MockTransport(handler)))
    hist = tmp_path / "regmem_history.json"
    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = refresh_history(hist, {FORMER: "2016-09-12"}, client=client, sleep=lambda _s: None)
    assert out["former_members"] == 1 and fetched[-1] == "regmem2016-09-05.xml"
    page = Register(latest).for_person(FORMER)
    assert page["former"] and page["edition"] == "2016-09-05" and page["categories"]
    fetched.clear()
    assert refresh_history(hist, {FORMER: "2016-09-12"}, client=client)["editions_fetched"] == 0
    assert fetched == [], "nothing is fetched again once known"
