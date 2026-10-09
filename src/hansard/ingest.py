"""Parse the local XML mirror into the Parquet store, incrementally.

Only files whose latest revision, size or mtime differ from the manifest are
parsed. Work is spread over a bounded process pool; each worker streams one
file at a time and recycles after ``max_tasks_per_child`` files, so peak memory
is (workers x one file's working set), far below the 4 GB budget.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hansard.config import Settings
from hansard.parse.xml_stream import parse_divisions, parse_file
from hansard.sources.twfy import SOURCES, RemoteFile, local_files
from hansard.store.parquet import remove_keys_from_compacted, write_divisions, write_records
from hansard.store.state import StateDB, utcnow

log = logging.getLogger(__name__)

DIVISION_DIRS = {"divisionsonly", "lordsdivisionsonly"}


@dataclass
class IngestStats:
    files_seen: int = 0
    files_parsed: int = 0
    files_new: int = 0
    files_revised: int = 0
    records: int = 0
    divisions: int = 0
    votes: int = 0
    errors: list[str] = field(default_factory=list)
    changed_keys: list[tuple[str, str]] = field(default_factory=list)
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["changed_keys"] = len(self.changed_keys)
        return d


def _parse_one(path_str: str, directory: str, out_root: str) -> dict[str, Any]:
    path, out = Path(path_str), Path(out_root)
    f = local_meta(path, directory)
    if directory in DIVISION_DIRS:
        divisions, votes = parse_divisions(path, directory)
        write_divisions(out, SOURCES[directory][0], f.key, f.file_date.year, divisions, votes)
        return {"rows": len(divisions), "divisions": len(divisions), "votes": len(votes)}
    rows = list(parse_file(path, directory))
    write_records(out, directory, f.key, f.file_date.year, rows)
    return {"rows": len(rows)}


def local_meta(path: Path, directory: str) -> RemoteFile:
    from hansard.sources.twfy import parse_name

    meta = parse_name(directory, path.name)
    if meta is None:
        raise ValueError(f"unrecognised file {path}")
    return meta


def ingest(settings: Settings, *, workers: int = 3, since=None, until=None,
           directories: list[str] | None = None, state: StateDB | None = None) -> IngestStats:
    started = time.time()
    state = state or StateDB(settings.state_db)
    dirs = directories or [*settings.record_dirs, *sorted(DIVISION_DIRS)]
    files = local_files(settings.raw_xml_dir, dirs, since or settings.archive_start)
    if until is not None:
        files = [f for f in files if f.file_date <= until]
    manifest = state.manifest()
    stats = IngestStats(files_seen=len(files))
    todo: list[tuple[RemoteFile, Path, int, int]] = []
    for f in files:
        p = settings.raw_xml_dir / f.rel_path
        st = p.stat()
        prev = manifest.get((f.directory, f.key))
        if prev and prev["revision"] == f.revision and prev["size"] == st.st_size and prev["mtime_ns"] == st.st_mtime_ns:
            continue
        todo.append((f, p, st.st_size, st.st_mtime_ns))
        if prev is None:
            stats.files_new += 1
        else:
            stats.files_revised += 1

    if todo:
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=max(1, workers), mp_context=ctx, max_tasks_per_child=200) as pool:
            futures = {pool.submit(_parse_one, str(p), f.directory, str(settings.parquet_dir)): (f, size, mtime)
                       for f, p, size, mtime in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                f, size, mtime = futures[fut]
                try:
                    res = fut.result()
                except Exception as exc:  # keep going; record the failure
                    stats.errors.append(f"{f.rel_path}: {exc!r}")
                    log.warning("parse failed for %s: %r", f.rel_path, exc)
                    continue
                stats.files_parsed += 1
                if f.directory in DIVISION_DIRS:
                    stats.divisions += res["divisions"]
                    stats.votes += res["votes"]
                else:
                    stats.records += res["rows"]
                    stats.changed_keys.append((f.directory, f.key))
                state.upsert_manifest({
                    "source": f.directory, "key": f.key, "revision": f.revision, "file_name": f.name,
                    "size": size, "mtime_ns": mtime, "rows": res["rows"], "parsed_at": utcnow(),
                })
                if i % 500 == 0:
                    log.info("parsed %d/%d files", i, len(todo))
    # A correction to an already-compacted day: drop that day's old rows from the
    # compacted file now that its new per-key file exists (serially, in this process).
    by_partition: dict[tuple[str, str, int], set[str]] = {}
    for f, _, _, _ in todo:
        if f.directory in DIVISION_DIRS:
            house = SOURCES[f.directory][0]
            by_partition.setdefault(("divisions", house, f.file_date.year), set()).add(f.key)
            by_partition.setdefault(("votes", house, f.file_date.year), set()).add(f.key)
        else:
            by_partition.setdefault(("records", f.directory, f.file_date.year), set()).add(f.key)
    for (table, part, year), keys in sorted(by_partition.items(), key=lambda kv: kv[0][0] != "votes"):
        remove_keys_from_compacted(settings.parquet_dir, table, part, year, keys)
    stats.seconds = round(time.time() - started, 1)
    return stats
