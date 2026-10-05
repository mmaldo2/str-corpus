"""Every citation of a decision, preferred first (spec section 3)."""
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.answers.citations import citation_sets, order_cites, reporter_of
from corpus_engine.ingest import parallel as par


def test_reporter_of_reads_the_text_between_volume_and_page():
    assert reporter_of("98 N.Y. 98") == "N.Y."
    assert reporter_of("12 N.Y. St. Rep. 783") == "N.Y. St. Rep."
    assert reporter_of("22 Ohio C.C. (n.s.) 334") == "Ohio C.C. (n.s.)"
    assert reporter_of("not a cite") == ""


def test_order_puts_listed_reporters_first_in_list_order_then_the_rest_alphabetically():
    pref = ("N.Y.", "A.D.", "N.Y.S.")
    got = order_cites(["2 N.Y. Crim. 539", "114 N.Y.S. 789", "98 N.Y. 98", "98 N.Y. 98",
                       "5 Abb. Pr. 1", "62 A.D. 259"], pref)
    assert got == ["98 N.Y. 98", "62 A.D. 259", "114 N.Y.S. 789", "2 N.Y. Crim. 539", "5 Abb. Pr. 1"]


def test_the_domain_prefers_official_state_reports():
    ny = load_domain().citation_preference["N.Y."]
    assert ny[0] == "N.Y." and ny.index("N.Y.") < ny.index("N.Y.S.") < ny.index("N.Y. Crim.")


def test_every_copy_of_a_decision_carries_the_whole_citation_set(tmp_path):
    conn = store.connect(tmp_path / "c.db")
    store.ensure_schema(conn)
    for cid, cite in ((1, "2 N.Y. Crim. 539"), (2, "98 N.Y. 98"), (3, "40 Barb. 1")):
        conn.execute("INSERT INTO cases (case_id, cite, jurisdiction) VALUES (?,?,?)", (cid, cite, "N.Y."))
        conn.execute("INSERT INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                     (cid, cite, cite.lower(), "official"))
    conn.execute("INSERT INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                 (2, "1 N.Y. Ann. Cas. 5", "1 n.y. ann. cas. 5", "parallel"))
    conn.commit()
    par.apply_merges(conn, [(1, 2, 0.9)], method="m", run_id="r", ts="t")
    pref = {"N.Y.": ("N.Y.", "Barb.", "N.Y. Crim.")}
    sets = citation_sets(conn, [1, 2, 3], jurisdiction_of={1: "N.Y.", 2: "N.Y.", 3: "N.Y."},
                         preference=pref)
    assert sets[1] == sets[2] == ["98 N.Y. 98", "2 N.Y. Crim. 539", "1 N.Y. Ann. Cas. 5"]
    assert sets[3] == ["40 Barb. 1"]
    conn.close()


def test_the_domain_lists_use_the_corpus_spellings_and_put_official_reports_first():
    pref = load_domain().citation_preference
    ny, dc = pref["N.Y."], pref["D.C."]
    assert order_cites(["624 N.Y.S.2d 341", "164 Misc. 2d 177"], ny) == ["164 Misc. 2d 177", "624 N.Y.S.2d 341"]
    assert order_cites(["51 N.Y.S. 1006", "23 App. Div. 623"], ny) == ["23 App. Div. 623", "51 N.Y.S. 1006"]
    assert order_cites(["318 F.3d 203", "355 U.S. App. D.C. 12"], dc) == ["355 U.S. App. D.C. 12", "318 F.3d 203"]
