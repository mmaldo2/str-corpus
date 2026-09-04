import json, shutil, sqlite3
import numpy as np
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import Partition, Selector, load_selectors
from corpus_engine.selector.ports import FrozenSeedResolver, RecordedEmbedder
from corpus_engine.selector.runners import EngineContext, RUNNERS, run_citation_graph, run_embedding, run_fts

def _ctx(tmp_path, fixture_db, repo_root, seeds=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); store.migrate(conn)
    return EngineContext(conn, load_domain(), RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz"),
                         seeds or FrozenSeedResolver({}))

def test_lexical_runners_reproduce_cycle_003_signals_on_fixture_cases(tmp_path, fixture_db, repo_root):
    ctx = _ctx(tmp_path, fixture_db, repo_root)
    sig = sqlite3.connect(repo_root / "tests/fixtures/cycle-003-signals.db")
    fixture_ids = {r[0] for r in ctx.conn.execute("SELECT case_id FROM cases")}
    sels = [s for s in load_selectors(ctx.domain) if s.kind in ("fts_phrase", "fts_near", "regex")]
    checked = 0
    for s in sels:
        want = {(r[0], r[1], r[2], r[3]) for r in sig.execute(
            "SELECT case_id, matched_text, char_span_start, char_span_end FROM signals WHERE selector_id=? AND selector_version=?", (s.id, s.version))
            if r[0] in fixture_ids}
        got = set()
        for era in s.era_scope:
            for jur in s.jurisdiction_scope:
                for g in RUNNERS[s.kind](ctx, s, Partition(era, jur)):
                    got.add((g.case_id, g.matched_text, g.char_span[0], g.char_span[1]))
        assert got == want, s.label
        checked += len(want)
    assert checked > 50

def test_embedding_runner_is_deterministic_and_stable_sorted(tmp_path, fixture_db, repo_root):
    ctx = _ctx(tmp_path, fixture_db, repo_root)
    s = next(x for x in load_selectors(ctx.domain) if x.label == "embed-householder-letting-21@v2")
    part = Partition(*ctx.conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL GROUP BY 1,2 ORDER BY count(*) DESC LIMIT 1").fetchone())
    a = run_embedding(ctx, s, part); b = run_embedding(_ctx(tmp_path / "b", fixture_db, repo_root), s, part)
    assert [(x.case_id, x.chunk_id, round(x.cosine, 6)) for x in a] == [(x.case_id, x.chunk_id, round(x.cosine, 6)) for x in b]
    assert all(a[i].cosine >= a[i + 1].cosine for i in range(len(a) - 1)) and len({x.case_id for x in a}) == len(a)
    assert all(x.cosine >= s.params["min_cosine"] for x in a) and len(a) <= s.params["top_k"]

def test_citation_graph_runner_walks_both_directions(tmp_path, fixture_db, repo_root):
    seeds = FrozenSeedResolver({"s": [1, 2, 3, 4, 5]})
    ctx = _ctx(tmp_path, fixture_db, repo_root, seeds)
    part = Partition(*ctx.conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL LIMIT 1").fetchone())
    a, b = [r[0] for r in ctx.conn.execute("SELECT case_id FROM cases WHERE era_partition=? AND jurisdiction=? AND is_duplicate_of IS NULL LIMIT 2", (part.era, part.jurisdiction))]
    ctx.conn.execute("INSERT OR IGNORE INTO cites_to VALUES (?,?,?,?,?,?,?,?)", (a, 1, "1 Seed 1", "reporters:state", "X", 1850, 1, 0))   # a cites seed 1
    ctx.conn.execute("INSERT OR IGNORE INTO cites_to VALUES (?,?,?,?,?,?,?,?)", (2, b, "2 B 2", "reporters:state", "X", 1850, 1, 0))       # seed 2 cites b
    ctx.conn.commit()
    sel = Selector("g", 1, "citation_graph", "c", "p", (part.era,), (part.jurisdiction,), {"seed_set": "s", "direction": "both"})
    got = {(g.case_id, g.matched_text) for g in run_citation_graph(ctx, sel, part)}
    assert got == {(a, "cites 1 Seed 1"), (b, "cited by 2 B 2")}
