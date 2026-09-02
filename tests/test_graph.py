from corpus_engine import store
from corpus_engine.ingest.graph import graph_rows_from_zip, backfill_graph
from tests.helpers.capzip import make_cap_zip, HTML

def _case(cid, cites):
    return {"id": cid, "name": f"C{cid}", "decision_date": "1900-01-01", "jurisdiction": "Mass.",
            "citations": [{"cite": f"{cid} Mass. {cid}", "type": "official"}], "html": HTML,
            "cites_to": [{"cite": f"{c} Mass. {c}", "case_ids": [c], "category": "reporters:state",
                          "reporter": "Mass.", "year": 1850, "weight": 1, "opinion_index": 0} for c in cites],
            "analysis": {"ocr_confidence": 0.8, "sha256": "s", "pagerank": {"raw": 0.2, "percentile": 0.9}}}

def test_graph_rows_are_metadata_only(tmp_path):
    (tmp_path / "mass").mkdir()
    z = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(1, [2, 3]), _case(2, [])])
    ct, pr = graph_rows_from_zip(z)
    assert [(a, b) for a, b, *_ in ct] == [(1, 2), (1, 3)]
    assert pr == [(1, 0.2, 0.9), (2, 0.2, 0.9)]

def test_backfill_populates_cites_to_and_pagerank_and_is_resumable(tmp_path):
    (tmp_path / "raw" / "mass").mkdir(parents=True)
    z = make_cap_zip(tmp_path / "raw" / "mass" / "1.zip", "mass", "1", [_case(1, [2]), _case(2, [])])
    conn = store.connect(tmp_path / "c.db"); store.ensure_schema(conn)
    conn.execute("INSERT INTO cases (case_id, jurisdiction) VALUES (1,'Mass.'),(2,'Mass.')")
    conn.execute("INSERT INTO ingest_log VALUES ('mass/1', 2, 2, 1, 'ts')"); conn.commit()
    assert backfill_graph(conn, tmp_path / "raw", workers=1, log=lambda *_: None) == (1, 1)
    assert conn.execute("SELECT cited_case_id FROM cites_to WHERE citing_case_id=1").fetchone()[0] == 2
    assert conn.execute("SELECT pagerank_pct FROM cases WHERE case_id=2").fetchone()[0] == 0.9
    assert backfill_graph(conn, tmp_path / "raw", workers=1, log=lambda *_: None) == (0, 0)
