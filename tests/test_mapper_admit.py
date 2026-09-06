"""Admission (spec section 8, D3/D8/D9).

Records are re-derived from the RESPONSE CACHE, not from the extraction files: the extraction
files are gitignored, derived, and editable, and what reaches the ledger has to be exactly what
the gate accepted. Every judged value arrives as a `set` under the D8 reader basis, so
`Basis.can_judge()` is satisfied and the record is machine-only until a human decides it (D3).

The fixture under tests/fixtures/mapper-admit is a whole synthetic map: two batches, four
synthetic opinions, five cached responses and the manifest that addresses them. One unit
parsed whole; the other came back truncated and was split, so its two halves answer for it.
One record is an irrelevant read, one carries a quote that is nowhere in its opinion, and one
unit was sampled by the checker and contradicted. Nothing here touches the store, the network,
or the real ledger.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from corpus_engine.domain import load_domain
from corpus_engine.ledger.fold import State, apply_patch, supported_fields
from corpus_engine.ledger.types import Basis, Patch
from corpus_engine.mapper.admit import (CODEBOOK_ID, IDENTITY_FIELDS, MAPPER_FIELDS,
                                        AdmittedRecord, basis_for, checker_notes, counts_by_cell,
                                        patches_for, prompt_version, records_from_manifest)
from corpus_engine.mapper.cells import BatchSource
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.model import CaseText, ModelPin, Response
from corpus_engine.reader.sources import InlinedCaseSource

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from textnorm import normalize  # noqa: E402

SHA = "f920166813144f09d3a8a8de575eb860dbcce18a42b46b2270b4b17cc1a52752"
PIN = ModelPin("claude-cli/claude-opus-5", "anthropic", "claude-cli", None,
               {"effort": "low", "cli_model": "claude-opus-5"})
CELL_NY = "1860-1900|N.Y."
CELL_OHIO = "1930-1970|Ohio"
UNIT_NY = "cycle-004-shard-01-batch-001"
UNIT_OHIO = "cycle-004-shard-01-batch-002"


# ---------------------------------------------------------------- the synthetic fixture ----
@pytest.fixture(scope="session")
def fixture_dir(repo_root) -> Path:
    return repo_root / "tests" / "fixtures" / "mapper-admit"


@pytest.fixture
def manifest(fixture_dir) -> dict:
    return json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def cases(fixture_dir) -> InlinedCaseSource:
    """The four synthetic opinions, normalised exactly as the store would have them, so the
    quote gate behaves here the way it behaves against a real case row."""
    raw = json.loads((fixture_dir / "cases.json").read_text(encoding="utf-8"))
    out = {}
    for cid, c in raw.items():
        norm, _offsets = normalize(c["raw_text"])
        out[int(cid)] = CaseText(int(cid), c["cite"], c["name"], c["court"], c["jurisdiction"],
                                 c["year"], c["raw_text"], norm, [[0, "1"]])
    return InlinedCaseSource(out)


@pytest.fixture
def derive(fixture_dir, cases):
    """`records_from_manifest` over the fixture, with everything but the manifest fixed."""
    dom = load_domain()
    cb = load_codebook(dom, CODEBOOK_ID)

    def go(manifest):
        return records_from_manifest(manifest, batch_source=BatchSource(fixture_dir / "batches"),
                                     cache=ResponseCache(fixture_dir / "cache"), codebook=cb,
                                     cases=cases, pin=PIN, families=dom.reader.families)
    return go


def _by_case(admitted):
    return {a.case_id: a for a in admitted}


# --------------------------------------------------------------------- the D8 basis --------
def test_the_basis_is_the_D8_one(manifest):
    b = basis_for(manifest)
    assert b == Basis(model="claude-opus-5@claude-cli",
                      prompt_version="mapper-v3:f92016681314", run_id="cycle-004-shard-01")
    assert b.can_judge() and b.kind() == "reader"
    assert prompt_version(SHA) == "mapper-v3:f92016681314"
    assert supported_fields(b.prompt_version) == (
        "characterization", "polarity", "holding_summary", "owner_freedom_characterization",
        "restriction_nature", "under_thirty_days")


def test_the_basis_names_the_pin_the_map_actually_ran_under(manifest):
    """The model string is derived from the manifest's pin label, not spelled in admit.py, so
    a map read under some other pin cannot claim the subscription's provenance."""
    other = {**manifest, "reader_pin": "google/gemini-3.7-flash@-:-"}
    assert basis_for(other).model == "gemini-3.7-flash@google"


def test_a_map_read_under_another_codebook_is_refused(manifest):
    """`fold.supported_fields` raises on a prompt_version segment it does not know, so a v1/v2
    map must be refused HERE rather than admitted under a support rule it never ran under."""
    with pytest.raises(ValueError, match="mapper-v3"):
        basis_for({**manifest, "codebook_id": "mapper-v1"})


def test_the_field_mapping_is_the_readers_own_names():
    """After D7 every mapper-v3 name IS the ledger name; there is no translation table left."""
    assert MAPPER_FIELDS == ("relevance_score", "polarity", "who_was_letting",
                             "duration_of_occupancy", "characterization", "under_thirty_days",
                             "owner_freedom_characterization", "restriction_nature",
                             "holding_summary", "doctrinal_concepts", "new_terms_observed")
    assert "under_30_days" not in MAPPER_FIELDS and "right_characterization" not in MAPPER_FIELDS
    assert set(IDENTITY_FIELDS) & set(MAPPER_FIELDS) == set()
    assert "relevant" in IDENTITY_FIELDS and "quotes" in IDENTITY_FIELDS


# ------------------------------------------------- re-deriving the records from the cache --
def test_a_whole_unit_is_re_gated_from_its_one_cache_key(manifest, derive):
    admitted = _by_case(derive(manifest))
    a = admitted[101]
    assert a.cell_key == CELL_NY and a.batch_id == UNIT_NY and a.cache_key == "key-001"
    assert a.record["polarity"] == "favorable" and a.record["extraction_status"] == "ok"
    assert a.record["quotes"][0]["status"] == "verified"          # the gate ran, not a copy
    assert a.record["quotes"][0]["reporter_page"] == "1"


def test_a_split_unit_is_re_derived_from_the_half_keys_the_manifest_lists(manifest, derive):
    """batch-002's whole response is truncated. Admission must fall back to the `-a`/`-b` keys
    the unit's row lists - and record the HALF key against each record, because that is the
    key the record can be re-derived from on its own."""
    admitted = _by_case(derive(manifest))
    assert admitted[201].cache_key == "key-002-a" and admitted[202].cache_key == "key-002-b"
    assert admitted[201].batch_id == UNIT_OHIO and admitted[201].cell_key == CELL_OHIO


def test_the_gate_decides_the_admitted_value_not_the_model(manifest, derive):
    """201's quote is nowhere in its opinion: the gate drops it and voids every judged field
    it was the only support for. That gated record is what admission carries."""
    a = _by_case(derive(manifest))[201]
    assert a.record["quotes"] == []
    for f in ("polarity", "characterization", "restriction_nature", "under_thirty_days",
              "owner_freedom_characterization", "holding_summary"):
        assert a.record[f] is None, f
    assert a.record["extraction_status"] == "extraction-invalid"
    assert set(a.record["nulled_fields"]) == set(load_domain().reader.judged_fields)
    # who_was_letting and duration_of_occupancy are NOT quote-supported under mapper-v3, so
    # the gate leaves them standing and they are still admitted.
    assert a.record["who_was_letting"] == "commercial_operator"


def test_a_unit_with_no_cached_response_is_skipped_not_guessed_at(manifest, derive):
    m = copy.deepcopy(manifest)
    m["cells"][CELL_NY]["cache_keys"] = {UNIT_NY: ["no-such-key"]}
    assert {a.case_id for a in derive(m)} == {201, 202}


def test_a_unit_with_no_batch_file_is_skipped(manifest, derive):
    m = copy.deepcopy(manifest)
    m["cells"][CELL_NY]["cache_keys"] = {"cycle-004-shard-01-batch-999": ["key-001"]}
    assert {a.case_id for a in derive(m)} == {201, 202}


def test_a_half_that_never_came_back_costs_only_its_own_cases(manifest, derive):
    m = copy.deepcopy(manifest)
    m["cells"][CELL_OHIO]["cache_keys"] = {UNIT_OHIO: ["key-002", "key-002-a", "gone"]}
    got = _by_case(derive(m))
    assert set(got) == {101, 102, 201}               # 202's half is missing, 201's is not


def test_the_pre_amendment_single_string_key_still_admits(tmp_path, fixture_dir, cases,
                                                          manifest):
    """A manifest written before the Task-5 review amendment records ONE key per unit. The
    whole-unit key still parses for batch-001, so its records are unchanged; a split unit in
    that shape has its half keys re-derived exactly as the runner composed them, which is what
    this test pins by composing them the same way and planting the response there."""
    from corpus_engine.mapper.runner import MapRunner, RunnerCaps
    from corpus_engine.reader.driver import plan_batch_extraction
    from corpus_engine.reader.model import Budget
    from corpus_engine.reader.parse import split_unit

    dom = load_domain()
    cb = load_codebook(dom, CODEBOOK_ID)
    src = ResponseCache(fixture_dir / "cache")
    cache = ResponseCache(tmp_path / "cache")
    for name in ("key-001", "key-002"):
        cache.put(name, src.get(name))
    batches = BatchSource(fixture_dir / "batches")
    batch = batches.get(UNIT_OHIO)
    runner = MapRunner(lambda: None, [], batch_source=batches, cache=cache,
                       manifest_path=tmp_path / "m.json", caps=RunnerCaps(1, 1.0), codebook=cb,
                       pin=PIN, run_id="cycle-004-shard-01", families=dom.reader.families)
    unit = plan_batch_extraction([batch], cb.id, PIN, Budget(), worker="reader").units[0]
    reader = type("R", (), {"cases": cases})()
    for half, key in zip(split_unit(unit), ("key-002-a", "key-002-b")):
        cache.put(runner._cache_key(reader, half), src.get(key))

    m = copy.deepcopy(manifest)
    m["cells"][CELL_NY]["cache_keys"] = {UNIT_NY: "key-001"}
    m["cells"][CELL_OHIO]["cache_keys"] = {UNIT_OHIO: "key-002"}
    admitted = records_from_manifest(m, batch_source=batches, cache=cache, codebook=cb,
                                     cases=cases, pin=PIN, families=dom.reader.families)
    assert {a.case_id for a in admitted} == {101, 102, 201, 202}
    assert _by_case(admitted)[202].record["characterization"] == "innkeeping"


# ------------------------------------------------------------------- the checker's verdict -
def test_checker_notes_carry_the_disagreement_and_the_sampling(manifest):
    by_unit = {UNIT_NY: (101, 102)}
    notes = checker_notes(manifest, case_ids_by_unit=by_unit)
    assert notes[101] == "checker:codex-cli: polarity 'favorable' vs 'adverse'"
    # A case in a SAMPLED unit with nothing recorded against it gets the claim the manifest
    # can actually support. It must NOT say the checker agreed: `checker_status == "ok"` means
    # the response parsed, not that it carried a record for this case, and `driver.read` skips
    # the cases the checker omitted - so "agreed" would assert a read that never happened.
    assert notes[102] == ("checker:codex-cli: unit sampled, no disagreement recorded on "
                          "relevant, polarity, characterization")
    assert "agreed" not in notes[102]
    assert 201 not in notes and 202 not in notes          # that unit was never sampled
    assert checker_notes(manifest) == {101: notes[101]}   # without the case map: the contra only


def test_a_failed_checker_call_is_not_an_agreement(manifest):
    m = copy.deepcopy(manifest)
    m["cells"][CELL_NY]["checker_status"] = {UNIT_NY: "failed:codex cli timed out"}
    m["cells"][CELL_NY]["checker_disagreements"] = []
    assert checker_notes(m, case_ids_by_unit={UNIT_NY: (101, 102)}) == {}


def test_the_checker_verdict_reaches_review_notes(manifest, derive):
    ps = patches_for(derive(manifest), manifest=manifest)
    notes = [p.new for p in ps if p.case_id == 101 and p.field == "review.notes"]
    assert notes == ["reader: boarders by the night",
                     "checker:codex-cli: polarity 'favorable' vs 'adverse'"]
    sampled = [p.new for p in ps if p.case_id == 102 and p.field == "review.notes"]
    assert sampled == []          # an irrelevant read carries no notes at all (section 8)


# ------------------------------------------------------------------------- the patch shapes -
def test_a_relevant_record_becomes_an_admit_then_one_set_per_decided_field(manifest, derive):
    ps = [p for p in patches_for(derive(manifest), manifest=manifest) if p.case_id == 101]
    assert ps[0].op == "admit" and ps[0].cycle == "cycle-004"
    body = ps[0].new
    assert set(body) <= set(IDENTITY_FIELDS)
    assert body["relevant"] is True and body["quotes"] and body["case_id"] == 101
    assert body["cite"] == "12 Abb. Pr. 147" and body["extraction_status"] == "ok"
    assert "polarity" not in body and "holding_summary" not in body
    assert "key-001" in ps[0].note and UNIT_NY in ps[0].note and CELL_NY in ps[0].note
    sets = [(p.field, p.new) for p in ps if p.op == "set"]
    assert sets == [("relevance_score", 0.82), ("polarity", "favorable"),
                    ("who_was_letting", "householder"), ("duration_of_occupancy", "nights"),
                    ("characterization", "lodging"), ("under_thirty_days", "yes"),
                    ("owner_freedom_characterization", "incident_of_ownership"),
                    ("holding_summary", "A householder letting rooms by the night keeps "
                                        "possession; the occupant is a lodger."),
                    ("doctrinal_concepts", ["lodger_status"])]
    assert all(p.basis == basis_for(manifest) for p in ps)
    assert all(p.why.startswith("cycle-004 map admission") for p in ps)


def test_the_admit_patch_carries_the_D8_basis_too(manifest, derive):
    """`fold._record_admitting_prompt` fixes the support rule from the FIRST admit patch that
    carries a prompt_version. An admit under a bare basis would leave a mapper-v3 record
    folding under the mapper-v1 three-field cascade (D7/Task-2 ruling)."""
    admits = [p for p in patches_for(derive(manifest), manifest=manifest) if p.op == "admit"]
    assert admits and all(p.basis.prompt_version == "mapper-v3:f92016681314" for p in admits)
    assert all(p.basis.can_judge() for p in admits)


def test_a_none_or_empty_field_gets_no_set_patch(manifest, derive):
    ps = [p for p in patches_for(derive(manifest), manifest=manifest) if p.case_id == 101]
    fields = {p.field for p in ps if p.op == "set"}
    assert "restriction_nature" not in fields          # None on the record
    assert "new_terms_observed" not in fields          # [] on the record


def test_an_irrelevant_record_is_admitted_with_no_judged_values(manifest, derive):
    """The irrelevant-read negatives the ranker's labelled reads use (spec section 8)."""
    ps = [p for p in patches_for(derive(manifest), manifest=manifest) if p.case_id == 102]
    assert [p.op for p in ps] == ["admit"]
    assert ps[0].new["relevant"] is False and ps[0].new["quotes"] == []
    assert "irrelevant read" in ps[0].why
    assert "relevance_score" not in ps[0].new


def test_a_record_the_gate_voided_still_admits_what_survived(manifest, derive):
    ps = [p for p in patches_for(derive(manifest), manifest=manifest) if p.case_id == 201]
    assert ps[0].op == "admit" and ps[0].new["quotes"] == []
    sets = {p.field: p.new for p in ps if p.op == "set"}
    assert sets == {"relevance_score": 0.61, "who_was_letting": "commercial_operator",
                    "duration_of_occupancy": "months", "doctrinal_concepts": ["zoning_power"]}


def test_the_patch_order_is_the_manifests_cell_order_then_case_id(manifest, derive):
    ps = patches_for(derive(manifest), manifest=manifest)
    assert [p.case_id for p in ps if p.op == "admit"] == [101, 102, 201, 202]
    reversed_cells = {**manifest, "cell_order": [CELL_OHIO, CELL_NY]}
    ps2 = patches_for(derive(manifest), manifest=reversed_cells)
    assert [p.case_id for p in ps2 if p.op == "admit"] == [201, 202, 101, 102]


def test_counts_by_cell_are_what_the_dry_run_prints(manifest, derive):
    got = counts_by_cell(derive(manifest))
    assert got[CELL_NY] == {"records": 2, "relevant": 1, "irrelevant": 1}
    assert got[CELL_OHIO] == {"records": 2, "relevant": 2, "irrelevant": 0}


def test_the_admitted_identity_is_the_stores_not_the_models(manifest, derive, fixture_dir):
    """The Critical of fix round 1. `cite`, `court`, `jurisdiction` and `year` are optional,
    nullable, model-emitted schema properties the quote gate never touches, so a hallucinated
    citation would otherwise become the record's identity in the ledger - and `jurisdiction`
    and `year` are what the published counts and the era analysis slice on. In the fixture the
    reader answered for 102 with a Cal. 1899 citation and for 201 with an Ind. 1802 one; the
    store says Ohio 1954 and Ohio 1941."""
    store = json.loads((fixture_dir / "cases.json").read_text(encoding="utf-8"))
    admitted = _by_case(derive(manifest))
    for cid in (101, 102, 201, 202):
        rec, want = admitted[cid].record, store[str(cid)]
        assert (rec["cite"], rec["court"], rec["jurisdiction"], rec["year"]) == (
            want["cite"], want["court"], want["jurisdiction"], want["year"]), cid
    # ... and the model's own answer really did contradict it, so this is not a tautology
    cached = json.loads(json.loads(
        (fixture_dir / "cache" / "key-001.json").read_text(encoding="utf-8"))["text"])
    assert next(r for r in cached["records"] if r["case_id"] == 102)["jurisdiction"] == "Cal."


def test_the_bookkeeping_fields_are_stamped_not_carried_through(manifest, derive):
    """`worker`, `batch_id` and `schema_version` say what admission KNOWS. The fixture's 102
    claims worker "codex", batch "some-other-batch" and schema_version 99."""
    for cid, unit in ((101, UNIT_NY), (102, UNIT_NY), (201, UNIT_OHIO), (202, UNIT_OHIO)):
        rec = _by_case(derive(manifest))[cid].record
        assert (rec["worker"], rec["batch_id"], rec["schema_version"]) == ("reader", unit, 3)


def test_the_identity_override_reaches_the_admit_body(manifest, derive):
    body = next(p.new for p in patches_for(derive(manifest), manifest=manifest)
                if p.case_id == 102)
    assert body["jurisdiction"] == "Ohio" and body["year"] == 1954
    assert body["cite"] == "44 Ohio St. 12" and body["schema_version"] == 3
    assert set(body) <= set(IDENTITY_FIELDS)


def test_the_worker_comes_from_the_manifest_when_it_records_one(manifest, derive):
    """`MapRunner.worker` is configurable and the manifest does not yet record it, so the
    stamp falls back to "reader"; when a manifest does carry one, that is what is stamped."""
    got = _by_case(derive({**manifest, "worker": "screener"}))
    assert got[101].record["worker"] == "screener"


def test_admitted_record_is_frozen():
    a = AdmittedRecord(1, CELL_NY, UNIT_NY, "k", {"case_id": 1}, "")
    with pytest.raises(Exception):
        a.case_id = 2


# ------------------------------------------------------------------ what the fold then does -
def test_the_support_rule_the_admitted_record_carries_is_the_v3_one(manifest, derive):
    """The end-to-end reason D7 exists: a later drop_quote on an admitted cycle-004 record
    must cascade over all six judged fields, not the mapper-v1 three."""
    s = State()
    judged = tuple(load_domain().judged_fields)
    for p in patches_for(derive(manifest), manifest=manifest):
        apply_patch(s, p, judged=judged, cascade=p.cascade)
    assert s.prompts[101] == "mapper-v3:f92016681314"
    assert s.records[101]["review"]["notes"][0] == "reader: boarders by the night"
    apply_patch(s, Patch(101, "drop_quote", "quotes",
                         "the lodger has not the possession, but the use only", "quote failed",
                         Basis(reviewer="mmaldo2")), judged=judged)
    rec = s.records[101]
    assert rec["polarity"] is None and rec["under_thirty_days"] is None
    assert rec["characterization"] is None and rec["owner_freedom_characterization"] is None
    assert rec["holding_summary"] is None
    # not quote-supported under mapper-v3, so untouched by the cascade
    assert rec["who_was_letting"] == "householder"


def test_a_dry_run_writes_nothing_and_reports_the_counts_both_ways(tmp_path, manifest, derive):
    """`Ledger.apply(dry_run=True)` validates the whole patch set on a deep copy of the head
    state and writes no file; the published counts before/after come from the same fold."""
    from corpus_engine.ledger import open_ledger
    led = open_ledger(root=tmp_path / "ledger", domain=load_domain())
    ps = patches_for(derive(manifest), manifest=manifest)
    res = led.apply(ps, note="cycle-004 map admission", dry_run=True)
    assert len(res.applied) == len(ps) and res.files_written == []
    assert not (tmp_path / "ledger" / "patches.jsonl").exists()
    assert led.view().counts().total.machine_only == 0


def test_the_patches_apply_to_a_real_ledger_and_publish_the_relevant_records(tmp_path, manifest,
                                                                            derive):
    from corpus_engine.ledger import open_ledger
    led = open_ledger(root=tmp_path / "ledger", domain=load_domain())
    ps = patches_for(derive(manifest), manifest=manifest)
    res = led.apply(ps, note="cycle-004 map admission")
    assert res.replay_ok and len(res.applied) == len(ps)
    counts = led.view().counts().total
    assert (counts.human_reviewed, counts.machine_only) == (0, 3)   # 102 is the irrelevant read
    assert led.view().counts(polarity="favorable").total.machine_only == 2
    # applying the same patch set again is a no-op: every patch id is already in the log
    assert len(open_ledger(root=tmp_path / "ledger", domain=load_domain())
               .apply(ps, note="again").applied) == 0


# ------------------------------------------------------------------------------- the tool ---
@pytest.fixture(scope="session")
def admit_map(repo_root):
    spec = importlib.util.spec_from_file_location("admit_map", repo_root / "tools"
                                                  / "admit_map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_tool_refuses_a_run_id_that_is_already_in_the_ledger(admit_map):
    view = type("V", (), {"patches": [Patch(1, "set", "polarity", "favorable", "w",
                                            Basis(model="m", prompt_version="p",
                                                  run_id="cycle-004-shard-01"))]})()
    assert admit_map.run_id_already_applied(view, "cycle-004-shard-01") is True
    assert admit_map.run_id_already_applied(view, "cycle-005-shard-01") is False


def test_the_tool_demands_exactly_one_of_dry_run_and_apply(admit_map):
    for argv in ([], ["--dry-run", "--apply"]):
        with pytest.raises(SystemExit) as exc:
            admit_map.main(argv)
        assert "exactly one" in str(exc.value)


def test_the_tool_refuses_a_manifest_that_is_not_there(admit_map, tmp_path):
    with pytest.raises(SystemExit) as exc:
        admit_map.main(["--dry-run", "--manifest", str(tmp_path / "nope.json")])
    assert "nothing to admit" in str(exc.value)


def test_the_tool_refuses_a_codebook_that_has_moved_since_the_map(admit_map, tmp_path, manifest):
    """Re-gating against a different codebook would admit values the map never produced."""
    m = {**manifest, "codebook_sha": "0" * 64}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        admit_map.main(["--dry-run", "--manifest", str(p)])
    assert "different codebook" in str(exc.value)


# The store the tool's own `--db` opens. The fixture cases are synthetic, so the rehearsal
# needs a store that holds them; `store.connect` over a scratch file plus the four rows is
# the whole dependency, and it is what makes `main()` runnable end to end (finding 5).
def _scratch_db(tmp_path, fixture_dir):
    from corpus_engine import store
    db = tmp_path / "cases.db"
    conn = store.connect(db)
    conn.execute("""CREATE TABLE IF NOT EXISTS cases (
                      case_id INTEGER PRIMARY KEY, cite TEXT, name_abbreviation TEXT,
                      court TEXT, jurisdiction TEXT, decision_year INTEGER,
                      raw_text TEXT, norm_text TEXT, page_map TEXT)""")
    for cid, c in json.loads((fixture_dir / "cases.json").read_text(encoding="utf-8")).items():
        norm, _o = normalize(c["raw_text"])
        conn.execute("INSERT OR REPLACE INTO cases VALUES (?,?,?,?,?,?,?,?,?)",
                     (int(cid), c["cite"], c["name"], c["court"], c["jurisdiction"], c["year"],
                      c["raw_text"], norm, json.dumps([[0, "1"]])))
    conn.commit()
    conn.close()
    return db


def _rehearsal_argv(tmp_path, fixture_dir, *extra):
    return ["--manifest", str(fixture_dir / "manifest.json"),
            "--batches", str(fixture_dir / "batches"),
            "--cache", str(fixture_dir / "cache"),
            "--db", str(_scratch_db(tmp_path, fixture_dir)),
            "--ledger", str(tmp_path / "ledger"), *extra]


def test_the_tool_runs_end_to_end_on_a_dry_run_and_writes_nothing(admit_map, tmp_path,
                                                                  fixture_dir, capsys):
    """`main()`'s happy path, over the fixture map and a scratch ledger - the rehearsal Task 9
    needs before it touches the real one."""
    assert admit_map.main(_rehearsal_argv(tmp_path, fixture_dir, "--dry-run")) == 0
    out = capsys.readouterr().out
    assert "4 accepted records -> 29 patches" in out
    assert f"  {CELL_NY}: 2 records (1 relevant, 1 irrelevant)" in out
    assert f"  {CELL_OHIO}: 2 records (2 relevant, 0 irrelevant)" in out
    assert "29 would apply, 0 already present (dry run)" in out
    assert "before: relevant 0 records (0 human-reviewed, 0 machine-only" in out
    assert "after:  relevant 3 records (0 human-reviewed, 3 machine-only" in out
    assert not (tmp_path / "ledger").exists()          # nothing was written, not even the dir


def test_the_tool_applies_and_then_refuses_the_same_run_id_but_never_a_dry_run(admit_map,
                                                                               tmp_path,
                                                                               fixture_dir,
                                                                               capsys):
    assert admit_map.main(_rehearsal_argv(tmp_path, fixture_dir, "--apply")) == 0
    assert "29 applied, 0 already present; replay_ok=True" in capsys.readouterr().out
    assert (tmp_path / "ledger" / "patches.jsonl").exists()
    with pytest.raises(SystemExit) as exc:
        admit_map.main(_rehearsal_argv(tmp_path, fixture_dir, "--apply"))
    assert "already has patches in the ledger" in str(exc.value)
    assert "cycle-004-shard-01" in str(exc.value)
    # --force gets past it, and an identical re-admission is skipped patch by patch anyway
    assert admit_map.main(_rehearsal_argv(tmp_path, fixture_dir, "--apply", "--force")) == 0
    assert "0 applied, 29 already present" in capsys.readouterr().out
    # ... and a dry run is NEVER refused: inspecting an admitted run must not need --force
    assert admit_map.main(_rehearsal_argv(tmp_path, fixture_dir, "--dry-run")) == 0


def test_the_guard_asks_about_the_manifests_run_id_not_the_flags(admit_map, tmp_path,
                                                                 fixture_dir, manifest, capsys):
    """`--manifest` may point at another run's manifest, and `basis_for` takes the run id from
    THERE. Keying the guard off `--run-id` would ask the ledger about a run the patches do not
    carry, silently disarming the duplicate-admission refusal."""
    admit_map.main(_rehearsal_argv(tmp_path, fixture_dir, "--apply"))
    capsys.readouterr()
    argv = _rehearsal_argv(tmp_path, fixture_dir, "--apply", "--run-id", "cycle-009-shard-07")
    with pytest.raises(SystemExit) as exc:
        admit_map.main(argv)
    assert "cycle-004-shard-01" in str(exc.value) and "cycle-009" not in str(exc.value)
    assert "the manifest's run id is 'cycle-004-shard-01'" in capsys.readouterr().out
