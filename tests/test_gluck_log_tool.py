"""tools/gluck_log.py end to end over a temporary store and ledger (spec sections 6-7)."""
import importlib.util
import json
from pathlib import Path
import pytest
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.types import Basis, Patch

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("gluck_log", ROOT / "tools" / "gluck_log.py")
gl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gl)

QUESTIONS = """
- id: q1
  title: Favorable before 1900
  population: {polarity: [favorable], era: [pre-1860, 1860-1900]}
  group_by: [characterization]
- id: q3
  title: Adverse by restriction
  population: {polarity: [adverse]}
  group_by: [restriction_nature, era]
  earliest_per_jurisdiction: {restriction_nature: [zoning]}
- id: q4
  title: Vocabulary
  kind: concordance
  terms:
    - {label: lodger, expr: lodger}
    - {label: board near lodging, expr: "NEAR(board lodging, 5)", fts_expression: true}
"""


def _rec(cid, year, polarity, restriction=None):
    return {"case_id": cid, "cite": "x", "year": year, "jurisdiction": "N.Y.", "relevant": True,
            "polarity": polarity, "who_was_letting": "householder", "duration_of_occupancy": "nights",
            "characterization": "lodging", "under_thirty_days": "yes",
            "owner_freedom_characterization": "incident_of_ownership", "restriction_nature": restriction,
            "holding_summary": "h", "extraction_status": "ok",
            "quotes": [{"text": "q", "supports": ["polarity"], "status": "verified", "reporter_page": "99"}]}


def _install(tmp_path):
    root = tmp_path / "gluck"
    root.mkdir()
    (root / "questions.yaml").write_text(QUESTIONS, encoding="utf-8")
    db = tmp_path / "c.db"
    conn = store.connect(db)
    store.ensure_schema(conn)
    store.ensure_fts(conn)
    for cid, name, court, cite, year, era, text in (
            (1, "Smith v. Jones", "Court of Appeals", "98 N.Y. 98", 1850, "pre-1860", "a lodger and his board and lodging"),
            (2, "Doe v. Roe", "Supreme Court", "40 Barb. 1", 1925, "1900-1930", "zoning of a lodging house")):
        conn.execute("INSERT INTO cases (case_id, name_abbreviation, court, cite, jurisdiction, decision_year, "
                     "era_partition, norm_text) VALUES (?,?,?,?,?,?,?,?)", (cid, name, court, cite, "N.Y.", year, era, text))
    conn.execute("INSERT INTO fts_raw(fts_raw) VALUES('rebuild')")
    conn.execute("INSERT INTO fts_porter(fts_porter) VALUES('rebuild')")
    conn.commit()
    conn.close()
    led = open_ledger(tmp_path / "ledger", domain=load_domain())
    reader = Basis(model="m", prompt_version="v", run_id="r")
    led.apply([Patch(1, "admit", "", _rec(1, 1850, "favorable"), "v", reader, cycle="cycle-004"),
               Patch(2, "admit", "", _rec(2, 1925, "adverse", "zoning"), "v", reader, cycle="cycle-004")],
              note="seed")
    return root, ["--root", str(root), "--db", str(db), "--ledger", str(tmp_path / "ledger"),
                  "--date", "2026-10-05"]


def test_run_writes_the_answers_and_the_log(tmp_path):
    root, common = _install(tmp_path)
    assert gl.main(common + ["run", "--all"]) == 0
    out = sorted(p.name for p in (root / "out").iterdir())
    assert out == ["2026-10-05-q1-favorable-before-1900", "2026-10-05-q3-adverse-by-restriction",
                   "2026-10-05-q4-vocabulary"]
    q1 = root / "out" / out[0]
    csv_text = (q1 / "cases.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("case_name,citations,") and csv_text.splitlines()[0].endswith("reviewer_note")
    assert "Smith v. Jones" in csv_text and "98 N.Y. 98" in csv_text
    assert b"\r\n" not in (q1 / "cases.csv").read_bytes()
    html = (q1 / "answer.html").read_text(encoding="utf-8")
    assert "Ledger seq 2" in html and "Counts are lower bounds." in html and "pin-cite" in html
    assert "polarity is favorable" in html
    doc = json.loads((q1 / "summary.json").read_text(encoding="utf-8"))
    assert doc["summary"]["total"] == {"human_reviewed": 0, "machine_only": 1}
    assert doc["stamp"]["ledger_seq"] == 2 and doc["question"]["id"] == "q1"
    q3 = json.loads((root / "out" / out[1] / "summary.json").read_text(encoding="utf-8"))
    assert [e["case_id"] for e in q3["earliest"]] == [2] and q3["earliest"][0]["case_name"] == "Doe v. Roe"
    counts = (root / "out" / out[2] / "counts.csv").read_text(encoding="utf-8").splitlines()
    assert counts[0] == "term,era,jurisdiction,matches,opinions,rate_per_1000"
    assert "lodger,pre-1860,N.Y.,1,1,1000.0" in counts
    log = (root / "log.md").read_text(encoding="utf-8")
    assert sum(1 for line in log.splitlines() if line.startswith("- 2026-10-05")) == 3
    assert "Drive: unpublished" in log


def test_a_second_run_the_same_day_gets_its_own_folder(tmp_path):
    root, common = _install(tmp_path)
    gl.main(common + ["run", "--question", "q1"])
    gl.main(common + ["run", "--question", "q1"])
    assert sorted(p.name for p in (root / "out").iterdir()) == [
        "2026-10-05-q1-favorable-before-1900", "2026-10-05-q1-favorable-before-1900-2"]


def test_a_bad_fts_expression_is_refused_without_writing(tmp_path):
    root, common = _install(tmp_path)
    (root / "questions.yaml").write_text(
        "- id: q9\n  title: Bad\n  kind: concordance\n  terms:\n"
        "    - {label: bad, expr: 'NEAR(', fts_expression: true}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="q9.*bad"):
        gl.main(common + ["run", "--all"])
    assert not (root / "out").exists()


def test_unknown_questions_and_a_bad_file_are_refused(tmp_path):
    root, common = _install(tmp_path)
    with pytest.raises(SystemExit, match="no such question: q7"):
        gl.main(common + ["run", "--question", "q7"])
    (root / "questions.yaml").write_text("- {id: q1, title: t, population: {polarity: [favourable]}}\n",
                                         encoding="utf-8")
    with pytest.raises(SystemExit, match="favourable"):
        gl.main(common + ["run", "--all"])


LIVE = ROOT / "data" / "db" / "corpus.db"


@pytest.mark.live_db
@pytest.mark.skipif(not LIVE.exists(), reason="no live corpus")
def test_live_question_one_has_a_two_tier_summary(tmp_path):
    root = tmp_path / "gluck"
    root.mkdir()
    (root / "questions.yaml").write_text(
        "- id: q1\n  title: Live\n  population: {polarity: [favorable], era: [pre-1860], "
        "owner_freedom_characterization: [incident_of_ownership]}\n  group_by: [characterization]\n",
        encoding="utf-8")
    assert gl.main(["--root", str(root), "--date", "2026-10-05", "run", "--all"]) == 0
    doc = json.loads(next((root / "out").iterdir()).joinpath("summary.json").read_text(encoding="utf-8"))
    total = doc["summary"]["total"]
    assert total["human_reviewed"] + total["machine_only"] > 0
