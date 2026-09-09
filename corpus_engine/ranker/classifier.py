from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from typing import Sequence
import numpy as np
from corpus_engine.ranker.evaluate import average_precision, evaluate_scores
from corpus_engine.ranker.features import FeatureLayout, case_features, feature_layout
from corpus_engine.ranker.labels import check_heldout
from corpus_engine.ranker.ports import FusionRanker, round6

MODEL_FILE, MANIFEST_FILE = "model.npz", "manifest.json"
C_GRID = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0)


class ClassifierRanker:
    def __init__(self, model_dir: Path):
        self.dir = Path(model_dir)
        self.manifest = json.loads((self.dir / MANIFEST_FILE).read_text(encoding="utf-8"))
        z = np.load(self.dir / MODEL_FILE)
        self.coef, self.intercept, self.mean, self.scale = z["coef"], float(z["intercept"]), z["mean"], z["scale"]
        self.layout = FeatureLayout.from_json(self.manifest["layout"])
        self.ranker_id = self.manifest["ranker_id"]

    @classmethod
    def from_domain(cls, domain, *, version: str | None = None):
        """`data/ranker/<version>`, defaulting to the version domain.yaml pins. `version` is
        only ever the one `load_ranker` has already checked against that pin."""
        from corpus_engine.store import paths
        return cls(paths().root / "data" / "ranker" / (version or domain.ranking.classifier_version))

    def digest(self) -> str:
        return hashlib.sha256((self.dir / MODEL_FILE).read_bytes()).hexdigest()[:16]

    def check_layout(self, current: FeatureLayout) -> None:
        if current != self.layout:
            a, b = self.layout.names, current.names
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    raise ValueError(f"model layout differs from the current selectors/domain at {i}: model {x!r} vs current {y!r}; retrain")
            raise ValueError(f"model layout size {len(a)} vs current {len(b)}; retrain")

    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]:
        ids = [int(c) for c in case_ids]
        X = (case_features(conn, ids, self.layout) - self.mean) / self.scale
        logits = X @ self.coef + self.intercept
        return {c: round6(1.0 / (1.0 + np.exp(-l))) for c, l in zip(ids, logits)}


def train(conn, domain, labels, heldout, *, version: str, out_dir: Path, commit: str,
         layout: FeatureLayout | None = None, heldout_path: Path | None = None,
         heldout_pin: str = "heldout_sha256", extra_rankers: dict | None = None,
         overwrite: bool = False) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from corpus_engine.selector.model import load_selectors
    out_dir = Path(out_dir)
    if (out_dir / MANIFEST_FILE).exists() and not overwrite:
        raise ValueError(f"{out_dir} already holds a trained model; a retrain of a shipped "
                         f"version is a new version, not an overwrite (spec section 9). Pass "
                         f"overwrite=True (tools/train_ranker.py --force) only deliberately.")
    held_ids = {l.case_id for l in heldout}
    overlap = [l.case_id for l in labels if l.case_id in held_ids]
    if overlap:
        raise ValueError(f"training set overlaps the held-out slice ({len(overlap)} ids, e.g. {overlap[:3]})")
    # I-4: the function the spec names, not only the CLI, verifies the held-out slice's
    # hash against domain.yaml before fitting - a caller using the library directly (as
    # tests do) no longer trains against an unverified slice.
    if heldout_path is not None:
        from corpus_engine.store import paths
        h = check_heldout(domain, heldout_path, pin=heldout_pin)
        try:
            rel = Path(heldout_path).resolve().relative_to(paths().root.resolve()).as_posix()
        except ValueError:
            rel = Path(heldout_path).as_posix()
        heldout_manifest = {"path": rel, "sha256": h, "n": len(heldout), "pin": heldout_pin}
    else:
        heldout_manifest = {"n": len(heldout), "pin": None}
    dim = int(dict(conn.execute("SELECT key, value FROM embed_meta")).get("dim", "512"))
    layout = layout or feature_layout(domain, load_selectors(domain), dim)
    ids = [l.case_id for l in labels]; y = np.array([l.label for l in labels]); w = np.array([l.weight for l in labels])
    X = case_features(conn, ids, layout)
    mean = X.mean(axis=0); scale = X.std(axis=0); scale[scale == 0] = 1.0
    Xs = (X - mean) / scale
    best_C, best_ap = None, -1.0
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    for C in C_GRID:
        aps = []
        for tr, va in skf.split(Xs, y):
            m = LogisticRegression(penalty="l2", C=C, class_weight="balanced", max_iter=2000).fit(Xs[tr], y[tr], sample_weight=w[tr])
            aps.append(average_precision(y[va], m.decision_function(Xs[va])))
        if np.mean(aps) > best_ap:
            best_C, best_ap = C, float(np.mean(aps))
    model = LogisticRegression(penalty="l2", C=best_C, class_weight="balanced", max_iter=2000).fit(Xs, y, sample_weight=w)
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(out_dir / MODEL_FILE, coef=model.coef_[0].astype(np.float32), intercept=np.float32(model.intercept_[0]),
             mean=mean.astype(np.float32), scale=scale.astype(np.float32))
    manifest = {"ranker_id": f"classifier:{version}", "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "commit": commit,
                "layout": layout.to_json(), "cv_C": best_C, "cv_ap": best_ap,
                "train": {"n_pos": int(y.sum()), "n_neg": int((1 - y).sum()),
                          "sha256_ids": hashlib.sha256(",".join(map(str, sorted(ids))).encode()).hexdigest()},
                "heldout": heldout_manifest, "metrics": {}}
    (out_dir / MANIFEST_FILE).write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    ranker = ClassifierRanker(out_dir); hid = [l.case_id for l in heldout]
    f = domain.ranking.fusion
    metrics = {"classifier": evaluate_scores(heldout, ranker.score(conn, "train", hid)),
               "fusion": evaluate_scores(heldout,
                                         FusionRanker(layout, f["lexical_weight"],
                                                      f["cosine_weight"]).score(conn, "train",
                                                                                hid))}
    # Every other ranker this run is told to compare against, on the SAME slice and the SAME
    # ids - the shipped classifier v1 in slice 3, so the report can say whether v2 beats what
    # is in the field as well as whether it beats fusion (D6 only tests the latter).
    for name, other in (extra_rankers or {}).items():
        metrics[name] = evaluate_scores(heldout, other.score(conn, "train", hid))
    manifest["metrics"] = metrics
    (out_dir / MANIFEST_FILE).write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    return manifest
