"""Columnar store: zstd Parquet, one file per source file key, partitioned by year.

Layout under ``settings.parquet_dir``::

    records/source=<dir>/year=<yyyy>/<key>.parquet
    divisions/house=<house>/year=<yyyy>/<key>.parquet
    votes/house=<house>/year=<yyyy>/<key>.parquet

A corrected Hansard revision replaces its key's file atomically (write to a
temporary name, then rename), so a re-issued sitting day never duplicates rows.
DuckDB reads the tree with hive partitioning for multi-year SQL.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
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
