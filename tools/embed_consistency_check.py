"""ADR-0006 gate: hosted vectors must agree with the local pinned model before they are trusted.
    .venv\\Scripts\\python tools\\embed_consistency_check.py --n 1000"""
import argparse, random, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.indexer.chunking import chunk_offsets, embedding_input  # noqa: E402
from corpus_engine.indexer.embedders import HostedEmbedder, LocalEmbedder  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=1000); a = ap.parse_args()
    spec = load_domain().embedding; conn = store.connect()
    key = store.env_value("OPENROUTER_API_KEY" if spec.hosted_provider == "openrouter" else "DEEPINFRA_API_KEY")
    local = LocalEmbedder(spec.model, spec.revision, spec.dim)
    hosted = HostedEmbedder(spec.hosted_provider, spec.hosted_model_id, spec.dim, key)
    ids = [r[0] for r in conn.execute("SELECT case_id FROM cases WHERE is_duplicate_of IS NULL AND norm_text != '' ORDER BY random() LIMIT ?", (a.n,))]
    texts = []
    for cid in ids:
        text, name, court, year = conn.execute("SELECT norm_text, name_abbreviation, court, decision_year FROM cases WHERE case_id=?", (cid,)).fetchone()
        s, e = chunk_offsets(local.tokenizer, text, spec.chunk_tokens, spec.chunk_overlap)[0]
        texts.append(embedding_input(spec.prefix_template, {"name": name, "court": court, "year": year}, text[s:e]))
    L, H = local.encode(texts), hosted.encode(texts)
    L /= np.linalg.norm(L, axis=1, keepdims=True); H /= np.linalg.norm(H, axis=1, keepdims=True)
    cos = (L * H).sum(axis=1)
    print(f"n={len(cos)} mean={cos.mean():.4f} p5={np.percentile(cos, 5):.4f} min={cos.min():.4f} tokens={hosted.tokens_used}")
    sys.exit(0 if cos.mean() >= 0.99 else 1)
