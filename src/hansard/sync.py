"""Daily incremental synchronisation.

1. Member data: ``git pull`` parlparse ``members/``; if the commit changed,
   rebuild the reference tables and work out exactly which people changed
   (offices, seats, parties, names). Only their passages are re-enriched, and
   their embeddings are kept because the text has not changed.
2. Hansard: mirror new and corrected scrapedxml files (rsync or HTTPS).
3. Ingest new/changed files into Parquet (corrections replace their day).
4. Index the changed files for keyword search; merge into the BM25 index.
5. Embed new passages within a time budget (the rest continues next run).
6. Compact Parquet days older than the correction window.
7. Record timings and counts in ``sync_log``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import time
import traceback
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from hansard.config import STATIC_DIR, Settings
from hansard.index.build import Indexer, embed_pending
from hansard.index.lance import SearchIndex
from hansard.ingest import ingest
from hansard.reference.build import ReferenceData, build_reference, write_reference
from hansard.store.parquet import compact
from hansard.store.state import StateDB

log = logging.getLogger(__name__)

COMPACT_AFTER_DAYS = 90
PERSON_TABLES = ("names", "memberships", "offices")


def _person_fingerprints(rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    acc: dict[str, list[str]] = defaultdict(list)
    for table, rows in rows_by_table.items():
        for r in rows:
            pid = r.get("person_id")
            if pid:
                acc[pid].append(table + json.dumps(r, sort_keys=True, default=str))
    return {pid: hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest() for pid, parts in acc.items()}


def changed_people(old_dir: Path, new: ReferenceData) -> set[str]:
    """People whose names, memberships or offices differ between two reference builds."""
    old_rows: dict[str, list[dict[str, Any]]] = {}
    for t in PERSON_TABLES:
        f = old_dir / f"{t}.parquet"
        old_rows[t] = pq.read_table(f).to_pylist() if f.exists() else []
    if not any(old_rows.values()):
        return set()  # first build: everything is new and will be indexed anyway
    new_rows = {t: getattr(new, t) for t in PERSON_TABLES}
    a, b = _person_fingerprints(old_rows), _person_fingerprints(new_rows)
    return {p for p in a.keys() | b.keys() if a.get(p) != b.get(p)}


def refresh_reference(settings: Settings, state: StateDB, members_dir: Path | None) -> dict[str, Any]:
    from hansard.sources import parlparse

    sha = None
    if members_dir is None:
        sha = parlparse.ensure_checkout(settings.sources["parlparse_repo"], settings.parlparse_dir,
                                        settings.sources.get("parlparse_branch", "master"))
        members_dir = parlparse.members_dir(settings.parlparse_dir)
        if sha == state.get("parlparse_sha") and (settings.reference_dir / "persons.parquet").exists():
            return {"parlparse_sha": sha, "reference_changed": False, "people_changed": []}
    ref = build_reference(members_dir, STATIC_DIR / "geo" / "constituencies.csv",
                          Path(settings.config_path).parent / "overrides" / "constituency_names.csv")
    people = changed_people(settings.reference_dir, ref)
    # write to a temporary directory, then swap, so readers never see a half-written set
    tmp = Path(tempfile.mkdtemp(prefix=".reference-", dir=settings.reference_dir.parent))
    write_reference(ref, tmp)
    if settings.reference_dir.exists():
        old = settings.reference_dir.with_name(".reference-old")
        shutil.rmtree(old, ignore_errors=True)
        settings.reference_dir.rename(old)
        tmp.rename(settings.reference_dir)
        shutil.rmtree(old, ignore_errors=True)
    else:
        tmp.rename(settings.reference_dir)
    if sha:
        state.set("parlparse_sha", sha)
    return {"parlparse_sha": sha, "reference_changed": True, "people_changed": sorted(people),
            "unmatched_seats": ref.stats.get("unmatched_seats_since_2010", [])}


def run_sync(settings: Settings, *, fetch: bool = True, embed_minutes: float | None = 60.0,
             members_dir: Path | None = None, embedder=None, workers: int = 3,
             today: date | None = None) -> dict[str, Any]:
    state = StateDB(settings.state_db)
    run_id = state.start_run("sync")
    started = time.time()
    stats: dict[str, Any] = {}
    try:
        t = time.time()
        stats["reference"] = refresh_reference(settings, state, members_dir)
        stats["reference"]["seconds"] = round(time.time() - t, 1)

        if fetch:
            from hansard.cli import fetch_xml

            t = time.time()
            stats["fetch"] = {**fetch_xml(settings), "seconds": round(time.time() - t, 1)}

        ing = ingest(settings, workers=workers, state=state)
        stats["ingest"] = ing.as_dict()

        idx = SearchIndex(settings.index_dir, int(settings.embedding.get("dim", 384)))
        indexer = Indexer(settings, idx, state)
        t = time.time()
        first_build = not idx.has_data()
        passages = indexer.index_pending()
        people = set(stats["reference"].get("people_changed") or [])
        reenriched = indexer.reenrich_people(people) if people and not first_build else 0
        if first_build and passages:
            idx.build_indices()
        elif passages or reenriched:
            idx.optimize()  # merges new rows into the BM25 and scalar indices incrementally
        stats["index"] = {"passages_written": passages, "files_reenriched": reenriched,
                          "people_reenriched": len(people), "seconds": round(time.time() - t, 1), **idx.stats()}

        if embed_minutes is None or embed_minutes > 0:
            from hansard.embed.base import get_embedder

            t = time.time()
            emb = embedder or get_embedder(settings)
            n = embed_pending(settings, idx, state, emb,
                              max_seconds=embed_minutes * 60 if embed_minutes else None)
            stats["embed"] = {"passages_embedded": n, "files_remaining": len(state.unembedded()),
                              "seconds": round(time.time() - t, 1)}

        t = time.time()
        cutoff = ((today or date.today()) - timedelta(days=COMPACT_AFTER_DAYS)).isoformat()
        stats["compact"] = {**compact(settings.parquet_dir, cutoff), "seconds": round(time.time() - t, 1)}
        stats["seconds"] = round(time.time() - started, 1)
        state.finish_run(run_id, stats)
    except Exception as exc:
        stats["seconds"] = round(time.time() - started, 1)
        stats["error"] = f"{type(exc).__name__}: {exc}"
        log.error("sync failed: %s", traceback.format_exc())
        state.finish_run(run_id, stats, error=stats["error"])
    return stats
