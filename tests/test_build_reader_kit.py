"""Kit v2 is kit v1's 195 cases with the labels the ledger now carries. What has to hold:
the same case ids in the same batching, `irrelevant` normalised out of polarity (D2), and
the fields the reviewer marked unsure recorded per case so scoring can drop them for that
field only (D6). Imported by path because tools/ is scripts, not a package."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_reader_kit", ROOT / "tools" / "build_reader_kit.py")
brk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brk)

ROWS = [{"case_id": 1, "source": "human", "era": "pre-1860", "jurisdiction": "N.Y."},
        {"case_id": 2, "source": "human", "era": "pre-1860", "jurisdiction": "N.Y."},
        {"case_id": 3, "source": "human", "era": "1860-1900", "jurisdiction": "Mass."},
        {"case_id": 4, "source": "machine", "era": "1860-1900", "jurisdiction": "Mass."}]
RECORDS = {1: {"relevant": True, "polarity": "irrelevant", "who_was_letting": "unclear"},
           2: {"relevant": True, "polarity": "mixed", "who_was_letting": "householder"},
           3: {"relevant": False, "polarity": "adverse", "who_was_letting": "commercial_operator"},
           4: {"relevant": True, "polarity": "favorable", "who_was_letting": "householder"}}
FLAGS = {2: ["needs-review:who_was_letting", "polarity-open-question"], 3: ["needs-review:polarity"]}


def test_reference_rows_normalise_polarity_and_record_the_exclusions():
    out = {r["case_id"]: r for r in brk.reference_rows(ROWS, RECORDS, FLAGS)}
    # `irrelevant` is not a polarity value; the case stays relevant and its polarity is undecided
    assert out[1]["relevant"] is True and out[1]["polarity"] is None and out[1]["who_was_letting"] == "unclear"
    assert out[2]["polarity"] == "mixed" and out[2]["excluded_fields"] == ["who_was_letting"]
    # a case the ledger now calls irrelevant carries no polarity and no who_was_letting
    assert out[3]["relevant"] is False and out[3]["polarity"] is None and out[3]["who_was_letting"] is None
    assert out[3]["excluded_fields"] == ["polarity"]
    # a machine row keeps its machine-irrelevant label whatever the ledger says: it is the
    # control sample, scored separately and never toward the bar
    assert out[4]["source"] == "machine" and out[4]["relevant"] is False and out[4]["polarity"] is None
    assert out[1]["excluded_fields"] == []


def test_reference_rows_read_the_flags_the_ledger_actually_carries():
    """R7: the flags live at `records[cid]["review"]["flags"]`; `reference_rows` is handed
    that list, and `flags_for` is the one place that knows where to find it."""
    records = {2: {"relevant": True, "polarity": "mixed", "who_was_letting": "householder",
                   "review": {"flags": ["needs-review:who_was_letting"]}},
               9: {"relevant": True, "review": {}}}
    assert brk.flags_for(records, [2, 9, 404]) == {2: ["needs-review:who_was_letting"], 9: [], 404: []}


def test_make_batches_is_deterministic_and_keeps_every_case():
    reference = brk.reference_rows(ROWS, RECORDS, FLAGS)
    a = brk.make_batches(reference, {1: [{"selector_id": "s"}]}, "kit-v2")
    b = brk.make_batches(reference, {1: [{"selector_id": "s"}]}, "kit-v2")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert [x["batch_id"] for x in a] == ["kit-v2-batch-001", "kit-v2-batch-002"]     # two strata
    ids = sorted(c["case_id"] for x in a for c in x["cases"])
    assert ids == [1, 2, 3, 4]
    assert a[0]["era_partition"] == "1860-1900" and a[0]["jurisdiction"] == "Mass."
    assert a[0]["cases"][0]["signals"] == []
    big = brk.make_batches([dict(ROWS[0], case_id=i, relevant=True, polarity=None,
                                 who_was_letting=None, excluded_fields=[]) for i in range(40)],
                           {}, "kit-v2")
    assert [len(x["cases"]) for x in big] == [18, 18, 4]


def test_case_ids_from_reads_an_existing_kit(tmp_path):
    kit = {"reference": [{"case_id": 7, "source": "human", "era": "pre-1860", "jurisdiction": "N.Y."},
                         {"case_id": 8, "source": "machine", "era": "pre-1860", "jurisdiction": "N.Y."}]}
    p = tmp_path / "kit.json"
    p.write_bytes(json.dumps(kit).encode("utf-8"))
    assert brk.case_ids_from(p) == [{"case_id": 7, "source": "human", "era": "pre-1860", "jurisdiction": "N.Y."},
                                    {"case_id": 8, "source": "machine", "era": "pre-1860", "jurisdiction": "N.Y."}]


def test_kit_v1_is_still_the_kit_v1_the_measurement_bought(repo_root):
    """kit-v1 is never edited: measurement-v1's numbers are only meaningful against it."""
    import hashlib
    raw = (repo_root / "data/reader/kit-v1/kit.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == \
        "b393f2863feef6c9f1810c2bdeb2af983f695aa9d64604ab3db8be364160891f"


def test_kit_v2_is_kit_v1s_cases_under_the_patched_ledger(repo_root):
    """The built kit is part of the repo, so the invariants the build promised are checked
    here rather than only in the build's own stdout: same 195 cases in the same order, the
    same 23 batches, no `irrelevant` anywhere in polarity, and the sha domain.yaml pins."""
    import hashlib
    from corpus_engine.domain import load_domain
    v2_path = repo_root / "data/reader/kit-v2/kit.json"
    if not v2_path.exists():
        import pytest
        pytest.skip("kit-v2 not built in this checkout")
    raw = v2_path.read_bytes()
    assert raw.endswith(b"\n")                                    # R11
    kit = json.loads(raw.decode("utf-8"))
    v1 = json.loads((repo_root / "data/reader/kit-v1/kit.json").read_text(encoding="utf-8"))
    assert [r["case_id"] for r in kit["reference"]] == [r["case_id"] for r in v1["reference"]]
    assert [r["source"] for r in kit["reference"]] == [r["source"] for r in v1["reference"]]
    assert len(kit["reference"]) == 195 and len(kit["batches"]) == 23
    assert all(r["polarity"] in ("favorable", "adverse", "mixed", None) for r in kit["reference"])
    assert all(r["polarity"] is None and r["who_was_letting"] is None
               for r in kit["reference"] if not r["relevant"])
    reader = load_domain().reader
    assert reader.kit_sha256 == hashlib.sha256(raw).hexdigest()
    sample = json.loads((repo_root / "data/reader/kit-v2/sample-50.json").read_text(encoding="utf-8"))
    assert sample == json.loads((repo_root / "data/reader/kit-v1/sample-50.json").read_text(encoding="utf-8"))
