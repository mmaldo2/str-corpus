# tools/capture_selector_goldens.py
"""One-time: freeze the pre-refactor recall report and the embedding selectors'
query vectors.

`embed_meta` is read from `tests/fixtures/corpus-tiny.db` (opened read-only),
NOT from the live database: the live index has since been re-embedded with
Qwen3-Embedding-4B (1024-d), but every downstream test and fixture in this
plan characterizes the 0.6B / 512-d index that the fixtures use. The recall
report itself still runs against the live DB via `eval_recall.evaluate(None)`
(read-only: it only SELECTs from `signals` and reads `data/gold/gold.jsonl`).
"""
import json, sqlite3, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline")); sys.path.insert(0, str(ROOT))
import eval_recall, shard  # noqa: E402  (old code, on purpose)

if __name__ == "__main__":
    rep = eval_recall.evaluate(None)
    slim = {"tiers": rep["tiers"],
            "hits": sorted([{"case_id": h["case_id"], "selectors": sorted(h["selectors"])} for h in rep["hits"]], key=lambda h: h["case_id"]),
            "misses": sorted(g["case_id"] for g in rep["misses"])}
    (ROOT / "tests/golden/recall-cycle-003.json").write_bytes(json.dumps(slim, indent=1, sort_keys=True).encode("utf-8"))

    fixture_conn = sqlite3.connect("file:tests/fixtures/corpus-tiny.db?mode=ro", uri=True)
    meta = dict(fixture_conn.execute("SELECT key, value FROM embed_meta"))
    fixture_conn.close()

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(meta["model"], revision=meta.get("revision") or None, device="cuda" if shard._cuda() else "cpu")
    dim = int(meta.get("dim", "512")); arrays = {"__meta__": np.array(json.dumps(meta))}
    for s in shard.load_selectors():
        if s["type"] == "embedding":
            q = model.encode([s["query_text"]], prompt_name="query", convert_to_numpy=True)[0][:dim].astype(np.float32)
            arrays[f"{s['id']}@v{s['version']}"] = q / (np.linalg.norm(q) + 1e-12)
    np.savez(ROOT / "tests/fixtures/query-vectors-v3.npz", **arrays)
    print("recall tiers:", slim["tiers"]); print("vectors:", sorted(k for k in arrays if k != "__meta__"))
