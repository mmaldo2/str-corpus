import json, shutil
from pathlib import Path
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.model import Unit
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.sources import StoreCaseSource

def _unit(batch: dict) -> Unit:
    return Unit(batch["batch_id"], tuple(c["case_id"] for c in batch["cases"]),
                {"batch_id": batch["batch_id"], "era_partition": batch["era_partition"], "jurisdiction": batch["jurisdiction"],
                 "signals": {c["case_id"]: c["signals"] for c in batch["cases"]}})

def test_mapper_v1_codebook_is_the_frozen_prompt(repo_root):
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1")
    assert cb.text.encode("utf-8") == (repo_root / "prompts/mapper.md").read_bytes().replace(b"\r\n", b"\n")
    assert len(cb.sha) == 64 and cb.judged_fields == dom.reader.judged_fields
    v2 = load_codebook(dom, "mapper-v2")
    assert "schema_version" in v2.text and "under_thirty_days" in v2.text and "non_resident_owner" in v2.text and v2.sha != cb.sha

def test_render_reproduces_the_ten_golden_prompts(tmp_path, fixture_db, repo_root, golden_dir):
    # tests/fixtures/corpus-tiny.db is built by tools/build_fixture_corpus.py from only
    # cycle-003-shard-01 batches 001-005 (tests/fixtures/README.md); batches 006-010's
    # cases are not in the fixture store, so only 5 of the ten golden prompts are
    # reproducible here (a "case missing from corpus-tiny.db" per the task brief -
    # reported, not adjusted; extending that fixture is out of this task's scope).
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1"); src = StoreCaseSource(conn)
    n = 0
    for bf in sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json")):
        batch = json.loads(bf.read_text(encoding="utf-8")); u = _unit(batch)
        want = (golden_dir / "prompts/cycle-003-shard-01" / (bf.stem + ".txt")).read_bytes().replace(b"\r\n", b"\n")
        got = render_unit(cb, u, src.fetch(u.case_ids), "claude").encode("utf-8")
        assert got == want, bf.name
        n += 1
    assert n == 5
