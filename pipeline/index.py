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
from corpus_engine.indexer.embed import EmbedRun, BudgetExceeded, build_embeddings, estimate_tokens, usd_for_tokens  # noqa: E402
from corpus_engine.indexer.embedders import LocalEmbedder, HostedEmbedder, tokenizer_for  # noqa: E402

# Old model/dim, kept for --legacy-0.6b comparison runs against the current default.
# Revision pinned to what store.migrate recorded for the pre-existing chunks under this
# same run key (store.LEGACY_EMBED_REVISION) -- never "main".
LEGACY_MODEL = "Qwen/Qwen3-Embedding-0.6B"
LEGACY_REVISION = store.LEGACY_EMBED_REVISION
LEGACY_DIM = 512
LEGACY_CHUNK_TOKENS = 1000
LEGACY_CHUNK_OVERLAP = 150
LEGACY_RUN_KEY = store.LEGACY_EMBED_RUN


def _parse_partitions(spec: str | None) -> list[tuple[str, str]] | None:
    if not spec:
        return None
    out = []
    for part in spec.split(","):
        if "|" not in part:
            raise SystemExit("--partitions expects era|jur[,era|jur...]")
        era, jur = part.split("|", 1)
        era, jur = era.strip(), jur.strip()
        if not era or not jur:
            raise SystemExit("--partitions expects era|jur[,era|jur...]")
        out.append((era, jur))
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
    ap.add_argument("--concurrency", type=int, default=4, help="parallel requests for --hosted (default 4)")
    ap.add_argument("--max-usd", dest="max_usd", type=float, default=None,
                     help="stop cleanly after the flush that pushes accumulated spend over this many USD "
                          "(requires the domain's embedding.hosted_usd_per_m_tokens; ignored otherwise)")
    args = ap.parse_args()

    conn = store.connect(Path(args.db))
    store.ensure_schema(conn)
    store.migrate(conn)

    if args.stage == "fts":
        build_fts(conn, log=print)
        conn.close()
        return 0

    domain = load_domain(args.domain)
    partitions = _parse_partitions(args.partitions)
    price = domain.embedding.hosted_usd_per_m_tokens

    # Every embed path is pinned -- no --legacy exemption. The default/hosted paths are
    # pinned via domain.yaml (checked here); the legacy path is pinned by construction
    # (LEGACY_REVISION == store.LEGACY_EMBED_REVISION, never "main").
    if domain.embedding.revision == "main":
        sys.exit("pin the model revision first: tools/estimate_embed_cost.py --pin (Task 6)")

    if args.hosted:
        spec = domain.embedding
        tokenizer = tokenizer_for(spec.model, spec.revision)
        run = EmbedRun.from_spec(spec, provider=spec.hosted_provider)
        cases, tokens = estimate_tokens(conn, tokenizer, run, partitions=partitions)
        usd = usd_for_tokens(tokens, price)
        usd_text = f"${usd:.2f}" if usd is not None else "unknown (embedding.hosted_usd_per_m_tokens not set)"
        print(f"estimate: {cases} cases, ~{tokens:,} tokens, ~{usd_text}")
        if not args.confirm:
            print("refusing: --hosted requires --confirm (acknowledging the cost estimate above)")
            conn.close()
            return 1
        key = store.env_value(f"{spec.hosted_provider.upper()}_API_KEY")
        if not key:
            sys.exit(f"no {spec.hosted_provider.upper()}_API_KEY in env or .env")
        embedder = HostedEmbedder(spec.hosted_provider, spec.hosted_model_id, spec.dim, key,
                                  concurrency=args.concurrency)
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

    try:
        build_embeddings(conn, embedder, tokenizer, run, batch_size=args.batch, limit=args.limit,
                         partitions=partitions, flush_batches=max(8, 2 * args.concurrency),
                         usd_per_m_tokens=price, max_usd=args.max_usd, log=print)
    except BudgetExceeded as exc:
        print(str(exc))
        conn.close()
        return 0

    tokens = getattr(embedder, "tokens_used", None) or 0
    usd = usd_for_tokens(tokens, price)
    print(f"tokens={tokens} usd={usd:.2f}" if usd is not None else f"tokens={tokens}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
