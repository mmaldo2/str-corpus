from __future__ import annotations

def chunk_offsets(tokenizer, text: str, chunk_tokens: int, chunk_overlap: int) -> list[tuple[int, int]]:
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False, verbose=False)
    offsets = enc["offset_mapping"]
    if not offsets:
        return []
    spans, step, i = [], chunk_tokens - chunk_overlap, 0
    while i < len(offsets):
        window = offsets[i:i + chunk_tokens]
        spans.append((window[0][0], window[-1][1]))
        if i + chunk_tokens >= len(offsets):
            break
        i += step
    return spans


class _Safe(dict):
    def __missing__(self, key): return ""


def embedding_input(prefix_template: str, case_meta: dict, span_text: str) -> str:
    return prefix_template.format_map(_Safe({k: ("" if v is None else v) for k, v in case_meta.items()})) + span_text
