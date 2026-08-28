# STR Historical Corpus Pipeline

Agentic MapReduce over the American case law record, recovering historical
authority on the right to let one's property short-term. Spec:
`sprint-one-handoff-corpus-pipeline (1).md` (including the dated Amendments
block, which governs on conflict); legal context:
`str-property-rights-corpus-research (1).md`.

## Reproduce from a clean machine

```powershell
python -m venv .venv                       # Python 3.11
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python pipeline\download.py  # static.case.law volume zips -> data/raw/  (~20 GB)
.venv\Scripts\python pipeline\ingest.py    # HTML casebody -> data/db/corpus.db
.venv\Scripts\python pipeline\index.py     # FTS5 + Qwen3-Embedding-0.6B (GPU)
.venv\Scripts\python pipeline\build_gold.py
.venv\Scripts\python -m pytest tests\
# STOP: human review of selectors/selectors.yaml before any shard run
.venv\Scripts\python pipeline\shard.py --run-id cycle-001-shard-01
# Map/Reduce driver: see runs/README (headless claude CLI + codex checker)
.venv\Scripts\python pipeline\verify_quotes.py --run-id <run>
.venv\Scripts\python pipeline\eval_recall.py --run-id <run>
```

## Layout

Per spec §3. `selectors/selectors.yaml` is the load-bearing versioned artifact;
never edit a selector in place past a shard run — bump `version`. `data/raw`
and `data/db` are gitignored; `data/raw/manifest.jsonl` records exactly which
volume zips (URL, sha256, bytes) were ingested, for reproducibility.
