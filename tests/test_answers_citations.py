"""Every citation of a decision, preferred first (spec section 3)."""
import sqlite3
from pathlib import Path
import pytest
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.answers.citations import citation_sets, order_cites, reporter_of
from corpus_engine.ingest import parallel as par

LIVE = Path(__file__).resolve().parent.parent / "data" / "db" / "corpus.db"


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
    assert ny["official"][0] == "N.Y." and "N.Y.S." in ny["reprint"] and "N.Y. Crim." in ny["reprint"]


def test_an_unknown_reporter_sorts_between_the_official_and_the_reprint_tiers():
    pref = {"official": ("Cal.",), "reprint": ("Cal. Rptr. 3d",)}
    assert order_cites(["248 Cal. Rptr. 3d 874", "36 Cal. App. Supp. 5th 12", "1 Cal. 1"], pref) == [
        "1 Cal. 1", "36 Cal. App. Supp. 5th 12", "248 Cal. Rptr. 3d 874"]


def test_reporters_match_ignoring_spaces_and_case_and_text_without_a_number_is_dropped():
    pref = {"official": ("Misc. 2d",), "reprint": ("N.Y.S.2d",)}
    assert order_cites(["624 N.Y.S.2d 341", "164 Misc.2d 177", "Judgment accordingly."], pref) == [
        "164 Misc.2d 177", "624 N.Y.S.2d 341"]


@pytest.mark.live_db
@pytest.mark.skipif(not LIVE.exists(), reason="no live corpus")
def test_no_counted_record_leads_with_a_reprint_when_an_official_report_is_in_its_set():
    from corpus_engine.ledger import open_ledger
    from corpus_engine.ledger.tally import counted_records
    from corpus_engine.answers.citations import reporter_tier
    dom = load_domain()
    recs = counted_records(open_ledger(domain=dom).view())
    conn = sqlite3.connect(f"file:{LIVE.as_posix()}?mode=ro", uri=True)
    sets = citation_sets(conn, [r["case_id"] for r in recs],
                         jurisdiction_of={r["case_id"]: r.get("jurisdiction") for r in recs},
                         preference=dom.citation_preference)
    jur = {r["case_id"]: r.get("jurisdiction") for r in recs}
    bad = [(cid, s) for cid, s in sets.items() if s
           and reporter_tier(s[0], dom.citation_preference.get(jur[cid], {})) == "reprint"
           and any(reporter_tier(c, dom.citation_preference.get(jur[cid], {})) == "official" for c in s)]
    assert bad == []


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


def test_a_combined_cite_string_is_split_and_every_misc_spelling_is_listed():
    ny = load_domain().citation_preference["N.Y."]
    assert order_cites(["96 N.Y.S. 671", "110 App. Div. 218; 48 Misc. Rep. 177"], ny) == [
        "110 App. Div. 218", "48 Misc. Rep. 177", "96 N.Y.S. 671"]
    assert order_cites(["886 N.Y.S.2d 587", "26 Misc.3d 170"], ny) == ["26 Misc.3d 170", "886 N.Y.S.2d 587"]
