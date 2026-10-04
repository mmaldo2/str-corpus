"""One-time: derive data/ledger/patches.jsonl from the existing artifacts.
Refuses to run if patches.jsonl already exists."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine.ledger import open_ledger  # noqa: E402
from corpus_engine.ledger.bootstrap import patches_from_artifacts  # noqa: E402

_LEDGER = ROOT / "data" / "ledger"
if (_LEDGER / "patches.jsonl").exists() or (_LEDGER / "patches").exists():
    raise SystemExit("the patch log exists; refusing to bootstrap twice")
led = open_ledger()
res = led.apply(patches_from_artifacts(ROOT), note="bootstrap from artifacts", at="2026-09-01T00:00:00")
print(f"{len(res.applied)} patches; replay_ok={res.replay_ok}; files={[p.name for p in res.files_written]}")
