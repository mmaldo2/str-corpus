"""Freeze a ranker held-out slice (spec section 4). Refuses to overwrite an existing file.

  .venv\\Scripts\\python tools\\build_ranker_heldout.py                       # v1's rule
  .venv\\Scripts\\python tools\\build_ranker_heldout.py --human-only \\
      --out data\\eval\\ranker-heldout-v2.jsonl                               # D3's rule
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                          # noqa: E402
from corpus_engine.domain import load_domain                             # noqa: E402
from corpus_engine.ledger import open_ledger                             # noqa: E402
from corpus_engine.ranker.labels import (HELDOUT_SEED, build_heldout,    # noqa: E402
                                          human_labelled_reads, labelled_reads,
                                          read_extractions, sha256_file, write_heldout)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="build_ranker_heldout.py",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None,
                    help="the file to freeze (default: domain.ranking.heldout for the v1 rule, "
                         "domain.ranking.heldout_v2 with --human-only)")
    ap.add_argument("--human-only", action="store_true",
                    help="D3: build from human relevance decisions alone - human-reviewed "
                         "relevant positives and reviewer-overturned negatives. No "
                         "machine-only label enters the slice.")
    ap.add_argument("--fraction", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=HELDOUT_SEED)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    dom = load_domain()
    pin = "heldout_v2_sha256" if a.human_only else "heldout_sha256"
    default = dom.ranking.heldout_v2 if a.human_only else dom.ranking.heldout
    out = Path(a.out) if a.out else ROOT / default
    if not out.is_absolute():
        out = ROOT / out
    frozen_v1 = (ROOT / dom.ranking.heldout).resolve()
    if a.human_only and out.resolve() == frozen_v1:
        sys.exit(f"{out}: held-out v1 is never edited (spec section 11); "
                 f"pass --out data/eval/ranker-heldout-v2.jsonl")
    if out.exists():
        sys.exit(f"{out} exists; a new slice is a new version, not an overwrite")
    conn = store.connect()
    view = open_ledger(domain=dom).view()
    if a.human_only:
        labels = human_labelled_reads(view, conn)
    else:
        labels = labelled_reads(view, read_extractions(store.paths().runs), conn)
    held = build_heldout(labels, fraction=a.fraction, seed=a.seed)
    write_heldout(out, held)
    pos, hpos = sum(l.label for l in labels), sum(l.label for l in held)
    print(f"candidates: {len(labels)} ({pos} pos / {len(labels) - pos} neg); "
          f"held-out: {len(held)} ({hpos} pos / {len(held) - hpos} neg)")
    strata: dict[tuple, int] = {}
    for l in labels:
        strata[(l.era, l.jurisdiction, l.label)] = strata.get((l.era, l.jurisdiction, l.label), 0) + 1
    taken: dict[tuple, int] = {}
    for l in held:
        taken[(l.era, l.jurisdiction, l.label)] = taken.get((l.era, l.jurisdiction, l.label), 0) + 1
    print(f"{len(strata)} strata, "
          f"{sum(1 for n in strata.values() if n < 2)} skipped for holding fewer than 2")
    for k in sorted(strata):
        print(f"  {k[0]:>10} {k[1]:>6} label={k[2]}: {taken.get(k, 0)} of {strata[k]}")
    print(f"jurisdictions covered: {', '.join(sorted({k[1] for k in taken}))}")
    print("sha256:", sha256_file(out))
    print(f"now set ranking.{pin} in domain.yaml to that value")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
