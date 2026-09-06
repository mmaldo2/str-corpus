"""Freeze a reader kit: reference labels, batches, and the case texts inlined.

v1 (2026-09-04) chose its cases: 155 human-reviewed ledger records plus 40 machine-labelled
irrelevant reads. v2 rebuilds THE SAME 195 cases from the patched ledger, so the two kits are
comparable case by case and the only thing that moved is the labels. kit-v1 is never edited:
measurement-v1's numbers are only meaningful against the bytes they were bought over.

Usage:
  .venv\\Scripts\\python tools\\build_reader_kit.py --case-ids-from data/reader/kit-v1/kit.json --out data/reader/kit-v2
"""
from __future__ import annotations
import argparse, hashlib, json, random, sys, time
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                  # noqa: E402
from corpus_engine.domain import load_domain                                     # noqa: E402
from corpus_engine.ledger import open_ledger                                     # noqa: E402
from corpus_engine.ranker.labels import labelled_reads, read_extractions         # noqa: E402
from corpus_engine.reader.measure import KIT_SEED, POLARITY_VALUES, kit_sample_50  # noqa: E402
from corpus_engine.reader.schema import FLAG_PREFIX                              # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                         # noqa: E402

BATCH_SIZE = 18


def case_ids_from(kit_path: Path) -> list[dict]:
    """The cases an existing kit froze, with the source and stratum each was frozen under."""
    kit = json.loads(Path(kit_path).read_text(encoding="utf-8"))
    return [{"case_id": int(r["case_id"]), "source": r["source"], "era": r["era"],
             "jurisdiction": r["jurisdiction"]} for r in kit["reference"]]


def flags_for(records: Mapping[int, dict], case_ids) -> dict[int, list]:
    """R7: the review flags for each case, read where the ledger's fold actually puts them -
    `records[cid]["review"]["flags"]`, not a flat `review.flags` key. A case the ledger has
    never seen, or one with no review block, carries no flags rather than raising."""
    out = {}
    for cid in case_ids:
        rec = records.get(int(cid)) or {}
        review = rec.get("review")
        out[int(cid)] = list((review or {}).get("flags") or ())
    return out


def reference_rows(rows: Sequence[dict], records: Mapping[int, dict],
                   flags: Mapping[int, list]) -> list[dict]:
    """The reference labels for one kit build.

    A human row takes the ledger's current values. `irrelevant` is not a polarity (D2): it
    becomes null, which scoring reads as "the reference did not decide this field", not as a
    value a reader can disagree with. An irrelevant case carries no polarity and no
    who_was_letting at all. A machine row keeps its machine-irrelevant label whatever the
    ledger now says - it is the control sample, scored separately and never toward the bar.
    `excluded_fields` is D6: the fields the reviewer marked unsure, dropped from agreement
    for that field only while the case stays in the kit for fidelity and its other fields."""
    out = []
    for row in rows:
        cid = int(row["case_id"])
        rec = records.get(cid) or {}
        if row["source"] == "human":
            relevant = bool(rec.get("relevant"))
            polarity = rec.get("polarity") if rec.get("polarity") in POLARITY_VALUES else None
            who = rec.get("who_was_letting")
        else:
            relevant, polarity, who = False, None, None
        if not relevant:
            polarity, who = None, None
        excluded = sorted({f[len(FLAG_PREFIX):] for f in (flags.get(cid) or [])
                           if isinstance(f, str) and f.startswith(FLAG_PREFIX)})
        out.append({"case_id": cid, "source": row["source"], "era": row["era"],
                    "jurisdiction": row["jurisdiction"], "relevant": relevant, "polarity": polarity,
                    "who_was_letting": who, "excluded_fields": excluded})
    return out


def make_batches(reference: Sequence[dict], signals: Mapping[int, list], version: str,
                 size: int = BATCH_SIZE) -> list[dict]:
    """Stratum by stratum (era x jurisdiction, sorted), cases in ascending id order, `size`
    to a batch. Deterministic: the same reference and the same signals give the same bytes."""
    groups: dict[tuple, list[int]] = {}
    for r in sorted(reference, key=lambda r: int(r["case_id"])):
        groups.setdefault((r["era"], r["jurisdiction"]), []).append(int(r["case_id"]))
    batches, n = [], 0
    for (era, jur), cids in sorted(groups.items()):
        for j in range(0, len(cids), size):
            n += 1
            batches.append({"batch_id": f"{version}-batch-{n:03d}", "era_partition": era,
                            "jurisdiction": jur,
                            "cases": [{"case_id": c, "signals": list(signals.get(c, []))[:6]}
                                      for c in cids[j:j + size]]})
    return batches


def _signals(conn, ids: Sequence[int]) -> dict:
    sig: dict[int, list] = {}
    for i in range(0, len(ids), 500):
        ch = ids[i:i + 500]
        for cid, sid, ver, mt in conn.execute(
                f"SELECT case_id, selector_id, selector_version, matched_text FROM signals "
                f"WHERE case_id IN ({','.join('?' * len(ch))})", ch):
            sig.setdefault(cid, []).append({"selector_id": sid, "selector_version": ver,
                                            "matched_text": mt or ""})
    return sig


def _fresh_rows(view, conn) -> list[dict]:
    """The v1 selection rule, for a kit built from scratch rather than from an existing one."""
    rows = []
    for cid in view.state.order:
        if view.state.in_file.get(cid) and view.reviewed(cid):
            rows.append({"case_id": int(cid), "source": "human"})
    labels = labelled_reads(view, read_extractions(store.paths().runs), conn)
    neg = [l for l in labels if l.label == 0]
    rng = random.Random(KIT_SEED)
    strata: dict[tuple, list] = {}
    for l in neg:
        strata.setdefault((l.era, l.jurisdiction), []).append(l)
    picked = []
    quota = max(1, 45 // len(strata))
    for k in sorted(strata):
        picked += rng.sample(strata[k], min(quota, len(strata[k])))
    rows += [{"case_id": l.case_id, "source": "machine"} for l in picked[:45]]
    ids = [r["case_id"] for r in rows]
    meta = {r[0]: r for r in conn.execute(
        f"SELECT case_id, era_partition, jurisdiction FROM cases WHERE case_id IN "
        f"({','.join('?' * len(ids))})", ids)}
    for r in rows:
        r["era"], r["jurisdiction"] = meta[r["case_id"]][1], meta[r["case_id"]][2]
    return rows


def _write(path: Path, payload, **dumps) -> bytes:
    """R11: every kit file ends in a newline, and the bytes written are the bytes hashed."""
    raw = (json.dumps(payload, **dumps) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def _guard_output_dir(out_dir: Path) -> None:
    """A new kit is a new version (module docstring): refuse to write into a directory that
    already holds anything, not just one that already holds `kit.json`. The old guard only
    checked `out.exists()` (kit.json itself); deleting just that file and rebuilding left the
    previous build's `batches/` alongside the new one, so a build whose strata packed
    differently would silently ship stale batch files next to a fresh kit.json
    (task-7-review finding 4)."""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"{out_dir} exists and is not empty; a new kit is a new version - "
                         f"remove it first or choose a different --out")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case-ids-from", default=None,
                    help="an existing kit.json; the new kit freezes exactly its cases")
    ap.add_argument("--out", required=True, help="the kit directory, e.g. data/reader/kit-v2")
    a = ap.parse_args()

    out_dir = ROOT / a.out
    out = out_dir / "kit.json"
    _guard_output_dir(out_dir)
    version = out_dir.name
    dom = load_domain()
    conn = store.connect()
    view = open_ledger(domain=dom).view()
    rows = case_ids_from(ROOT / a.case_ids_from) if a.case_ids_from else _fresh_rows(view, conn)
    flags = flags_for(view.state.records, {r["case_id"] for r in rows})
    reference = reference_rows(rows, view.state.records, flags)
    ids = [r["case_id"] for r in reference]
    batches = make_batches(reference, _signals(conn, ids), version)
    texts = {str(t.case_id): {"cite": t.cite, "name": t.name, "court": t.court,
                              "jurisdiction": t.jurisdiction, "year": t.year, "raw_text": t.raw_text,
                              "norm_text": t.norm_text, "page_map": t.page_map}
             for t in StoreCaseSource(conn).fetch(ids)}
    # `built_at` sits inside the bytes `reader.kit_sha256` pins (task-7-review finding 2), so a
    # fresh build's sha never matches a rebuild's - only the *content* is reproducible, not the
    # number domain.yaml carries. Moving `built_at` out of the hashed payload (a sidecar
    # `built.json`, or a hash that excludes it) would change kit-v2's sha and its byte layout,
    # which this fix wave must not do; deferred to slice 2.
    kit = {"version": version, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": KIT_SEED,
           "built_from": a.case_ids_from, "reference": reference, "batches": batches, "texts": texts}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "batches").mkdir(exist_ok=True)
    raw = _write(out, kit, sort_keys=True)
    for b in batches:
        _write(out_dir / "batches" / f"{b['batch_id']}.json", b, indent=1)
    _write(out_dir / "sample-50.json", kit_sample_50(reference))
    excluded = sorted((r["case_id"], r["excluded_fields"]) for r in reference if r["excluded_fields"])
    human = sum(1 for r in reference if r["source"] == "human")
    print(f"kit {version}: {human} human + {len(reference) - human} machine = {len(reference)} cases, "
          f"{len(batches)} batches, {len(excluded)} cases with an excluded field")
    for cid, fields in excluded:
        print(f"  excluded {cid}: {', '.join(fields)}")
    print("sha256:", hashlib.sha256(raw).hexdigest(), "-> set reader.kit_sha256 in domain.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
