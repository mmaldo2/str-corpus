from corpus_engine.ledger import open_ledger
from corpus_engine.domain import load_domain
from corpus_engine.ledger.fold import (JUDGED_DEFAULT, PROTECTION_FROM_SEQ, apply_patch)
from corpus_engine.ledger.types import UNSET, Basis, Patch


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
    assert v.counts().total.human_reviewed + v.counts().total.machine_only == 2716   # 2795 after round 3b; round 4 overturned relevance on 79 (full text)
    fav = v.counts(polarity="favorable").total
    assert fav.human_reviewed + fav.machine_only == 1229   # 1228 after round 4; round 5b set one polarity favorable
    hh = v.counts(polarity="favorable", who_was_letting="householder").total
    assert hh.human_reviewed + hh.machine_only == 303    # 317 after round 3b; round 4


# ---------------------------------------------------------------- D2: reviewer protection

# The six writes over a reviewer-decided field that the real log already contains, all of
# them below `PROTECTION_FROM_SEQ` and so grandfathered (controller ruling R1):
# (case_id, field, seq, rule).
HISTORICAL = [
    (4268287, "polarity", 7368, "retraction-cascade-v1"),
    (1932707, "polarity", 7372, "retraction-cascade-v1"),
    (2186819, "characterization", 7376, "retraction-cascade-v1"),
    (2186819, "polarity", 7378, "retraction-cascade-v1"),
    (608729, "polarity", 7818, "vocab-v3-cleanup"),
    (10225079, "polarity", 7820, "vocab-v3-cleanup"),
]


def test_the_protection_rule_rejects_nothing_in_the_committed_log(repo_root):
    """Spec section 3's claim, proved over the real 42,984-patch log: no write above the
    grandfather baseline has ever overwritten a human decision, so the new rule changes no
    committed byte. The 161 value-identical re-admit writes are no-ops and must not appear
    here either."""
    v = open_ledger(domain=load_domain()).view()
    assert v.conflicts() == {}
    assert v.state.provenance                                  # it is being tracked at all
    assert v.provenance(v.state.order[0])["relevant"] == "reader"


def test_the_six_historical_overwrites_are_recorded_and_only_recorded(repo_root):
    """R1. They applied when they were written and they still apply; the rule lists them for
    the record, adds no flag, and leaves the rendered bytes alone (see the sha256 replay)."""
    v = open_ledger(domain=load_domain()).view()
    rows = v.conflicts(historical=True)
    got = sorted((cid, c["field"], c["at"], c["by"]["rule_id"])
                 for cid, entries in rows.items() for c in entries)
    assert got == sorted(HISTORICAL)
    assert all(c["historical"] is True and c["attempted"] is None
               for entries in rows.values() for c in entries)
    for cid, field, _, _ in HISTORICAL:
        assert v.provenance(cid)[field] == "human"           # the judgment is not un-made
        assert f"needs-review:{field}" not in v.record(cid)["review"]["flags"]
    assert v.conflicts(4268287, historical=True)[4268287][0]["at"] == 7368
    assert v.conflicts(4268287) == {}                          # not an enforced conflict
    assert v.conflicts(11596913, historical=True) == {}        # a case with no conflict at all


def test_the_committed_log_replays_to_the_same_bytes_under_the_rule(repo_root):
    """The other half of R1: a fresh in-memory replay of data/ledger/patches.jsonl still
    hashes to the committed cycle files, sha256 for sha256. If protection had been enforced
    over history, five records would have moved."""
    import hashlib
    v = open_ledger(domain=load_domain()).view()
    rendered = v.render()
    assert len(rendered) == 4
    for name, data in rendered.items():
        on_disk = (repo_root / "data" / "ledger" / name).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == hashlib.sha256(on_disk).hexdigest(), name


def test_a_patch_above_the_baseline_is_rejected_over_the_real_state(repo_root):
    """The rule is live for everything the slice is about to write. Replayed in memory
    against a deep copy of the committed state: nothing is written, nothing is applied."""
    import copy
    v = open_ledger(domain=load_domain()).view()
    cid, field, _, _ = HISTORICAL[0]
    trial = copy.deepcopy(v.state)
    standing = trial.records[cid][field]
    assert trial.provenance[cid][field] == "human"
    old = apply_patch(trial, Patch(cid, "set", field, "favorable", "slice-3 re-read",
                                   Basis(model="claude-opus-5@claude-cli",
                                         prompt_version="mapper-v3:f92016681314",
                                         run_id="cycles-001-003-reread"),
                                   seq=PROTECTION_FROM_SEQ + 1),
                      judged=JUDGED_DEFAULT)
    assert old is UNSET and trial.records[cid][field] == standing
    entry = trial.conflicts[cid][-1]
    assert entry["historical"] is False and entry["at"] == PROTECTION_FROM_SEQ + 1
    assert f"needs-review:{field}" in trial.records[cid]["review"]["flags"]
    assert v.record(cid)["review"]["flags"] == []               # the real view is untouched


def test_the_protection_rule_leaves_the_published_counts_untouched(repo_root):
    v = open_ledger(domain=load_domain()).view()
    assert v.counts().total.human_reviewed + v.counts().total.machine_only == 2716
    assert v.counts().total.human_reviewed == 821
    flagged = sum(1 for cid in v.state.order
                  for f in (v.state.records[cid].get("review") or {}).get("flags") or ()
                  if f.startswith("needs-review:"))
    assert flagged == 34          # every one of them already in the committed log
