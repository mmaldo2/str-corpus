"""Draw the frozen audit sample (spec §4.1): 150 machine-only relevant records, simple random,
seeded, with the judged record at draw time, the opinion texts, and a blind audit queue.

  PYTHONPATH=. .venv/Scripts/python tools/draw_audit_sample.py --seed 20260912 --n 150 --out runs/audit-cycle-004

Never rewrites an existing --out directory: a redraw is a new directory."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import random
import subprocess
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from corpus_engine.domain import load_domain                 # noqa: E402
from corpus_engine.ledger import open_ledger                 # noqa: E402
from corpus_engine.evaluation.summary import ledger_content_sha256   # noqa: E402
from export_review_cards import write_text        # noqa: E402

RUN_ID = "audit-cycle-004"
DECIDE_FIELDS = ["relevant", "polarity", "who_was_letting"]
JUDGED = ("relevant", "polarity", "who_was_letting", "duration_of_occupancy", "characterization",
          "under_thirty_days", "owner_freedom_characterization", "restriction_nature")
BAND = 0.05


def _in_frame(view, cid: int) -> bool:
    """The audit frame (spec §4.1): relevant, and not yet reached by a human reviewer. One
    predicate, so `draw()` (the frame it samples from) and `main()` (the frame it fetches
    opinion text for) can never quietly diverge on what counts."""
    rec = view.state.records[cid]
    return rec.get("relevant") is True and not rec.get("duplicate_of") and not view.reviewed(cid)


def _band(score: float) -> str:
    # Plain `score // BAND` is float-imprecise at exact band edges (0.5 // 0.05 == 9.0, not
    # 10.0, because 0.05 has no exact binary representation) - a tiny epsilon before flooring
    # keeps a score that IS a band edge in the band it names rather than the one below it.
    lo = math.floor(score / BAND + 1e-9) * BAND
    return f"{lo:.2f}-{lo + BAND:.2f}"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def draw(view, *, seed: int, n: int, texts: Mapping[int, str], scores: Mapping[int, float],
         cells: Mapping[int, str], head_seq: int, content_sha256: str, tool_revision: str,
         brief_sha256: str, drawn_at: str) -> tuple[dict, dict]:
    frame = sorted(cid for cid in view.state.order if _in_frame(view, cid))
    if n > len(frame):
        raise ValueError(f"the frame has {len(frame)} records; cannot draw {n}")
    ids = random.Random(seed).sample(frame, n)
    records, cards = [], []
    for cid in ids:
        r = view.state.records[cid]
        basis = ((r.get("review") or {}).get("basis") or {})
        records.append({"case_id": cid,
                        "record": {**{f: r.get(f) for f in JUDGED}, "quotes": list(r.get("quotes") or ()),
                                   "holding_summary": r.get("holding_summary")},
                        "reader_run_id": basis.get("run_id"), "prompt_version": basis.get("prompt_version"),
                        "rank_score": scores.get(cid), "band": _band(float(scores.get(cid) or 0.0)),
                        "cell": cells.get(cid), "opinion_sha256": _sha(texts[cid])})
        cards.append({"case_id": cid, "section": "H", "reason": "audit_sample", "other_reasons": [],
                      "decide_fields": list(DECIDE_FIELDS), "cite": r.get("cite"), "name": r.get("name"),
                      "court": r.get("court"), "jur": r.get("jurisdiction"), "year": r.get("year")})
    manifest = {"drawn_at": drawn_at, "ledger_head_seq": head_seq, "ledger_content_sha256": content_sha256,
                "frame_size": len(frame), "frame_sha256": _sha("\n".join(map(str, frame))), "seed": seed,
                "method": "random.Random(seed).sample", "n": n, "tool_revision": tool_revision,
                "brief_sha256": brief_sha256, "records": records}
    queue = {"run_id": RUN_ID, "cap": n, "titles": {"H": "Audit sample: relevance, polarity, who was letting"},
             "sections": {"H": cards}, "deferred": []}
    return manifest, queue


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True); ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--out", default=f"runs/{RUN_ID}")
    ap.add_argument("--brief", default="reports/review-audit-brief.md")
    ap.add_argument("--pool-run", default="cycle-004-shard-02", help="run whose batches carry rank scores")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists():
        sys.exit(f"{out} exists; a redraw is a new directory")
    from corpus_engine import store
    from corpus_engine.reader.sources import StoreCaseSource
    dom = load_domain(); led = open_ledger(domain=dom); view = led.view()
    frame_ids = [cid for cid in view.state.order if _in_frame(view, cid)]
    conn = store.connect()
    texts = {t.case_id: t.norm_text for t in StoreCaseSource(conn).fetch(frame_ids)}
    scores, cells = {}, {}
    for p in sorted((ROOT / "runs" / a.pool_run / "batches").glob("batch-*.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        for c in b.get("cases") or ():
            scores[int(c["case_id"])] = c.get("rank_score"); cells[int(c["case_id"])] = f"{b['era_partition']}|{b['jurisdiction']}"
    for cid in frame_ids:                                  # records from earlier cycles: cell from the store row
        if cid not in cells:
            row = conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE case_id=?", (cid,)).fetchone()
            cells[cid] = f"{row[0]}|{row[1]}" if row else None
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    from datetime import datetime, timezone
    manifest, queue = draw(view, seed=a.seed, n=a.n, texts=texts, scores=scores, cells=cells,
                           head_seq=led.log.head(), content_sha256=ledger_content_sha256(led.dir),
                           tool_revision=rev, brief_sha256=hashlib.sha256(Path(a.brief).read_bytes()).hexdigest(),
                           drawn_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    write_text(out / "sample-manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False))
    write_text(out / "audit-queue.json", json.dumps(queue, indent=1, ensure_ascii=False))
    for r in manifest["records"]:
        write_text(out / "opinions" / f"{r['case_id']}.txt", texts[r["case_id"]])
    print(f"frame {manifest['frame_size']} (sha {manifest['frame_sha256'][:12]}), drew {a.n} with seed {a.seed} "
          f"at seq {manifest['ledger_head_seq']} -> {out.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
