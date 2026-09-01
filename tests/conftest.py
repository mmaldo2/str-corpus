import sqlite3
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent

def pytest_configure(config):
    config.addinivalue_line("markers", "live_db: needs data/db/corpus.db")

@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO

@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return REPO / "tests" / "golden"

@pytest.fixture(scope="session")
def fixture_db() -> Path:
    p = REPO / "tests" / "fixtures" / "corpus-tiny.db"
    if not p.exists():
        pytest.skip("tests/fixtures/corpus-tiny.db not built yet (Task 3)")
    return p

@pytest.fixture(scope="session")
def live_db() -> Path:
    p = REPO / "data" / "db" / "corpus.db"
    if not p.exists():
        pytest.skip("live corpus.db not present")
    return p
