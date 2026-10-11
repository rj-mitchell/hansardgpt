"""Speaker profiles on a date: the temporal join between records and reference data.

Invariants (tested):

* identity is resolved only through ids (``person_ids`` table), never names;
* every interval end has been normalised (``9999-12-31`` for open-ended), so
  current office-holders match today's speeches;
* each enrichment is aggregated per record before joining back, so concurrent
  offices or overlapping spells never multiply record rows (no fan-out).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from hansard.reference.build import office_display
from hansard.reference.portfolios import KIND_CHAIR, KIND_GOV, KIND_SHADOW
from hansard.sources.demographics import age_band, age_on, assumed_birth

REFERENCE_TABLES = ("persons", "person_ids", "names", "memberships", "offices", "constituencies", "parties")


def attach_reference(con: duckdb.DuckDBPyConnection, reference_dir: Path) -> None:
    """Create views over the reference Parquet files."""
    for name in REFERENCE_TABLES:
        path = Path(reference_dir) / f"{name}.parquet"
        con.execute(f"CREATE OR REPLACE VIEW ref_{name} AS SELECT * FROM read_parquet('{path.as_posix()}')")
    # reference sets built before gender and date of birth were added: treat them as not known
    cols = {r[0] for r in con.execute("DESCRIBE ref_persons").fetchall()}
    missing = [f"NULL::{t} AS {c}" for c, t in (("gender", "VARCHAR"), ("birth_date", "DATE"),
                                                 ("birth_precision", "VARCHAR")) if c not in cols]
    if missing:
        path = (Path(reference_dir) / "persons.parquet").as_posix()
        con.execute(f"CREATE OR REPLACE VIEW ref_persons AS SELECT *, {', '.join(missing)} "
                    f"FROM read_parquet('{path}')")


# SQL that enriches a relation ``recs(record_id, xml_person_id, date)``.
ENRICH_SQL = """
WITH r AS (
    SELECT recs.record_id, recs.date, coalesce(pid.person_id, recs.xml_person_id) AS person_id
    FROM recs LEFT JOIN ref_person_ids pid ON pid.xml_id = recs.xml_person_id
),
nm AS (
    SELECT r.record_id, arg_max(n.name, n.start) AS speaker_name
    FROM r JOIN ref_names n ON n.person_id = r.person_id AND r.date BETWEEN n.start AND n."end"
    GROUP BY r.record_id
),
ms AS (
    SELECT r.record_id,
           arg_max(struct_pack(house := m.house, constituency := m.constituency, gss_code := m.gss_code,
                               region := m.region, nation := m.nation, settlement := m.settlement,
                               urban_area := m.urban_area, urban_area_pop := m.urban_area_pop,
                               party_id := m.party_id, party_name := m.party_name), m.start) AS mem
    FROM r JOIN ref_memberships m ON m.person_id = r.person_id AND r.date BETWEEN m.start AND m."end"
    GROUP BY r.record_id
),
of AS (
    SELECT r.record_id,
           list(DISTINCT struct_pack(kind := o.kind, role := o.role, portfolios := o.portfolios,
                                     committee_id := o.committee_id, committee_name := o.committee_name,
                                     display_name := o.display_name)) AS offices
    FROM r JOIN ref_offices o ON o.person_id = r.person_id AND r.date BETWEEN o.start AND o."end"
    WHERE o.kind IN ('gov', 'shadow', 'chair', 'whip', 'parliamentary')
    GROUP BY r.record_id
)
SELECT r.record_id, r.person_id, nm.speaker_name,
       ms.mem.house AS member_house, ms.mem.constituency AS constituency, ms.mem.gss_code AS gss_code,
       ms.mem.region AS region, ms.mem.nation AS nation, ms.mem.party_id AS party_id,
       ms.mem.party_name AS party_name, ms.mem.settlement AS settlement,
       ms.mem.urban_area AS urban_area, ms.mem.urban_area_pop AS urban_area_pop,
       coalesce(of.offices, []) AS offices,
       pe.gender AS gender, pe.birth_date AS birth_date, pe.birth_precision AS birth_precision
FROM r
LEFT JOIN ref_persons pe ON pe.person_id = r.person_id
LEFT JOIN nm ON nm.record_id = r.record_id
LEFT JOIN ms ON ms.record_id = r.record_id
LEFT JOIN of ON of.record_id = r.record_id
"""


def enrich(con: duckdb.DuckDBPyConnection, recs_relation: str = "recs") -> duckdb.DuckDBPyRelation:
    """Return the enrichment for ``recs_relation`` (one row per input record)."""
    sql = ENRICH_SQL if recs_relation == "recs" else ENRICH_SQL.replace("FROM recs", f"FROM {recs_relation}")
    return con.sql(sql)


def office_columns(offices: list[dict[str, Any]]) -> dict[str, Any]:
    """Search-index columns summarising a speaker's offices on the record date."""
    gov, shadow, chair = set(), set(), set()
    has = {KIND_GOV: False, KIND_SHADOW: False, KIND_CHAIR: False}
    for o in offices or []:
        kind = o["kind"]
        if kind in has:
            has[kind] = True
        target = {KIND_GOV: gov, KIND_SHADOW: shadow, KIND_CHAIR: chair}.get(kind)
        if target is not None:
            target.update(o.get("portfolios") or [])
    return {
        "is_gov": has[KIND_GOV],
        "is_shadow": has[KIND_SHADOW],
        "is_chair": has[KIND_CHAIR],
        "gov_portfolios": sorted(gov),
        "shadow_portfolios": sorted(shadow),
        "chair_portfolios": sorted(chair),
    }


@dataclass
class SpeakerProfile:
    person_id: str | None
    on: date
    name: str | None = None
    house: str | None = None
    constituency: str | None = None
    gss_code: str | None = None
    region: str | None = None
    nation: str | None = None
    party: str | None = None
    party_id: str | None = None
    settlement: str | None = None   # city | town | rural, by size of urban area (Commons seats only)
    urban_area: str | None = None   # the seat's main urban area, named for city seats
    urban_area_pop: int | None = None
    offices: list[dict[str, Any]] = field(default_factory=list)
    other_names: list[str] = field(default_factory=list)
    gender: str | None = None             # "F" | "M", as recorded by Parliament
    birth_date: date | None = None
    birth_precision: str | None = None    # day | month | year

    @property
    def office_titles(self) -> list[str]:
        return [office_display(o, self.on) for o in self.offices]

    @property
    def age(self) -> int | None:
        """Age on the date of the record (not today)."""
        return age_on(assumed_birth(self.birth_date, self.birth_precision), self.on)

    @property
    def age_approximate(self) -> bool:
        return self.birth_precision == "year"

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "date": self.on.isoformat(),
            "name": self.name,
            "house": self.house,
            "constituency": self.constituency,
            "gss_code": self.gss_code,
            "region": self.region,
            "nation": self.nation,
            "party": self.party,
            "party_id": self.party_id,
            "settlement": self.settlement,
            "urban_area": self.urban_area,
            "urban_area_pop": self.urban_area_pop,
            "offices": [{**o, "title": office_display(o, self.on)} for o in self.offices],
            "other_names": self.other_names,
            "gender": self.gender,
            "age": self.age,
            "age_approximate": self.age_approximate if self.age is not None else None,
            "age_band": age_band(self.age),
        }


class ProfileResolver:
    """Look up speaker profiles (for citation cards and tests)."""

    def __init__(self, reference_dir: Path, con: duckdb.DuckDBPyConnection | None = None):
        self.con = con or duckdb.connect()
        attach_reference(self.con, reference_dir)

    def canonical_person(self, xml_id: str | None) -> str | None:
        if not xml_id:
            return None
        row = self.con.execute("SELECT person_id FROM ref_person_ids WHERE xml_id = ?", [xml_id]).fetchone()
        return row[0] if row else None

    def profiles(self, items: list[tuple[str, str | None, date]]) -> dict[str, SpeakerProfile]:
        """Profiles for ``(record_id, xml_person_id, date)`` triples."""
        if not items:
            return {}
        self.con.register("recs", pa.table({
            "record_id": pa.array([i[0] for i in items], pa.string()),
            "xml_person_id": pa.array([i[1] for i in items], pa.string()),
            "date": pa.array([i[2] for i in items], pa.date32()),
        }))
        rows = enrich(self.con).fetchall()
        cols = ["record_id", "person_id", "speaker_name", "member_house", "constituency", "gss_code",
                "region", "nation", "party_id", "party_name", "settlement", "urban_area", "urban_area_pop", "offices",
                "gender", "birth_date", "birth_precision"]
        dates = {rid: d for rid, _, d in items}
        out: dict[str, SpeakerProfile] = {}
        person_ids = set()
        for row in rows:
            r = dict(zip(cols, row, strict=True))
            person_ids.add(r["person_id"])
            out[r["record_id"]] = SpeakerProfile(
                person_id=r["person_id"], on=dates[r["record_id"]], name=r["speaker_name"],
                house=r["member_house"], constituency=r["constituency"], gss_code=r["gss_code"],
                region=r["region"], nation=r["nation"], party=r["party_name"], party_id=r["party_id"],
                settlement=r["settlement"], urban_area=r["urban_area"], urban_area_pop=r["urban_area_pop"],
                offices=sorted(r["offices"], key=lambda o: (o["kind"], o["display_name"] or "")),
                gender=r["gender"], birth_date=r["birth_date"], birth_precision=r["birth_precision"],
            )
        names = self._all_names([p for p in person_ids if p])
        for prof in out.values():
            prof.other_names = [n for n in names.get(prof.person_id, []) if n != prof.name]
        return out

    def profile(self, xml_person_id: str, on: date) -> SpeakerProfile:
        return self.profiles([("_", xml_person_id, on)])["_"]

    def _all_names(self, person_ids: list[str]) -> dict[str, list[str]]:
        if not person_ids:
            return {}
        rows = self.con.execute(
            "SELECT person_id, list(DISTINCT name ORDER BY name) FROM ref_names WHERE list_contains(?, person_id) "
            "GROUP BY person_id", [person_ids]).fetchall()
        return dict(rows)
