"""Oral evidence transcripts: parsing turns, fetching, search and the transcript page (invented data)."""

from __future__ import annotations

import base64
from datetime import date

import httpx

from hansard.sources.evidence import EvidenceStore, parse_transcript, sync_transcripts

DOC = """<html><body><div>
<p><img src="data:image/png;base64,AAAA" /></p>
<p><span>Transport Committee</span></p><p>Oral evidence: Rail fares</p><p>Tuesday 5 March 2024</p>
<p>Watch the meeting</p><p>Members present: Test Chair (Chair); Test Member.</p>
<p>Witnesses</p><p>Ann Expert, Chief Executive, Passenger Watch.</p><p>27</p>
<p>Examination of witnesses</p>
<p>Ann Expert and A Minister.</p>
<p>Q1 <b>The Chair:</b> Welcome. What has happened to fares?</p>
<p>Ann Expert: Fares have risen faster than wages.</p>
<p>Season tickets in particular.</p>
<p>Q2 Lord Jay of Ewelme: And what should change?</p>
<p>A Minister: We are reviewing it. Note the time: 10:30 am.</p>
</div></body></html>"""


def test_turns_are_read_with_continuations():
    header, turns = parse_transcript(DOC)
    assert header[0] == "Transport Committee" and "27" not in header and "Watch the meeting" not in header
    assert [(t["question"], t["speaker"]) for t in turns] == [("Q1", "The Chair"), (None, "Ann Expert"),
                                                              ("Q2", "Lord Jay of Ewelme"), (None, "A Minister")]
    assert turns[1]["text"] == "Fares have risen faster than wages.\n\nSeason tickets in particular."
    assert turns[3]["text"].endswith("10:30 am."), "a colon later in the text does not start a new turn"


def fake(calls: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "/77/" in request.url.path:
            return httpx.Response(200, json={"data": base64.b64encode(DOC.encode()).decode()})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sync_search_and_page(indexed_settings, tmp_path):
    from fastapi.testclient import TestClient

    from hansard.sources.committees import build
    from hansard.sync import committees_path, evidence_path

    from .test_api import make_app
    from .test_committees import fake_api

    store = EvidenceStore(tmp_path / "evidence.sqlite")
    calls: list[str] = []
    stats = sync_transcripts(store, [(77, "2024-03-05"), (78, "2024-04-05"), (5, "2015-01-01")],
                             since=date(2022, 1, 1), client=fake(calls), sleep=lambda _s: None)
    assert stats == {"fetched": 1, "turns": 4, "missing": 1, "still_to_fetch": 0}
    assert len(calls) == 2, "sessions before the start date are not fetched"
    again = sync_transcripts(store, [(77, "2024-03-05"), (78, "2024-04-05")], client=fake(calls),
                             sleep=lambda _s: None)
    assert again["fetched"] == 0 and len(calls) == 2, "nothing is fetched twice"
    assert store.search("season tickets")[0] == 1

    cpath, epath = committees_path(indexed_settings), evidence_path(indexed_settings)
    try:
        build(cpath, fake_api(), lambda _s: None)
        sync_transcripts(EvidenceStore(epath), [(77, "2024-03-05")], client=fake([]), sleep=lambda _s: None)
        client = TestClient(make_app(indexed_settings, tmp_path, auth=False)[0])
        t = client.get("/api/evidence/77").json()
        assert t["inquiry"] == "Rail fares" and len(t["turns"]) == 4 and t["witnesses"]
        found = client.get("/api/evidence", params={"q": "wages"}).json()
        assert found["total"] == 1 and found["items"][0]["committees"] == "Transport Committee"
        assert client.get("/api/inquiries/900").json()["sessions"][0]["transcript"] is True
        assert client.get("/evidence/77").status_code == 200 and client.get("/evidence/78").status_code == 404
    finally:
        for p in (cpath, epath):
            for suffix in ("", "-wal", "-shm"):
                p.with_name(p.name + suffix).unlink(missing_ok=True)
