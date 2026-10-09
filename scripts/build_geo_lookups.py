# /// script
# requires-python = ">=3.12"
# dependencies = ["duckdb", "numpy", "pyarrow", "pyproj", "scipy", "shapely"]
# ///
"""Build data_static/geo/constituencies.csv from mySociety's 2025-constituencies repo.

Usage:
    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/mysociety/2025-constituencies /tmp/2025-constituencies
    git -C /tmp/2025-constituencies sparse-checkout set data/packages data/raw/external
    uv run scripts/build_geo_lookups.py /tmp/2025-constituencies

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

Seat type (``settlement``) depends on the size of the continuous urban area a
seat's residents live in, not on whether a place has official city status:

* ``city``  - most residents live in urban areas, and the largest share of them
              in a "major" one: 200,000+ people on the ONS count (ONS_MAJOR,
              scaled by how this method's sizes compare with ONS's, so about
              190,000 here). Ripon or Wells are towns here; Reading, Milton
              Keynes and Bolton (part of the Manchester urban area) are cities.
* ``town``  - most residents live in urban areas, the main one smaller than that;
* ``rural`` - most residents live outside urban areas of URBAN_POPULATION+ (the
              ONS rural definition: settlements of under 10,000 people).

Urban areas follow the ONS built-up-area method (built land, joined where gaps
are short) using the location of every GB postcode (OS Code-Point Open) as the
built land: a CELL-metre grid cell holding a postcode is built-up, and built-up
cells with gaps of up to 220 m between them join one urban area (ONS joins built
land less than 200 m apart). Each postcode carries
an equal share of its 2024 seat's population. The result is checked against the
ONS 2011 built-up areas (ONS_2011 below): the median error is about 7%.

Northern Ireland postcodes are not in Code-Point Open, so its four Belfast seats
are city seats (Belfast urban area) and the rest are town or rural by density.

``main_area`` is the local authority holding most of the seat's population;
``urban_area`` / ``urban_area_pop`` name and size the seat's main urban area.

Source data: ONS and Ordnance Survey (Open Government Licence v3.0) via mySociety.
"""

from __future__ import annotations

import csv
import glob
import sys
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.csv as pcsv
import pyarrow.parquet as pq
import shapely
from pyproj import Transformer
from scipy import ndimage

ITL1 = {
    "Eastern": "East of England",
    "Yorkshire and the Humber": "Yorkshire and The Humber",
}

OUT = Path(__file__).resolve().parents[1] / "data_static" / "geo" / "constituencies.csv"

CELL = 55               # metres
LINK = 2                # each built cell grows by this many cells; touching areas join, which joins
                        # built cells with up to 2 * LINK empty cells (220 m) between them
URBAN_POPULATION = 10_000
ONS_MAJOR = 200_000     # ONS size class "major" built-up area
RURAL_DENSITY = 250     # people per km2, Northern Ireland only

# ONS 2011 Census built-up areas, usual residents in thousands, keyed by the
# largest council in each (a check on the method, not an input to it).
ONS_2011 = {
    "London": 9787, "Manchester": 2553, "Birmingham": 2441, "Leeds": 1778, "Liverpool": 864,
    "Southampton": 855, "Newcastle upon Tyne": 775, "Nottingham": 730, "Sheffield": 685,
    "Bristol, City of": 617, "Leicester": 509, "Brighton and Hove": 474,
    "Bournemouth, Christchurch and Poole": 466, "Cardiff": 447, "Middlesbrough": 377, "Stoke-on-Trent": 373,
    "Coventry": 359, "Sunderland": 335, "Wirral": 325, "Reading": 318, "Kingston upon Hull, City of": 314,
    "Preston": 313, "Newport": 307, "Swansea": 300, "Southend-on-Sea": 295, "Derby": 270, "Plymouth": 260,
    "Luton": 258, "Rushmoor": 252, "Medway": 244, "Blackpool": 239, "Milton Keynes": 230, "Barnsley": 223,
    "West Northamptonshire": 215, "Norwich": 213, "Swindon": 186, "Crawley": 181, "Ipswich": 179,
    "Wigan": 175, "Mansfield": 172, "Oxford": 171, "Warrington": 165, "Slough": 164, "Peterborough": 163,
    "Cambridge": 158, "Doncaster": 158, "York": 154, "Gloucester": 150, "Burnley": 149,
    "Telford and Wrekin": 148, "Blackburn with Darwen": 147,
}
GROWTH_2011_2021 = 1.07  # England and Wales population growth between the censuses

# ONS names for the conurbations, which are otherwise named after their largest council.
CONURBATIONS = {
    "Manchester": "Greater Manchester", "Birmingham": "West Midlands", "Leeds": "West Yorkshire",
    "Newcastle upon Tyne": "Tyneside", "Southampton": "South Hampshire", "Wirral": "Birkenhead",
    "Rushmoor": "Farnborough/Aldershot", "West Northamptonshire": "Northampton",
    "Bournemouth, Christchurch and Poole": "Bournemouth/Poole", "Medway": "Medway Towns",
}
NAMED_SHARE = 0.4  # name a smaller area after its council only if it holds this share of the council's people

CODEPO = ["postcode", "pqi", "e", "n", "country", "nhs_r", "nhs_ha", "county", "district", "ward"]


def postcodes(repo: Path, con: duckdb.DuckDBPyConnection) -> None:
    """Table ``pc``: GB postcodes with grid position, council and an equal share of the seat population."""
    types = {"pqi": pa.int32(), "e": pa.int64(), "n": pa.int64()} | {
        c: pa.string() for c in CODEPO if c not in ("pqi", "e", "n")}
    raw = pa.concat_tables(
        pcsv.read_csv(f, read_options=pcsv.ReadOptions(column_names=CODEPO),
                      convert_options=pcsv.ConvertOptions(column_types=types))
        for f in sorted(glob.glob(str(repo / "data/raw/external/codepo/csv/*.csv"))))
    pkg = repo / "data" / "packages"
    con.register("pc_raw", raw)
    con.execute(f"""
        create table pc as
        with p as (
            select r.postcode, r.e, r.n, r.district, l.short_code
            from pc_raw r join '{pkg}/uk_parliament_2025_postcode_lookup/postcodes_with_con.parquet' l
                 using (postcode)
            where r.e > 0 and r.pqi < 90),
        seat as (select PARL25 short_code, any_value(original_pop) pop
                 from '{pkg}/geographic_overlaps/PARL25_LAD23_combo_overlap.parquet' group by 1)
        select p.*, seat.pop / count(*) over (partition by p.short_code) as w
        from p join seat using (short_code)""")


def display_name(council: str) -> str:
    name = CONURBATIONS.get(council, council)
    for junk in (", City of", ", County of", "City of ", " City"):
        name = name.replace(junk, "")
    return name


def urban_areas(con: duckdb.DuckDBPyConnection, lad_names: pa.Table) -> dict[int, tuple[str | None, float]]:
    """Label each postcode with its urban area (column ``area``); returns area -> (name, population).

    The name is None where the area's largest council is much bigger than the area
    (a small town in a county-wide council such as Cornwall)."""
    e, n, w = (np.asarray(con.sql(f"select {c} from pc order by postcode").fetchnumpy()[c]) for c in "enw")
    ix, iy = e // CELL, n // CELL
    ix, iy = ix - ix.min(), iy - iy.min()
    built = np.zeros((iy.max() + 1, ix.max() + 1), dtype=bool)
    built[iy, ix] = True
    linked = ndimage.binary_dilation(built, structure=np.ones((3, 3), bool), iterations=LINK)
    labels, _ = ndimage.label(linked, structure=np.ones((3, 3), bool))
    area = labels[iy, ix]
    postcodes_sorted = con.sql("select postcode from pc order by postcode").fetchnumpy()["postcode"]
    con.register("areas", pa.table({"postcode": postcodes_sorted, "area": area}))
    con.execute("create table pca as select pc.*, areas.area from pc join areas using (postcode)")
    con.register("lad_names", lad_names)
    rows = con.execute("""
        with c as (select area, district, sum(w) p from pca group by all),
             council as (select district, sum(w) people from pca group by district)
        select area, sum(p),
               arg_max(coalesce(l.LAD23NM, c.district), p),
               arg_max(council.people, p),
               sum(case when c.district like 'E09%' then p else 0 end) / sum(p)
        from c join council using (district) left join lad_names l on l.LAD23CD = c.district
        group by area""").fetchall()
    out = {}
    for a, pop, top, council_people, london in rows:
        if london > 0.5:
            out[a] = ("London", pop)
        else:
            out[a] = (display_name(top) if pop >= NAMED_SHARE * council_people else None, pop, top)
    return out


def check_against_ons(areas: dict[int, tuple[str, float]]) -> float:
    """Compare sizes with the ONS 2011 built-up areas; returns the median ratio (ours / ONS)."""
    biggest: dict[str, float] = {}
    for name, pop, *council in sorted(areas.values(), key=lambda x: -x[1]):
        biggest.setdefault(council[0] if council else name, pop)
    errors, ratios = [], []
    for name, ref in ONS_2011.items():
        ratio = biggest.get(name, 0) / (ref * 1000 * GROWTH_2011_2021)
        errors.append(abs(ratio - 1))
        ratios.append(ratio)
        if not 0.8 <= ratio <= 1.25:
            print(f"  {name}: {biggest.get(name, 0) / 1e3:.0f}k here vs ONS 2011 {ref}k")
    median = sorted(errors)[len(errors) // 2]
    print(f"urban areas vs ONS 2011: median error {median:.1%}, "
          f"{sum(x < 0.2 for x in errors)}/{len(errors)} within 20%")
    if median > 0.15:
        raise SystemExit("urban areas no longer match the ONS built-up areas; check the inputs")
    return sorted(ratios)[len(ratios) // 2]


def seats_2010(repo: Path, con: duckdb.DuckDBPyConnection) -> None:
    """Add column ``seat10`` (2010-set GSS code) to ``pca`` by point in polygon."""
    t = pq.read_table(repo / "data/raw/external/Westminster_Parliamentary_Constituencies_(Dec_2021)_UK_BFC.parquet",
                      columns=["PCON21CD", "geometry"])
    to_bng = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    polys = shapely.transform(shapely.from_wkb(t.column("geometry").to_numpy(zero_copy_only=False)),
                              lambda xy: np.column_stack(to_bng.transform(xy[:, 0], xy[:, 1])))
    codes = np.asarray(t.column("PCON21CD").to_pylist())
    tree = shapely.STRtree(polys)
    pcs = con.sql("select postcode, e, n from pca").fetchnumpy()
    pts = shapely.points(pcs["e"].astype(float), pcs["n"].astype(float))
    seat = np.full(len(pts), None, dtype=object)
    pi, si = tree.query(pts, predicate="within")
    seat[pi] = codes[si]
    missing = np.flatnonzero(seat == None)  # noqa: E711  (coastal postcodes just outside the clipped boundary)
    if len(missing):
        _, near = tree.query_nearest(pts[missing], return_distance=False, all_matches=False)
        seat[missing] = codes[near]
    con.register("s10", pa.table({"postcode": pcs["postcode"], "seat10": seat.astype(str)}))
    con.execute("create table pcs as select pca.*, s10.seat10 from pca join s10 using (postcode)")


def classify(con: duckdb.DuckDBPyConnection, seat_col: str, areas: dict[int, tuple[str, float]],
             city_population: float) -> dict:
    """seat -> (settlement, urban area name, urban area population, urban share)."""
    big = [a for a, (_, pop, *_) in areas.items() if pop >= URBAN_POPULATION]
    con.register("big_areas", pa.table({"area": pa.array(big, pa.int64())}))
    rows = con.execute(f"""
        with s as (select {seat_col} seat, area, sum(w) p from pcs group by all),
             t as (select seat, sum(p) total from s group by seat)
        select s.seat, any_value(t.total),
               coalesce(sum(case when b.area is not null then s.p end), 0),
               arg_max(s.area, case when b.area is not null then s.p else -1 end)
        from s join t using (seat) left join big_areas b using (area)
        group by s.seat""").fetchall()
    out = {}
    for seat, total, urban, main in rows:
        share = urban / total
        name, pop = areas[main][:2] if share > 0 else (None, None)
        kind = "rural" if share < 0.5 else ("city" if pop >= city_population else "town")
        out[seat] = (kind, name if share > 0 else None, round(pop) if share > 0 else None, round(share, 2))
    return out


def main(repo: Path) -> None:
    pkg = repo / "data" / "packages"
    c25 = pkg / "parliament_con_2025" / "parl_constituencies_2025.parquet"
    ov = pkg / "geographic_overlaps" / "PARL10_PARL25_combo_overlap.parquet"
    c21 = repo / "data" / "raw" / "external" / "Westminster_Parliamentary_Constituencies_(Dec_2021)_UK_BFC.parquet"
    lad_file = next((repo / "data" / "raw" / "external").glob("Local_Authority_Districts_May_2023*.parquet"))
    lad_names = pq.read_table(lad_file, columns=["LAD23CD", "LAD23NM"])
    con = duckdb.connect()
    con.execute(f"create view c25 as select short_code, gss_code, name as cname, nation, region from '{c25}'")
    con.execute(f"create view ov as select * from '{ov}'")
    con.execute(f"create view c21 as select PCON21CD as gss, PCON21NM as cname from '{c21}'")
    con.register("lad", lad_names)

    postcodes(repo, con)
    areas = urban_areas(con, lad_names)
    city_population = round(ONS_MAJOR * check_against_ons(areas), -4)
    print(f"city seats: main urban area of {city_population:,.0f}+ people")
    seats_2010(repo, con)
    con.execute("create or replace table pcs as select pcs.*, c25.gss_code seat24 from pcs "
                "join c25 using (short_code)")
    kinds = {"2010": classify(con, "seat10", areas, city_population),
             "2024": classify(con, "seat24", areas, city_population)}

    # density and main council, from mySociety's population-weighted overlaps (all four nations)
    basics = {}
    for seat_col, table in (("PARL10", "PARL10_LAD23"), ("PARL25", "PARL25_LAD23")):
        rows = con.execute(f"""
            select o.{seat_col},
                   any_value(o.original_pop) / (any_value(o.original_area) / 1e6) as density,
                   arg_max(l.LAD23NM, o.overlap_pop) as main_area
            from '{pkg}/geographic_overlaps/{table}_combo_overlap.parquet' o
            join lad l on l.LAD23CD = o.LAD23 group by 1""").fetchall()
        for seat, density, main_area in rows:
            basics[(seat_col, seat)] = (round(density), main_area)

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
           select c21.gss, c21.cname, best.region, best.nation, c21.gss
           from c21 join best on best.gss = c21.gss order by c21.cname"""
    ).fetchall()
    new = con.execute("select gss_code, cname, region, nation, short_code from c25 order by cname").fetchall()
    if len(old) != 650 or len(new) != 650:
        raise SystemExit(f"expected 650 + 650 seats, got {len(old)} + {len(new)}")

    def seat_type(boundary: str, gss: str, name: str, nation: str, density: int):
        if nation == "Northern Ireland":
            if name.startswith("Belfast"):
                return "city", "Belfast", None, None
            return ("rural" if density < RURAL_DENSITY else "town"), None, None, None
        return kinds[boundary][gss]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[tuple[str, str], int] = {}
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["gss_code", "name", "region", "nation", "boundary_set", "valid_from", "valid_to",
                    "settlement", "density_per_km2", "main_area", "urban_area", "urban_area_pop", "urban_share"])
        for boundary, rows, col, start, end in (("2010", old, "PARL10", "2010-05-06", "2024-07-03"),
                                                ("2024", new, "PARL25", "2024-07-04", "9999-12-31")):
            for gss, name, region, nation, key in rows:
                density, main_area = basics[(col, key)]
                kind, area, area_pop, share = seat_type(boundary, gss, name, nation, density)
                counts[(boundary, kind)] = counts.get((boundary, kind), 0) + 1
                w.writerow([gss, name, ITL1.get(region, region), nation, boundary, start, end, kind, density,
                            main_area, area or "", area_pop or "", "" if share is None else share])
    print(f"wrote {OUT} ({len(old)} + {len(new)} seats): {dict(sorted(counts.items()))}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
