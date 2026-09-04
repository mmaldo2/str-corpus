"""Train classifier:<version> on the labelled reads minus the held-out slice; apply the ship rule (spec §5.4)."""
import argparse, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                                   # noqa: E402
from corpus_engine.domain import load_domain                                      # noqa: E402
from corpus_engine.ledger import open_ledger                                      # noqa: E402
from corpus_engine.ranker.classifier import train                                 # noqa: E402
from corpus_engine.ranker.labels import check_heldout, labelled_reads, load_heldout, read_extractions  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--version", default=None); a = ap.parse_args()
    dom = load_domain(); version = a.version or dom.ranking.classifier_version
    hpath = ROOT / dom.ranking.heldout; check_heldout(dom, hpath); held = load_heldout(hpath)
    conn = store.connect()
    labels = labelled_reads(open_ledger(domain=dom).view(), read_extractions(store.paths().runs), conn)
    held_ids = {l.case_id for l in held}; train_set = [l for l in labels if l.case_id not in held_ids]
    held_present = [l for l in held if l.case_id in {x.case_id for x in labels}]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    man = train(conn, dom, train_set, held_present, version=version, out_dir=ROOT / "data" / "ranker" / version,
               commit=commit, heldout_path=hpath)
    c, f = man["metrics"]["classifier"], man["metrics"]["fusion"]
    print(f"train {man['train']} cv_C={man['cv_C']} cv_ap={man['cv_ap']:.4f}")
    print(f"held-out n={c['n_all']} (reviewed view n={c['n_reviewed']})")
    print(f"  classifier: ap_all={c['ap_all']:.4f} ap_reviewed={c['ap_reviewed']:.4f} p50={c['p50_all']:.3f} p200={c['p200_all']:.3f}")
    print(f"  fusion:     ap_all={f['ap_all']:.4f} ap_reviewed={f['ap_reviewed']:.4f} p50={f['p50_all']:.3f} p200={f['p200_all']:.3f}")
    ships = c["ap_all"] > f["ap_all"] and c["ap_reviewed"] > f["ap_reviewed"]
    print("SHIP RULE:", "classifier becomes the default" if ships else "fusion stays the default (classifier did not beat it on both views)")
    print(f"set ranking.default to {'classifier' if ships else 'fusion'} in domain.yaml")
