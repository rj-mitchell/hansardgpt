"""Build data_static/geo/constituencies.csv from mySociety's 2025-constituencies repo.

Usage:
    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/mysociety/2025-constituencies /tmp/2025-constituencies
    git -C /tmp/2025-constituencies sparse-checkout set data/packages data/raw/external
    uv run python scripts/build_geo_lookups.py /tmp/2025-constituencies

Output: one row per Westminster constituency per boundary set, with its ONS
GSS code, ITL1 region (English regions, plus Scotland / Wales / Northern Ireland)
and validity interval:

* 2010 set (ONS "Westminster Parliamentary Constituencies (Dec 2021)", the
  2010-2024 boundaries): valid 2010-05-06 .. 2024-07-03 (Scotland's 59 seats were
  first used in 2005; the archive starts in 2010 so 2010-05-06 is used).
* 2024 set (mySociety parl_constituencies_2025): valid 2024-07-04 .. 9999-12-31.

Regions for 2010-set seats come from the 2024 seats they overlap. The script
asserts every 2010 seat overlaps seats in exactly one region (true for the
current data: English regions were respected by both boundary reviews).

Source data: ONS (Open Government Licence v3.0) via mySociety.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import duckdb

ITL1 = {
    "Eastern": "East of England",
    "Yorkshire and the Humber": "Yorkshire and The Humber",
}

OUT = Path(__file__).resolve().parents[1] / "data_static" / "geo" / "constituencies.csv"


def main(repo: Path) -> None:
    pkg = repo / "data" / "packages"
    c25 = pkg / "parliament_con_2025" / "parl_constituencies_2025.parquet"
    ov = pkg / "geographic_overlaps" / "PARL10_PARL25_combo_overlap.parquet"
    c21 = repo / "data" / "raw" / "external" / "Westminster_Parliamentary_Constituencies_(Dec_2021)_UK_BFC.parquet"
    con = duckdb.connect()
    con.execute(f"create view c25 as select short_code, gss_code, name as cname, nation, region from '{c25}'")
    con.execute(f"create view ov as select * from '{ov}'")
    con.execute(f"create view c21 as select PCON21CD as gss, PCON21NM as cname from '{c21}'")

    spans = con.execute(
        """select o.PARL10, list(distinct c.region) from ov o join c25 c on c.short_code = o.PARL25
           where o.percentage_overlap_area > 0.01 group by 1 having len(list(distinct c.region)) <> 1"""
    ).fetchall()
    if spans:
        raise SystemExit(f"2010 seats overlapping several regions: {spans[:5]}")

    old = con.execute(
        """with best as (
             select o.PARL10 gss, arg_max(c.region, o.percentage_overlap_area) region,
                    arg_max(c.nation, o.percentage_overlap_area) nation
             from ov o join c25 c on c.short_code = o.PARL25 group by 1)
           select c21.gss, c21.cname, best.region, best.nation
           from c21 join best on best.gss = c21.gss order by c21.cname"""
    ).fetchall()
    new = con.execute("select gss_code, cname, region, nation from c25 order by cname").fetchall()
    if len(old) != 650 or len(new) != 650:
        raise SystemExit(f"expected 650 + 650 seats, got {len(old)} + {len(new)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["gss_code", "name", "region", "nation", "boundary_set", "valid_from", "valid_to"])
        for gss, name, region, nation in old:
            w.writerow([gss, name, ITL1.get(region, region), nation, "2010", "2010-05-06", "2024-07-03"])
        for gss, name, region, nation in new:
            w.writerow([gss, name, ITL1.get(region, region), nation, "2024", "2024-07-04", "9999-12-31"])
    print(f"wrote {OUT} ({len(old)} + {len(new)} seats)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
