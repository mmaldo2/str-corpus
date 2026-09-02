from corpus_engine.domain import load_domain
from corpus_engine.ingest.rows import case_rows_from_zip
from tests.helpers.capzip import make_cap_zip, HTML

def _case(cid, jur, cite="1 Test 1", **kw):
    d = {"id": cid, "name": f"Case {cid}", "decision_date": "1855-03-01", "jurisdiction": jur,
         "citations": [{"cite": cite, "type": "official"}], "html": HTML}
    d.update(kw); return d

def test_admission_by_jurisdiction_or_reporter_slug(tmp_path):
    dom = load_domain()
    (tmp_path / "mass").mkdir(); (tmp_path / "f-cas").mkdir(); (tmp_path / "wyo").mkdir()
    zm = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(1, "Mass."), _case(2, "Wyo.", "2 Test 2")])
    zf = make_cap_zip(tmp_path / "f-cas" / "3.zip", "f-cas", "3", [_case(3, "U.S.", "3 F. Cas. 3")])
    zw = make_cap_zip(tmp_path / "wyo" / "4.zip", "wyo", "4", [_case(4, "U.S.", "4 Wyo. 4")])
    assert [r[0] for r in case_rows_from_zip(zm, dom).cases] == [1]          # Wyo. not in domain
    assert [r[0] for r in case_rows_from_zip(zf, dom).cases] == [3]          # slug allowlist admits U.S.
    assert case_rows_from_zip(zw, dom).cases == []                           # U.S. outside the allowlist
    assert case_rows_from_zip(zm, dom).n_total == 2

def test_rows_carry_text_pages_graph_and_pagerank(tmp_path):
    dom = load_domain(); (tmp_path / "mass").mkdir()
    z = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(
        7, "Mass.", cites_to=[{"cite": "9 Mass. 9", "case_ids": [9, 10], "category": "reporters:state",
                               "reporter": "Mass.", "year": 1810, "weight": 2, "opinion_index": 0}],
        analysis={"ocr_confidence": 0.7, "sha256": "abc", "pagerank": {"raw": 1e-7, "percentile": 0.42}})])
    rows = case_rows_from_zip(z, dom)
    case = rows.cases[0]
    assert case[0] == 7 and case[3] == "1 Test 1" and case[8] == "pre-1860" and case[9] == "mass" and case[10] == "1"
    assert "lodgers" in case[14] and case[16].startswith('[[0, "1"], [') and case[17] == 1
    assert rows.citations == [(7, "1 Test 1", "1 test 1", "official")]
    assert rows.cites_to == [(7, 9, "9 Mass. 9", "reporters:state", "Mass.", 1810, 2, 0),
                             (7, 10, "9 Mass. 9", "reporters:state", "Mass.", 1810, 2, 0)]
    assert rows.pagerank == [(7, 1e-7, 0.42)]
