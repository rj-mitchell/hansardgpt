from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hansard.config import STATIC_DIR, load_settings
from hansard.reference.build import build_reference, write_reference
from hansard.reference.profiles import ProfileResolver

FIXTURES = Path(__file__).parent / "fixtures"
MEMBERS = FIXTURES / "members"
XML = FIXTURES / "xml"
GEO_CSV = STATIC_DIR / "geo" / "constituencies.csv"

CAMERON = "uk.org.publicwhip/person/10777"
BENN = "uk.org.publicwhip/person/10669"
GREENING = "uk.org.publicwhip/person/11771"


@pytest.fixture(scope="session")
def reference(tmp_path_factory):
    ref = build_reference(MEMBERS, GEO_CSV)
    out = tmp_path_factory.mktemp("reference")
    write_reference(ref, out)
    return ref, out


@pytest.fixture(scope="session")
def reference_dir(reference) -> Path:
    return reference[1]


@pytest.fixture(scope="session")
def resolver(reference_dir) -> ProfileResolver:
    return ProfileResolver(reference_dir)


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    """Settings pointing at an empty temporary data directory."""
    monkeypatch.setenv("HANSARD_DATA_DIR", str(tmp_path / "data"))
    return load_settings(**{"embedding.backend": "hashing", "embedding.dim": 64})


@pytest.fixture()
def xml_mirror(settings) -> Path:
    """Copy the XML fixtures into the settings' raw mirror directory."""
    dest = settings.raw_xml_dir
    shutil.copytree(XML, dest)
    return dest
