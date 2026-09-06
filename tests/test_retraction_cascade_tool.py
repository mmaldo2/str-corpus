"""tools/apply_retraction_cascade.py reads the same prompt-scoped support rule the fold does.

The tool used to import the flat `fold.SUPPORTED` and to build its supported set with
`{q.get("supports") for q in ...}`. Both are now wrong for a mapper-v3 record: the rule is
six fields wide, and `supports` arrives as a list (unhashable). This pins both halves with
one fixture record of each kind in a single view.
"""
import importlib.util
from pathlib import Path

from corpus_engine.domain import load_domain
from corpus_engine.ledger.fold import State, apply_patch
from corpus_engine.ledger.ledger import LedgerView
from corpus_engine.ledger.types import Basis, Patch

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):                     # tools/ is scripts, not a package
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


find_unsupported = _load("apply_retraction_cascade").find_unsupported

MAPPER_V3 = "mapper-v3:f92016681314"
READER_V3 = Basis(model="claude-opus-5@claude-cli", prompt_version=MAPPER_V3,
                  run_id="cycle-004-shard-01")
READER_V1 = Basis(model="sonnet@claude-cli", prompt_version="mapper-v1",
                  run_id="cycle-001-shard-02")

V1_REC = {"case_id": 11, "relevant": True, "polarity": "favorable",
          "characterization": "lease", "holding_summary": "h",
          "quotes": [{"text": "A", "supports": "characterization"}]}
V3_REC = {"case_id": 12, "relevant": True, "polarity": "favorable",
          "characterization": "lodging", "holding_summary": "h",
          "under_thirty_days": "yes", "restriction_nature": "zoning",
          "owner_freedom_characterization": "incident_of_ownership",
          "quotes": [{"text": "B", "supports": ["characterization", "under_thirty_days"]}]}


def _view() -> LedgerView:
    """A two-record view whose history contains a drop_quote for each case, since
    `find_unsupported` only considers records that actually had a quote dropped."""
    state = State()
    patches = [
        Patch(11, "admit", "", V1_REC, "admit", READER_V1, cycle="cycle-001"),
        Patch(12, "admit", "", V3_REC, "admit", READER_V3, cycle="cycle-004"),
        # The bootstrap replayed drops with the cascade off; that is what left the
        # records unsupported and what this tool exists to repair.
        Patch(11, "drop_quote", "quotes", "gone", "mismatch", Basis(reviewer="mmaldo2"),
              cascade=False),
        Patch(12, "drop_quote", "quotes", "gone", "mismatch", Basis(reviewer="mmaldo2"),
              cascade=False),
    ]
    for p in patches:
        apply_patch(state, p, cascade=p.cascade)
    return LedgerView("tradition", len(patches), state, patches, load_domain())


def test_a_mapper_v1_record_is_checked_against_the_three_field_rule():
    found = [(cid, f) for cid, f in find_unsupported(_view()) if cid == 11]
    # characterization is supported by the surviving quote; the other two are not.
    assert found == [(11, "polarity"), (11, "holding_summary")]


def test_a_mapper_v3_record_is_checked_against_the_six_field_rule_with_list_supports():
    found = [(cid, f) for cid, f in find_unsupported(_view()) if cid == 12]
    # The list-valued `supports` names characterization and under_thirty_days; the
    # remaining four of the six mapper-v3 fields have no surviving support.
    assert found == [(12, "polarity"), (12, "holding_summary"),
                     (12, "owner_freedom_characterization"), (12, "restriction_nature")]
