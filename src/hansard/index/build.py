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
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from hansard.config import Settings
from hansard.embed.base import Embedder
from hansard.index.lance import FILTER_FIELDS, SearchIndex
from hansard.reference.profiles import ENRICH_SQL, attach_reference, office_columns
from hansard.store.parquet import read_partition_rows
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

    def index_keys(self, keys: list[tuple[str, str]], batch: int = 200, keep_vectors: bool = False) -> int:
        """(Re)index the given (source, key) files. Returns passages written.

        ``keep_vectors`` is for metadata-only refreshes (member data changed but
        the text did not): existing embeddings are kept and their filter
        columns updated, instead of being dropped for re-embedding.
        """
        max_words = int(self.settings.embedding.get("passage_words", 250))
        written = 0
        for i in range(0, len(keys), batch):
            part = keys[i:i + batch]
            records = self._records(part)
            rows = passage_rows(records, self._enrich(records), max_words) if records else []
            if keep_vectors:
                self.index.replace_keys([k for _, k in part], rows, drop_vectors=False)
                self.index.refresh_vector_metadata([k for _, k in part], rows)
            else:
                self.index.replace_keys([k for _, k in part], rows)
            self.state.mark_indexed(part)
            written += len(rows)
        return written

    def index_pending(self, batch: int = 200) -> int:
        keys = self.state.unindexed()
        if not keys:
            return 0
        t = time.time()
        n = self.index_keys(keys, batch)
        log.info("indexed %d files (%d passages) in %.0fs", len(keys), n, time.time() - t)
        return n

    def reenrich_people(self, person_ids: set[str]) -> int:
        """Refresh speaker columns for every passage by the given people."""
        if not person_ids:
            return 0
        from hansard.index.lance import sql_str

        tbl = self.index.passages()
        where = f"person_id IN ({', '.join(sql_str(p) for p in sorted(person_ids))})"
        keys = sorted({(r["source"], r["source_key"]) for r in
                       tbl.search().where(where).select(["source", "source_key"]).limit(None).to_list()})
        # Re-indexing those files recomputes every derived column consistently;
        # the text is unchanged, so embeddings are kept.
        self.index_keys(keys, keep_vectors=True)
        return len(keys)


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


def speaker_update_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_record: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in rows:
        by_record[r["record_id"]] = {k: r[k] for k, _ in FILTER_FIELDS if k in r}
    return by_record


__all__ = ["Indexer", "chunk_text", "embed_pending", "heading_of", "passage_rows", "Path"]
