from __future__ import annotations
import glob, hashlib, json, math, random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

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
    meta: dict[int, tuple] = {}
    for i in range(0, len(wanted), 500):
        chunk = wanted[i:i + 500]; ph = ",".join("?" * len(chunk))
        for cid, era, jur, dup in conn.execute(f"SELECT case_id, era_partition, jurisdiction, is_duplicate_of FROM cases WHERE case_id IN ({ph})", chunk):
            if dup is None:
                meta[cid] = (era, jur)
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


def check_heldout(domain, path: Path) -> str:
    h = sha256_file(path); want = domain.ranking.heldout_sha256
    if not want:
        raise ValueError(f"domain.ranking.heldout_sha256 is not pinned; held-out file {path} is not frozen")
    if h != want:
        raise ValueError(f"held-out file {path} sha256 {h[:12]}… does not match domain.yaml {str(want)[:12]}…; never edit it, make a v2")
    return h
