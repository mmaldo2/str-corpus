import hashlib, json, shutil, sqlite3
import pytest
from corpus_engine.verification import verify_record

def _replay(conn, extractions_dir, run, batch_names):
    out = {}
    for name in batch_names:
        recs = json.loads((extractions_dir / name).read_text(encoding="utf-8"))
        verified = [verify_record(conn, dict(r)) for r in recs]
        out[name] = hashlib.sha256(json.dumps(verified, indent=1).encode("utf-8")).hexdigest()
    return out

def test_verified_files_reproduce_on_fixture_subset(fixture_db, repo_root, golden_dir):
    digests = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["verified"]
    run = "cycle-003-shard-01"
    names = [f"batch-{n:03d}.json" for n in range(1, 6)]
    extractions_dir = repo_root / "tests" / "fixtures" / "extractions" / run
    got = _replay(sqlite3.connect(fixture_db), extractions_dir, run, names)
    assert got == {n: digests[f"{run}/{n}"] for n in names}

@pytest.mark.live_db
def test_verified_files_reproduce_for_all_cycle_003(live_db, repo_root, golden_dir):
    digests = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["verified"]
    conn = sqlite3.connect(live_db)
    for run in ("cycle-003-shard-01", "cycle-003-remap"):
        extractions_dir = repo_root / "runs" / run / "extractions"
        names = sorted(p.name for p in extractions_dir.glob("*.json"))
        got = _replay(conn, extractions_dir, run, names)
        assert got == {n: digests[f"{run}/{n}"] for n in names}, run


def test_verify_record_accepts_list_valued_supports_without_crashing(tmp_path, fixture_db):
    """task-2-review finding 4. `verify_record` used to do
    `supported_ok.add(q["supports"])` directly on the raw value, which raises
    `unhashable type: 'list'` the first time a quote's `supports` is a mapper-v3-style
    list rather than a mapper-v1 bare string."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = sqlite3.connect(p)
    cid = conn.execute(
        "SELECT case_id FROM cases WHERE length(norm_text) > 2000 ORDER BY case_id LIMIT 1"
    ).fetchone()[0]
    raw_text = conn.execute("SELECT raw_text FROM cases WHERE case_id=?", (cid,)).fetchone()[0]
    exact = raw_text[500:620]
    rec = {"case_id": cid, "relevant": True, "polarity": "favorable",
           "characterization": "license", "holding_summary": "x",
           "quotes": [{"text": exact, "supports": ["polarity", "characterization"]}]}
    out = verify_record(conn, dict(rec))
    assert out["polarity"] == "favorable" and out["characterization"] == "license"
    assert out["holding_summary"] is None and out["nulled_fields"] == ["holding_summary"]


def test_verify_record_scopes_the_cascade_by_prompt_version(tmp_path, fixture_db):
    """task-2-review finding 4: the legacy check no longer hardcodes the three-field
    mapper-v1 tuple -- it uses `supported_fields`, keyed on `rec["prompt_version"]`, the
    same rule the ledger's own drop_quote cascade (D7) uses."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = sqlite3.connect(p)
    cid = conn.execute(
        "SELECT case_id FROM cases WHERE length(norm_text) > 2000 ORDER BY case_id LIMIT 1"
    ).fetchone()[0]
    raw_text = conn.execute("SELECT raw_text FROM cases WHERE case_id=?", (cid,)).fetchone()[0]
    exact = raw_text[500:620]
    rec = {"case_id": cid, "relevant": True, "polarity": "favorable",
           "characterization": "license", "holding_summary": "x", "under_thirty_days": "yes",
           "prompt_version": "mapper-v3:deadbeefcafe",
           "quotes": [{"text": exact, "supports": "polarity"}]}
    out = verify_record(conn, dict(rec))
    assert out["polarity"] == "favorable"                    # Q still supports it
    assert out["characterization"] is None and out["holding_summary"] is None
    assert out["under_thirty_days"] is None                  # mapper-v3 widens the cascade to six
    assert set(out["nulled_fields"]) == {"characterization", "holding_summary", "under_thirty_days"}


def test_verify_record_falls_back_to_the_three_field_rule_without_a_prompt_version(tmp_path, fixture_db):
    """Legacy cycle-001..003 extraction records carry no `prompt_version` key at all; the
    fallback must stay the historical mapper-v1 three-field rule so golden replay digests
    do not move."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = sqlite3.connect(p)
    cid = conn.execute(
        "SELECT case_id FROM cases WHERE length(norm_text) > 2000 ORDER BY case_id LIMIT 1"
    ).fetchone()[0]
    raw_text = conn.execute("SELECT raw_text FROM cases WHERE case_id=?", (cid,)).fetchone()[0]
    exact = raw_text[500:620]
    rec = {"case_id": cid, "relevant": True, "polarity": "favorable",
           "characterization": "license", "holding_summary": "x", "under_thirty_days": "yes",
           "quotes": [{"text": exact, "supports": "polarity"}]}
    out = verify_record(conn, dict(rec))
    assert out["polarity"] == "favorable"
    assert out["characterization"] is None and out["holding_summary"] is None
    assert out["under_thirty_days"] == "yes"                 # outside the three-field rule
    assert out["nulled_fields"] == ["characterization", "holding_summary"]
