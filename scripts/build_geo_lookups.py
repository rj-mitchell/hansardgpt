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

Seat type (``settlement``), used to compare e.g. big-city and rural MPs:

* ``city``  - most of the seat's population lives in London or a major city
              council area (the Core Cities, plus Edinburgh);
* ``rural`` - population density below RURAL_DENSITY people per km2;
* ``town``  - everything else (towns, suburbs and smaller cities).

``main_area`` is the local authority holding most of the seat's population.

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

# Core Cities UK members plus Edinburgh; every London borough also counts as "city".
MAJOR_CITY_AREAS = {
    "Belfast", "Birmingham", "Bristol, City of", "Cardiff", "Glasgow City", "Leeds", "Liverpool",
    "Manchester", "Newcastle upon Tyne", "Nottingham", "Sheffield", "City of Edinburgh",
}
RURAL_DENSITY = 250  # people per km2


def main(repo: Path) -> None:
    pkg = repo / "data" / "packages"
    c25 = pkg / "parliament_con_2025" / "parl_constituencies_2025.parquet"
    ov = pkg / "geographic_overlaps" / "PARL10_PARL25_combo_overlap.parquet"
    c21 = repo / "data" / "raw" / "external" / "Westminster_Parliamentary_Constituencies_(Dec_2021)_UK_BFC.parquet"
    con = duckdb.connect()
    con.execute(f"create view c25 as select short_code, gss_code, name as cname, nation, region from '{c25}'")
    con.execute(f"create view ov as select * from '{ov}'")
    con.execute(f"create view c21 as select PCON21CD as gss, PCON21NM as cname from '{c21}'")
    lad = next((repo / "data" / "raw" / "external").glob("Local_Authority_Districts_May_2023*.parquet"))
    con.execute(f"create view lad as select LAD23CD as code, LAD23NM as lname from '{lad}'")
    city_list = ", ".join("'" + n.replace("'", "''") + "'" for n in MAJOR_CITY_AREAS)
    settlement = {}
    for seat_col, table in (("PARL10", "PARL10_LAD23"), ("PARL25", "PARL25_LAD23")):
        con.execute(f"create or replace view ov_lad as select * from '{pkg}/geographic_overlaps/{table}_combo_overlap.parquet'")
        rows = con.execute(f"""
            select o.{seat_col},
                   any_value(o.original_pop) / (any_value(o.original_area) / 1e6) as density,
                   arg_max(l.lname, o.overlap_pop) as main_area,
                   sum(case when l.code like 'E09%' or l.lname in ({city_list}) then o.overlap_pop else 0 end)
                     / any_value(o.original_pop) as city_share
            from ov_lad o join lad l on l.code = o.LAD23 group by 1""").fetchall()
        for seat, density, main_area, city_share in rows:
            kind = "city" if city_share > 0.5 else ("rural" if density < RURAL_DENSITY else "town")
            settlement[(seat_col, seat)] = (kind, round(density), main_area)

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
    new = con.execute("select gss_code, cname, region, nation, short_code from c25 order by cname").fetchall()
    if len(old) != 650 or len(new) != 650:
        raise SystemExit(f"expected 650 + 650 seats, got {len(old)} + {len(new)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["gss_code", "name", "region", "nation", "boundary_set", "valid_from", "valid_to",
                    "settlement", "density_per_km2", "main_area"])
        for gss, name, region, nation in old:
            kind, density, area = settlement[("PARL10", gss)]
            w.writerow([gss, name, ITL1.get(region, region), nation, "2010", "2010-05-06", "2024-07-03",
                        kind, density, area])
        for gss, name, region, nation, short in new:
            kind, density, area = settlement[("PARL25", short)]
            w.writerow([gss, name, ITL1.get(region, region), nation, "2024", "2024-07-04", "9999-12-31",
                        kind, density, area])
    print(f"wrote {OUT} ({len(old)} + {len(new)} seats)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
