from corpus_engine.ledger import open_ledger
from corpus_engine.domain import load_domain
from corpus_engine.ledger.fold import JUDGED_DEFAULT


def test_committed_log_renders_to_the_committed_snapshot(repo_root):
    v = open_ledger(domain=load_domain()).view()
    rendered = v.render()
    for name, data in rendered.items():
        on_disk = (repo_root / "data" / "ledger" / name).read_bytes().replace(b"\r\n", b"\n")
        assert data == on_disk, name


def test_the_rename_leaves_the_committed_counts_and_the_replay_untouched(repo_root):
    """D7 renames two names nothing ever wrote. If the rename had touched data, one of these
    three numbers would move; the byte-identical replay above is the other half of the proof."""
    dom = load_domain()
    assert "under_thirty_days" in dom.judged_fields
    assert "owner_freedom_characterization" in dom.judged_fields
    assert "under_30_days" not in dom.judged_fields
    assert "right_characterization" not in dom.judged_fields
    assert tuple(dom.judged_fields) == JUDGED_DEFAULT
    log = (repo_root / "data" / "ledger" / "patches.jsonl").read_text(encoding="utf-8")
    assert "under_30_days" not in log and "right_characterization" not in log
    v = open_ledger(domain=dom).view()
    assert v.counts().total.human_reviewed + v.counts().total.machine_only == 2939   # 693 before the cycle-004 map admission (2026-09-06): +2,246 relevant machine-only
    fav = v.counts(polarity="favorable").total
    assert fav.human_reviewed + fav.machine_only == 1259   # 1261 after the map admission; 2 favorable -> adverse in review round 1
    hh = v.counts(polarity="favorable", who_was_letting="householder").total
    assert hh.human_reviewed + hh.machine_only == 325    # 326 after the map admission; 1 householder reclassified in review round 1
