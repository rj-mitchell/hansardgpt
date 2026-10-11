"""Committees: building the local copy from the API, the pages, and the witness index (invented data)."""

from __future__ import annotations

import httpx

from hansard.sources.committees import Committees, build, refresh

INQ = {"id": 900, "title": "Rail fares", "type": {"name": "Inquiry"}, "openDate": "2024-01-10T00:00:00",
       "closeDate": None}
COMMITTEE = {"id": 10, "name": "Transport Committee", "house": "Commons", "category": {"name": "Select"},
             "startDate": "2010-01-01T00:00:00", "endDate": None, "parentCommittee": None,
             "scrutinisingDepartments": [{"name": "Department for Transport"}]}
DATA = {
    "/api/Committees": [COMMITTEE, {**COMMITTEE, "id": 11, "name": "Old Committee", "endDate": "2015-03-30T00:00:00"}],
    "/api/CommitteeBusiness": [INQ],
    "/api/Publications": [
        {"id": 1, "type": {"id": 1}, "description": "Rail fares: first report", "publicationStartDate": "2024-06-01T10:00:00",
         "committee": COMMITTEE, "hcNumber": {"number": "HC 123", "sessionId": 38}, "hlPaper": None,
         "businesses": [INQ], "documents": [{"documentId": 55}]},
        {"id": 2, "type": {"id": 2}, "description": "Government response", "publicationStartDate": "2024-07-31T10:00:00",
         "committee": COMMITTEE, "responseToPublicationId": 1, "businesses": [INQ], "documents": []},
    ],
    "/api/OralEvidence": [
        {"id": 77, "meetingDate": "2024-03-05T00:00:00", "committees": [COMMITTEE], "committeeBusinesses": [INQ],
         "witnesses": [{"name": "Ann  Expert", "organisations": [{"name": "Passenger Watch", "role": "Chief Executive"}]},
                       {"name": "A Minister", "organisations": [{"name": "Department for Transport", "role": "Minister"}],
                        "memberInfo": {"mnisId": 4514}}]},
        {"id": 78, "meetingDate": "2024-04-05T00:00:00", "committees": [COMMITTEE], "committeeBusinesses": [INQ],
         "witnesses": [{"name": "Bo Other", "organisations": [{"name": "passenger watch", "role": "Analyst"}]}]},
    ],
}


def fake_api() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/api/Committees/"):
            return httpx.Response(200, json={"purpose": "<p>We scrutinise <b>transport</b>.</p><p>More.</p>"})
        items = DATA.get(path, [])
        start, end = request.url.params.get("StartDate"), request.url.params.get("EndDate")
        if start:  # the real service filters by date
            items = [i for i in items
                     if start <= (i.get("publicationStartDate") or i.get("meetingDate") or "")[:10] <= end]
        skip, take = int(request.url.params.get("Skip", 0)), int(request.url.params.get("Take", 500))
        return httpx.Response(200, json={"items": items[skip:skip + take], "totalResults": len(items)})

    return httpx.Client(transport=httpx.MockTransport(handler))


def no_wait(_s: float) -> None:
    return None


def test_build_and_read(tmp_path):
    path = tmp_path / "committees.sqlite"
    stats = build(path, fake_api(), no_wait)
    assert stats["sessions"] == 2 and stats["witnesses"] == 3
    c = Committees(path)
    index = c.index()
    assert [r["name"] for r in index] == ["Transport Committee"], "ended committees are not listed"
    assert index[0]["inquiries"] == 1 and index[0]["reports"] == 1
    page = c.committee(10)
    assert page["purpose"] == "We scrutinise transport." and page["departments"] == "Department for Transport"
    assert page["top_organisations"][0] == {"organisation": "Passenger Watch", "n": 2}, "counted whatever the case"
    inq = c.inquiry(900)
    response = next(p for p in inq["publications"] if p["type"] == "Government response")
    assert response["days_after_report"] == 60
    assert next(p for p in inq["publications"] if p["type"] == "Report")["hc"] == "HC 123", "the paper number as given"
    assert [len(s["witnesses"]) for s in inq["sessions"]] == [2, 1]
    found = c.witnesses("passenger watch")
    assert found["organisations"][0]["sessions"] == 2 and len(found["sessions"]) == 2
    assert c.for_member(4514)[0]["id"] == 77, "members who gave evidence are found by their UK Parliament ID"
    assert c.committee(999) is None and c.inquiry(999) is None


def test_refresh_waits_a_week(tmp_path):
    path = tmp_path / "committees.sqlite"
    assert refresh(path, fake_api(), no_wait)["updated"]
    assert refresh(path, fake_api(), no_wait)["updated"] is False


def test_pages(indexed_settings, tmp_path):
    from fastapi.testclient import TestClient

    from hansard.sync import committees_path

    from .test_api import make_app

    path = committees_path(indexed_settings)
    app, _, _ = make_app(indexed_settings, tmp_path, auth=False)
    client = TestClient(app)
    try:
        assert client.get("/api/committees").status_code == 503, "a clear message before the first collection"
        build(path, fake_api(), no_wait)
        assert client.get("/api/committees").json()["committees"][0]["id"] == 10
        assert client.get("/api/inquiries/900").json()["title"] == "Rail fares"
        assert client.get("/committees/10").status_code == 200 and client.get("/committees/999").status_code == 404
        assert client.get("/inquiries/900").status_code == 200
        assert client.get("/api/witnesses", params={"q": "passenger"}).json()["organisations"]
    finally:
        path.unlink(missing_ok=True)


def test_reports_feed(indexed_settings, tmp_path):
    import xml.etree.ElementTree as ET

    from fastapi.testclient import TestClient

    from hansard.sync import committees_path

    from .test_api import make_app

    path = committees_path(indexed_settings)
    app, _, _ = make_app(indexed_settings, tmp_path, auth=False)
    client = TestClient(app)
    try:
        assert client.get("/feeds/committee-reports.xml").status_code == 200, "an empty feed before collection"
        build(path, fake_api(), no_wait)
        items = ET.fromstring(client.get("/feeds/committee-reports.xml").content).findall("channel/item")
        assert [i.findtext("title") for i in items] == ["Government response: Government response",
                                                        "Report: Rail fares: first report"]
        assert items[0].findtext("link").endswith("/inquiries/900")
        assert client.get("/feeds/edms.xml").status_code == 200
    finally:
        path.unlink(missing_ok=True)


def test_sitemaps(indexed_settings, tmp_path):
    from fastapi.testclient import TestClient

    from hansard.sync import committees_path

    from .test_api import make_app

    path = committees_path(indexed_settings)
    app, _, _ = make_app(indexed_settings, tmp_path, auth=False)
    client = TestClient(app)
    try:
        build(path, fake_api(), no_wait)
        body = client.get("/sitemap-committees.xml").text
        assert "/committees/10</loc>" in body and "/inquiries/900</loc>" in body and "/committees/11<" not in body
        for p in ("/sitemap-edms.xml", "/sitemap-devolved.xml"):
            assert client.get(p).status_code == 200
    finally:
        path.unlink(missing_ok=True)
