"""Incremental daily sync: new sittings, corrections and member-data changes."""

import json
import shutil
from datetime import date

from hansard.embed.base import HashingEmbedder
from hansard.index.lance import SearchIndex, sql_str
from hansard.store.state import StateDB
from hansard.sync import run_sync

from .conftest import MEMBERS

BENN = "uk.org.publicwhip/person/10669"


def _passages(settings, where):
    idx = SearchIndex(settings.index_dir, 64)
    return idx.passages().search().where(where).limit(None).to_list()


def test_sync_end_to_end_and_member_reshuffle(settings, xml_mirror, tmp_path):
    members = tmp_path / "members"
    shutil.copytree(MEMBERS, members)
    first = run_sync(settings, fetch=False, members_dir=members, embedder=HashingEmbedder(64), embed_minutes=None,
                     workers=1, today=date(2026, 10, 1))
    assert "error" not in first, first
    assert first["ingest"]["files_new"] > 0 and first["index"]["passages_written"] > 0
    assert first["embed"]["files_remaining"] == 0
    vectors_before = SearchIndex(settings.index_dir, 64).stats()["vectors"]
    assert vectors_before > 0

    # Pick a speaker who appears in the fixture debates and give them a new government post.
    rows = _passages(settings, "source = 'debates' AND person_id IS NOT NULL AND date >= DATE '2026-01-01'")
    target = rows[0]["person_id"]
    others = {r["person_id"] for r in rows} - {target}
    f = members / "ministers-2010.json"
    data = json.loads(f.read_text())
    data["memberships"].append({
        "id": "test/new-post", "source": "datadotparl/governmentpost", "organization_id": "house-of-commons",
        "person_id": target, "role": "Minister of State (Department for Transport)",
        "start_date": "2026-01-01",
    })
    f.write_text(json.dumps(data))

    second = run_sync(settings, fetch=False, members_dir=members, embedder=HashingEmbedder(64), embed_minutes=None,
                      workers=1, today=date(2026, 10, 1))
    assert "error" not in second, second
    assert second["reference"]["people_changed"] == [target]
    assert second["ingest"]["files_parsed"] == 0          # no Hansard re-parsing
    assert second["index"]["files_reenriched"] >= 1
    after = _passages(settings, f"person_id = {sql_str(target)} AND date >= DATE '2026-01-01'")
    assert after and all("transport" in r["gov_portfolios"] for r in after)
    # other speakers untouched, embeddings kept (text unchanged)
    assert second["embed"]["passages_embedded"] == 0
    assert SearchIndex(settings.index_dir, 64).stats()["vectors"] == vectors_before
    vt = SearchIndex(settings.index_dir, 64).vectors()
    vec_rows = vt.search().where(f"person_id = {sql_str(target)} AND date >= DATE '2026-01-01'").limit(None).to_list()
    assert vec_rows and all(r["is_gov"] for r in vec_rows)
    assert others  # sanity: fixture has several speakers

    runs = StateDB(settings.state_db).runs()
    assert len(runs) == 2 and all(r["status"] == "ok" for r in runs)
    assert runs[0]["stats"]["reference"]["people_changed"] == [target]


def test_sync_applies_a_hansard_correction(settings, xml_mirror, tmp_path):
    members = tmp_path / "members"
    shutil.copytree(MEMBERS, members)
    run_sync(settings, fetch=False, members_dir=members, embedder=HashingEmbedder(64), embed_minutes=None, workers=1,
             today=date(2026, 10, 1))
    before = _passages(settings, "source_key = 'debates2026-09-15'")
    src = xml_mirror / "debates" / "debates2026-09-15c.xml"
    text = src.read_text(encoding="utf-8").replace("2026-09-15c.", "2026-09-15d.").replace(
        "Trial by Jury", "Trial by Jury (corrected)")
    (xml_mirror / "debates" / "debates2026-09-15d.xml").write_text(text, encoding="utf-8")

    stats = run_sync(settings, fetch=False, members_dir=members, embedder=HashingEmbedder(64), embed_minutes=None,
                     workers=1, today=date(2026, 10, 1))
    assert stats["ingest"]["files_revised"] == 1 and stats["ingest"]["files_parsed"] == 1
    after = _passages(settings, "source_key = 'debates2026-09-15'")
    assert len(after) == len(before)
    assert all("2026-09-15d." in r["record_id"] for r in after)
    assert any("Trial by Jury (corrected)" in r["heading"] for r in after)
    assert stats["embed"]["passages_embedded"] == len(after)  # corrected text is re-embedded


def test_sync_records_failures(settings, tmp_path):
    stats = run_sync(settings, fetch=False, members_dir=tmp_path / "missing", embed_minutes=0)
    assert "error" in stats
    assert StateDB(settings.state_db).runs()[0]["status"] == "failed"
