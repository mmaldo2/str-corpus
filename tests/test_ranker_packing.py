import json
from corpus_engine.selector.packing import build_batches, pack_batches
from corpus_engine.ranker.ports import NullRanker
from tests.helpers.ranker_fixture import make_ranker_db

class _Const:
    ranker_id = "const:test"
    def __init__(self, table): self.t = table
    def digest(self): return "abc"
    def score(self, conn, run_id, ids): return {i: self.t.get(i, 0.0) for i in ids}

def _case_ids_by_cell(batches):
    # Batches for the same (era, jurisdiction) cell can land at different positions in
    # the overall list depending on the batch-level sort key (legacy: max density;
    # scored: mean score) - those two keys are not equivalent whenever a cell's
    # per-case scores are non-uniform, so overall list position is not a guaranteed
    # invariant. What NullRanker does guarantee - because its score equals legacy's
    # per-case density exactly - is the within-cell case order (and, for a cell split
    # across multiple chunks, the relative order of those chunks, since chunks of one
    # cell are internally score-descending regardless of how other cells interleave
    # around them). Concatenating a cell's batches in list order reconstructs that.
    out: dict = {}
    for b in batches:
        out.setdefault((b["era_partition"], b["jurisdiction"]), []).extend(c["case_id"] for c in b["cases"])
    return out

def test_null_ranker_reproduces_legacy_order_and_writes_rankings(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    legacy = build_batches(conn, "r", gold_ids=set(), exclude_ids=set())
    ranked = build_batches(conn, "r", gold_ids=set(), exclude_ids=set(), ranker=NullRanker(), ts="t")
    assert _case_ids_by_cell(ranked) == _case_ids_by_cell(legacy)
    assert all(b["ranker_id"] == "null" for b in ranked) and all("rank_score" in c for b in ranked for c in b["cases"])
    n = conn.execute("SELECT count(*) FROM rankings WHERE run_id='r' AND ranker_id='null'").fetchone()[0]
    assert n == sum(len(b["cases"]) for b in legacy)
    assert "ranker_id" not in legacy[0] and "rank_score" not in legacy[0]["cases"][0]

def test_scores_order_cells_and_batches_with_six_place_rounding(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    pool = [r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals ORDER BY case_id")]
    table = {cid: 0.5 for cid in pool}; table[pool[0]] = 0.5 + 1e-9; table[pool[-1]] = 0.9      # tie after rounding
    out = build_batches(conn, "r", gold_ids=set(), exclude_ids=set(), ranker=_Const(table), ts="t")
    cell = next(b for b in out if any(c["case_id"] == pool[-1] for c in b["cases"]))
    assert cell["cases"][0]["case_id"] == pool[-1] and cell["cases"][0]["rank_score"] == 0.9
    same = [c for b in out for c in b["cases"] if c["rank_score"] == 0.5]
    assert any(c["case_id"] == pool[0] for c in same)                         # rounding collapsed the 1e-9 lead
    means = [sum(c["rank_score"] for c in b["cases"]) / len(b["cases"]) for b in out]
    assert means == sorted(means, reverse=True)
    assert out == build_batches(conn, "r", gold_ids=set(), exclude_ids=set(), ranker=_Const(table), ts="t")

def test_pack_writes_ranker_id_and_leaves_signals_untouched(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    before = conn.execute("SELECT count(*), sum(signal_id) FROM signals").fetchone()
    n = pack_batches(conn, "r", tmp_path / "b", gold_ids=set(), exclude_ids=set(), ranker=NullRanker(), ts="t")
    b1 = json.loads((tmp_path / "b" / "batch-001.json").read_text(encoding="utf-8"))
    assert n > 0 and b1["ranker_id"] == "null" and before == conn.execute("SELECT count(*), sum(signal_id) FROM signals").fetchone()


def test_restrict_ids_narrows_the_pool_before_the_exclusion(tmp_path, fixture_db, repo_root):
    from corpus_engine.selector.packing import build_batches
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    everything = {c["case_id"] for b in build_batches(conn, "r", gold_ids=set(), exclude_ids=set())
                  for c in b["cases"]}
    keep = set(sorted(everything)[:20])
    packed = {c["case_id"] for b in build_batches(conn, "r", gold_ids=set(), exclude_ids=set(),
                                                  restrict_ids=keep) for c in b["cases"]}
    assert packed == keep and packed < everything
    drop = set(sorted(keep)[:5])
    packed = {c["case_id"] for b in build_batches(conn, "r", gold_ids=set(), exclude_ids=drop,
                                                  restrict_ids=keep) for c in b["cases"]}
    assert packed == keep - drop          # restriction and exclusion compose
