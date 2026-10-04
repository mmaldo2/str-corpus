"""Supplementary calibration draw (user request 2026-10-04): 50 more guarded pairs from the
c5 band [0.5, 0.6) - 25 Texas Court of Criminal Appeals, 25 from every other court - appended
to calibration-sample.json as pair_ids 200-249, written blind as parts 5 and 6."""
import importlib.util, json, random, sqlite3
from pathlib import Path

ROOT = Path(r"C:/Users/marcu/Desktop/Str-corpus")
spec = importlib.util.spec_from_file_location("mpr", ROOT / "tools" / "merge_parallel_reports.py")
mpr = importlib.util.module_from_spec(spec); spec.loader.exec_module(mpr)
out = ROOT / "runs" / "parallel-reports"

sample = json.loads((out / "calibration-sample.json").read_text(encoding="utf-8"))
assert len(sample) == 200 and max(r["pair_id"] for r in sample) == 199
taken = {(r["winner"], r["loser"]) for r in sample}
band = [r for r in mpr._jsonl(out / "candidates.jsonl")
        if mpr.par.passes_guards(r) and 0.5 <= r["c5"] < 0.6 and (r["winner"], r["loser"]) not in taken]
tx = [r for r in band if r["court"] == "Texas Court of Criminal Appeals"]
rest = [r for r in band if r["court"] != "Texas Court of Criminal Appeals"]
rng = random.Random(20261005)
picked = rng.sample(tx, 25) + rng.sample(rest, 25)
rng.shuffle(picked)
for i, r in enumerate(picked, start=200):
    r["pair_id"] = i
    r["supplement"] = "band-0.5-0.6 (25 Tex. Crim. App. + 25 other courts), user request 2026-10-04"
mpr._write_text(out / "calibration-sample.json", json.dumps(sample + picked, indent=1) + "\n")

conn = sqlite3.connect(f"file:{(ROOT / 'data/db/corpus.db').as_posix()}?mode=ro", uri=True)
for k, part in ((5, picked[:25]), (6, picked[25:])):
    lines = [f"# Calibration pairs, part {k}", ""]
    for r in part:
        texts = dict(conn.execute("SELECT case_id, norm_text FROM cases WHERE case_id IN (?, ?)",
                                  (r["winner"], r["loser"])))
        lines += [f"## pair {r['pair_id']}", f"{r['court']}, {r['year']}: {r['name']}", "",
                  f"### A ({r['winner_cite']})", mpr._excerpt(texts.get(r["winner"], "")), "",
                  f"### B ({r['loser_cite']})", mpr._excerpt(texts.get(r["loser"], "")), ""]
    mpr._write_text(out / f"calibration-pairs-part{k}.md", "\n".join(lines))
print(f"band pool: {len(tx)} Tex. Crim. App. + {len(rest)} other; drew 25 + 25 -> pair_ids 200-249")
