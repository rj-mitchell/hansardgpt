"""Web API: public access with caps and cache, optional sign-in, streaming answers, search."""

from __future__ import annotations

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from hansard.api.app import create_app
from hansard.api.auth import create_user
from hansard.api.usage import cost_usd, record_usage
from hansard.embed.base import HashingEmbedder
from hansard.engine import Engine
from hansard.rag.pipeline import Pipeline
from hansard.store.state import StateDB

from .test_rag import TODAY, FakeClient


def make_app(indexed_settings, tmp_path, *, auth: bool, **usage):
    # each test gets its own state DB (users, usage, cache) on top of the shared index
    s = dataclasses.replace(indexed_settings, raw={
        **indexed_settings.raw,
        "auth": {"required": auth},
        "usage": {**indexed_settings.raw["usage"], "per_user_daily_questions": 2, "per_visitor_daily_questions": 2,
                  **usage}})
    client = FakeClient()
    pipeline = Pipeline(s, Engine(s, embedder=HashingEmbedder(64), today=TODAY), client=client, today=TODAY)
    state = StateDB(tmp_path / "state.sqlite")
    return create_app(s, pipeline, state), state, client


@pytest.fixture()
def api(indexed_settings, tmp_path):
    """Invite-only mode."""
    app, state, _ = make_app(indexed_settings, tmp_path, auth=True, answer_cache_hours=0)
    create_user(state, "researcher@example.org", "correct horse battery")
    create_user(state, "admin@example.org", "admin password 123", admin=True)
    return TestClient(app), state


@pytest.fixture()
def public(indexed_settings, tmp_path):
    """The default: open to everyone."""
    app, state, client = make_app(indexed_settings, tmp_path, auth=False)
    return TestClient(app), state, client


def login(client, email="researcher@example.org", password="correct horse battery"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


def events(resp):
    out = []
    for chunk in resp.text.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def test_requires_sign_in(api):
    client, _ = api
    assert client.get("/api/meta").status_code == 401
    assert client.post("/api/ask", json={"question": "trial by jury"}).status_code == 401
    assert client.get("/api/health").status_code == 200


def test_login_logout_and_bad_password_throttle(api):
    client, _ = api
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "researcher@example.org", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "researcher@example.org", "password": "nope"}).status_code == 429
    client2 = TestClient(client.app)
    client2.headers["X-Forwarded-For"] = "x"
    # the throttle is keyed on client + email; a different email still works
    login(client2, "admin@example.org", "admin password 123")
    assert client2.get("/api/me").json()["email"] == "admin@example.org"
    client2.post("/api/auth/logout")
    assert client2.get("/api/me").status_code == 401


def test_meta_lists_filters_and_attribution(api):
    client, _ = api
    login(client)
    m = client.get("/api/meta").json()
    assert "North East" in m["regions"] and "transport" in m["portfolios"]
    assert any("Open Parliament Licence" in a["text"] for a in m["attribution"])
    assert any("Open Government Licence" in a["text"] for a in m["attribution"])
    assert any("mySociety" in a["text"] for a in m["attribution"])


def test_ask_streams_plan_sources_text_and_verified_answer(api):
    client, state = api
    login(client)
    r = client.post("/api/ask", json={"question": "What has been said about trial by jury?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    evs = events(r)
    types = [e["type"] for e in evs]
    assert types[0] == "plan" and types[1] == "sources" and "text" in types and types[-1] == "final"
    final = evs[-1]["answer"]
    assert "[Source 1]" in final["markdown"] and final["citations_invalid"] == 0
    with state.connect() as con:
        assert con.execute("SELECT count(*) FROM usage WHERE kind = 'answer'").fetchone()[0] == 1


def test_daily_question_cap(api):
    client, _ = api
    login(client)
    for _ in range(2):
        assert events(client.post("/api/ask", json={"question": "trial by jury"}))[-1]["type"] == "final"
    last = events(client.post("/api/ask", json={"question": "trial by jury"}))
    assert last[-1]["type"] == "error" and "limit" in last[-1]["message"]


def test_search_endpoint_needs_no_model(api):
    client, _ = api
    login(client)
    r = client.post("/api/search", json={"question": "Northern Ireland security", "scope": {"written": False}})
    body = r.json()
    assert body["sources"] and all(s["kind"] == "record" for s in body["sources"])
    assert all("written" not in s["chamber"].lower() for s in body["sources"])


def test_admin_usage_is_admin_only(api):
    client, state = api
    login(client)
    assert client.get("/api/admin/usage").status_code == 403
    admin = TestClient(client.app)
    login(admin, "admin@example.org", "admin password 123")
    record_usage(state, None, "answer", "claude-opus-5-5", {"input_tokens": 10_000, "output_tokens": 1_000}, {})
    assert admin.get("/api/admin/usage").json()["total_usd"] > 0


def test_cost_calculation():
    assert cost_usd({"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0},
                    {"price_input_per_mtok": 4.0, "price_output_per_mtok": 20.0}) == pytest.approx(6.0)


# ---- public mode (the default) -------------------------------------------------------------------


def test_public_site_needs_no_sign_in(public):
    client, state, _ = public
    assert client.get("/api/me").json() == {"email": None, "is_admin": False, "auth_required": False}
    assert client.get("/api/meta").status_code == 200
    evs = events(client.post("/api/ask", json={"question": "What has been said about trial by jury?"}))
    assert evs[-1]["type"] == "final" and evs[-1]["answer"]["citations_total"] == 1
    with state.connect() as con:
        visitor = con.execute("SELECT visitor FROM usage WHERE kind = 'answer'").fetchone()[0]
    assert visitor and "testclient" not in visitor  # a salted hash, never the address


def test_repeat_questions_come_from_the_cache_and_cost_nothing(public):
    client, state, model = public
    first = events(client.post("/api/ask", json={"question": "What has been said about trial by jury?"}))
    again = events(client.post("/api/ask", json={"question": "what has been said about  trial by jury?"}))
    assert len(model.calls) == 1
    assert again[-1]["cached"] is True and again[-1]["answer"] == first[-1]["answer"]
    assert [e["type"] for e in again] == ["plan", "sources", "text", "final"]
    other = events(client.post("/api/ask", json={"question": "What has been said about trial by jury?",
                                                 "mode": "comprehensive"}))
    assert len(model.calls) == 2 and "cached" not in other[-1]
    with state.connect() as con:
        assert con.execute("SELECT count(*) FROM usage WHERE kind = 'answer'").fetchone()[0] == 2


def test_each_visitor_has_a_daily_limit_but_cached_answers_still_load(public):
    client, _, _ = public
    for q in ("trial by jury", "jury trials and courts"):
        assert events(client.post("/api/ask", json={"question": q}))[-1]["type"] == "final"
    blocked = events(client.post("/api/ask", json={"question": "security in Northern Ireland"}))
    assert blocked[-1]["type"] == "error" and "limit" in blocked[-1]["message"]
    assert events(client.post("/api/ask", json={"question": "trial by jury"}))[-1]["type"] == "final"
    other = TestClient(client.app, client=("203.0.113.9", 50000))
    assert events(other.post("/api/ask", json={"question": "security in Northern Ireland"}))[-1]["type"] == "final"


def test_site_wide_daily_budget(public):
    client, state, _ = public
    record_usage(state, None, "answer", "claude-opus-5-5", {"input_tokens": 3_000_000}, {})
    evs = events(client.post("/api/ask", json={"question": "trial by jury"}))
    assert evs[-1]["type"] == "error" and "budget" in evs[-1]["message"]


def test_requests_per_minute_limit(indexed_settings, tmp_path):
    app, _, _ = make_app(indexed_settings, tmp_path, auth=False, requests_per_minute=3)
    client = TestClient(app)
    codes = [client.post("/api/search", json={"question": "trial by jury"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_admin_endpoints_need_the_admin_token(indexed_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("HANSARD_ADMIN_TOKEN", "s3cret-token")
    app, _, _ = make_app(indexed_settings, tmp_path, auth=False)
    client = TestClient(app)
    assert client.get("/api/admin/usage").status_code == 403
    assert client.get("/api/admin/usage", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.get("/api/admin/sync", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_feedback_refers_to_the_briefing_and_shows_in_admin_usage(indexed_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("HANSARD_ADMIN_TOKEN", "s3cret-token")
    app, state, _ = make_app(indexed_settings, tmp_path, auth=False)
    client = TestClient(app)
    final = events(client.post("/api/ask", json={"question": "trial by jury"}))[-1]
    key = final["briefing_key"]
    assert key and client.post("/api/ask", json={"question": "trial by jury"}).text.count(key) == 1  # replay too
    assert client.post("/api/feedback", json={"question": "trial by jury", "useful": False,
                                              "briefing_key": key}).json() == {"ok": True}
    usage = client.get("/api/admin/usage", headers={"Authorization": "Bearer s3cret-token"}).json()
    assert usage["visits"]["feedback"]["total"] == 1
    assert usage["visits"]["feedback"]["recent_not_useful"][0]["question"] == "trial by jury"


def test_visit_counts_keep_daily_totals_only(public):
    client, state, _ = public
    for path in ("/", "/", "/methodology"):
        assert client.post("/api/hit", json={"path": path, "referrer": "https://news.example.org/story"}).status_code == 200
    with state.connect() as con:
        assert con.execute("SELECT sum(views) FROM page_views").fetchone()[0] == 3
        assert tuple(con.execute("SELECT host, views FROM referrers").fetchone()) == ("news.example.org", 3)
        assert con.execute("SELECT count(*) FROM day_visitors").fetchone()[0] == 1  # one visitor, hashed
        con.execute("UPDATE day_visitors SET day = '2026-01-01'")  # yesterday's hashes...
    client.post("/api/hit", json={"path": "/"})
    with state.connect() as con:  # ...are rolled up into a count and deleted
        assert con.execute("SELECT visitors FROM day_totals WHERE day = '2026-01-01'").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM day_visitors WHERE day = '2026-01-01'").fetchone()[0] == 0


def test_public_status(public):
    client, state, _ = public
    st = client.get("/api/status").json()
    assert st["briefings"] == "available" and st["archive_start"]
    record_usage(state, None, "answer", "claude-opus-5-5", {"input_tokens": 3_000_000}, {})
    st = client.get("/api/status").json()
    assert st["briefings"] == "paused" and "budget" in st["briefings_note"]
