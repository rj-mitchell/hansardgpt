"""Web API: authentication, caps, streaming answers, retrieval-only search."""

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


@pytest.fixture()
def api(indexed_settings, tmp_path):
    # each test gets its own state DB (users, usage) on top of the shared index
    s = dataclasses.replace(indexed_settings,
                            raw={**indexed_settings.raw,
                                 "usage": {**indexed_settings.raw["usage"], "per_user_daily_questions": 2}})
    state_path = tmp_path / "state.sqlite"
    pipeline = Pipeline(s, Engine(s, embedder=HashingEmbedder(64), today=TODAY), client=FakeClient(), today=TODAY)
    state = StateDB(state_path)
    app = create_app(s, pipeline, state)
    create_user(state, "researcher@example.org", "correct horse battery")
    create_user(state, "admin@example.org", "admin password 123", admin=True)
    return TestClient(app), state


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
