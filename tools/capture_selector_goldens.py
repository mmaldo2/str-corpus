# tools/capture_selector_goldens.py
"""One-time: freeze the pre-refactor recall report and the embedding selectors'
query vectors.

`embed_meta` is read from `tests/fixtures/corpus-tiny.db` (opened read-only),
NOT from the live database: the live index has since been re-embedded with
Qwen3-Embedding-4B (1024-d), but every downstream test and fixture in this
plan characterizes the 0.6B / 512-d index that the fixtures use. The recall
report itself still runs against the live DB via `eval_recall.evaluate(None)`
(read-only: it only SELECTs from `signals` and reads `data/gold/gold.jsonl`).

Ported to the selector engine (Stage 2B): the selector list now comes from
`corpus_engine.selector.model.load_selectors(load_domain())` — filtered to
`kind == "embedding"` — because `pipeline/shard.py:load_selectors()` and
`shard._cuda()`, which this tool used to call, were deleted when shard.py
became a thin CLI wrapper. Output keys are unchanged (`f"{id}@v{version}"`,
i.e. `Selector.label`), so re-running it produces the same golden shape.

The goldens under `tests/golden/` are frozen; do not re-run this without a
logged reason (see tests/golden/README.md).
"""
import json, sqlite3, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline")); sys.path.insert(0, str(ROOT))
import eval_recall  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.selector.model import load_selectors  # noqa: E402

if __name__ == "__main__":
    rep = eval_recall.evaluate(None)
    slim = {"tiers": rep["tiers"],
            "hits": sorted([{"case_id": h["case_id"], "selectors": sorted(h["selectors"])} for h in rep["hits"]], key=lambda h: h["case_id"]),
            "misses": sorted(g["case_id"] for g in rep["misses"])}
    (ROOT / "tests/golden/recall-cycle-003.json").write_bytes(json.dumps(slim, indent=1, sort_keys=True).encode("utf-8"))

    fixture_db = ROOT / "tests/fixtures/corpus-tiny.db"
    fixture_conn = sqlite3.connect(f"file:{fixture_db.as_posix()}?mode=ro", uri=True)
    meta = dict(fixture_conn.execute("SELECT key, value FROM embed_meta"))
    fixture_conn.close()

    import torch
    from sentence_transformers import SentenceTransformer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(meta["model"], revision=meta.get("revision") or None, device=device)
    dim = int(meta.get("dim", "512")); arrays = {"__meta__": np.array(json.dumps(meta))}
    for s in load_selectors(load_domain()):
        if s.kind == "embedding":
            q = model.encode([s.params["query_text"]], prompt_name="query", convert_to_numpy=True)[0][:dim].astype(np.float32)
            arrays[s.label] = q / (np.linalg.norm(q) + 1e-12)
    np.savez(ROOT / "tests/fixtures/query-vectors-v3.npz", **arrays)
    print("recall tiers:", slim["tiers"]); print("vectors:", sorted(k for k in arrays if k != "__meta__"))
