"""Estimate hosted-embedding cost for the pending cases; optionally pin the model revision.
    .venv\\Scripts\\python tools\\estimate_embed_cost.py [--partitions "pre-1860|Mass.,..."] [--pin]"""
import argparse, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.indexer.embed import EmbedRun, estimate_tokens  # noqa: E402
from corpus_engine.indexer.embedders import tokenizer_for  # noqa: E402

USD_PER_M = 0.01

def parse_partitions(s):
    return [tuple(p.split("|")) for p in s.split(",")] if s else None

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--partitions"); ap.add_argument("--pin", action="store_true"); a = ap.parse_args()
    dom = load_domain(); spec = dom.embedding
    if a.pin and spec.revision == "main":
        from huggingface_hub import HfApi
        sha = HfApi().model_info(spec.model, revision="main").sha
        y = (dom.root / "domain.yaml"); txt = y.read_bytes().decode("utf-8")
        y.write_bytes(txt.replace("revision: main", f"revision: {sha}", 1).encode("utf-8")); print("pinned", sha)
        dom = load_domain(); spec = dom.embedding
    conn = store.connect(); store.migrate(conn)
    cases, tokens = estimate_tokens(conn, tokenizer_for(spec.model, spec.revision), EmbedRun.from_spec(spec, spec.hosted_provider),
                                    partitions=parse_partitions(a.partitions))
    print(f"{cases} cases, ~{tokens:,} tokens, ~${tokens / 1e6 * USD_PER_M:.2f} at ${USD_PER_M}/M")
