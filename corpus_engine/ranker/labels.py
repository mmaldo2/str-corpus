from __future__ import annotations
import glob, hashlib, json, math, random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from corpus_engine.store import case_partitions

HELDOUT_SEED = 20260904
POS_WEIGHT_REVIEWED, POS_WEIGHT_MACHINE, NEG_WEIGHT = 3.0, 1.0, 1.0


@dataclass(frozen=True)
class Label:
    case_id: int; label: int; weight: float; reviewed: bool; era: str; jurisdiction: str


def read_extractions(runs_dir: Path) -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(runs_dir / "*" / "extractions*" / "*.json"))):
        try:
            recs = json.loads(Path(f).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out += [r for r in recs if isinstance(r, dict) and r.get("case_id") is not None] if isinstance(recs, list) else []
    return out


def labelled_reads(view, extraction_records: Iterable[dict], conn) -> list[Label]:
    relevant = {int(c) for c in view.state.order if view.state.in_file.get(c) and view.state.records[c].get("relevant")}
    retracted = {int(c) for c in view.state.order if view.state.in_file.get(c) and view.state.records[c].get("relevant") is False}
    neg = set()
    for r in extraction_records:
        cid = int(r["case_id"])
        if r.get("relevant") is False and cid not in relevant:
            neg.add(cid)
    neg |= retracted - relevant
    wanted = sorted(relevant | neg)
    meta = case_partitions(conn, wanted)
    out = []
    for cid in wanted:
        if cid not in meta:
            continue
        era, jur = meta[cid]
        if cid in relevant:
            rv = bool(view.reviewed(cid))
            out.append(Label(cid, 1, POS_WEIGHT_REVIEWED if rv else POS_WEIGHT_MACHINE, rv, era, jur))
        else:
            out.append(Label(cid, 0, NEG_WEIGHT, False, era, jur))
    return out


def human_relevance_decisions(view) -> tuple[set[int], set[int]]:
    """(confirmed relevant, overturned to irrelevant) - the two label classes of held-out v2.

    D3: positives are records a human reviewed and that stand relevant; negatives are the
    records a reviewer took OUT of the corpus with a reviewer-basis `set relevant False`. A
    machine's `relevant: false` is not a negative here - it is exactly the kind of label the
    slice exists not to grade the ranker against."""
    overturned = {p.case_id for p in view.patches
                  if p.basis.reviewer and p.op == "set" and p.field == "relevant"
                  and p.new is False}
    pos: set[int] = set()
    neg: set[int] = set()
    for cid in view.state.order:
        if not view.state.in_file.get(cid):
            continue
        rec = view.state.records[cid]
        if rec.get("relevant"):
            if view.reviewed(cid):
                pos.add(cid)
        elif rec.get("relevant") is False and cid in overturned:
            neg.add(cid)
    return pos, neg


def human_labelled_reads(view, conn) -> list[Label]:
    """The D3 candidate pool: every human relevance decision, as a `Label`.

    `reviewed=True` on BOTH classes, because both are human decisions. One consequence worth
    knowing before reading the numbers: `evaluate_scores`'s reviewed view is
    `reviewed or label == 0`, so on this slice it is the whole slice and `ap_reviewed` equals
    `ap_all`. D6's two-view test is then arithmetically one view - a property of a slice made
    entirely of human labels, not a defect."""
    pos, neg = human_relevance_decisions(view)
    meta = case_partitions(conn, pos | neg)
    out = []
    for cid in sorted(pos | neg):
        if cid not in meta:
            continue
        era, jur = meta[cid]
        if cid in pos:
            out.append(Label(cid, 1, POS_WEIGHT_REVIEWED, True, era, jur))
        else:
            out.append(Label(cid, 0, NEG_WEIGHT, True, era, jur))
    return out


def build_heldout(labels: list[Label], *, fraction: float = 0.25, seed: int = HELDOUT_SEED) -> list[Label]:
    rng = random.Random(seed); strata: dict[tuple, list[Label]] = {}
    for l in sorted(labels, key=lambda l: l.case_id):
        strata.setdefault((l.era, l.jurisdiction, l.label), []).append(l)
    out = []
    for key in sorted(strata):
        members = strata[key]
        k = math.ceil(len(members) * fraction) if len(members) >= 2 else 0
        out += rng.sample(members, k)
    return sorted(out, key=lambda l: l.case_id)


def write_heldout(path: Path, labels: list[Label]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes("".join(json.dumps(asdict(l), sort_keys=True) + "\n" for l in labels).encode("utf-8"))


def load_heldout(path: Path) -> list[Label]:
    return [Label(**json.loads(line)) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_heldout(domain, path: Path, *, pin: str = "heldout_sha256") -> str:
    """The frozen slice's sha, verified against the domain key `pin`.

    `pin` names WHICH slice is being checked (`heldout_sha256` for v1, `heldout_v2_sha256` for
    v2), so one function guards both and neither can be trained against unverified."""
    want = getattr(domain.ranking, pin, None)
    if not want:
        # Pin first, hash second: an unpinned slice must say so even when its file is absent.
        raise ValueError(f"domain.ranking.{pin} is not pinned; held-out file {path} is not frozen")
    h = sha256_file(path)
    if h != want:
        raise ValueError(f"held-out file {path} sha256 {h[:12]}… does not match domain.yaml "
                         f"{pin} {str(want)[:12]}…; never edit it, make a new version")
    return h
