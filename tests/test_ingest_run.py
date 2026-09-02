from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ingest.dedupe import dedupe
from corpus_engine.ingest.run import ingest
from tests.helpers.capzip import make_cap_zip, HTML

def _case(cid, jur, cite, ctype="official"):
    return {"id": cid, "name": f"Case {cid}", "decision_date": "1880-01-01", "jurisdiction": jur,
            "citations": [{"cite": cite, "type": ctype}], "html": HTML}

def test_ingest_two_zips_with_workers_and_resume(tmp_path):
    dom = load_domain()
    (tmp_path / "mass").mkdir(); (tmp_path / "ne").mkdir()
    z1 = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(1, "Mass.", "1 Mass. 1")])
    z2 = make_cap_zip(tmp_path / "ne" / "2.zip", "ne", "2", [_case(2, "Mass.", "2 N.E. 2"), _case(3, "Ill.", "2 N.E. 3")])
    conn = store.connect(tmp_path / "c.db"); store.ensure_schema(conn)
    rep = ingest(conn, [z1, z2], dom, workers=2, log=lambda *_: None)
    assert (rep.zips_done, rep.cases_ingested, rep.errors) == (2, 2, [])
    assert conn.execute("SELECT count(*) FROM cases").fetchone()[0] == 2         # Ill. excluded
    assert conn.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 2
    assert conn.execute("SELECT pagerank_pct FROM cases WHERE case_id=1").fetchone()[0] == 0.5
    rep2 = ingest(conn, [z1, z2], dom, workers=1, log=lambda *_: None)
    assert rep2.zips_done == 0                                                     # resume skips both

def test_dedupe_prefers_official_copy(tmp_path):
    dom = load_domain(); (tmp_path / "mass").mkdir(); (tmp_path / "ne").mkdir()
    z1 = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(1, "Mass.", "5 Mass. 5")])
    z2 = make_cap_zip(tmp_path / "ne" / "2.zip", "ne", "2", [_case(2, "Mass.", "5 Mass. 5", ctype="parallel")])
    conn = store.connect(tmp_path / "c.db"); store.ensure_schema(conn)
    ingest(conn, [z1, z2], dom, workers=1, log=lambda *_: None)
    assert dedupe(conn) == 1
    assert conn.execute("SELECT is_duplicate_of FROM cases WHERE case_id=2").fetchone()[0] == 1
    assert conn.execute("SELECT is_duplicate_of FROM cases WHERE case_id=1").fetchone()[0] is None
