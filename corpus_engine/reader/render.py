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
    signals = unit.meta.get("signals", {})
    for t in texts:
        sig_lines = "\n".join(f"  - {s['selector_id']} v{s['selector_version']}: ...{s['matched_text'][:160]}..."
                              for s in signals.get(t.case_id, signals.get(str(t.case_id), [])))
        parts.append(f"\n## case_id {t.case_id} — {t.name}, {t.cite} ({t.court}, {t.jurisdiction} {t.year})\n"
                     f"Retrieval provenance:\n{sig_lines}\n\n### Opinion text\n{t.raw_text}\n")
    return "".join(parts)
