import json
import pytest
from corpus_engine.ledger.types import (Basis, Patch, UNSET, UnknownCase, DuplicateRecord,
                                        MissingBasis)
from corpus_engine.ledger.fold import (FLAG_PREFIX, JUDGED_DEFAULT, PROTECTION_FROM_SEQ,
                                       PROTECTION_RULE_ID, SUPPORTED, SUPPORTED_BY_PROMPT,
                                       State, apply_patch, is_protected_write,
                                       is_reader_write, provenance_kind, quote_supports,
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


def test_supported_fields_falls_back_to_mapper_v1_only_when_missing_or_empty():
    """Review finding 1 (controller amendment): `None`/missing/`""` is a real historical
    state - every pre-D7 admit patch predates the field - and stays SUPPORTED. Anything
    non-empty that isn't a known codebook version is a bug (typo, or a shipped codebook with
    no SUPPORTED_BY_PROMPT entry) and must not be silently narrowed to three fields."""
    assert supported_fields(None) == SUPPORTED
    assert supported_fields("") == SUPPORTED


def test_supported_fields_raises_on_an_unknown_non_empty_version_naming_it():
    with pytest.raises(ValueError, match="mapper-v9"):
        supported_fields("mapper-v9")
    with pytest.raises(ValueError, match="mapper-v4"):
        supported_fields("mapper-v4:deadbeefcafe")


def test_every_shipped_codebook_has_a_support_rule(repo_root):
    """M5. `mapper-v2.md` shipped and had no entry, so a legacy record carrying it would have
    raised straight out of `corpus_engine.verification` and taken the pipeline down. Its own
    hard requirement 1 names the same six fields mapper-v3's does."""
    shipped = sorted(p.stem for p in
                     (repo_root / "domains/str-right-to-let/codebooks").glob("mapper-v*.md"))
    assert shipped == ["mapper-v1", "mapper-v2", "mapper-v3"]
    assert all(v in SUPPORTED_BY_PROMPT for v in shipped)
    assert supported_fields("mapper-v2:deadbeefcafe") == SUPPORTED_BY_PROMPT["mapper-v3"]


def test_supported_fields_lookup_is_exact_not_case_or_whitespace_folded():
    """The lookup is on the segment before ':' verbatim - `"MAPPER-V3"` and `"mapper-v3 "`
    (trailing space) are unknown, not aliases for `mapper-v3`."""
    with pytest.raises(ValueError, match="MAPPER-V3"):
        supported_fields("MAPPER-V3")
    with pytest.raises(ValueError):
        supported_fields("mapper-v3 ")


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


def test_prompt_falls_back_to_the_earliest_judged_set_when_the_admit_carries_none():
    """Review finding 2: spec section 8 does not require the D8 basis to live on the admit
    patch itself. When an admit's own basis carries no `prompt_version` (here a rule-only
    admit), the record's admitting prompt comes from the earliest `set` on a judged field
    whose OWN basis carries one - and, once found, stays fixed (finding 3's guard applies
    here too: a later judged `set` under a different basis must not move it)."""
    s = State()
    rec = {"case_id": 6, "relevant": True, "polarity": None, "quotes": []}
    apply_patch(s, Patch(6, "admit", "", rec, "cycle-004 admit", Basis(rule_id="cycle-004-admit"),
                         cycle="cycle-004"))
    assert s.prompts[6] == ""
    apply_patch(s, Patch(6, "set", "polarity", "favorable", "reader set", READER_V3))
    assert s.prompts[6] == MAPPER_V3
    apply_patch(s, Patch(6, "set", "characterization", "lease", "reviewer set",
                         Basis(reviewer="mmaldo2")))
    assert s.prompts[6] == MAPPER_V3                      # not erased by the reviewer's set


def test_a_reviewer_readmit_does_not_erase_the_recorded_reader_prompt():
    """Task-2 review finding 3, still in force under I2: a re-admit under a reviewer-only
    basis (the `admit` branch does not require `can_judge`) carries no `prompt_version` and
    must not narrow an already-known mapper-v3 record to mapper-v1."""
    s = State()
    rec = {"case_id": 7, "relevant": True, "polarity": "favorable", "quotes": []}
    _admit(s, 7, READER_V3, rec)
    assert s.prompts[7] == MAPPER_V3
    readmit_rec = {"case_id": 7, "relevant": True, "polarity": "adverse", "quotes": []}
    apply_patch(s, Patch(7, "admit", "", readmit_rec, "re-admit after correction",
                         Basis(reviewer="mmaldo2"), cycle="cycle-004"))
    assert s.prompts[7] == MAPPER_V3
    assert s.records[7]["polarity"] == "adverse"


def test_a_re_read_under_a_new_codebook_moves_the_record_to_the_new_support_rule():
    """Final-review I2, which REVERSES the Task-2 fix-round rule that pinned the admitting
    prompt at first sight. Slice 3 re-reads cycles 1-3 under mapper-v3, and a re-read
    re-admits: the record now stands on the new read's quotes, so it must fold under the new
    codebook's six-field rule. Pinned at first sight, its mapper-v3 values would survive a
    dropped quote on evidence the mapper-v1 codebook never asked for."""
    s = State()
    v1_rec = {"case_id": 9, "relevant": True, "polarity": "favorable",
              "characterization": "lease", "holding_summary": "h",
              "quotes": [{"text": "Q1", "supports": "polarity"}]}
    apply_patch(s, Patch(9, "admit", "", v1_rec, "cycle-001 admit", READER_V1,
                         cycle="cycle-001"))
    assert s.prompts[9] == "mapper-v1"

    v3_rec = {"case_id": 9, "relevant": True, "polarity": "favorable",
              "characterization": "lodging", "under_thirty_days": "yes",
              "owner_freedom_characterization": "incident_of_ownership",
              "restriction_nature": "zoning", "holding_summary": "h",
              "quotes": [{"text": "Q1", "supports": ["polarity"]},
                         {"text": "Q2", "supports": ["characterization"]}]}
    apply_patch(s, Patch(9, "admit", "", v3_rec, "slice 3 re-read", READER_V3,
                         cycle="cycle-001"))
    assert s.prompts[9] == MAPPER_V3

    apply_patch(s, Patch(9, "drop_quote", "quotes", "Q1", "quote failed",
                         Basis(reviewer="mmaldo2")))
    out = s.records[9]
    assert out["characterization"] == "lodging"           # Q2 still supports it
    assert out["polarity"] is None                        # both rules null this one
    assert out["under_thirty_days"] is None               # only the six-field rule nulls these
    assert out["owner_freedom_characterization"] is None and out["restriction_nature"] is None
    assert out["holding_summary"] is None


def test_a_later_admit_that_names_no_prompt_leaves_the_read_that_did_standing():
    """The other half of I2: only an admit that NAMES a prompt moves the record. A rule-only
    or reviewer-only re-admit is provenance for the record, not for the read."""
    s = State()
    _admit(s, 10, READER_V3, {"case_id": 10, "relevant": True, "quotes": []})
    apply_patch(s, Patch(10, "admit", "", {"case_id": 10, "relevant": True, "quotes": []},
                         "rule-only re-admit", Basis(rule_id="cycle-004-admit"),
                         cycle="cycle-004"))
    assert s.prompts[10] == MAPPER_V3
    apply_patch(s, Patch(10, "set", "polarity", "adverse", "reader set", READER_V1))
    assert s.prompts[10] == MAPPER_V3                     # nor does a later judged `set`


def test_a_hand_built_state_missing_prompts_falls_back_to_the_three_field_rule():
    """Review finding 6. A caller that reconstructs `State(records=..., order=..., cycles=...,
    in_file=...)` from a snapshot without copying `prompts` (the pattern in
    test_apply_validates_on_a_fresh_replay_not_a_mutated_trial) gets the mapper-v1 rule for
    every case in it, even one admitted under mapper-v3 in the real ledger -- this is legal
    (finding 1 requires missing to stay legal) but is documented here so the fallback is a
    pinned, known behaviour rather than a surprise."""
    real = State()
    rec = {"case_id": 8, "relevant": True, "polarity": "favorable", "under_thirty_days": "yes",
           "quotes": [{"text": "Q1", "supports": ["polarity", "under_thirty_days"]}]}
    _admit(real, 8, READER_V3, rec)
    assert real.prompts[8] == MAPPER_V3

    trial = State(records=dict(real.records), order=list(real.order),
                  cycles=dict(real.cycles), in_file=dict(real.in_file))  # prompts dropped
    apply_patch(trial, Patch(8, "drop_quote", "quotes", "Q1", "quote failed", Basis(reviewer="m")))
    out = trial.records[8]
    assert out["polarity"] is None                            # both rules null this field
    assert out["under_thirty_days"] == "yes"                  # mapper-v1 rule wrongly spares it
    assert out["nulled_fields"] == ["polarity"]


def test_cascade_false_still_skips_the_cascade_under_the_v3_rule():
    s = State()
    rec = {"case_id": 4, "relevant": True, "polarity": "favorable", "under_thirty_days": "yes",
           "quotes": [{"text": "Q1", "supports": ["polarity", "under_thirty_days"]}]}
    _admit(s, 4, READER_V3, rec)
    apply_patch(s, Patch(4, "drop_quote", "quotes", "Q1", "no cascade", Basis(reviewer="mmaldo2"),
                         cascade=False), cascade=False)
    assert s.records[4]["polarity"] == "favorable" and s.records[4]["under_thirty_days"] == "yes"


# ---------------------------------------------------------------- D2: reviewer protection

READER = Basis(model="claude-opus-5@claude-cli", prompt_version="mapper-v3:f92016681314",
               run_id="cycles-001-003-reread")
HUMAN = Basis(reviewer="mmaldo2", run_id="map-cycle-004-round-1")
# Protection is enforced above the grandfather baseline only (R1), so every patch that is
# meant to be judged by the rule carries a seq the real log has not reached.
AFTER = PROTECTION_FROM_SEQ + 1


def _admitted() -> State:
    s = State()
    apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(model="m", prompt_version="mapper-v1",
                                                         run_id="cycle-001"), cycle="cycle-001"))
    return s


def test_the_fold_flag_prefix_is_the_readers_flag_prefix():
    """One spelling of the flag. The ledger cannot import the reader (it is upstream of it),
    so the constant is re-declared there and pinned equal here instead."""
    from corpus_engine.reader.schema import FLAG_PREFIX as READER_PREFIX
    assert FLAG_PREFIX == READER_PREFIX == "needs-review:"


def test_the_refusing_rule_names_itself_on_the_entry():
    """R2. `by` is the basis that attempted the write; `by_rule` is what refused it, so the
    section-G card can cite the rule rather than infer it."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "polarity", "favorable", "re-read", READER, seq=AFTER))
    assert s.conflicts[5][0]["by_rule"] == PROTECTION_RULE_ID == "reviewer-protection"


def test_a_reader_set_never_overwrites_a_reviewer_value():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    assert s.provenance[5]["polarity"] == "human"
    old = apply_patch(s, Patch(5, "set", "polarity", "favorable", "re-read", READER, seq=AFTER))
    assert old is UNSET                                     # nothing was replaced
    assert s.records[5]["polarity"] == "adverse"            # the human's value stands
    assert s.provenance[5]["polarity"] == "human"
    assert s.conflicts[5] == [{"field": "polarity", "attempted": "favorable",
                               "standing": "adverse", "by": READER.to_json(), "at": AFTER,
                               "op": "set", "historical": False,
                               "by_rule": PROTECTION_RULE_ID}]
    assert s.records[5]["review"]["flags"] == ["needs-review:polarity"]


def test_a_reader_set_of_the_same_value_is_silent():
    """161 writes in the real log do exactly this. Nothing is overwritten, so nothing is
    reported - and the committed snapshot still reproduces."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "re-read", READER, seq=AFTER))
    assert s.records[5]["polarity"] == "adverse"
    assert 5 not in s.conflicts
    assert s.records[5]["review"]["flags"] == []


def test_a_value_identical_no_op_still_records_the_admitting_prompt():
    """Review finding 7: D2 must change nothing but the judged value. The silent no-op sits
    AFTER the prompt record, so a record whose only prompt source is one of the 161
    value-identical writes still folds under its own codebook's support rule rather than
    falling back to mapper-v1's three fields on a later `drop_quote`."""
    s = State()
    apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(rule_id="cycle-004-admit"), cycle="c"))
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    assert s.prompts[5] == ""                                # nothing has named a codebook yet
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "re-read", READER, seq=AFTER))
    assert s.prompts[5] == "mapper-v3:f92016681314"
    assert 5 not in s.conflicts                              # and it is still a silent no-op


def test_a_reader_retraction_to_none_is_rejected_on_a_reviewer_field():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "who_was_letting", "householder", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "who_was_letting", None, "re-read", READER, seq=AFTER))
    assert s.records[5]["who_was_letting"] == "householder"
    assert s.conflicts[5][0]["attempted"] is None and s.conflicts[5][0]["at"] == AFTER
    assert s.records[5]["review"]["flags"] == ["needs-review:who_was_letting"]


def test_a_reader_set_replaces_a_reader_value_and_keeps_reader_provenance():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "mixed", "re-read", READER, seq=AFTER))
    assert s.records[5]["polarity"] == "mixed"
    assert s.provenance[5]["polarity"] == "reader" and 5 not in s.conflicts


def test_a_rule_retraction_over_a_reviewer_value_is_rejected_too():
    """Controller ruling: D2 rejects EVERY non-reviewer write, rule basis included. The
    `retraction-cascade-v1` null of a human characterization is exactly the overwrite the
    protection exists to stop, so after the baseline a rule must go through a reviewer."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    old = apply_patch(s, Patch(5, "set", "polarity", None, "cascade",
                               Basis(rule_id="retraction-cascade-v1"), seq=AFTER))
    assert old is UNSET
    assert s.records[5]["polarity"] == "adverse"
    assert s.provenance[5]["polarity"] == "human"
    assert s.conflicts[5][0]["by"] == {"rule_id": "retraction-cascade-v1"}
    assert s.conflicts[5][0]["historical"] is False
    assert s.records[5]["review"]["flags"] == ["needs-review:polarity"]


def test_a_write_at_or_below_the_baseline_is_grandfathered_and_only_recorded():
    """R1. The six rule-basis writes over reviewer values already in the log applied when
    they were written; re-judging them now would rewrite five committed records. They stay
    applied, carry no flag, and are visible only through `historical=True`."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "polarity", None, "cascade",
                         Basis(rule_id="retraction-cascade-v1"), seq=PROTECTION_FROM_SEQ))
    assert s.records[5]["polarity"] is None                  # it applied, as it always has
    assert s.provenance[5]["polarity"] == "human"            # and the judgment is not un-made
    assert s.records[5]["review"]["flags"] == []             # no flag, so no rendered byte moves
    assert s.conflicts[5] == [{"field": "polarity", "attempted": None, "standing": "adverse",
                               "by": {"rule_id": "retraction-cascade-v1"},
                               "at": PROTECTION_FROM_SEQ, "op": "set", "historical": True,
                               "by_rule": PROTECTION_RULE_ID}]
    # and the field is still human, so a later re-read is carded rather than silently applied
    apply_patch(s, Patch(5, "set", "polarity", "favorable", "re-read", READER, seq=AFTER))
    assert s.records[5]["polarity"] is None and s.conflicts[5][1]["standing"] is None


def test_a_reviewer_may_always_redecide():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "polarity", "mixed", "round 2", Basis(reviewer="mmaldo2"),
                         seq=AFTER))
    assert s.records[5]["polarity"] == "mixed" and 5 not in s.conflicts


def test_a_re_admit_body_may_not_change_a_reviewer_decided_field():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    body = {**REC, "polarity": "favorable", "characterization": "tenancy"}
    apply_patch(s, Patch(5, "admit", "", body, "re-read", READER, cycle="cycle-001", seq=AFTER))
    assert s.records[5]["polarity"] == "adverse"            # the human's value survives
    assert s.records[5]["characterization"] == "tenancy"    # a reader field does not
    assert s.conflicts[5] == [{"field": "polarity", "attempted": "favorable",
                               "standing": "adverse", "by": READER.to_json(), "at": AFTER,
                               "op": "admit", "historical": False,
                               "by_rule": PROTECTION_RULE_ID}]
    assert s.records[5]["review"]["flags"] == ["needs-review:polarity"]


def test_a_re_admit_body_that_omits_a_human_field_carries_the_value_forward():
    """A re-admit REPLACES the record, so a body that says nothing about a field a human
    decided would drop the value - a null by omission, which is an overwrite by any other
    name (controller ruling, fix round 2). The standing value is carried forward instead.
    Nothing was attempted against it, so there is no conflict and no flag; a body that does
    carry a DIFFERENT value for the same field is still refused, with both."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    body = {k: v for k, v in REC.items() if k != "polarity"}
    apply_patch(s, Patch(5, "admit", "", body, "re-read", READER, cycle="cycle-001", seq=AFTER))
    assert s.records[5]["polarity"] == "adverse"             # the human's value stands
    assert s.provenance[5]["polarity"] == "human"
    assert 5 not in s.conflicts                              # nothing was attempted against it
    assert s.records[5]["review"]["flags"] == []
    # A reader field the body omits is NOT carried forward: the body is the read now.
    body2 = {k: v for k, v in REC.items() if k not in ("polarity", "characterization")}
    apply_patch(s, Patch(5, "admit", "", body2, "re-read", READER, cycle="cycle-001",
                         seq=AFTER + 1))
    assert s.records[5]["polarity"] == "adverse" and "characterization" not in s.records[5]
    # ...and a body that speaks against the human value is refused, as in round 1.
    apply_patch(s, Patch(5, "admit", "", {**REC, "polarity": "favorable"}, "re-read", READER,
                         cycle="cycle-001", seq=AFTER + 2))
    assert s.records[5]["polarity"] == "adverse"
    assert s.conflicts[5][0]["attempted"] == "favorable" and s.conflicts[5][0]["op"] == "admit"
    assert s.records[5]["review"]["flags"] == ["needs-review:polarity"]


def test_a_reviewer_re_admit_may_still_drop_a_field_it_omits():
    """The protection is against non-reviewer writes only: a reviewer re-admitting a record
    is a human replacing it, omissions included."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    body = {k: v for k, v in REC.items() if k != "polarity"}
    apply_patch(s, Patch(5, "admit", "", body, "re-admit", Basis(reviewer="mmaldo2"),
                         cycle="cycle-001", seq=AFTER))
    assert "polarity" not in s.records[5] and 5 not in s.conflicts


def test_a_migrate_never_touches_a_decided_field_and_records_no_conflict():
    """R1 exempts `migrate`: a vocabulary migration renames a value rather than judging a
    case, and it only ever fills a key the record does not already carry."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    apply_patch(s, Patch(5, "migrate", "", {"schema_version": 3, "polarity": "favorable",
                                            "restriction_nature": None}, "v3",
                         Basis(rule_id="m"), seq=AFTER))
    assert s.records[5]["polarity"] == "adverse"            # a present key is never rewritten
    assert s.records[5]["restriction_nature"] is None       # an absent one is filled
    assert s.records[5]["schema_version"] == 3
    assert 5 not in s.conflicts and s.records[5]["review"]["flags"] == []


def test_provenance_and_the_protection_helpers():
    assert provenance_kind(HUMAN) == "human"
    assert provenance_kind(READER) == "reader"
    assert provenance_kind(Basis(rule_id="r")) == "rule"
    assert provenance_kind(Basis()) == "reader"             # an admit body with a bare basis
    # `is_reader_write` still answers only "did a reader write this"...
    assert is_reader_write(READER) is True
    assert is_reader_write(HUMAN) is False
    assert is_reader_write(Basis(rule_id="retraction-cascade-v1")) is False
    # ...but the gate is wider: everything that is not a reviewer is protected against.
    assert is_protected_write(READER) is True
    assert is_protected_write(Basis(rule_id="retraction-cascade-v1")) is True
    assert is_protected_write(Basis()) is True
    assert is_protected_write(HUMAN) is False
    assert is_protected_write(Basis(reviewer="m", rule_id="r")) is False


def test_an_admit_body_records_provenance_for_every_judged_field_it_carries():
    s = _admitted()
    assert s.provenance[5]["relevant"] == "reader"
    assert s.provenance[5]["polarity"] == "reader"
    assert "who_was_letting" not in s.provenance[5]         # the body does not carry it
