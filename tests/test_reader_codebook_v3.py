"""mapper-v3 is mapper-v2 with three repairs: `mixed` is defined, `irrelevant` is not a
polarity value, and the support rule says out loud what the gate does to a judged value no
quote names. The render check is the byte-stable part: the prompt the reader sees is the
codebook body followed by exactly the batch text the frozen mapper-v1 goldens contain, so
the codebook is the only thing that changed."""
import json
import shutil

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.model import Unit
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.sources import StoreCaseSource


def _body(text: str) -> str:
    """The codebook as render_unit uses it: the metadata comment line is stripped."""
    return text.split("\n", 1)[1] if text.startswith("<!--") else text


def _norm(s: str) -> str:
    """R4: the codebook and CONTEXT.md are hard-wrapped at ~80 columns, so every
    content assertion normalises whitespace on both sides before checking `in`."""
    return " ".join(s.split())


def test_mapper_v3_carries_the_v3_vocabulary_and_the_support_rule():
    dom = load_domain()
    v2 = load_codebook(dom, "mapper-v2")
    cb = load_codebook(dom, "mapper-v3")
    body = _norm(cb.text)
    assert cb.validated_norm_version == "v1" and cb.sha != v2.sha and len(cb.sha) == 64
    assert _norm('"schema_version": 3') in body
    # D2: mixed is defined, irrelevant is gone as a polarity value
    assert _norm("Mixed means the same opinion both recognizes the owner's freedom to let on one "
                 "point and restricts it on another") in body
    assert _norm("An owner who wins on a ground unrelated to letting is not favorable") in body
    assert _norm("`favorable` | `adverse` | `mixed` | `null`") in body
    assert _norm('"irrelevant"') not in body
    # the support rule, with the worked example and the consequence spelled out
    assert _norm('"supports": ["polarity", "characterization"]') in body
    assert _norm("a judged value not named in any quote's supports list will be erased by the verifier") in body
    # who_was_letting vocabulary unchanged from v2
    for value in ("householder", "commercial_operator", "non_resident_owner", "unclear"):
        assert _norm(value) in body
    # irrelevant records: no polarity, no who, quotes optional
    assert _norm("`relevant: false`, `polarity: null`, `who_was_letting: null`, no quotes required") in body


def test_render_under_v3_is_the_v3_body_plus_the_frozen_batch_text(tmp_path, fixture_db, repo_root, golden_dir):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    dom = load_domain()
    v1 = load_codebook(dom, "mapper-v1")
    v3 = load_codebook(dom, "mapper-v3")
    src = StoreCaseSource(conn)
    n = 0
    for bf in sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json")):
        batch = json.loads(bf.read_text(encoding="utf-8"))
        unit = Unit(batch["batch_id"], tuple(c["case_id"] for c in batch["cases"]),
                    {"batch_id": batch["batch_id"], "era_partition": batch["era_partition"],
                     "jurisdiction": batch["jurisdiction"],
                     "signals": {c["case_id"]: c["signals"] for c in batch["cases"]}})
        golden = (golden_dir / "prompts/cycle-003-shard-01" / (bf.stem + ".txt")
                  ).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        assert golden.startswith(v1.text)
        want = _body(v3.text) + golden[len(v1.text):]
        assert render_unit(v3, unit, src.fetch(unit.case_ids), "claude") == want, bf.name
        n += 1
    assert n == 5          # only 5 of the ten golden batches are in corpus-tiny.db


def test_context_and_adr_carry_the_mixed_definition(repo_root):
    ctx = _norm((repo_root / "CONTEXT.md").read_text(encoding="utf-8"))
    assert _norm("A case the reader finds irrelevant carries no polarity.") in ctx
    assert _norm("both are holdings rather than remarks in passing") in ctx
    adr = _norm((repo_root / "docs/adr/0004-extraction-schema-v2.md").read_text(encoding="utf-8"))
    assert _norm("## Amendment 2026-09-05") in adr and _norm("mapper-v3") in adr
