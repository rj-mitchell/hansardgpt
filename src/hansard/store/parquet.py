"""Columnar store: zstd Parquet, partitioned by source/house and year.

Layout under ``settings.parquet_dir``::

    records/source=<dir>/year=<yyyy>/<key>.parquet          recent sitting days
    records/source=<dir>/year=<yyyy>/compacted.parquet      older days, merged
    divisions/house=<house>/year=<yyyy>/...                 same scheme
    votes/house=<house>/year=<yyyy>/...

New and corrected sitting days are written as one file per *key* (one
scrapedxml file), replaced atomically, so a re-issued day never duplicates
rows. Days older than the compaction window are merged into one
``compacted.parquet`` per partition, sorted by date, which keeps multi-year
SQL sub-second (thousands of tiny files would cost seconds just to open). If a
correction arrives for an already-compacted day, that key's rows are removed
from the compacted file when its new per-key file is written.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute  # noqa: F401  (pa.compute)
import pyarrow.parquet as pq

RECORD_SCHEMA = pa.schema([
    ("record_id", pa.string()),
    ("source", pa.string()),
    ("source_key", pa.string()),
    ("revision", pa.string()),
    ("house", pa.string()),
    ("chamber", pa.string()),
    ("record_type", pa.string()),
    ("speech_type", pa.string()),
    ("date", pa.date32()),
    ("time", pa.string()),
    ("colnum", pa.string()),
    ("oral_heading", pa.string()),
    ("major_heading", pa.string()),
    ("minor_heading", pa.string()),
    ("bill", pa.string()),
    ("bill_session", pa.string()),
    ("xml_person_id", pa.string()),
    ("speaker_name_raw", pa.string()),
    ("uin", pa.string()),
    ("thread_id", pa.string()),
    ("text", pa.string()),
    ("context", pa.string()),
    ("official_url", pa.string()),
    ("url_kind", pa.string()),
    ("twfy_url", pa.string()),
])

DIVISION_SCHEMA = pa.schema([
    ("division_id", pa.string()),
    ("source_key", pa.string()),
    ("house", pa.string()),
    ("date", pa.date32()),
    ("number", pa.int32()),
    ("time", pa.string()),
    ("colnum", pa.string()),
    ("major_heading", pa.string()),
    ("minor_heading", pa.string()),
    ("ayes", pa.int32()),
    ("noes", pa.int32()),
    ("official_url", pa.string()),
    ("twfy_url", pa.string()),
])

VOTE_SCHEMA = pa.schema([
    ("division_id", pa.string()),
    ("date", pa.date32()),
    ("house", pa.string()),
    ("xml_person_id", pa.string()),
    ("vote", pa.string()),
    ("teller", pa.bool_()),
    ("proxy_person_id", pa.string()),
])


def _atomic_write(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(table, tmp, compression="zstd", row_group_size=50_000)
    tmp.replace(path)


def record_path(root: Path, source: str, year: int, key: str) -> Path:
    return root / "records" / f"source={source}" / f"year={year}" / f"{key}.parquet"


def write_records(root: Path, source: str, key: str, year: int, rows: Iterable[dict[str, Any]]) -> Path:
    path = record_path(root, source, year, key)
    table = pa.Table.from_pylist(list(rows), schema=RECORD_SCHEMA)
    _atomic_write(table, path)
    return path


def write_divisions(root: Path, house: str, key: str, year: int,
                    divisions: list[dict[str, Any]], votes: list[dict[str, Any]]) -> None:
    _atomic_write(pa.Table.from_pylist(divisions, schema=DIVISION_SCHEMA),
                  root / "divisions" / f"house={house}" / f"year={year}" / f"{key}.parquet")
    _atomic_write(pa.Table.from_pylist(votes, schema=VOTE_SCHEMA),
                  root / "votes" / f"house={house}" / f"year={year}" / f"{key}.parquet")


COMPACTED = "compacted.parquet"
TABLES = {"records": "source", "divisions": "house", "votes": "house"}


def partition_dir(root: Path, table: str, part: str, year: int) -> Path:
    return Path(root) / table / f"{TABLES[table]}={part}" / f"year={year}"


def remove_keys_from_compacted(root: Path, table: str, part: str, year: int, keys: set[str]) -> int:
    """Drop rows for ``keys`` from a partition's compacted file (after a late correction)."""
    path = partition_dir(root, table, part, year) / COMPACTED
    if not path.exists() or not keys:
        return 0
    if table == "votes":
        # votes carry no source_key; resolve via the partition's divisions
        div = partition_dir(root, "divisions", part, year)
        con = duckdb.connect()
        ids = [r[0] for r in con.execute(
            f"SELECT division_id FROM read_parquet('{div.as_posix()}/*.parquet') WHERE source_key IN "
            f"({', '.join('?' for _ in keys)})", list(keys)).fetchall()] if div.exists() else []
        keep_filter = pa.compute.invert(pa.compute.is_in(pq.read_table(path).column("division_id"),
                                                         value_set=pa.array(ids, pa.string())))
    else:
        keep_filter = pa.compute.invert(pa.compute.is_in(pq.read_table(path).column("source_key"),
                                                         value_set=pa.array(sorted(keys), pa.string())))
    table_data = pq.read_table(path)
    kept = table_data.filter(keep_filter)
    removed = table_data.num_rows - kept.num_rows
    if removed:
        _atomic_write(kept, path)
    return removed


def compact(root: Path, cutoff_year_month: str) -> dict[str, int]:
    """Merge per-key files older than ``cutoff`` (YYYY-MM-DD) into compacted.parquet per partition.

    Vote files are named after their divisions file, so the same date cut applies.
    """
    stats = {"partitions": 0, "files_merged": 0}
    for table in ("records", "divisions", "votes"):
        base = Path(root) / table
        if not base.exists():
            continue
        for part_dir in sorted(base.glob("*=*/year=*")):
            files = [f for f in part_dir.glob("*.parquet") if f.name != COMPACTED and f.stem[-10:] < cutoff_year_month]
            if not files:
                continue
            existing = part_dir / COMPACTED
            tables = [pq.read_table(f) for f in files]
            if existing.exists():
                tables.insert(0, pq.read_table(existing))
            merged = pa.concat_tables(tables, promote_options="default")
            sort_cols = [c for c in ("date", "source_key", "division_id") if c in merged.column_names]
            merged = merged.sort_by([(c, "ascending") for c in sort_cols])
            pq.write_table(merged, part_dir / f".{COMPACTED}.tmp", compression="zstd", row_group_size=100_000)
            (part_dir / f".{COMPACTED}.tmp").replace(existing)
            for f in files:
                f.unlink()
            stats["partitions"] += 1
            stats["files_merged"] += len(files)
    return stats


def read_partition_rows(con: duckdb.DuckDBPyConnection, root: Path, table: str, part: str, year: int,
                        where: str, params: list | None = None) -> list[dict[str, Any]]:
    d = partition_dir(root, table, part, year)
    if not d.exists() or not any(d.glob("*.parquet")):
        return []
    rel = con.execute(f"SELECT * FROM read_parquet('{d.as_posix()}/*.parquet', union_by_name = true) WHERE {where}",
                      params or [])
    cols = [c[0] for c in rel.description]
    return [dict(zip(cols, row, strict=True)) for row in rel.fetchall()]


def attach_store(con: duckdb.DuckDBPyConnection, root: Path) -> list[str]:
    """Create ``records``, ``divisions`` and ``votes`` views over the Parquet tree."""
    created = []
    for name in ("records", "divisions", "votes"):
        base = Path(root) / name
        if any(base.glob("**/*.parquet")):
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{base.as_posix()}/**/*.parquet', "
                "hive_partitioning = true, union_by_name = true)")
            created.append(name)
    return created
