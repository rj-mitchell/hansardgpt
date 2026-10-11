"""FastAPI application: streaming answers, source search, record drawer, metadata.

Public by default: anyone may ask. Model-written briefings cost money, so they are
limited per visitor and overall, and identical requests are served from a cache.
Invite-only sign-in remains available (``[auth] required = true``)."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

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
from hansard.api.briefings import (
    ID_PATTERN,
    feature,
    featured_list,
    fmt_date,
    get_briefing,
    is_featured,
    keep,
    page_with_meta,
    public_view,
    recent_briefings,
    summary_text,
    unfeature,
    withdraw_briefing,
)
from hansard.api.cards import card_png
from hansard.api.feeds import FEED_TYPE, changelog_items, rss
from hansard.api.reports import (
    CLOSED,
    DAILY_LIMIT,
    add_report,
    close_report,
    corrections,
    list_reports,
    recent_count,
)
from hansard.api.usage import (
    RateLimiter,
    alerts,
    cache_key,
    cached_events,
    check_caps,
    count_question,
    mark_supporter,
    popular_questions,
    recent_failures,
    record_failure,
    record_feedback,
    record_usage,
    record_visit,
    store_events,
    summary,
    support_reminder_due,
    visit_summary,
    visitor_key,
)
from hansard.config import REPO_ROOT, Settings, load_settings
from hansard.devolution import notes_for
from hansard.engine import Engine, Scope
from hansard.rag import prompts
from hansard.rag.pipeline import AskRequest, Pipeline
from hansard.rag.query_parse import ITL1_REGIONS, QueryPlan, parse_model
from hansard.reference.portfolios import PORTFOLIOS
from hansard.store.state import StateDB

log = logging.getLogger(__name__)

# a cached briefing is only reused while the instructions that wrote it are unchanged
INSTRUCTIONS_VERSION = __import__("hashlib").sha256(
    (prompts.ANSWER_SYSTEM + json.dumps([prompts.MODE_INSTRUCTIONS, prompts.GROUP_BY_INSTRUCTIONS],
                                        sort_keys=True)).encode()).hexdigest()[:12]

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
    edms: bool = True


class FeedbackBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    useful: bool
    briefing_key: str | None = Field(default=None, max_length=128)


class ReportBody(BaseModel):
    kind: Literal["correction", "complaint", "general"]
    message: str = Field(min_length=10, max_length=4000)
    briefing_id: str | None = Field(default=None, max_length=20)
    contact: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=200)  # left empty by people; filled in by spam bots


class CloseReportBody(BaseModel):
    status: Literal["resolved", "dismissed"]
    resolution: str = Field(min_length=3, max_length=2000)       # private
    public_note: str | None = Field(default=None, max_length=1000)  # shown on the corrections page


class WithdrawBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class FeatureBody(BaseModel):
    briefing: str = Field(min_length=10, max_length=300, description="the briefing's id or full address")
    title: str | None = Field(default=None, max_length=200)
    blurb: str | None = Field(default=None, max_length=600)


class HitBody(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    referrer: str | None = Field(default=None, max_length=500)


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    mode: Literal["summary", "comprehensive"] = "summary"
    recency: float | None = Field(default=None, ge=0, le=1)
    role_weight: float | None = Field(default=None, ge=1, le=2)
    scope: ScopeBody = ScopeBody()
    plan: dict[str, Any] | None = None
    history: list[dict[str, str]] = Field(default_factory=list, max_length=10)
    sources_only: bool = False  # find and show the sources, but write no briefing (free)
    compare: list[dict[str, str]] = Field(default_factory=list, max_length=3)  # sides, from the Compare page


def donate_url(settings: Settings) -> str | None:
    """The 'Support this site' link, if one is set and is a plain https address."""
    url = (os.environ.get("HANSARD_DONATE_URL") or settings.section("site").get("donate_url") or "").strip()
    return url if url.startswith("https://") and len(url) < 300 and not any(c in url for c in "\"'<> ") else None


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    """What visitors may see of an update run: when it finished and whether it worked (no internal details)."""
    return {"finished_at": run.get("finished_at"), "status": run.get("status")}


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None,
               state: StateDB | None = None) -> FastAPI:
    settings = settings or load_settings()
    state = state or StateDB(settings.state_db)
    app = FastAPI(title="Where They Stand", docs_url="/api/docs", openapi_url="/api/openapi.json")
    throttle = LoginThrottle()
    auth_required = bool(settings.section("auth").get("required", False))
    limiter = RateLimiter(int(settings.usage.get("requests_per_minute", 20)))
    cache_hours = float(settings.usage.get("answer_cache_hours", 24))
    admin_token = os.environ.get("HANSARD_ADMIN_TOKEN") or None
    lock = threading.Lock()
    dist = Path(settings.section("paths").get("web_dist", REPO_ROOT / "web" / "dist"))
    holder: dict[str, Pipeline] = {}
    if pipeline is not None:
        holder["p"] = pipeline

    def get_pipeline() -> Pipeline:
        with lock:
            if "p" not in holder:
                holder["p"] = Pipeline(settings, Engine(settings))
            return holder["p"]

    def get_people():
        from hansard.people import People

        p = get_pipeline()
        with lock:
            if "people" not in holder:
                holder["people"] = People(settings, p.engine.resolver, p.today)
            return holder["people"]

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
            "last_sync": _public_run(runs[0]) if runs else None,
            "defaults": {"recency": settings.ranking.get("default_recency", 0.5),
                         "role_weight": settings.ranking.get("default_role_weight", 1.5)},
            "attribution": ATTRIBUTION,
            "donate_url": donate_url(settings),
        }

    @app.get("/api/site")
    def site():
        """Small, public settings for the static pages."""
        return {"donate_url": donate_url(settings)}

    @app.post("/api/support-clicked")
    def support_clicked(request: Request, user=Depends(current_user)):
        """The reader went through to the donation page from the reminder: no more reminders for them today."""
        visitor, _ = requester(request, user)
        if visitor:
            mark_supporter(state, visitor)
        return {"ok": True}

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
                         history=body.history, compare=body.compare)
        model_on = p.has_model()
        key = None
        if model_on and cache_hours > 0:
            last = state.runs(1)
            key = cache_key({"q": " ".join(body.question.lower().split()), **body.model_dump(exclude={"question"}),
                             "model": settings.answer.get("model"), "data": last[0]["run_id"] if last else None,
                             "instructions": INSTRUCTIONS_VERSION})
        count_question(state, body.question)
        hit = cached_events(state, key, cache_hours) if key and not body.sources_only else None
        blocked = (check_caps(state, uid, settings.usage, visitor)
                   if model_on and hit is None and not body.sources_only else None)

        def events() -> Iterator[dict[str, Any]]:
            if hit is not None:
                final = hit[-1]
                if final.get("answer") and not final["answer"].get("no_records") and not final.get("briefing_id"):
                    # cached before shareable links existed: give it an address now, and remember it
                    hit[-1] = {**final, **keep_briefing(body, hit, final)}
                    store_events(state, key, hit, cache_hours)
                yield from hit
                return
            if body.sources_only:
                yield from sources_only_events(body, "Sources only: no briefing was written. Ask again without "
                                                     "'Sources only' for a written briefing.", uid, visitor)
                return
            if blocked:  # the sources still help, and cost nothing
                yield from sources_only_events(body, f"{blocked} The sources found are shown below.", uid, visitor)
                return
            kept: list[dict[str, Any]] = []
            text: list[str] = []
            remind = 0  # > 0: show this reader the note on costs, with the number of briefings so far today
            try:
                for ev in p.run(req):
                    if ev["type"] == "plan" and ev.get("parse_error"):
                        # the model could not read the question (a bad API key, say); offline rules were used
                        record_failure(state, "question reading", body.question, ev.pop("parse_error"))
                    if ev["type"] == "error":
                        record_failure(state, "briefing", body.question, ev.get("message", ""))
                    if ev["type"] == "plan" and ev.get("usage"):
                        record_usage(state, uid, "parse", parse_model(settings), ev["usage"], settings.usage,
                                     visitor)
                    if ev["type"] == "final" and ev.get("usage"):
                        record_usage(state, uid, "answer", ev.get("model"), ev["usage"], settings.usage, visitor)
                        if uid is None and donate_url(settings):
                            remind = support_reminder_due(state, visitor,
                                                          int(settings.usage.get("support_reminder_every", 10)))
                    if ev["type"] == "final" and key:
                        ev = {**ev, "briefing_key": key}  # lets the reader's feedback refer to this briefing
                    if ev["type"] == "final" and ev.get("answer") and not ev["answer"].get("no_records"):
                        ev = {**ev, **keep_briefing(body, kept, ev)}  # a permanent, shareable address
                    if ev["type"] == "text":
                        text.append(ev["text"])
                    else:
                        kept.append(ev)
                    # the reminder goes to this reader only: never into saved, shared or cached copies
                    yield {**ev, "support_reminder": remind} if ev["type"] == "final" and remind else ev
            except Exception as exc:  # never leave the client hanging
                log.exception("ask failed")
                record_failure(state, "briefing", body.question, f"{type(exc).__name__}: {exc}")
                yield {"type": "error", "message": "The briefing could not be written just now. The sources found are "
                                                   "shown above; please try again later."}
                return
            final = kept[-1] if kept else {}
            if key and final.get("type") == "final" and final.get("answer"):
                replay = [e for e in kept if e["type"] in ("plan", "sources")]
                replay += [{"type": "text", "text": "".join(text)}, {**final, "usage": None, "cached": True}]
                store_events(state, key, replay, cache_hours)

        return StreamingResponse(_sse(events()), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def retrieve(body: AskBody, read_with_model: bool = False, uid: int | None = None,
                 visitor: str | None = None) -> dict[str, Any]:
        """The plan and ranked sources for the question or edited plan, without writing a briefing.

        The question is read by the model when ``read_with_model`` (a fraction of a penny with a small model, and far
        more accurate), otherwise by the free built-in rules.
        """
        p = get_pipeline()
        if body.plan:
            plan = QueryPlan.from_dict({"question": body.question, **body.plan})
        elif read_with_model and p.has_model():
            plan, usage = p.make_plan(AskRequest(question=body.question, history=body.history, compare=body.compare))
            if plan.parse_error:
                record_failure(state, "question reading", body.question, plan.parse_error)
            if usage:
                record_usage(state, uid, "parse", parse_model(settings), usage, settings.usage, visitor)
        else:
            from hansard.rag.query_parse import parse_offline

            plan = parse_offline(body.question, settings.regions, p.today)
            p._set_comparison(plan, AskRequest(question=body.question, compare=body.compare))
        req = AskRequest(question=body.question, mode=body.mode, recency=body.recency, role_weight=body.role_weight,
                         scope=Scope(**body.scope.model_dump()))
        res, _, sources = p.find(plan, req)
        return {"plan": plan.to_dict(), "sources": [s.card() for s in sources if s.kind in ("record", "edm")],
                "candidates": res.candidates, "semantic": res.semantic_available,
                "evidence": {**res.evidence, "devolution": notes_for(plan.question),
                             "edms": sum(1 for s in sources if s.kind == "edm")} if res.evidence else res.evidence}

    def sources_only_events(body: AskBody, note: str, uid: int | None = None,
                            visitor: str | None = None) -> Iterator[dict[str, Any]]:
        # read the question with the model unless the site's own budget is used up
        r = retrieve(body, check_caps(state, None, settings.usage, None) is None, uid, visitor)
        yield {"type": "plan", "plan": r["plan"], "usage": None}
        yield {"type": "sources", **{k: r[k] for k in ("sources", "candidates", "semantic", "evidence")}}
        yield {"type": "final", "answer": None, "usage": None, "note": note}

    @app.post("/api/search")
    def search(body: AskBody, request: Request, user=Depends(current_user)):
        """Retrieval only (no model call): ranked sources for the question or edited plan."""
        requester(request, user)
        return retrieve(body)

    def keep_briefing(body: AskBody, kept: list[dict[str, Any]], final: dict[str, Any]) -> dict[str, Any]:
        return keep(state, body.question, body.model_dump(exclude={"question", "history"}), kept, final)

    # ---- shared briefings ---------------------------------------------------------------
    def _briefing_or_error(bid: str) -> dict[str, Any]:
        b = get_briefing(state, bid)
        if b is None:
            raise HTTPException(404, "There is no briefing at this address.")
        if b["withdrawn_at"]:
            raise HTTPException(410, "This briefing has been withdrawn.")
        return b

    @app.get("/api/briefings/{bid}")
    def briefing(bid: str):
        return public_view(_briefing_or_error(bid))

    @app.get("/b/{bid}/card.png", include_in_schema=False)
    def briefing_card(bid: str):
        b = _briefing_or_error(bid)
        view = public_view(b)
        path = card_png(settings.data_dir / "cards", bid, b["question"], fmt_date(b["created_at"]),
                        fmt_date(b["records_up_to"]), view["evidence"])
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/b/{bid}", include_in_schema=False)
    def briefing_page(bid: str, request: Request):
        """The app, with this briefing's title and link-preview card in the page head."""
        index = dist / "index.html"
        page = index.read_text() if index.is_file() else "<!doctype html><html><head></head><body></body></html>"
        b = get_briefing(state, bid) if ID_PATTERN.match(bid) else None
        base = str(request.base_url).rstrip("/")
        if b is None or b["withdrawn_at"]:
            gone = b is not None
            html_page = page_with_meta(
                page, title="Briefing withdrawn — Where They Stand" if gone else "Briefing not found — Where They Stand",
                description="This briefing is no longer available." if gone else "There is no briefing at this address.",
                url=f"{base}/b/{bid}", image=None)
            return Response(html_page, status_code=410 if gone else 404, media_type="text/html")
        view = public_view(b)
        prepared = fmt_date(b["created_at"])
        description = summary_text(view["answer"]) or "A sourced briefing on the record of Parliament."
        html_page = page_with_meta(
            page, title=f"{b['question']} — Where They Stand", description=description, url=f"{base}/b/{bid}",
            image=f"{base}/b/{bid}/card.png",
            image_alt=f"Where They Stand briefing: {b['question']} Prepared {prepared}.",
            noindex=not is_featured(state, bid))  # featured briefings are for search engines to find
        return Response(html_page, media_type="text/html")

    @app.post("/api/admin/briefings/{bid}/withdraw")
    def withdraw(bid: str, body: WithdrawBody, user=Depends(admin_user)):
        if not withdraw_briefing(state, bid, body.reason):
            raise HTTPException(404, "There is no briefing at this address.")
        (settings.data_dir / "cards" / f"{bid}.png").unlink(missing_ok=True)
        return {"ok": True}

    @app.get("/api/admin/briefings")
    def briefings_list(limit: int = 50, user=Depends(admin_user)):
        return {"briefings": recent_briefings(state, min(max(limit, 1), 500))}

    # ---- topic briefings and featured briefings ------------------------------------------------
    def _topic(slug: str):
        from hansard.topics import load_topics, topics_file

        t = next((t for t in load_topics(topics_file(settings)) if t.slug == slug), None)
        if t is None:
            raise HTTPException(404, "There is no topic at this address.")
        return t

    @app.get("/api/topics")
    def topics_index():
        from hansard.topics import topic_listing

        topics = [{k: v for k, v in t.items() if k != "last_check"} for t in topic_listing(settings, state)]
        return {"topics": topics, "featured": featured_list(state)}

    @app.get("/api/topics/{slug}")
    def topic_detail(slug: str):
        from hansard.topics import versions

        t = _topic(slug)
        vs = versions(state, slug)
        b = get_briefing(state, vs[0]["briefing_id"]) if vs else None
        return {"topic": {"slug": t.slug, "title": t.title, "area": t.area, "question": t.question,
                          "description": t.description, "refresh_days": t.refresh_days},
                "briefing": public_view(b) if b else None, "versions": vs}

    @app.get("/topics/{slug}", include_in_schema=False)
    def topic_page(slug: str, request: Request):
        """The app, showing the topic's current briefing, with its title and preview card in the page head."""
        from hansard.topics import current

        t = _topic(slug)
        index = dist / "index.html"
        page = index.read_text() if index.is_file() else "<!doctype html><html><head></head><body></body></html>"
        base = str(request.base_url).rstrip("/")
        cur = current(state, slug)
        b = get_briefing(state, cur["briefing_id"]) if cur else None
        description = (summary_text(public_view(b)["answer"]) if b else "") or t.description or t.question
        html_page = page_with_meta(
            page, title=f"{t.title}: where MPs and peers stand — Where They Stand", description=description,
            url=f"{base}/topics/{slug}", image=f"{base}/b/{b['id']}/card.png" if b else None,
            image_alt=f"Where They Stand topic briefing: {t.title}", noindex=False)
        return Response(html_page, media_type="text/html")

    @app.get("/sitemap-briefings.xml", include_in_schema=False)
    def sitemap_briefings(request: Request):
        from hansard.topics import topic_listing

        base = str(request.base_url).rstrip("/")
        urls = [f"<url><loc>{base}/topics</loc><changefreq>weekly</changefreq></url>"]
        for t in topic_listing(settings, state):
            if t["current"]:
                urls.append(f"<url><loc>{base}/topics/{t['slug']}</loc>"
                            f"<lastmod>{t['current']['prepared_at'][:10]}</lastmod></url>")
        urls += [f"<url><loc>{base}/b/{f['id']}</loc><lastmod>{f['prepared_at'][:10]}</lastmod></url>"
                 for f in featured_list(state)]
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset '
                        f'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{"".join(urls)}</urlset>',
                        media_type="application/xml")

    @app.get("/api/admin/topics")
    def admin_topics(user=Depends(admin_user)):
        from hansard.topics import topic_listing

        return {"topics": topic_listing(settings, state), "featured": featured_list(state)}

    @app.post("/api/admin/featured")
    def admin_feature(body: FeatureBody, user=Depends(admin_user)):
        m = re.search(r"([a-km-z2-9]{10})/?$", body.briefing.strip())
        if not m or not feature(state, m.group(1), body.title, body.blurb):
            raise HTTPException(404, "There is no briefing at that address (or it has been withdrawn).")
        return {"ok": True, "id": m.group(1)}

    @app.delete("/api/admin/featured/{bid}")
    def admin_unfeature(bid: str, user=Depends(admin_user)):
        if not unfeature(state, bid):
            raise HTTPException(404, "That briefing is not featured.")
        return {"ok": True}

    # ---- bills ---------------------------------------------------------------------------------
    def get_bills():
        from hansard.bills import Bills

        with lock:
            if "bills" not in holder:
                holder["bills"] = Bills(settings)
        return holder["bills"]

    @app.get("/api/bills")
    def bills_index():
        """Every bill debated since 2010, newest first (summary only)."""
        out = []
        for b in get_bills().all(state.latest_record_date()):
            last = b["sittings"][-1]
            out.append({k: b[k] for k in ("slug", "name", "first", "last", "houses", "contributions")}
                       | {"sittings": len(b["sittings"]), "divisions": len(b["divisions"]),
                          "latest": f"{', '.join(last['stages'])} ({'Lords' if last['house'] == 'lords' else 'Commons'})"})
        return {"bills": out}

    @app.get("/api/bills/{slug}")
    def bill_detail(slug: str):
        b = get_bills().get(slug, state.latest_record_date())
        if b is None:
            raise HTTPException(404, "There is no bill at this address.")
        return b

    @app.get("/bills/{slug}", include_in_schema=False)
    def bill_page(slug: str, request: Request):
        b = get_bills().get(slug, state.latest_record_date())
        index = dist / "bill.html"
        page = index.read_text() if index.is_file() else "<!doctype html><html><head></head><body></body></html>"
        base = str(request.base_url).rstrip("/")
        if b is None:
            return Response(page_with_meta(page, title="Bill not found — Where They Stand",
                                           description="There is no bill at this address.", url=f"{base}/bills/{slug}",
                                           image=None), status_code=404, media_type="text/html")
        houses = " and ".join("the Lords" if h == "lords" else "the Commons" for h in b["houses"])
        description = (f"The {b['name']} in Parliament: every debate and vote in {houses}, "
                       f"{fmt_date(b['first'])} to {fmt_date(b['last'])}, from the official record.")
        return Response(page_with_meta(page, title=f"{b['name']} — Where They Stand", description=description,
                                       url=f"{base}/bills/{slug}", image=None, noindex=False), media_type="text/html")

    @app.get("/sitemap-bills.xml", include_in_schema=False)
    def sitemap_bills(request: Request):
        base = str(request.base_url).rstrip("/")
        urls = "".join(f"<url><loc>{base}/bills/{b['slug']}</loc><lastmod>{b['last']}</lastmod></url>"
                       for b in get_bills().all(state.latest_record_date()))
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset '
                        f'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                        media_type="application/xml")

    # ---- debates -------------------------------------------------------------------------------
    def get_debates():
        from hansard.debates import Debates

        with lock:
            if "debates" not in holder:
                holder["debates"] = Debates(settings)
        return holder["debates"]

    _DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _SLUG = re.compile(r"^[a-z0-9-]{1,200}$")

    def find_debate(day: str, chamber: str, slug: str):
        if not (_DAY.match(day) and _SLUG.match(chamber) and _SLUG.match(slug)):
            return None
        return get_debates().get(day, chamber, slug, state.latest_record_date())

    @app.get("/api/debates/{day}/{chamber}/{slug}")
    def debate_detail(day: str, chamber: str, slug: str):
        """A whole debate as recorded, in order, with each speaker as they were on the day. Free: no AI."""
        d = find_debate(day, chamber, slug)
        if d is None:
            raise HTTPException(404, "There is no debate at this address.")
        return d

    @app.get("/debates/{day}/{chamber}/{slug}", include_in_schema=False)
    def debate_page(day: str, chamber: str, slug: str, request: Request):
        d = find_debate(day, chamber, slug)
        index = dist / "debate.html"
        page = index.read_text() if index.is_file() else "<!doctype html><html><head></head><body></body></html>"
        url = f"{str(request.base_url).rstrip('/')}/debates/{day}/{chamber}/{slug}"
        if d is None:
            return Response(page_with_meta(page, title="Debate not found — Where They Stand",
                                           description="There is no debate at this address.", url=url, image=None),
                            status_code=404, media_type="text/html")
        description = (f"{d['title']}: the debate in the {d['chamber_name']} on {fmt_date(d['date'])}, as recorded "
                       f"in Hansard, with {d['contributions']} contributions from {d['speakers']} members.")
        return Response(page_with_meta(page, title=f"{d['title']}, {fmt_date(d['date'])} — Where They Stand",
                                       description=description, url=url, image=None, noindex=False),
                        media_type="text/html")

    # ---- the week in Parliament ---------------------------------------------------------------
    def get_weeks():
        from hansard.week import Weeks

        with lock:
            if "weeks" not in holder:
                holder["weeks"] = Weeks(settings)
        return holder["weeks"]

    def find_week(start: str | None):
        from hansard.week import monday

        w = get_weeks()
        if start is None:
            day = w.latest()
        else:
            try:
                day = date.fromisoformat(start) if _DAY.match(start) else None
            except ValueError:
                day = None
        return w.get(monday(day), state.latest_record_date()) if day else None

    @app.get("/api/week")
    def week_detail(start: str | None = None):
        """One sitting week (Monday to Sunday; the latest if no start is given). Free: no AI."""
        w = find_week(start)
        if w is None:
            raise HTTPException(404, "Parliament did not sit that week, or the week is outside the record.")
        return w

    def week_page(start: str | None, request: Request) -> Response:
        w = find_week(start)
        index = dist / "week.html"
        page = index.read_text() if index.is_file() else "<!doctype html><html><head></head><body></body></html>"
        base = str(request.base_url).rstrip("/")
        if w is None:
            return Response(page_with_meta(page, title="Week not found — Where They Stand",
                                           description="Parliament did not sit that week.",
                                           url=f"{base}/weeks/{start}", image=None),
                            status_code=404, media_type="text/html")
        url = f"{base}/this-week" if start is None else f"{base}/weeks/{w['start']}"
        span = f"{fmt_date(w['start'])} to {fmt_date(w['end'])}"
        return Response(page_with_meta(page, title=f"In Parliament, week of {fmt_date(w['start'])} — Where They Stand",
                                       description=f"The debates, votes, bills and statements in Parliament, {span}, "
                                                   "from the official record.", url=url, image=None, noindex=False),
                        media_type="text/html")

    @app.get("/this-week", include_in_schema=False)
    def this_week_page(request: Request):
        return week_page(None, request)

    @app.get("/weeks/{start}", include_in_schema=False)
    def a_week_page(start: str, request: Request):
        return week_page(start, request)

    # ---- early day motions -----------------------------------------------------------------------
    def get_edms():
        from hansard.sources.edms import EdmStore
        from hansard.sync import edms_path

        with lock:
            if "edms" not in holder:
                holder["edms"] = EdmStore(edms_path(settings))
        return holder["edms"]

    def edm_member(found: dict, mnis: int | None, on: str | None, name: str | None, party: str | None) -> dict:
        m = found.get((mnis, on)) or {}
        return {"name": m.get("name") or name, "party": m.get("party") or party, "number": m.get("number"),
                "slug": m.get("slug")}

    def edm_rows(rows: list[dict]) -> list[dict]:
        found = get_people().by_parliament_id([(r["primary_mnis"], r["date_tabled"]) for r in rows
                                               if r["primary_mnis"]])
        return [{**{k: r[k] for k in ("id", "uin", "title", "date_tabled", "status", "sponsors_count", "prayer")},
                 "sponsor": edm_member(found, r["primary_mnis"], r["date_tabled"], r["primary_name"],
                                       r["primary_party"])} for r in rows]

    @app.get("/api/edms")
    def edms_index(q: str = "", page: int = 1, person: int | None = None):
        """Early day motions, newest first, optionally matching words or signed by one member. Free: no AI."""
        store = get_edms()
        page = max(1, min(page, 500))
        mnis = None
        if person is not None:
            pp = get_people()
            pid = pp.resolve(person)
            info = pp.page(pid) if pid else None
            if not info or not info.get("parliament_id"):
                raise HTTPException(404, "There is no member with that number.")
            mnis = [int(info["parliament_id"])]
        total, rows = store.search(q[:200], mnis=mnis, limit=25, offset=(page - 1) * 25)
        return {"total": total, "page": page, "per_page": 25, "items": edm_rows(rows), "available": store.count() > 0}

    @app.get("/api/edms/{edm_id}")
    def edm_detail(edm_id: int):
        e = get_edms().get(edm_id)
        if e is None:
            raise HTTPException(404, "There is no early day motion with that number.")
        pairs = [(s["mnis"], s["signed"]) for s in e["sponsors"]]
        if e["primary_mnis"]:
            pairs.append((e["primary_mnis"], e["date_tabled"]))
        found = get_people().by_parliament_id(pairs)
        sponsors = [{**edm_member(found, s["mnis"], s["signed"], s["name"], s["party"]),
                     **{k: s[k] for k in ("sponsoring_order", "signed", "withdrawn")}} for s in e["sponsors"]]
        parties: dict[str, int] = {}
        for s in sponsors:
            if not s["withdrawn"]:
                parties[s["party"] or "Unknown"] = parties.get(s["party"] or "Unknown", 0) + 1
        return {**{k: e[k] for k in ("id", "uin", "title", "text", "date_tabled", "status", "status_date",
                                     "sponsors_count", "amendment_to", "prayer")},
                "sponsor": edm_member(found, e["primary_mnis"], e["date_tabled"], e["primary_name"],
                                      e["primary_party"]),
                "sponsors": sponsors, "signatures_known": bool(e["sponsors_fetched"]),
                "party_counts": sorted(parties.items(), key=lambda x: (-x[1], x[0])),
                "amendments": e["amendments"],
                "official_url": f"https://edm.parliament.uk/early-day-motion/{e['id']}"}

    @app.get("/edms/{edm_id}", include_in_schema=False)
    def edm_page(edm_id: int, request: Request):
        e = get_edms().get(edm_id)
        index = dist / "edm.html"
        page = index.read_text() if index.is_file() else "<!doctype html><html><head></head><body></body></html>"
        url = f"{str(request.base_url).rstrip('/')}/edms/{edm_id}"
        if e is None:
            return Response(page_with_meta(page, title="Early day motion not found — Where They Stand",
                                           description="There is no early day motion with that number.", url=url,
                                           image=None), status_code=404, media_type="text/html")
        when = fmt_date(e["date_tabled"]) if e["date_tabled"] else "an unknown date"
        return Response(page_with_meta(page, title=f"{e['title']} (early day motion) — Where They Stand",
                                       description=f"Early day motion tabled on {when} by {e['primary_name']}, with "
                                                   f"{e['sponsors_count'] or 0} signatures: the text and who signed.",
                                       url=url, image=None, noindex=False), media_type="text/html")

    # ---- charts --------------------------------------------------------------------------------
    chart_slots = threading.Semaphore(2)  # each chart scans the record for a few seconds; keep the server responsive

    def get_trends():
        from hansard.trends import Trends

        today = get_pipeline().today  # before taking the lock: get_pipeline takes it too
        with lock:
            if "trends" not in holder:
                holder["trends"] = Trends(settings, today)
        return holder["trends"]

    @app.get("/api/trends")
    def trends(request: Request, q: str = "", by: str = "all", user=Depends(current_user)):
        """How often words were used in Parliament each year, with the context to read the numbers (free)."""
        requester(request, user)
        phrases = [p for p in q.split(",") if p.strip()]
        if not chart_slots.acquire(timeout=30):
            raise HTTPException(503, "The site is busy drawing other charts. Please try again in a moment.")
        try:
            return get_trends().chart(phrases, by, str(state.latest_record_date()))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            chart_slots.release()

    # ---- timelines -----------------------------------------------------------------------------
    @app.get("/api/timeline")
    def timeline_api(request: Request, q: str = "", person: int | None = None, party: str | None = None,
                     user=Depends(current_user)):
        """What a member or a party said on a topic, and how they voted, in date order (free: no AI)."""
        from hansard.timeline import timeline

        requester(request, user)
        q = " ".join(q.split())
        if len(q) < 3:
            raise HTTPException(400, "Give a topic of at least three letters.")
        pid = get_people().resolve(person) if person is not None else None
        if person is not None and pid is None:
            raise HTTPException(404, "There is no member with that number.")
        if (pid is None) == (not party):
            raise HTTPException(400, "Choose a member or a party.")
        if party and party not in {p for p, _ in get_pipeline().parties()}:
            raise HTTPException(404, "There is no party with that name.")
        return timeline(get_pipeline().engine, get_people(), q, person_id=pid, party_id=party)

    # ---- MPs and peers -----------------------------------------------------------------------
    @app.get("/api/people")
    def people_list(q: str = "", everyone: bool = False):
        return {"people": get_people().search(q.strip()[:80], current_only=not everyone)}

    @app.get("/api/people/{number}")
    def person(number: int):
        pp = get_people()
        pid = pp.resolve(number)
        page = pp.page(pid) if pid else None
        if page is None:
            raise HTTPException(404, "There is no member with that number.")
        edms = None
        if page.get("parliament_id"):
            try:
                edms = get_edms().member_summary(int(page["parliament_id"]), recent=8)
                edms["recent"] = edm_rows(edms["recent"])
            except (ValueError, OSError):
                edms = None
        return {**page, "contributions": pp.contributions(pid), "voting": pp.voting(pid), "edms": edms}

    @app.get("/api/postcode/{postcode}")
    def postcode(postcode: str, request: Request, user=Depends(current_user)):
        requester(request, user)
        try:
            found = get_people().by_postcode(postcode)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:  # Parliament's service could not be reached
            raise HTTPException(503, "The postcode service could not be reached. Please try again.") from None
        if not found:
            raise HTTPException(404, "No constituency was found for that postcode.")
        return found

    @app.get("/people/{number}", include_in_schema=False)
    @app.get("/people/{number}/{name}", include_in_schema=False)
    def person_page(number: int, request: Request, name: str = ""):
        """The person page, with that member's name and description in the page head."""
        page_file = dist / "person.html"
        html_doc = page_file.read_text() if page_file.is_file() else "<!doctype html><html><head></head><body></body></html>"
        pp = get_people()
        pid = pp.resolve(number)
        info = pp.page(pid) if pid else None
        base = str(request.base_url).rstrip("/")
        if info is None:
            return Response(page_with_meta(html_doc, title="Member not found — Where They Stand",
                                           description="There is no member at this address.",
                                           url=f"{base}/people/{number}", image=None), status_code=404,
                            media_type="text/html")
        desc = f"{info['status']}. What {info['name']} has said in Parliament, with roles, majorities and votes."
        return Response(page_with_meta(html_doc, title=f"{info['name']} — Where They Stand", description=desc,
                                       url=f"{base}/people/{info['number']}/{info['slug']}",
                                       image=f"{base}/og-image.png", image_alt="Where They Stand", noindex=False),
                        media_type="text/html")

    @app.get("/sitemap-people.xml", include_in_schema=False)
    def sitemap_people(request: Request):
        base = str(request.base_url).rstrip("/")
        urls = "".join(f"<url><loc>{base}/people/{p['number']}/{p['slug']}</loc><changefreq>weekly</changefreq></url>"
                       for p in get_people().search(current_only=True))
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset '
                        f'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                        media_type="application/xml")

    # ---- RSS feeds -------------------------------------------------------------------------
    def feed(request: Request, path: str, title: str, link: str, description: str, items: list) -> Response:
        base = str(request.base_url).rstrip("/")
        return Response(rss(title=f"{title} — Where They Stand", link=base + link, description=description,
                            self_url=base + path, items=items), media_type=FEED_TYPE)

    @app.get("/feeds/people/{number}.xml", include_in_schema=False)
    def feed_person(number: int, request: Request):
        pp = get_people()
        pid = pp.resolve(number)
        page = pp.page(pid) if pid else None
        if page is None:
            raise HTTPException(404, "There is no member with that number.")
        base = str(request.base_url).rstrip("/")
        items = [{"title": c["heading"] or c["chamber"], "date": c["date"], "guid": c["record_id"],
                  "link": base + c["debate_path"] if c.get("debate_path") else c["twfy_url"],
                  "description": f"{c['chamber']}, {fmt_date(c['date'])}. {c['excerpt'].strip()}…"}
                 for c in pp.contributions(pid)]
        return feed(request, f"/feeds/people/{number}.xml", page["name"], f"/people/{number}/{page['slug']}",
                    f"What {page['name']} has said in Parliament, newest first, from the official record.", items)

    @app.get("/feeds/topics.xml", include_in_schema=False)
    def feed_topics(request: Request):
        from hansard.topics import topic_listing

        base = str(request.base_url).rstrip("/")
        items = [{"title": f"{t['title']}: updated briefing", "link": f"{base}/topics/{t['slug']}",
                  "guid": f"{base}/b/{t['current']['briefing_id']}", "date": t["current"]["prepared_at"],
                  "description": t["current"].get("summary") or t["question"]}
                 for t in topic_listing(settings, state) if t["current"]]
        items.sort(key=lambda i: i["date"], reverse=True)
        return feed(request, "/feeds/topics.xml", "Topic briefings", "/topics",
                    "Each topic briefing when it is updated with new contributions.", items)

    @app.get("/feeds/bills.xml", include_in_schema=False)
    def feed_bills(request: Request):
        base = str(request.base_url).rstrip("/")
        items = []
        for b in get_bills().all(state.latest_record_date())[:40]:
            last = b["sittings"][-1]
            house = "Lords" if last["house"] == "lords" else "Commons"
            items.append({"title": f"{b['name']}: {', '.join(last['stages'])} ({house})",
                          "link": f"{base}/bills/{b['slug']}", "guid": f"{base}/bills/{b['slug']}#{last['date']}",
                          "date": last["date"],
                          "description": f"Debated in the {house} on {fmt_date(last['date'])}."})
        return feed(request, "/feeds/bills.xml", "Bills", "/bills",
                    "Bills as they are debated in Parliament, latest sitting first.", items)

    @app.get("/feeds/corrections.xml", include_in_schema=False)
    def feed_corrections(request: Request):
        base = str(request.base_url).rstrip("/")
        items = [{"title": "Briefing withdrawn" if c["kind"] == "withdrawn" else "Correction",
                  "link": f"{base}/corrections", "guid": f"{base}/corrections#{c['date']}-{k}", "date": c["date"],
                  "description": " ".join(x for x in (c.get("question"), c.get("note")) if x)}
                 for k, c in enumerate(corrections(state))]
        return feed(request, "/feeds/corrections.xml", "Corrections", "/corrections",
                    "Withdrawn briefings and published corrections.", items)

    @app.get("/feeds/changelog.xml", include_in_schema=False)
    def feed_changelog(request: Request):
        page = dist / "changelog.html"
        base = str(request.base_url).rstrip("/")
        items = changelog_items(page.read_text(), base) if page.is_file() else []
        return feed(request, "/feeds/changelog.xml", "Changelog", "/changelog",
                    "New features and changes to the site.", items)

    # ---- feedback, visit counts and public status ---------------------------------------
    @app.post("/api/feedback")
    def feedback(body: FeedbackBody, request: Request, user=Depends(current_user)):
        visitor, _ = requester(request, user)
        record_feedback(state, body.briefing_key, body.question, body.useful, visitor)
        return {"ok": True}

    @app.post("/api/report")
    def report(body: ReportBody, request: Request, user=Depends(current_user)):
        visitor, _ = requester(request, user)
        if body.website:  # a bot: say thanks, keep nothing
            return {"ok": True}
        if recent_count(state, visitor) >= DAILY_LIMIT:
            raise HTTPException(429, "Thank you, we have your reports. Please email us if there is more to add.")
        bid = body.briefing_id if body.briefing_id and ID_PATTERN.match(body.briefing_id) else None
        add_report(state, body.kind, body.message.strip(), bid, (body.contact or "").strip() or None, visitor)
        return {"ok": True}

    @app.get("/api/corrections")
    def corrections_log():
        return {"corrections": corrections(state)}

    @app.get("/api/admin/reports")
    def reports_list(status: str | None = None, user=Depends(admin_user)):
        return {"reports": list_reports(state, status if status in ("open", *CLOSED) else None)}

    @app.post("/api/admin/reports/{report_id}/close")
    def report_close(report_id: int, body: CloseReportBody, user=Depends(admin_user)):
        if not close_report(state, report_id, body.status, body.resolution, body.public_note):
            raise HTTPException(404, "No such report.")
        return {"ok": True}

    @app.post("/api/hit")
    def hit(body: HitBody, request: Request, user=Depends(current_user)):
        """Cookie-free page counting: no identifiers are sent or stored beyond today's salted hash."""
        visitor, _ = requester(request, user)
        host = urlparse(body.referrer).hostname if body.referrer else None
        own = request.url.hostname
        record_visit(state, body.path.split("?")[0], host if host and host != own else None, visitor)
        return {"ok": True}

    @app.get("/api/status")
    def status():
        p = get_pipeline()
        runs = state.runs(1)
        idx = p.engine.index.stats()
        model_on = p.has_model()
        paused = check_caps(state, None, settings.usage, None) if model_on else None
        return {
            "archive_start": settings.archive_start.isoformat(),
            "latest_record": state.latest_record_date(),
            "last_update": _public_run(runs[0]) if runs else None,
            "briefings": "unavailable" if not model_on else ("paused" if paused else "available"),
            "briefings_note": paused,
            "passages": idx.get("passages", 0),
            "meaning_search_coverage": round(idx["vectors"] / idx["passages"], 3) if idx.get("passages") else 0,
        }

    @app.get("/api/admin/usage")
    def usage(user=Depends(admin_user)):
        return {**summary(state), "visits": visit_summary(state), "alerts": alerts(state, settings.usage),
                "failures": recent_failures(state), "popular_questions": popular_questions(state)}

    @app.get("/api/admin/sync")
    def sync_log(user=Depends(admin_user)):
        return {"runs": state.runs(30)}

    # ---- web app -------------------------------------------------------------------
    @app.middleware("http")
    async def head_requests(request: Request, call_next):
        """HEAD (used by link checkers and search engines) answers like GET, without the body."""
        if request.method != "HEAD":
            return await call_next(request)
        request.scope["method"] = "GET"
        resp = await call_next(request)
        return Response(status_code=resp.status_code, headers=dict(resp.headers))

    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            f = (dist / path).resolve()
            if path and f.is_file() and f.is_relative_to(dist.resolve()):  # never serve outside the build
                return FileResponse(f)
            page = dist / f"{path.strip('/')}.html"  # static pages: /methodology -> methodology.html
            if path and "/" not in path.strip("/") and page.is_file() and page.name != "404.html":
                return FileResponse(page)
            if path.strip("/") in ("", "index.html"):
                return FileResponse(dist / "index.html")
            # anything else is not a page: say so, so search engines do not index it as one
            missing = dist / "404.html"
            return FileResponse(missing if missing.is_file() else dist / "index.html", status_code=404)

    return app
