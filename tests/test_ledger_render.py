import json
from corpus_engine.ledger.render import dumps_record, render_cycle, parse_cycle

def test_render_matches_json_dumps_defaults_and_preserves_key_order():
    rec = {"case_id": 1, "cite": "quâ boarder", "review": {"status": "machine", "flags": [], "notes": []}}
    assert dumps_record(rec) == json.dumps(rec)
    assert dumps_record(rec).startswith('{"case_id": 1, "cite": "qu\\u00e2 boarder"')

def test_render_cycle_round_trips_committed_ledger(repo_root):
    data = (repo_root / "data/ledger/cycle-001.jsonl").read_bytes().replace(b"\r\n", b"\n")
    assert render_cycle(parse_cycle(data)) == data
