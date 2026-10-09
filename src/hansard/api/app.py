"""FastAPI application: streaming answers, source search, record drawer, metadata.

Public by default: anyone may ask. Model-written briefings cost money, so they are
limited per visitor and overall, and identical requests are served from a cache.
Invite-only sign-in remains available (``[auth] required = true``)."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hansard.api.auth import (
    COOKIE,
    LoginThrottle,
    authenticate,
    create_session,
    end_session,
    user_for_token,
)
from hansard.api.usage import (
    RateLimiter,
    cache_key,
    cached_events,
    check_caps,
    record_usage,
    store_events,
    summary,
    visitor_key,
)
from hansard.config import REPO_ROOT, Settings, load_settings
from hansard.engine import Engine, Scope
from hansard.rag.pipeline import AskRequest, Pipeline
from hansard.rag.query_parse import ITL1_REGIONS, QueryPlan
from hansard.reference.portfolios import PORTFOLIOS
from hansard.store.state import StateDB

log = logging.getLogger(__name__)

ATTRIBUTION = [
    {"text": "Contains Parliamentary information licensed under the Open Parliament Licence v3.0.",
     "url": "https://www.parliament.uk/site-information/copyright-parliament/open-parliament-licence/"},
    {"text": "Contains public sector information licensed under the Open Government Licence v3.0 "
             "(ONS, NRS and NISRA boundaries, urban areas and census populations).",
     "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"},
    {"text": "Hansard data and member records via TheyWorkForYou / ParlParse, with thanks to mySociety.",
     "url": "https://www.mysociety.org/"},
]


class LoginBody(BaseModel):
    email: str
    password: str


class ScopeBody(BaseModel):
    written: bool = True
    pbc: bool = True
    votes: bool = True


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    mode: Literal["summary", "comprehensive"] = "summary"
    recency: float | None = Field(default=None, ge=0, le=1)
    role_weight: float | None = Field(default=None, ge=1, le=2)
    scope: ScopeBody = ScopeBody()
    plan: dict[str, Any] | None = None
    history: list[dict[str, str]] = Field(default_factory=list, max_length=10)


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None,
               state: StateDB | None = None) -> FastAPI:
    settings = settings or load_settings()
    state = state or StateDB(settings.state_db)
    app = FastAPI(title="HansardGPT", docs_url="/api/docs", openapi_url="/api/openapi.json")
    throttle = LoginThrottle()
    auth_required = bool(settings.section("auth").get("required", False))
    limiter = RateLimiter(int(settings.usage.get("requests_per_minute", 20)))
    cache_hours = float(settings.usage.get("answer_cache_hours", 24))
    admin_token = os.environ.get("HANSARD_ADMIN_TOKEN") or None
    lock = threading.Lock()
    holder: dict[str, Pipeline] = {}
    if pipeline is not None:
        holder["p"] = pipeline

    def get_pipeline() -> Pipeline:
        with lock:
            if "p" not in holder:
                holder["p"] = Pipeline(settings, Engine(settings))
            return holder["p"]

    def current_user(request: Request) -> dict[str, Any] | None:
        user = user_for_token(state, request.cookies.get(COOKIE))
        if user is None and auth_required:
            raise HTTPException(401, "Please sign in.")
        return user

    def admin_user(request: Request, user=Depends(current_user)):
        if user and user["is_admin"]:
            return user
        given = request.headers.get("authorization", "")
        if admin_token and secrets.compare_digest(given.encode(), f"Bearer {admin_token}".encode()):
            return None
        raise HTTPException(403, "Admins only.")

    def requester(request: Request, user: dict[str, Any] | None) -> tuple[str | None, str]:
        """(visitor hash for anonymous people, rate-limit key); 429 when over the per-minute limit."""
        visitor = None if user else visitor_key(state, request.client.host if request.client else None)
        key = f"user:{user['user_id']}" if user else f"visitor:{visitor}"
        if not limiter.allow(key):
            raise HTTPException(429, "Too many requests. Please wait a minute and try again.")
        return visitor, key

    # ---- auth --------------------------------------------------------------------
    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response):
        key = f"{request.client.host if request.client else '-'}|{body.email.lower()}"
        if throttle.blocked(key):
            raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")
        user = authenticate(state, body.email, body.password)
        if user is None:
            throttle.fail(key)
            raise HTTPException(401, "Incorrect email or password.")
        throttle.reset(key)
        days = int(settings.section("auth").get("session_days", 14))
        token = create_session(state, user["user_id"], days)
        response.set_cookie(COOKIE, token, max_age=days * 86400, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https", path="/")
        return {"email": user["email"], "is_admin": bool(user["is_admin"])}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        end_session(state, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(user=Depends(current_user)):
        return {"email": user["email"] if user else None, "is_admin": bool(user and user["is_admin"]),
                "auth_required": auth_required}

    # ---- metadata ----------------------------------------------------------------
    @app.get("/api/meta")
    def meta(user=Depends(current_user)):
        p = get_pipeline()
        idx = p.engine.index.stats()
        runs = state.runs(1)
        return {
            "regions": ITL1_REGIONS,
            "region_groups": settings.regions,
            "portfolios": PORTFOLIOS,
            "parties": [{"id": i, "name": n} for i, n in p.parties()],
            "answers_enabled": p.has_model(),
            "model": settings.answer.get("model"),
            "archive_start": settings.archive_start.isoformat(),
            "index": idx,
            "last_sync": runs[0] if runs else None,
            "defaults": {"recency": settings.ranking.get("default_recency", 0.5),
                         "role_weight": settings.ranking.get("default_role_weight", 1.5)},
            "attribution": ATTRIBUTION,
        }

    @app.get("/api/health")
    def health():
        return {"ok": True}

    # ---- questions -----------------------------------------------------------------
    def _sse(events: Iterator[dict[str, Any]]) -> Iterator[bytes]:
        for ev in events:
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n".encode()

    @app.post("/api/ask")
    def ask(body: AskBody, request: Request, user=Depends(current_user)):
        visitor, _ = requester(request, user)
        p = get_pipeline()
        uid = user["user_id"] if user else None
        req = AskRequest(question=body.question, mode=body.mode, recency=body.recency,
                         role_weight=body.role_weight, scope=Scope(**body.scope.model_dump()), plan=body.plan,
                         history=body.history)
        model_on = p.has_model()
        key = None
        if model_on and cache_hours > 0:
            last = state.runs(1)
            key = cache_key({"q": " ".join(body.question.lower().split()), **body.model_dump(exclude={"question"}),
                             "model": settings.answer.get("model"), "data": last[0]["run_id"] if last else None})
        hit = cached_events(state, key, cache_hours) if key else None
        blocked = check_caps(state, uid, settings.usage, visitor) if model_on and hit is None else None

        def events() -> Iterator[dict[str, Any]]:
            if hit is not None:
                yield from hit
                return
            if blocked:
                yield {"type": "error", "message": blocked}
                return
            kept: list[dict[str, Any]] = []
            text: list[str] = []
            try:
                for ev in p.run(req):
                    if ev["type"] == "plan" and ev.get("usage"):
                        record_usage(state, uid, "parse", settings.answer.get("model"), ev["usage"], settings.usage,
                                     visitor)
                    if ev["type"] == "final" and ev.get("usage"):
                        record_usage(state, uid, "answer", ev.get("model"), ev["usage"], settings.usage, visitor)
                    if ev["type"] == "text":
                        text.append(ev["text"])
                    else:
                        kept.append(ev)
                    yield ev
            except Exception as exc:  # never leave the client hanging
                log.exception("ask failed")
                yield {"type": "error", "message": f"Something went wrong: {type(exc).__name__}"}
                return
            final = kept[-1] if kept else {}
            if key and final.get("type") == "final" and final.get("answer"):
                replay = [e for e in kept if e["type"] in ("plan", "sources")]
                replay += [{"type": "text", "text": "".join(text)}, {**final, "usage": None, "cached": True}]
                store_events(state, key, replay, cache_hours)

        return StreamingResponse(_sse(events()), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/search")
    def search(body: AskBody, request: Request, user=Depends(current_user)):
        """Retrieval only (no model call): ranked sources for the question or edited plan."""
        requester(request, user)
        p = get_pipeline()
        if body.plan:
            plan = QueryPlan.from_dict({"question": body.question, **body.plan})
        else:
            from hansard.rag.query_parse import parse_offline

            plan = parse_offline(body.question, settings.regions, p.today)
        limit = int(settings.answer.get("comprehensive_sources" if body.mode == "comprehensive"
                                        else "summary_sources", 12))
        res = p.engine.search(plan.search_text, plan.filters, Scope(**body.scope.model_dump()), plan.portfolios,
                              body.recency, body.role_weight, limit, diversify=True)
        from hansard.rag.sources import build_sources

        return {"plan": plan.to_dict(), "sources": [s.card() for s in build_sources(res.records, [])],
                "candidates": res.candidates, "semantic": res.semantic_available, "evidence": res.evidence}

    @app.get("/api/admin/usage")
    def usage(user=Depends(admin_user)):
        return summary(state)

    @app.get("/api/admin/sync")
    def sync_log(user=Depends(admin_user)):
        return {"runs": state.runs(30)}

    # ---- web app -------------------------------------------------------------------
    dist = Path(settings.section("paths").get("web_dist", REPO_ROOT / "web" / "dist"))
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            f = dist / path
            return FileResponse(f if path and f.is_file() else dist / "index.html")

    return app
