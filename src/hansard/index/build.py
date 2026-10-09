"""Turn Parquet records into search-index passages, and embed them.

``index_keys``   records -> speaker-enriched passages -> ``passages`` table (BM25)
``embed_pending`` passages without vectors -> ``vectors`` table, newest first,
                  resumable at file granularity (progress kept in the manifest)
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Any

import duckdb
import pyarrow as pa

from hansard.config import Settings
from hansard.embed.base import Embedder
from hansard.index.lance import FILTER_FIELDS, PASSAGE_SCHEMA, VECTORS, SearchIndex, sql_str
from hansard.reference.profiles import ENRICH_SQL, attach_reference, office_columns
from hansard.store.parquet import attach_store, read_partition_rows
from hansard.store.state import StateDB

log = logging.getLogger(__name__)

SKIP_TYPES = {"procedural"}
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, max_words: int = 250) -> list[str]:
    """Split on paragraph boundaries into passages of at most ~max_words words."""
    chunks: list[str] = []
    current: list[str] = []
    count = 0

    def flush():
        nonlocal current, count
        if current:
            chunks.append("\n\n".join(current))
        current, count = [], 0

    for para in [p for p in text.split("\n\n") if p.strip()]:
        words = len(para.split())
        if words > max_words:
            flush()
            sentence_buf: list[str] = []
            n = 0
            for sent in _SENTENCE.split(para):
                w = len(sent.split())
                if n + w > max_words and sentence_buf:
                    chunks.append(" ".join(sentence_buf))
                    sentence_buf, n = [], 0
                sentence_buf.append(sent)
                n += w
            if sentence_buf:
                chunks.append(" ".join(sentence_buf))
            continue
        if count + words > max_words:
            flush()
        current.append(para)
        count += words
    flush()
    return chunks or [text]


def heading_of(r: dict[str, Any]) -> str:
    parts = [r.get("bill"), r.get("major_heading"), r.get("minor_heading")]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return " — ".join(seen)


def passage_rows(records: list[dict[str, Any]], enrich: dict[str, dict[str, Any]],
                 max_words: int) -> list[dict[str, Any]]:
    out = []
    for r in records:
        if r["record_type"] in SKIP_TYPES:
            continue
        e = enrich.get(r["record_id"], {})
        offices = office_columns(e.get("offices") or [])
        heading = heading_of(r)
        for i, chunk in enumerate(chunk_text(r["text"], max_words)):
            lead = f"Question: {r['context']}\n\nAnswer: " if (i == 0 and r.get("context")) else ""
            out.append({
                "passage_id": f"{r['record_id']}#{i}",
                "record_id": r["record_id"],
                "source": r["source"],
                "source_key": r["source_key"],
                "record_type": r["record_type"],
                "house": r["house"],
                "date": r["date"],
                "year": r["date"].year,
                "person_id": e.get("person_id"),
                "party_id": e.get("party_id"),
                "region": e.get("region"),
                **offices,
                "chunk": i,
                "chamber": r["chamber"],
                "speaker_name": e.get("speaker_name") or r.get("speaker_name_raw"),
                "party": e.get("party_name"),
                "constituency": e.get("constituency"),
                "member_house": e.get("member_house"),
                "heading": heading,
                "text": chunk,
                "search_text": f"{heading}\n{lead}{chunk}",
            })
    return out


class Indexer:
    def __init__(self, settings: Settings, index: SearchIndex, state: StateDB):
        self.settings = settings
        self.index = index
        self.state = state
        self.con = duckdb.connect()
        attach_reference(self.con, settings.reference_dir)

    def _records(self, keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
        by_part: dict[tuple[str, int], list[str]] = defaultdict(list)
        for source, key in keys:
            by_part[(source, int(key[-10:-6]))].append(key)
        out: list[dict[str, Any]] = []
        for (source, year), ks in by_part.items():
            out.extend(read_partition_rows(self.con, self.settings.parquet_dir, "records", source, year,
                                           f"source_key IN ({', '.join('?' for _ in ks)})", ks))
        return out

    def _enrich(self, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        keep = [r for r in records if r["record_type"] not in SKIP_TYPES]
        staged = pa.table({
            "record_id": pa.array([r["record_id"] for r in keep], pa.string()),
            "xml_person_id": pa.array([r["xml_person_id"] for r in keep], pa.string()),
            "date": pa.array([r["date"] for r in keep], pa.date32()),
        })
        self.con.register("recs", staged)  # zero-copy Arrow scan; executemany is far too slow here
        rel = self.con.sql(ENRICH_SQL)
        cols = rel.columns
        return {row[0]: dict(zip(cols, row, strict=True)) for row in rel.fetchall()}

    def _copies(self, sources: set[str], record_ids: list[str]) -> dict[str, tuple[str, list[str]]]:
        """For records held in more than one file: record_id -> (newest file's key, every key).

        TWFY republishes corrected written answers in a later day's file under the
        same ID (about 37k since 2010); like TWFY itself, only the newest copy counts.
        """
        globs = [f"'{d.as_posix()}/**/*.parquet'" for d in
                 (self.settings.parquet_dir / "records" / f"source={s}" for s in sorted(sources))
                 if any(d.glob("**/*.parquet"))]
        if not globs or not record_ids:
            return {}
        self.con.register("batch_ids", pa.table({"record_id": pa.array(sorted(set(record_ids)), pa.string())}))
        rows = self.con.execute(f"""
            SELECT r.record_id, arg_max(r.source_key, strftime(r.date, '%Y-%m-%d') || r.source_key),
                   list(DISTINCT r.source_key)
            FROM read_parquet([{', '.join(globs)}], union_by_name = true) r
            SEMI JOIN batch_ids b ON r.record_id = b.record_id
            GROUP BY r.record_id HAVING count(DISTINCT r.source_key) > 1""").fetchall()
        self.con.unregister("batch_ids")
        return {r[0]: (r[1], r[2]) for r in rows}

    def _newest_copies(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        """Keep one copy of each record: the first in its file, from the newest file holding it.

        Returns the records to index, and the (record_id, source_key) copies in
        files outside this batch that a copy here supersedes.
        """
        seen: set[tuple[str, str]] = set()
        unique = []
        for r in records:  # parlparse occasionally repeats an ID within one file; keep the first
            if (r["record_id"], r["source_key"]) not in seen:
                seen.add((r["record_id"], r["source_key"]))
                unique.append(r)
        copies = self._copies({r["source"] for r in unique}, [r["record_id"] for r in unique])
        keep = [r for r in unique if copies.get(r["record_id"], (r["source_key"],))[0] == r["source_key"]]
        batch_keys = {r["source_key"] for r in unique}
        stale = sorted({(rid, k) for rid, (newest, keys) in copies.items() if newest in batch_keys
                        for k in keys if k != newest and k not in batch_keys})
        return keep, stale

    def index_keys(self, keys: list[tuple[str, str]], batch: int = 200) -> int:
        """(Re)index the given (source, key) files, dropping their old vectors. Returns passages written."""
        max_words = int(self.settings.embedding.get("passage_words", 250))
        written = 0
        for i in range(0, len(keys), batch):
            part = keys[i:i + batch]
            records, stale = self._newest_copies(self._records(part))
            rows = passage_rows(records, self._enrich(records), max_words) if records else []
            self.index.replace_keys([k for _, k in part], rows)
            if stale:
                self.index.delete_copies(stale)
            self.state.mark_indexed(part)
            written += len(rows)
        return written

    def dedupe(self) -> dict[str, int]:
        """One-off clean-up of an index built before older copies were dropped at index time."""
        attach_store(self.con, self.settings.parquet_dir)
        stale = self.con.execute("""
            WITH c AS (SELECT record_id, source_key, date FROM records GROUP BY ALL),
                 n AS (SELECT record_id, arg_max(source_key, strftime(date, '%Y-%m-%d') || source_key) newest
                       FROM c GROUP BY record_id HAVING count(*) > 1)
            SELECT c.record_id, c.source_key FROM c JOIN n USING (record_id) WHERE c.source_key <> n.newest
            ORDER BY 1, 2""").fetchall()
        self.index.delete_copies([(r[0], r[1]) for r in stale])
        repeated = self.con.execute("""
            SELECT DISTINCT source, source_key FROM records
            GROUP BY source, source_key, record_id HAVING count(*) > 1 ORDER BY 1, 2""").fetchall()
        self.index_keys([(r[0], r[1]) for r in repeated])
        return {"stale_copies_deleted": len(stale), "files_reindexed": len(repeated)}

    def index_pending(self, batch: int = 200) -> int:
        keys = self.state.unindexed()
        if not keys:
            return 0
        t = time.time()
        n = self.index_keys(keys, batch)
        log.info("indexed %d files (%d passages) in %.0fs", len(keys), n, time.time() - t)
        return n

    def reenrich_people(self, person_ids: set[str], batch: int = 50) -> int:
        """Refresh speaker columns in place for every passage by the given people.

        Text and embeddings are untouched (member data changed, Hansard did not).
        The distinct (person, date) pairs are enriched once, and the new speaker
        columns are written with one partial-column merge per table per batch,
        keyed on passage_id. Returns the number of passages updated.
        """
        if not person_ids:
            return 0
        tbl = self.index.passages()
        has_vectors = VECTORS in self.index._names()
        speaker_cols = ["speaker_name", "party", "party_id", "region", "constituency", "member_house",
                        "is_gov", "is_shadow", "is_chair", "gov_portfolios", "shadow_portfolios", "chair_portfolios"]
        vector_cols = [c for c in speaker_cols if c in {name for name, _ in FILTER_FIELDS}]
        updated = 0
        people = sorted(person_ids)
        for i in range(0, len(people), batch):
            part = people[i:i + batch]
            rows = tbl.search().where(f"person_id IN ({', '.join(sql_str(p) for p in part)})") \
                .select(["passage_id", "person_id", "date"]).limit(None).to_arrow()
            if rows.num_rows == 0:
                continue
            pids, persons, dates = (rows.column(c).to_pylist() for c in ("passage_id", "person_id", "date"))
            uniq = sorted(set(zip(persons, dates, strict=True)))
            self.con.register("recs", pa.table({
                "record_id": pa.array([f"{p}|{d.isoformat()}" for p, d in uniq], pa.string()),
                "xml_person_id": pa.array([p for p, _ in uniq], pa.string()),
                "date": pa.array([d for _, d in uniq], pa.date32()),
            }))
            rel = self.con.sql(ENRICH_SQL)
            cols = rel.columns
            values: dict[str, dict[str, Any]] = {}
            for row in rel.fetchall():
                e = dict(zip(cols, row, strict=True))
                values[e["record_id"]] = {
                    "speaker_name": e["speaker_name"], "party": e["party_name"], "party_id": e["party_id"],
                    "region": e["region"], "constituency": e["constituency"], "member_house": e["member_house"],
                    **office_columns(e["offices"] or []),
                }
            out = {c: [] for c in ["passage_id", *speaker_cols]}
            for pid, person, d in zip(pids, persons, dates, strict=True):
                v = values.get(f"{person}|{d.isoformat()}")
                if v is None:
                    continue
                out["passage_id"].append(pid)
                for c in speaker_cols:
                    out[c].append(v[c])
            schema = pa.schema([PASSAGE_SCHEMA.field(c) for c in ["passage_id", *speaker_cols]])
            table = pa.Table.from_pydict(out, schema=schema)
            tbl.merge_insert("passage_id").when_matched_update_all().execute(table)
            if has_vectors:
                self.index.vectors().merge_insert("passage_id").when_matched_update_all().execute(
                    table.select(["passage_id", *vector_cols]))
            updated += table.num_rows
        return updated


def embed_pending(settings: Settings, index: SearchIndex, state: StateDB, embedder: Embedder, *,
                  max_files: int | None = None, max_seconds: float | None = None, batch_files: int = 20) -> int:
    """Embed passages of indexed-but-unembedded files, newest first. Returns passages embedded."""
    keys = state.unembedded(newest_first=True)
    if max_files is not None:
        keys = keys[:max_files]
    started = time.time()
    total = 0
    for i in range(0, len(keys), batch_files):
        part = keys[i:i + batch_files]
        rows = index.rows_for_keys([k for _, k in part])
        texts = [f"{r['heading']}: {r['search_text'].split(chr(10), 1)[-1]}" if r["heading"] else r["search_text"]
                 for r in rows]
        vecs = embedder.embed_documents(texts)
        index.add_vectors([k for _, k in part], rows, vecs)
        state.mark_embedded(part)
        total += len(rows)
        elapsed = time.time() - started
        log.info("embedded %d passages (%d/%d files, %.1f/s)", total, i + len(part), len(keys),
                 total / max(elapsed, 1e-6))
        if max_seconds is not None and elapsed > max_seconds:
            break
    return total


__all__ = ["Indexer", "chunk_text", "embed_pending", "heading_of", "passage_rows"]
