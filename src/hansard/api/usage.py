"""Spend tracking, caps and the answer cache (every model-written briefing costs money).

The site is public, so limits apply per visitor as well as overall. A visitor is
identified by a salted hash of their IP address; the address itself is never stored.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

from hansard.store.state import StateDB, utcnow


def cost_usd(usage: dict[str, int] | None, prices: dict[str, Any]) -> float:
    if not usage:
        return 0.0
    return round(
        usage.get("input_tokens", 0) / 1e6 * float(prices.get("price_input_per_mtok", 4.0))
        + usage.get("output_tokens", 0) / 1e6 * float(prices.get("price_output_per_mtok", 20.0))
        + usage.get("cache_read_tokens", 0) / 1e6 * float(prices.get("price_cache_read_per_mtok", 0.4)),
        6,
    )


def visitor_key(state: StateDB, address: str | None) -> str:
    salt = state.get("visitor_salt")
    if salt is None:
        state.set("visitor_salt", secrets.token_hex(16))
        salt = state.get("visitor_salt")
    return hashlib.sha256(f"{salt}|{address or '-'}".encode()).hexdigest()[:24]


def record_usage(state: StateDB, user_id: int | None, kind: str, model: str | None,
                 usage: dict[str, int] | None, prices: dict[str, Any], visitor: str | None = None) -> float:
    cost = cost_usd(usage, prices)
    u = usage or {}
    with state.connect() as con:
        con.execute(
            """INSERT INTO usage (user_id, visitor, at, kind, model, input_tokens, output_tokens,
                                  cache_read_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, visitor, utcnow(), kind, model, u.get("input_tokens", 0), u.get("output_tokens", 0),
             u.get("cache_read_tokens", 0), cost))
    return cost


def check_caps(state: StateDB, user_id: int | None, limits: dict[str, Any], visitor: str | None = None) -> str | None:
    """Return a plain-English reason if this person may not have another briefing written now."""
    now = datetime.now(UTC)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    with state.connect() as con:
        if user_id is not None:
            asked = con.execute("SELECT count(*) FROM usage WHERE user_id = ? AND kind = 'answer' AND at >= ?",
                                (user_id, day)).fetchone()[0]
            if asked >= int(limits.get("per_user_daily_questions", 60)):
                return "You have reached today's question limit. It resets at midnight UTC."
        elif visitor is not None:
            asked = con.execute("SELECT count(*) FROM usage WHERE visitor = ? AND kind = 'answer' AND at >= ?",
                                (visitor, day)).fetchone()[0]
            if asked >= int(limits.get("per_visitor_daily_questions", 15)):
                return ("You have reached today's limit for new briefings. It resets at midnight UTC; "
                        "briefings others have already asked for still load.")
        spent_today = con.execute("SELECT coalesce(sum(cost_usd), 0) FROM usage WHERE at >= ?", (day,)).fetchone()[0]
        spent_month = con.execute("SELECT coalesce(sum(cost_usd), 0) FROM usage WHERE at >= ?", (month,)).fetchone()[0]
    if spent_today >= float(limits.get("daily_spend_cap_usd", 10.0)):
        return "Today's budget for new briefings has been used up. It resets at midnight UTC."
    if spent_month >= float(limits.get("monthly_spend_cap_usd", 150.0)):
        return "This month's budget for new briefings has been used up."
    return None


class RateLimiter:
    """At most ``per_minute`` requests per key in any rolling minute (in memory, per process)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            if len(self.hits) > 50_000:  # forget idle visitors
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                    del self.hits[k]
            return True


# ---- answer cache ---------------------------------------------------------------------

def cache_key(parts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def cached_events(state: StateDB, key: str, hours: float) -> list[dict[str, Any]] | None:
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with state.connect() as con:
        row = con.execute("SELECT events FROM answer_cache WHERE key = ? AND created_at >= ?", (key, since)).fetchone()
    return json.loads(row[0]) if row else None


def store_events(state: StateDB, key: str, events: list[dict[str, Any]], hours: float) -> None:
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with state.connect() as con:
        con.execute("DELETE FROM answer_cache WHERE created_at < ?", (since,))
        con.execute("INSERT OR REPLACE INTO answer_cache (key, created_at, events) VALUES (?, ?, ?)",
                    (key, utcnow(), json.dumps(events, default=str)))


def summary(state: StateDB) -> dict[str, Any]:
    month = datetime.now(UTC).strftime("%Y-%m")
    with state.connect() as con:
        rows = con.execute(
            """SELECT coalesce(u.email, CASE WHEN x.visitor IS NULL THEN '(system)' ELSE '(public)' END),
                      count(*), round(sum(cost_usd), 4), count(DISTINCT x.visitor)
               FROM usage x LEFT JOIN users u ON u.user_id = x.user_id
               WHERE x.at >= ? GROUP BY 1 ORDER BY 3 DESC""", (month,)).fetchall()
    return {"month": month,
            "by_user": [{"email": r[0], "calls": r[1], "cost_usd": r[2], "visitors": r[3]} for r in rows],
            "total_usd": round(sum(r[2] or 0 for r in rows), 4)}
