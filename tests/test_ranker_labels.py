import json, pytest
from corpus_engine.ranker.labels import (Label, build_heldout, check_heldout, labelled_reads, load_heldout,
                                         sha256_file, write_heldout)
from tests.helpers.ranker_fixture import make_ranker_db

class _View:
    def __init__(self, rel, reviewed):
        class S: pass
        self.state = S(); self.state.order = list(rel); self.state.in_file = {c: True for c in rel}
        self.state.records = {c: {"relevant": v} for c, v in rel.items()}; self._rev = set(reviewed)
    def reviewed(self, c): return c in self._rev

def test_labelled_reads_rules(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    ids = [r[0] for r in conn.execute("SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 6")]
    a, b, c, d, e, f = ids
    conn.execute("UPDATE cases SET is_duplicate_of=? WHERE case_id=?", (a, f)); conn.commit()
    view = _View({a: True, b: True, c: False}, reviewed={a})          # c: retracted to not-relevant
    ext = [{"case_id": a, "relevant": True}, {"case_id": b, "relevant": False},   # ledger wins over extraction
           {"case_id": c, "relevant": True}, {"case_id": d, "relevant": False},
           {"case_id": e, "relevant": None}, {"case_id": f, "relevant": False}, {"case_id": 424242, "relevant": False}]
    labs = {l.case_id: l for l in labelled_reads(view, ext, conn)}
    assert labs[a].label == 1 and labs[a].weight == 3 and labs[a].reviewed
    assert labs[b].label == 1 and labs[b].weight == 1
    assert labs[c].label == 0 and labs[d].label == 0 and labs[d].weight == 1
    assert e not in labs and f not in labs and 424242 not in labs
    assert labs[a].era and labs[a].jurisdiction

def test_heldout_stratified_frozen_and_checked(tmp_path):
    labs = [Label(i, i % 2, 1.0, False, "pre-1860" if i < 40 else "1860-1900", "Tex." if i % 3 else "N.Y.") for i in range(100)]
    h1 = build_heldout(labs); h2 = build_heldout(labs)
    assert [l.case_id for l in h1] == [l.case_id for l in h2] and 20 <= len(h1) <= 30
    strata = {(l.era, l.jurisdiction, l.label) for l in labs}
    assert all(any((h.era, h.jurisdiction, h.label) == s for h in h1) for s in strata)
    p = tmp_path / "h.jsonl"; write_heldout(p, h1)
    assert load_heldout(p) == h1 and len(sha256_file(p)) == 64
    class D: pass
    dom = D(); dom.ranking = D(); dom.ranking.heldout_sha256 = sha256_file(p)
    assert check_heldout(dom, p) == dom.ranking.heldout_sha256
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        check_heldout(dom, p)

def test_check_heldout_refuses_unpinned_hash(tmp_path):
    p = tmp_path / "h2.jsonl"; write_heldout(p, [Label(1, 1, 1.0, False, "pre-1860", "Tex.")])
    class D: pass
    dom = D(); dom.ranking = D(); dom.ranking.heldout_sha256 = None
    with pytest.raises(ValueError):
        check_heldout(dom, p)
    dom.ranking.heldout_sha256 = ""
    with pytest.raises(ValueError):
        check_heldout(dom, p)


def test_case_partitions_drops_duplicates(tmp_path, fixture_db, repo_root):
    from corpus_engine.store import case_partitions
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    a, b = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 2")]
    conn.execute("UPDATE cases SET is_duplicate_of=? WHERE case_id=?", (a, b)); conn.commit()
    meta = case_partitions(conn, [a, b, 424242])
    assert a in meta and b not in meta and 424242 not in meta
    assert len(meta[a]) == 2


def test_check_heldout_names_the_missing_pin_before_touching_the_file(tmp_path):
    """An unpinned v2 slice fails on the pin, not with FileNotFoundError over an absent file."""
    from types import SimpleNamespace
    dom = SimpleNamespace(ranking=SimpleNamespace(heldout_v2_sha256=None))
    with pytest.raises(ValueError, match="heldout_v2_sha256 is not pinned"):
        check_heldout(dom, tmp_path / "does-not-exist.jsonl", pin="heldout_v2_sha256")
