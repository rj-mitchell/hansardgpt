"""Operational state in SQLite (WAL): file manifest, sync log, users, sessions, usage.

SQLite rather than DuckDB because the web app and the scheduled sync are
separate processes that both write here; DuckDB permits one writing process.
Analytical queries use DuckDB over the Parquet store instead.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS manifest (
    source      TEXT NOT NULL,
    key         TEXT NOT NULL,
    revision    TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime_ns    INTEGER NOT NULL,
    rows        INTEGER NOT NULL,
    parsed_at   TEXT NOT NULL,
    indexed_at  TEXT,
    PRIMARY KEY (source, key)
);
CREATE TABLE IF NOT EXISTS sync_log (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    stats       TEXT,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    at            TEXT NOT NULL,
    kind          TEXT NOT NULL,
    model         TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS usage_user_at ON usage(user_id, at);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StateDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connect() as con:
            con.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            self._local.con = con
        return con

    @contextmanager
    def connect(self):
        con = self._conn()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise

    # ---- manifest ------------------------------------------------------------
    def manifest(self) -> dict[tuple[str, str], sqlite3.Row]:
        with self.connect() as con:
            return {(r["source"], r["key"]): r for r in con.execute("SELECT * FROM manifest")}

    def upsert_manifest(self, row: dict[str, Any]) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO manifest (source, key, revision, file_name, size, mtime_ns, rows, parsed_at, indexed_at)
                   VALUES (:source, :key, :revision, :file_name, :size, :mtime_ns, :rows, :parsed_at, NULL)
                   ON CONFLICT(source, key) DO UPDATE SET revision=excluded.revision, file_name=excluded.file_name,
                     size=excluded.size, mtime_ns=excluded.mtime_ns, rows=excluded.rows,
                     parsed_at=excluded.parsed_at, indexed_at=NULL""",
                row,
            )

    def mark_indexed(self, keys: list[tuple[str, str]]) -> None:
        now = utcnow()
        with self.connect() as con:
            con.executemany("UPDATE manifest SET indexed_at=? WHERE source=? AND key=?",
                            [(now, s, k) for s, k in keys])

    def unindexed(self) -> list[tuple[str, str]]:
        with self.connect() as con:
            return [(r[0], r[1]) for r in con.execute(
                "SELECT source, key FROM manifest WHERE indexed_at IS NULL ORDER BY source, key")]

    # ---- sync log --------------------------------------------------------------
    def start_run(self, kind: str) -> int:
        with self.connect() as con:
            cur = con.execute("INSERT INTO sync_log (kind, started_at) VALUES (?, ?)", (kind, utcnow()))
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: dict[str, Any], error: str | None = None) -> None:
        with self.connect() as con:
            con.execute("UPDATE sync_log SET finished_at=?, status=?, stats=?, error=? WHERE run_id=?",
                        (utcnow(), "failed" if error else "ok", json.dumps(stats, default=str), error, run_id))

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM sync_log ORDER BY run_id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["stats"] = json.loads(d["stats"]) if d["stats"] else {}
            out.append(d)
        return out

    # ---- key/value -------------------------------------------------------------
    def get(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as con:
            row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))
