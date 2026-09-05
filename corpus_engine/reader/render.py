"""Byte-identical to the legacy pipeline/run_map.py build_payload (the Stage 1 golden prompts)."""
from __future__ import annotations
from corpus_engine.reader.codebook import Codebook
from corpus_engine.reader.model import CaseText, Unit


def render_unit(codebook: Codebook, unit: Unit, texts: list[CaseText], worker: str) -> str:
    text = codebook.text
    if text.startswith("<!--"):                      # strip the metadata comment line, never shown to the model
        text = text.split("\n", 1)[1] if "\n" in text else ""
    parts = [text]
    parts.append(f"\n\n# Batch {unit.meta['batch_id']} ({unit.meta['era_partition']} x {unit.meta['jurisdiction']})\n"
                 f'Set "worker": "{worker}" and "batch_id": "{unit.meta["batch_id"]}" on every record.\n')
    # A judgment unit (plan_judgment) carries the question it exists to ask. It used to be
    # put in Unit.meta and never rendered, so the model was paid to answer a question it
    # was never shown (I3). It goes directly after the batch header, before the cases;
    # batch-extraction units carry no question, so the mapper-v1 goldens are unchanged.
    question = unit.meta.get("question")
    if question:
        parts.append(f"\n## Question\n{question}\n")
    signals = unit.meta.get("signals", {})
    for t in texts:
        sig_lines = "\n".join(f"  - {s['selector_id']} v{s['selector_version']}: ...{(s.get('matched_text') or '')[:160]}..."
                              for s in signals.get(t.case_id, signals.get(str(t.case_id), [])))
        parts.append(f"\n## case_id {t.case_id} — {t.name}, {t.cite} ({t.court}, {t.jurisdiction} {t.year})\n"
                     f"Retrieval provenance:\n{sig_lines}\n\n### Opinion text\n{t.raw_text}\n")
    return "".join(parts)
