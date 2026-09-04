"""One-time: freeze the ranker held-out slice (spec §4). Refuses to overwrite an existing file."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                   # noqa: E402
from corpus_engine.domain import load_domain                      # noqa: E402
from corpus_engine.ledger import open_ledger                      # noqa: E402
from corpus_engine.ranker.labels import build_heldout, labelled_reads, read_extractions, sha256_file, write_heldout  # noqa: E402

if __name__ == "__main__":
    dom = load_domain(); out = ROOT / dom.ranking.heldout
    if out.exists():
        sys.exit(f"{out} exists; a new slice is a new version, not an overwrite")
    conn = store.connect()
    labels = labelled_reads(open_ledger(domain=dom).view(), read_extractions(store.paths().runs), conn)
    held = build_heldout(labels); write_heldout(out, held)
    pos = sum(l.label for l in labels); hpos = sum(l.label for l in held)
    print(f"labelled reads: {len(labels)} ({pos} pos / {len(labels) - pos} neg); held-out: {len(held)} ({hpos} pos / {len(held) - hpos} neg)")
    strata = {}
    for l in held:
        strata[(l.era, l.jurisdiction, l.label)] = strata.get((l.era, l.jurisdiction, l.label), 0) + 1
    for k in sorted(strata):
        print(f"  {k[0]:>10} {k[1]:>6} label={k[2]}: {strata[k]}")
    print("sha256:", sha256_file(out)); print("now set ranking.heldout_sha256 in domain.yaml to that value")
