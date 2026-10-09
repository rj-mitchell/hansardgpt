"""Spend tracking and caps (every question costs money in model fees)."""

from __future__ import annotations

from datetime import UTC, datetime
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


def record_usage(state: StateDB, user_id: int | None, kind: str, model: str | None,
                 usage: dict[str, int] | None, prices: dict[str, Any]) -> float:
    cost = cost_usd(usage, prices)
    u = usage or {}
    with state.connect() as con:
        con.execute(
            """INSERT INTO usage (user_id, at, kind, model, input_tokens, output_tokens, cache_read_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, utcnow(), kind, model, u.get("input_tokens", 0), u.get("output_tokens", 0),
             u.get("cache_read_tokens", 0), cost))
    return cost


def check_caps(state: StateDB, user_id: int | None, limits: dict[str, Any]) -> str | None:
    """Return a human-readable reason if this user may not ask another question now."""
    now = datetime.now(UTC)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    with state.connect() as con:
        if user_id is not None:
            asked = con.execute("SELECT count(*) FROM usage WHERE user_id = ? AND kind = 'answer' AND at >= ?",
                                (user_id, day)).fetchone()[0]
            if asked >= int(limits.get("per_user_daily_questions", 60)):
                return "You have reached today's question limit. It resets at midnight UTC."
        spent = con.execute("SELECT coalesce(sum(cost_usd), 0) FROM usage WHERE at >= ?", (month,)).fetchone()[0]
    if spent >= float(limits.get("monthly_spend_cap_usd", 150.0)):
        return "This month's spending cap for AI answers has been reached. Source search still works."
    return None


def summary(state: StateDB) -> dict[str, Any]:
    month = datetime.now(UTC).strftime("%Y-%m")
    with state.connect() as con:
        rows = con.execute(
            """SELECT coalesce(u.email, '(system)'), count(*), round(sum(cost_usd), 4)
               FROM usage x LEFT JOIN users u ON u.user_id = x.user_id
               WHERE x.at >= ? GROUP BY 1 ORDER BY 3 DESC""", (month,)).fetchall()
    return {"month": month, "by_user": [{"email": r[0], "calls": r[1], "cost_usd": r[2]} for r in rows],
            "total_usd": round(sum(r[2] or 0 for r in rows), 4)}
