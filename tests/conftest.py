import sqlite3
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent

@pytest.fixture(autouse=True)
def _selector_scratch_state_is_isolated():
    """corpus_engine.selector.runners.PENDING_SCRATCH / _pending_owned_dirs are
    module-level (process-global), so a test that leaves an entry behind pollutes every
    test that runs after it in this session. A test that deliberately forces an entry
    (e.g. simulating the Windows unlink failure) must clean it up itself - restore
    Path.unlink and call close() again, or discard what it added directly - before it
    ends; this fixture is what enforces that.
    """
    from corpus_engine.selector import runners as runners_mod
    before_pending = set(runners_mod.PENDING_SCRATCH)
    before_dirs = set(runners_mod._pending_owned_dirs)
    yield
    assert runners_mod.PENDING_SCRATCH == before_pending, (
        "a test left an entry in runners.PENDING_SCRATCH behind - clean it up "
        "before the test ends (see this fixture's docstring)")
    assert runners_mod._pending_owned_dirs == before_dirs, (
        "a test left an entry in runners._pending_owned_dirs behind - clean it up "
        "before the test ends (see this fixture's docstring)")

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
