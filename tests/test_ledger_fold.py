import json
import pytest
from corpus_engine.ledger.types import Basis, Patch, UnknownCase, DuplicateRecord, MissingBasis
from corpus_engine.ledger.fold import (JUDGED_DEFAULT, SUPPORTED, SUPPORTED_BY_PROMPT,
                                       State, apply_patch, quote_supports,
                                       supported_fields)
from corpus_engine.ledger.log import PatchLog, patch_id

REC = {"case_id": 5, "cite": "1 X 1", "year": 1880, "relevant": True, "polarity": "favorable",
       "characterization": "lodging", "holding_summary": "h",
       "quotes": [{"text": "A", "supports": "polarity"}, {"text": "B", "supports": "characterization"}]}

def test_admit_adds_review_default_and_tracks_order_and_cycle():
    s = State()
    apply_patch(s, Patch(5, "admit", "", REC, "verified", Basis(model="m", prompt_version="v1", run_id="r"), cycle="cycle-001"))
    assert s.order == [5] and s.cycles[5] == "cycle-001" and s.in_file[5] is True
    assert s.records[5]["review"] == {"status": "machine", "flags": [], "notes": []}
    assert list(s.records[5].keys())[-1] == "review"
    with pytest.raises(DuplicateRecord):
        apply_patch(s, Patch(5, "admit", "", REC, "again", Basis(), cycle="cycle-002"))

def test_set_on_judged_field_needs_authority_and_returns_old():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    with pytest.raises(MissingBasis):
        apply_patch(s, Patch(5, "set", "polarity", "adverse", "hunch", Basis(rule_id="x")))
    old = apply_patch(s, Patch(5, "set", "polarity", "adverse", "re-review", Basis(reviewer="mmaldo2")))
    assert old == "favorable" and s.records[5]["polarity"] == "adverse"
    apply_patch(s, Patch(5, "set", "review.status", "human-adjudicated", "x", Basis(rule_id="r")))
    apply_patch(s, Patch(5, "append", "review.notes", "note", "x", Basis(rule_id="r")))
    assert s.records[5]["review"] == {"status": "human-adjudicated", "flags": [], "notes": ["note"]}
    with pytest.raises(UnknownCase):
        apply_patch(s, Patch(6, "set", "polarity", "adverse", "x", Basis(reviewer="m")))

def test_set_none_on_judged_field_needs_no_judging_authority():
    # A retraction to None removes a claim rather than judging the case, so
    # it needs no reviewer/model authority -- unlike setting a real value.
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    old = apply_patch(s, Patch(5, "set", "polarity", None, "retraction", Basis(rule_id="retraction-cascade-v1")))
    assert old == "favorable" and s.records[5]["polarity"] is None
    with pytest.raises(MissingBasis):
        apply_patch(s, Patch(5, "set", "polarity", "adverse", "hunch", Basis(rule_id="retraction-cascade-v1")))

def test_drop_quote_cascades_only_when_asked():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    apply_patch(s, Patch(5, "drop_quote", "quotes", "A", "mismatch", Basis(reviewer="m")), cascade=False)
    assert s.records[5]["polarity"] == "favorable" and len(s.records[5]["quotes"]) == 1
    apply_patch(s, Patch(5, "drop_quote", "quotes", "B", "mismatch", Basis(reviewer="m")), cascade=True)
    assert s.records[5]["characterization"] is None
    assert s.records[5]["polarity"] is None
    assert s.records[5]["holding_summary"] is None
    assert s.records[5]["nulled_fields"] == ["characterization", "polarity", "holding_summary"]

def test_drop_quote_does_not_append_field_twice():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    apply_patch(s, Patch(5, "drop_quote", "quotes", "A", "mismatch", Basis(reviewer="m")), cascade=True)
    apply_patch(s, Patch(5, "drop_quote", "quotes", "B", "mismatch", Basis(reviewer="m")), cascade=True)
    # Sequential cascading nulls fields, but no field appears twice in nulled_fields
    nulled = s.records[5]["nulled_fields"]
    assert len(nulled) == len(set(nulled))  # no duplicates
    assert set(nulled) == {"characterization", "polarity", "holding_summary"}

def test_migrate_appends_v2_fields_at_end():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    apply_patch(s, Patch(5, "migrate", "", {"schema_version": 2, "under_30_days": None}, "v2", Basis(rule_id="schema-v2")))
    keys = list(s.records[5].keys())
    assert keys[-2:] == ["schema_version", "under_30_days"] or keys[-1] == "under_30_days"

def test_patch_log_stamps_and_round_trips(tmp_path):
    log = PatchLog(tmp_path / "patches.jsonl")
    p = Patch(5, "set", "polarity", "adverse", "why", Basis(reviewer="m"))
    [stamped] = log.append([p])
    assert stamped.seq == 1 and stamped.patch_id == patch_id(p) and stamped.at
    assert log.read() == [stamped] and log.head() == 1
    assert json.loads((tmp_path / "patches.jsonl").read_text().splitlines()[0])["seq"] == 1


MAPPER_V3 = "mapper-v3:f92016681314"
READER_V3 = Basis(model="claude-opus-5@claude-cli", prompt_version=MAPPER_V3,
                  run_id="cycle-004-shard-01")
READER_V1 = Basis(model="sonnet@claude-cli", prompt_version="mapper-v1", run_id="cycle-001-shard-02")


def test_the_judged_vocabulary_is_the_readers_spelling():
    """D7. The ledger never carried `under_30_days` or `right_characterization` - no record
    and no patch has ever used either name - so this is a rename, not a migration."""
    assert JUDGED_DEFAULT == ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                              "characterization", "holding_summary", "under_thirty_days",
                              "restriction_nature", "owner_freedom_characterization")
    assert "under_30_days" not in JUDGED_DEFAULT and "right_characterization" not in JUDGED_DEFAULT


def test_the_support_rule_is_scoped_by_the_prompt_that_read_the_record():
    assert SUPPORTED_BY_PROMPT["mapper-v1"] == SUPPORTED == ("characterization", "polarity",
                                                             "holding_summary")
    assert SUPPORTED_BY_PROMPT["mapper-v3"] == ("characterization", "polarity", "holding_summary",
                                                "owner_freedom_characterization",
                                                "restriction_nature", "under_thirty_days")
    assert supported_fields(MAPPER_V3) == SUPPORTED_BY_PROMPT["mapper-v3"]   # sha suffix ignored
    assert supported_fields("mapper-v1") == SUPPORTED
    assert supported_fields(None) == SUPPORTED and supported_fields("mapper-v9") == SUPPORTED


def _admit(state, cid, basis, rec):
    apply_patch(state, Patch(cid, "admit", "", rec, "test admit", basis, cycle="cycle-004"))


def test_drop_quote_cascades_over_six_fields_for_a_mapper_v3_record():
    s = State()
    rec = {"case_id": 1, "relevant": True, "polarity": "favorable",
           "characterization": "lodging", "under_thirty_days": "yes",
           "owner_freedom_characterization": "incident_of_ownership",
           "restriction_nature": "zoning", "holding_summary": "h",
           "quotes": [{"text": "Q1", "supports": ["polarity", "under_thirty_days"]},
                      {"text": "Q2", "supports": ["characterization"]}]}
    _admit(s, 1, READER_V3, rec)
    apply_patch(s, Patch(1, "drop_quote", "quotes", "Q1", "quote failed", Basis(reviewer="mmaldo2")))
    out = s.records[1]
    assert [q["text"] for q in out["quotes"]] == ["Q2"]
    assert out["polarity"] is None and out["under_thirty_days"] is None      # lost their support
    assert out["characterization"] == "lodging"                              # Q2 still supports it
    assert out["holding_summary"] is None and out["owner_freedom_characterization"] is None
    assert out["restriction_nature"] is None
    assert set(out["nulled_fields"]) == {"polarity", "under_thirty_days", "holding_summary",
                                         "owner_freedom_characterization", "restriction_nature"}


def test_a_mapper_v1_record_keeps_the_three_field_rule():
    """A cycle-001 record carries `supports` as a bare string and only three fields are
    cascaded, exactly as before: widening the rule for it would null fields that the v1
    codebook never asked a quote to support."""
    s = State()
    rec = {"case_id": 2, "relevant": True, "polarity": "favorable", "characterization": "lease",
           "holding_summary": "h", "who_was_letting": "householder",
           "quotes": [{"text": "Q1", "supports": "polarity"},
                      {"text": "Q2", "supports": "characterization"}]}
    _admit(s, 2, READER_V1, rec)
    apply_patch(s, Patch(2, "drop_quote", "quotes", "Q1", "quote failed", Basis(reviewer="mmaldo2")))
    out = s.records[2]
    assert out["polarity"] is None and out["holding_summary"] is None
    assert out["characterization"] == "lease"
    assert out["who_was_letting"] == "householder"        # never in SUPPORTED; untouched
    assert out["nulled_fields"] == ["polarity", "holding_summary"]


def test_quote_supports_reads_a_string_a_list_and_nothing():
    assert quote_supports({"supports": "polarity"}) == ("polarity",)
    assert quote_supports({"supports": ["polarity", "characterization"]}) == ("polarity",
                                                                              "characterization")
    assert quote_supports({"supports": ["polarity", 7, "", None]}) == ("polarity",)
    assert quote_supports({}) == () and quote_supports({"supports": None}) == ()


def test_the_admitting_prompt_is_remembered_without_touching_the_record():
    """`prompts` is a side map on State, like `cycles`: the rendered record must not gain a
    key, or every committed snapshot line changes and the replay guard fails."""
    s = State()
    rec = {"case_id": 3, "relevant": True, "polarity": "favorable", "quotes": []}
    _admit(s, 3, READER_V3, rec)
    assert s.prompts[3] == MAPPER_V3
    assert "prompt_version" not in s.records[3] and set(rec) <= set(s.records[3])
    assert set(s.records[3]) - set(rec) == {"review"}


def test_cascade_false_still_skips_the_cascade_under_the_v3_rule():
    s = State()
    rec = {"case_id": 4, "relevant": True, "polarity": "favorable", "under_thirty_days": "yes",
           "quotes": [{"text": "Q1", "supports": ["polarity", "under_thirty_days"]}]}
    _admit(s, 4, READER_V3, rec)
    apply_patch(s, Patch(4, "drop_quote", "quotes", "Q1", "no cascade", Basis(reviewer="mmaldo2"),
                         cascade=False), cascade=False)
    assert s.records[4]["polarity"] == "favorable" and s.records[4]["under_thirty_days"] == "yes"
