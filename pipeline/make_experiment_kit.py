"""Export a self-contained mapper-model experiment kit OUTSIDE the repo.

The kit lets another agent/model run the extraction task on a few already-
mapped batches with zero access to the repo, the database, or credentials:
opinion texts are inlined, Sonnet's verified outputs are included as the
reference, and a standalone scorer (verbatim-quote fidelity, field
agreement, schema compliance) needs nothing but the kit itself.

Usage: python pipeline/make_experiment_kit.py --out C:/.../str-mapper-experiment
           [--run-id cycle-001-shard-02] [--batches 5] [--small 5]
"""

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", default="cycle-001-shard-02")
    ap.add_argument("--batches", type=int, default=5)
    ap.add_argument("--small", type=int, default=5, help="cases per small sub-batch")
    a = ap.parse_args()
    out = Path(a.out)
    for d in ("prompts", "batches", "batches_small", "reference", "outputs", "lib"):
        (out / d).mkdir(parents=True, exist_ok=True)

    shutil.copy(ROOT / "prompts" / "mapper.md", out / "prompts" / "mapper.md")
    shutil.copy(ROOT / "pipeline" / "textnorm.py", out / "lib" / "textnorm.py")

    conn = sqlite3.connect(DB)
    run = ROOT / "runs" / a.run_id
    chosen = sorted((run / "batches").glob("batch-*.json"))[: a.batches]
    manifest = []
    for bf in chosen:
        batch = json.loads(bf.read_text(encoding="utf-8"))
        cases_out = []
        for c in batch["cases"]:
            r = conn.execute(
                "SELECT cite, name_abbreviation, court, jurisdiction, decision_year, raw_text "
                "FROM cases WHERE case_id=?", (c["case_id"],)).fetchone()
            if not r:
                continue
            cases_out.append({
                "case_id": c["case_id"], "cite": r[0], "name": r[1], "court": r[2],
                "jurisdiction": r[3], "year": r[4],
                "signals": [{"selector_id": s["selector_id"],
                             "matched_text": s["matched_text"][:200]} for s in c["signals"]],
                "opinion_text": r[5],
            })
        kit_batch = {"batch_id": batch["batch_id"], "era_partition": batch["era_partition"],
                     "jurisdiction": batch["jurisdiction"], "cases": cases_out}
        (out / "batches" / bf.name).write_text(json.dumps(kit_batch, indent=1), encoding="utf-8")
        # small sub-batches for context-limited local models
        for i in range(0, len(cases_out), a.small):
            sub = {**kit_batch, "batch_id": f"{batch['batch_id']}-part{i//a.small+1}",
                   "cases": cases_out[i : i + a.small]}
            (out / "batches_small" / f"{bf.stem}-part{i//a.small+1}.json").write_text(
                json.dumps(sub, indent=1), encoding="utf-8")
        ref = run / "verified" / bf.name
        if ref.exists():
            shutil.copy(ref, out / "reference" / f"{bf.stem}.sonnet.json")
        manifest.append({"batch": bf.name, "cases": len(cases_out),
                         "chars": sum(len(c["opinion_text"]) for c in cases_out)})

    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "score.py").write_text(SCORER, encoding="utf-8")
    (out / "README.md").write_text(README, encoding="utf-8")
    print(f"kit -> {out}: {len(chosen)} batches, "
          f"{sum(m['cases'] for m in manifest)} cases, "
          f"{sum(m['chars'] for m in manifest)//1000}k chars of opinion text")
    return 0


SCORER = r'''"""Score a candidate model's extractions against the kit.

    python score.py outputs/<model>/            # scores every batch-*.json in the dir

Metrics per batch and overall:
  schema     every case in the batch has a record with required fields
  quotes     verbatim fidelity: exact / fuzzy(>=92) / failed, against the inlined
             opinion text (same normalization as the real pipeline)
  agreement  relevant / polarity / characterization vs Sonnet reference
No database, no network, no credentials required.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
from textnorm import normalize_text
try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

REQ = {"case_id", "relevant", "polarity", "quotes"}

def quote_status(q, norm_text):
    qn = normalize_text(q or "")
    if not qn: return "failed"
    if qn in norm_text: return "exact"
    if fuzz is None: return "failed"
    n = len(qn); best = 0.0; step = max(20, n // 4)
    for pos in range(0, max(1, len(norm_text) - n + 1), step):
        s = fuzz.partial_ratio(qn, norm_text[pos:pos + n + step])
        if s > best: best = s
        if best == 100: break
    return "fuzzy" if best >= 92 else "failed"

def main():
    outdir = Path(sys.argv[1])
    kit = Path(__file__).parent
    tot = {"cases": 0, "records": 0, "missing": 0, "bad_schema": 0,
           "exact": 0, "fuzzy": 0, "failed": 0, "agree": {}, "compared": {}}
    for f in sorted(outdir.glob("batch-*.json")):
        stem = f.stem.split("-part")[0]
        batch_file = kit / "batches" / f"{stem}.json"
        if not batch_file.exists():
            print("no kit batch for", f.name); continue
        batch = json.loads(batch_file.read_text(encoding="utf-8"))
        texts = {c["case_id"]: normalize_text(c["opinion_text"]) for c in batch["cases"]}
        want = set(texts) if "-part" not in f.stem else None
        try:
            recs = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"{f.name}: INVALID JSON"); continue
        recs = [r for r in recs if isinstance(r, dict)]
        got = {r.get("case_id") for r in recs}
        if want is not None:
            tot["cases"] += len(want); tot["missing"] += len(want - got)
        tot["records"] += len(recs)
        ref_file = kit / "reference" / f"{stem}.sonnet.json"
        ref = {r["case_id"]: r for r in json.loads(ref_file.read_text(encoding="utf-8"))} if ref_file.exists() else {}
        for r in recs:
            if not REQ <= set(r): tot["bad_schema"] += 1
            nt = texts.get(r.get("case_id"), "")
            for q in r.get("quotes") or []:
                tot[quote_status(q.get("text") if isinstance(q, dict) else q, nt)] += 1
            rr = ref.get(r.get("case_id"))
            if rr:
                for fld in ("relevant", "polarity", "characterization"):
                    tot["compared"][fld] = tot["compared"].get(fld, 0) + 1
                    if r.get(fld) == rr.get(fld):
                        tot["agree"][fld] = tot["agree"].get(fld, 0) + 1
    q = tot["exact"] + tot["fuzzy"] + tot["failed"]
    print(json.dumps({
        "records": tot["records"], "cases_expected": tot["cases"],
        "missing_cases": tot["missing"], "bad_schema_records": tot["bad_schema"],
        "quotes": {"total": q, "exact": tot["exact"], "fuzzy": tot["fuzzy"],
                   "failed": tot["failed"],
                   "verified_rate": round((tot["exact"] + tot["fuzzy"]) / q, 3) if q else None},
        "agreement_vs_sonnet": {k: round(tot["agree"].get(k, 0) / v, 3)
                                for k, v in tot["compared"].items()},
    }, indent=1))

if __name__ == "__main__":
    main()
'''

README = r'''# Mapper-model experiment kit

Self-contained. Nothing here needs the main repo, its database, or any
credential. Purpose: test whether a cheaper API model or a local model can
do the extraction job the pipeline currently gives to Claude Sonnet.

## What's here
- `prompts/mapper.md` — the exact extraction instructions the production
  mappers receive. Use it VERBATIM for every candidate model.
- `batches/batch-NNN.json` — 5 real batches (18 cases each) with full opinion
  text inlined (`cases[].opinion_text`) plus retrieval provenance.
- `batches_small/` — the same cases split into 5-case sub-batches, for
  models with limited context (e.g. a local ~64k-context model).
- `reference/batch-NNN.sonnet.json` — Sonnet's outputs for the same batches,
  after the pipeline's verbatim-quote gate. The comparison target.
- `score.py` + `lib/textnorm.py` — standalone scorer (see below).
- `outputs/` — write candidate outputs here: `outputs/<model-name>/batch-NNN.json`
  (or `batch-NNN-partK.json` when using the small sub-batches). Each file:
  a JSON array of records exactly as `mapper.md` specifies, with
  `"worker": "<model-name>"`.

## How to run a candidate
For each batch file: build the prompt = `mapper.md` + a header line naming
the batch, then for each case a section with its case_id, cite/name/court/
year, provenance, and `### Opinion text` followed by `opinion_text`. Send
to the model; save the JSON array it returns. Do not edit model output —
the scorer measures raw compliance.

## How to score
    pip install rapidfuzz          # optional; enables the fuzzy tier
    python score.py outputs/<model-name>/

Reports: schema compliance (every case accounted, required fields present),
verbatim-quote fidelity (exact / fuzzy>=92 / failed against the inlined
opinion text — the production gate), and field agreement with Sonnet on
relevant / polarity / characterization.

## What "good enough" looks like
Sonnet in production: ~99.5% of quotes pass the gate (exact+fuzzy), 0
schema failures, every case accounted. A candidate is interesting if it
keeps quote fidelity above ~97% and agreement above ~85%; below that, the
re-map cost of voided records erases any per-token savings.

## Rules
- Keep all outputs inside this folder. Do NOT write into the main repo.
- Same prompt for every model; no per-model prompt tuning in the first pass.
'''


if __name__ == "__main__":
    sys.exit(main())
