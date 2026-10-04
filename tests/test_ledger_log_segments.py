"""The patch log as numbered segments (spec 2026-10-04 section 5)."""
import json
import pytest
from corpus_engine.domain import load_domain
from corpus_engine.evaluation.summary import ledger_content_sha256
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.log import PatchLog, log_files
from corpus_engine.ledger.types import Basis, LedgerError, Patch


def _p(i: int) -> Patch:
    return Patch(i, "set", "polarity", "adverse", f"why {i}", Basis(reviewer="m"))


def test_appends_rotate_at_the_cap_and_read_back_in_seq_order(tmp_path):
    log = PatchLog(tmp_path / "patches", cap_bytes=600)
    log.append([_p(1), _p(2)])
    assert [p.name for p in log.segments()] == ["0001.jsonl"]
    while log.segments()[-1].stat().st_size < 600:
        log.append([_p(9)])
    n_before = log.head()
    log.append([_p(3), _p(4)])
    assert [p.name for p in log.segments()] == ["0001.jsonl", "0002.jsonl"]
    assert [p.seq for p in log.read()] == list(range(1, n_before + 3))
    assert log.head() == n_before + 2
    first = json.loads((tmp_path / "patches" / "0002.jsonl").read_text().splitlines()[0])
    assert first["seq"] == n_before + 1          # segment 2 starts where segment 1 ended


def test_one_append_never_spans_two_segments(tmp_path):
    log = PatchLog(tmp_path / "patches", cap_bytes=300)
    log.append([_p(i) for i in range(1, 11)])    # far over the cap in one append
    assert [p.name for p in log.segments()] == ["0001.jsonl"]
    assert log.head() == 10


def test_an_empty_append_writes_nothing(tmp_path):
    log = PatchLog(tmp_path / "patches")
    assert log.append([]) == []
    assert not (tmp_path / "patches").exists()


def test_an_unmigrated_ledger_is_refused_not_restarted(tmp_path):
    """Review focus 1: a directory still holding the old single file must not open as an
    empty segmented log - the next apply would restart the seqs at 1."""
    (tmp_path / "patches.jsonl").write_text(json.dumps({"seq": 1}) + "\n", encoding="utf-8")
    with pytest.raises(LedgerError, match="split_patch_log"):
        PatchLog(tmp_path / "patches").read()
    with pytest.raises(LedgerError, match="split_patch_log"):
        PatchLog(tmp_path / "patches").append([_p(1)])
    with pytest.raises(LedgerError):
        open_ledger(tmp_path, domain=load_domain()).view()
    assert not (tmp_path / "patches").exists()


def test_both_layouts_in_one_directory_are_refused(tmp_path):
    (tmp_path / "patches.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "patches").mkdir()
    (tmp_path / "patches" / "0001.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(LedgerError, match="both"):
        log_files(tmp_path)


def test_the_content_hash_is_the_same_split_or_whole(tmp_path):
    whole, split = tmp_path / "whole", tmp_path / "split"
    for d in (whole, split):
        d.mkdir()
        (d / "cycle-001.jsonl").write_bytes(b'{"b":2}\n')
    (whole / "patches.jsonl").write_bytes(b'{"a":1}\n{"a":2}\n{"a":3}\n')
    (split / "patches").mkdir()
    (split / "patches" / "0001.jsonl").write_bytes(b'{"a":1}\n{"a":2}\n')
    (split / "patches" / "0002.jsonl").write_bytes(b'{"a":3}\n')
    assert ledger_content_sha256(whole) == ledger_content_sha256(split)


def test_a_ledger_applies_through_segments(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    rec = {"case_id": 1, "cite": "1 X", "year": 1850, "relevant": True, "polarity": "favorable",
           "who_was_letting": "householder", "duration_of_occupancy": "nights",
           "characterization": "lodging", "holding_summary": "h",
           "quotes": [{"text": "q", "supports": "polarity"}], "extraction_status": "ok"}
    res = led.apply([Patch(1, "admit", "", rec, "v",
                           Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")],
                    note="seed")
    assert res.replay_ok
    assert (tmp_path / "patches" / "0001.jsonl").exists()
    assert not (tmp_path / "patches.jsonl").exists()
    assert led.log.head() == 1


def test_a_seq_gap_between_segments_is_refused(tmp_path):
    log = PatchLog(tmp_path / "patches")
    log.append([_p(1), _p(2)])
    seg2 = tmp_path / "patches" / "0002.jsonl"
    late = log.read()[-1]
    from dataclasses import replace
    seg2.write_text(json.dumps(replace(late, seq=5).to_json()) + "\n", encoding="utf-8")
    with pytest.raises(LedgerError, match=r"seq 3 is missing.*0001\.jsonl.*0002\.jsonl"):
        log.read()
