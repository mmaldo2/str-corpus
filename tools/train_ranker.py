r"""Train classifier:<tag> on the labelled reads minus BOTH frozen held-out slices, evaluate
it against the shipped classifier and fusion on one of them, and apply the ship rule (D6).

  .venv\Scripts\python tools\train_ranker.py --heldout v2 --tag v2 --report reports\ranking-v2.md

It never edits domain.yaml. That file carries the comments this project's decisions are
recorded in, and a programmatic rewrite would drop every one of them; the tool prints the one
line to change and the operator makes that edit by hand.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                   # noqa: E402
from corpus_engine.domain import load_domain                                      # noqa: E402
from corpus_engine.ledger import open_ledger                                      # noqa: E402
from corpus_engine.ranker.classifier import ClassifierRanker, train               # noqa: E402
from corpus_engine.ranker.evaluate import ships                                   # noqa: E402
from corpus_engine.ranker.labels import (labelled_reads, load_heldout,            # noqa: E402
                                          read_extractions)

PINS = {"v1": "heldout_sha256", "v2": "heldout_v2_sha256"}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="train_ranker.py", description=__doc__.splitlines()[0])
    ap.add_argument("--tag", "--version", dest="tag", default=None,
                    help="the classifier version this run trains, and the directory it writes "
                         "(data/ranker/<tag>); default: domain.ranking.classifier_version")
    ap.add_argument("--heldout", default="v1", choices=sorted(PINS),
                    help="which frozen slice to EVALUATE on. Both are always excluded from "
                         "training, whichever one is evaluated against.")
    ap.add_argument("--report", default=None, help="write the markdown report here")
    ap.add_argument("--force", action="store_true",
                    help="retrain into a directory that already holds a model")
    return ap


def split_labels(labels, held_v1, held_v2, *, evaluate_on: str):
    """(training set, evaluation slice). BOTH frozen slices leave the training set, whichever
    one is being evaluated: a model trained on v1's rows and graded on v2's would still have
    seen v1's, and the two overlap wherever a v1 case has since been human-decided.

    The evaluation slice is narrowed to the labels this run actually has - a held-out case
    with no label today (a duplicate marked since, a case dropped from the store) is not
    scored rather than scored as a miss."""
    excluded = {l.case_id for l in held_v1} | {l.case_id for l in held_v2}
    train_set = [l for l in labels if l.case_id not in excluded]
    chosen = held_v2 if evaluate_on == "v2" else held_v1
    known = {l.case_id for l in labels}
    return train_set, [l for l in chosen if l.case_id in known]


def write_report(path: Path, *, metrics, tag, heldout, strata, shipped, commit, cv, train) -> None:
    """reports/ranking-<tag>.md: what the slice is made of, the AP table for every ranker
    evaluated, the rule verbatim, and the outcome."""
    rows = [(f"classifier:{tag}", metrics["classifier"])]
    rows += [(name, m) for name, m in sorted(metrics.items())
             if name not in ("classifier", "fusion")]
    rows.append(("fusion:v1", metrics["fusion"]))
    c, f = metrics["classifier"], metrics["fusion"]
    lines = [f"# Ranker {tag}: held-out {heldout['path']}, three-way evaluation, ship rule", "",
             f"**Trained at commit `{commit}`.** Training set: {train['n_pos']} positives / "
             f"{train['n_neg']} negatives, both frozen slices excluded. Cross-validated `C` = "
             f"{cv['cv_C']} (mean AP {cv['cv_ap']:.4f}).", "",
             "## 1. The held-out slice", "",
             f"- Path: `{heldout['path']}` (sha256 `{str(heldout['sha256'])[:12]}...`, pinned "
             f"in domain.yaml as `{heldout['pin']}`).",
             f"- Rows scored: {heldout['n']}. Every row is a human relevance decision (D3): "
             f"human-reviewed relevant positives, reviewer-overturned negatives.",
             "- Because every row is human-decided, the reviewed view "
             "(`reviewed or label == 0`) is the whole slice, so **ap_reviewed equals ap_all** "
             "here and D6's two-view test is arithmetically one view. That is a property of a "
             "slice made only of human labels, not a defect in the rule.", "",
             "### Per-stratum counts", "", "| era \\| jurisdiction \\| label | n |", "|---|---|"]
    lines += [f"| {k} | {strata[k]} |" for k in sorted(strata)]
    lines += ["", "## 2. Average precision on the held-out slice", "",
              "| Ranker | ap_all | ap_reviewed | p50_all | p200_all |", "|---|---|---|---|---|"]
    for name, m in rows:
        lines.append(f"| {name} | {m['ap_all']:.4f} | {m['ap_reviewed']:.4f} | "
                     f"{m['p50_all']:.3f} | {m['p200_all']:.3f} |")
    lines += ["", "## 3. Ship rule (D6)", "",
              f"> classifier {tag} ships as `ranking.default` only if its average precision "
              "exceeds fusion's on BOTH views (all held-out reads, human-reviewed reads). "
              "No margin.", "",
              f"- ap_all: {c['ap_all']:.4f} vs fusion {f['ap_all']:.4f} - "
              f"{'passes' if c['ap_all'] > f['ap_all'] else 'FAILS'}",
              f"- ap_reviewed: {c['ap_reviewed']:.4f} vs fusion {f['ap_reviewed']:.4f} - "
              f"{'passes' if c['ap_reviewed'] > f['ap_reviewed'] else 'FAILS'}", "",
              f"**Outcome: classifier:{tag} " + ("SHIPS" if shipped else "DOES NOT SHIP")
              + ".** " + (f"Set `ranking.classifier_version: {tag}` in domain.yaml; the tail "
                          f"map runs on it."
                          if shipped else
                          "domain.yaml is unchanged: the tail map runs on the existing "
                          "classifier v1 ordering under the same budget (D6)."), "",
              "## 4. Per-cell AP (the evaluated classifier)", "",
              "| Cell | n | ap | p50 |", "|---|---|---|---|"]
    for cell, m in sorted(metrics["classifier"]["per_cell"].items()):
        lines.append(f"| {cell} | {m['n']} | {m['ap']:.4f} | {m['p50']:.3f} |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(lines).replace("\r\n", "\n") + "\n").encode("utf-8"))


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    dom = load_domain()
    tag = a.tag or dom.ranking.classifier_version
    hpath = ROOT / (dom.ranking.heldout_v2 if a.heldout == "v2" else dom.ranking.heldout)
    held_v1 = load_heldout(ROOT / dom.ranking.heldout)
    v2_path = ROOT / dom.ranking.heldout_v2 if dom.ranking.heldout_v2 else None
    held_v2 = load_heldout(v2_path) if v2_path and v2_path.exists() else []
    conn = store.connect()
    labels = labelled_reads(open_ledger(domain=dom).view(),
                            read_extractions(store.paths().runs), conn)
    train_set, evaluated = split_labels(labels, held_v1, held_v2, evaluate_on=a.heldout)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    extra = {}
    shipped_dir = ROOT / "data" / "ranker" / dom.ranking.classifier_version
    if dom.ranking.classifier_version != tag and (shipped_dir / "manifest.json").exists():
        extra[f"classifier:{dom.ranking.classifier_version}"] = ClassifierRanker(shipped_dir)
    man = train(conn, dom, train_set, evaluated, version=tag,
                out_dir=ROOT / "data" / "ranker" / tag, commit=commit, heldout_path=hpath,
                heldout_pin=PINS[a.heldout], extra_rankers=extra, overwrite=a.force)
    c, f = man["metrics"]["classifier"], man["metrics"]["fusion"]
    print(f"train {man['train']} cv_C={man['cv_C']} cv_ap={man['cv_ap']:.4f}")
    print(f"held-out {a.heldout} n={c['n_all']} (reviewed view n={c['n_reviewed']})")
    for name, m in sorted(man["metrics"].items()):
        print(f"  {name:>16}: ap_all={m['ap_all']:.4f} ap_reviewed={m['ap_reviewed']:.4f} "
              f"p50={m['p50_all']:.3f} p200={m['p200_all']:.3f}")
    shipped = ships(c, f)
    print("SHIP RULE (D6):",
          f"classifier:{tag} beats fusion on both views and ships" if shipped
          else f"classifier:{tag} did NOT beat fusion on both views; it does not ship")
    print(f"domain.yaml: {'set ranking.classifier_version to ' + tag if shipped else 'unchanged'}")
    if a.report:
        strata: dict[str, int] = {}
        for l in evaluated:
            key = f"{l.era}|{l.jurisdiction}|{l.label}"
            strata[key] = strata.get(key, 0) + 1
        report = Path(a.report)
        write_report(report if report.is_absolute() else ROOT / report, metrics=man["metrics"],
                     tag=tag, heldout=man["heldout"], strata=strata, shipped=shipped,
                     commit=commit, cv=man, train=man["train"])
        print(f"report -> {a.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
