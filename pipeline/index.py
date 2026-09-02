"""Build retrieval indexes over the ingested corpus.

Two FTS5 indexes over norm_text (spec §5): a porter-stemmed one and a raw
unicode61 one — historical terms of art must be matchable exactly. Both are
external-content tables over `cases` and exclude nothing at build time;
shard.py excludes duplicates at query time.

Embeddings: run through the domain's configured Embedder (local pinned
weights or a hosted API), chunked with the domain's tokenizer, L2-normalized
then symmetric int8 per-vector quantized, and tagged with the run that
produced them (corpus_engine/indexer). Chunk rows store char offsets into
norm_text, not copied text.

Usage:
    python pipeline/index.py fts                 # (re)build both FTS tables
    python pipeline/index.py embed [--batch 64] [--limit N]
    python pipeline/index.py embed --legacy-0.6b  # old model/dim, for comparison runs
    python pipeline/index.py embed --hosted --confirm [--partitions "era|jur,era|jur"]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "db" / "corpus.db"

sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.indexer.fts import build_fts  # noqa: E402
from corpus_engine.indexer.embed import EmbedRun, build_embeddings  # noqa: E402
from corpus_engine.indexer.embedders import LocalEmbedder, HostedEmbedder, tokenizer_for  # noqa: E402

# Old model/dim, kept for --legacy-0.6b comparison runs against the current default.
LEGACY_MODEL = "Qwen/Qwen3-Embedding-0.6B"
LEGACY_REVISION = "main"
LEGACY_DIM = 512
LEGACY_CHUNK_TOKENS = 1000
LEGACY_CHUNK_OVERLAP = 150
LEGACY_RUN_KEY = "qwen3-0.6b-512-int8"


def _parse_partitions(spec: str | None) -> list[tuple[str, str]] | None:
    if not spec:
        return None
    out = []
    for part in spec.split(","):
        era, jur = part.split("|", 1)
        out.append((era.strip(), jur.strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["fts", "embed"])
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--domain", default="str-right-to-let")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--legacy-0.6b", dest="legacy", action="store_true",
                     help="embed with the old Qwen3-Embedding-0.6B/512d model for a comparison run")
    ap.add_argument("--hosted", action="store_true", help="embed via a hosted API instead of local weights")
    ap.add_argument("--partitions", default=None, help='restrict embed to "era|jur,era|jur"')
    ap.add_argument("--confirm", action="store_true", help="required with --hosted; acknowledges the cost estimate")
    args = ap.parse_args()

    conn = store.connect(Path(args.db))
    store.ensure_schema(conn)

    if args.stage == "fts":
        build_fts(conn, log=print)
        conn.close()
        return 0

    if args.hosted and not args.confirm:
        print("refusing: --hosted requires --confirm (acknowledging the cost estimate)")
        print("estimate: see tools/estimate_embed_cost.py (Task 6)")
        conn.close()
        return 1

    domain = load_domain(args.domain)
    partitions = _parse_partitions(args.partitions)

    if args.hosted:
        spec = domain.embedding
        print("estimate: see tools/estimate_embed_cost.py (Task 6)")
        key = store.env_value(f"{spec.hosted_provider.upper()}_API_KEY")
        if not key:
            sys.exit(f"no {spec.hosted_provider.upper()}_API_KEY in env or .env")
        embedder = HostedEmbedder(spec.hosted_provider, spec.hosted_model_id, spec.dim, key)
        tokenizer = tokenizer_for(spec.model, spec.revision)
        run = EmbedRun.from_spec(spec, provider=spec.hosted_provider)
    elif args.legacy:
        embedder = LocalEmbedder(LEGACY_MODEL, LEGACY_REVISION, LEGACY_DIM)
        tokenizer = embedder.tokenizer
        run = EmbedRun(LEGACY_RUN_KEY, LEGACY_MODEL, LEGACY_REVISION, LEGACY_DIM,
                       "int8-symmetric-pervector", LEGACY_CHUNK_TOKENS, LEGACY_CHUNK_OVERLAP, "", "local")
    else:
        spec = domain.embedding
        embedder = LocalEmbedder(spec.model, spec.revision, spec.dim)
        tokenizer = embedder.tokenizer
        run = EmbedRun.from_spec(spec, provider="local")

    build_embeddings(conn, embedder, tokenizer, run, batch_size=args.batch, limit=args.limit,
                     partitions=partitions, log=print)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
