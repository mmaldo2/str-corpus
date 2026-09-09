"""Guards on the held-out v2 builder (spec section 4, D3). Nothing here touches the live
ledger or the live store: a fake view supplies the decisions, the tiny fixture store supplies
the era/jurisdiction, and the output goes to tmp_path."""
import importlib.util
import json
from pathlib import Path

import pytest

from corpus_engine.ledger.types import Basis, Patch
from corpus_engine.ranker.labels import (check_heldout, human_labelled_reads,
                                         human_relevance_decisions, load_heldout, sha256_file,
                                         write_heldout, Label)
from tests.helpers.ranker_fixture import make_ranker_db

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_ranker_heldout",
                                               ROOT / "tools" / "build_ranker_heldout.py")
bh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bh)

HUMAN = Basis(reviewer="mmaldo2", run_id="map-cycle-004-round-1")
READER = Basis(model="m@p", prompt_version="mapper-v3:abc", run_id="cycle-004-shard-01")


class _View:
    """The slice of LedgerView the builder actually uses."""

    def __init__(self, records, reviewed=(), patches=()):
        class S:
            pass
        self.state = S()
        self.state.order = list(records)
        self.state.in_file = {c: True for c in records}
        self.state.records = {c: {"relevant": r} for c, r in records.items()}
        self._rev, self.patches = set(reviewed), list(patches)

    def reviewed(self, cid):
        return cid in self._rev


def test_human_relevance_decisions_takes_only_human_decided_records():
    view = _View({1: True, 2: True, 3: False, 4: False},
                 reviewed=[1],
                 patches=[Patch(3, "set", "relevant", False, "overturn", HUMAN),
                          Patch(4, "set", "relevant", False, "reader", READER)])
    pos, neg = human_relevance_decisions(view)
    assert pos == {1}            # 2 is relevant but machine-only
    assert neg == {3}            # 4 was called irrelevant by a machine, not a person


def test_human_labelled_reads_weights_and_marks_both_classes_reviewed(tmp_path, fixture_db,
                                                                      repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    a, b = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 2")]
    view = _View({a: True, b: False}, reviewed=[a],
                 patches=[Patch(b, "set", "relevant", False, "overturn", HUMAN)])
    labs = {l.case_id: l for l in human_labelled_reads(view, conn)}
    assert labs[a].label == 1 and labs[a].weight == 3.0 and labs[a].reviewed is True
    assert labs[b].label == 0 and labs[b].weight == 1.0 and labs[b].reviewed is True
    assert labs[a].era and labs[a].jurisdiction


def test_the_builder_refuses_to_overwrite_and_refuses_the_v1_path(tmp_path):
    out = tmp_path / "v2.jsonl"
    write_heldout(out, [Label(1, 1, 3.0, True, "pre-1860", "N.Y.")])
    with pytest.raises(SystemExit) as exc:
        bh.main(["--out", str(out), "--human-only"])
    assert "is a new version, not an overwrite" in str(exc.value)
    with pytest.raises(SystemExit) as exc:
        bh.main(["--out", "data/eval/ranker-heldout-v1.jsonl", "--human-only"])
    assert "held-out v1 is never edited" in str(exc.value)


def test_check_heldout_reads_the_pin_it_is_given(tmp_path):
    p = tmp_path / "v2.jsonl"
    write_heldout(p, [Label(1, 1, 3.0, True, "pre-1860", "N.Y.")])

    class D:
        pass

    dom = D(); dom.ranking = D()
    dom.ranking.heldout_sha256 = "not-this-one"
    dom.ranking.heldout_v2_sha256 = sha256_file(p)
    assert check_heldout(dom, p, pin="heldout_v2_sha256") == dom.ranking.heldout_v2_sha256
    with pytest.raises(ValueError):
        check_heldout(dom, p)                       # the v1 pin, against the v2 file
    dom.ranking.heldout_v2_sha256 = None
    with pytest.raises(ValueError):
        check_heldout(dom, p, pin="heldout_v2_sha256")


def test_the_builder_writes_a_stratified_frozen_slice_and_reports_its_strata(tmp_path,
                                                                            fixture_db,
                                                                            repo_root, capsys,
                                                                            monkeypatch):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    ids = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 12")]
    records = {c: (i % 2 == 0) for i, c in enumerate(ids)}
    patches = [Patch(c, "set", "relevant", False, "overturn", HUMAN)
               for c, rel in records.items() if not rel]
    view = _View(records, reviewed=[c for c, rel in records.items() if rel], patches=patches)
    monkeypatch.setattr(bh, "open_ledger", lambda **kw: type("L", (), {"view": lambda s: view})())
    monkeypatch.setattr(bh.store, "connect", lambda *a, **kw: conn)
    out = tmp_path / "v2.jsonl"
    report = bh.main(["--out", str(out), "--human-only"])
    assert report == 0 and out.exists()
    rows = load_heldout(out)
    assert rows and all(l.reviewed for l in rows)
    assert out.read_bytes().endswith(b"\n") and b"\r" not in out.read_bytes()
    printed = capsys.readouterr().out
    assert "sha256:" in printed and "heldout_v2_sha256" in printed
