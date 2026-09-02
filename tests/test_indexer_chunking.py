from corpus_engine.indexer.chunking import chunk_offsets, embedding_input
from corpus_engine.indexer.embedders import FakeEmbedder

def test_chunk_offsets_cover_text_with_overlap():
    tok = FakeEmbedder().tokenizer
    text = " ".join(f"w{i}" for i in range(1000))
    spans = chunk_offsets(tok, text, 400, 40)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert len(spans) == 3 and spans[1][0] < spans[0][1]        # overlap
    assert chunk_offsets(tok, "", 400, 40) == []

def test_embedding_input_prefix_with_missing_keys():
    meta = {"name": "Howth v. Franklin", "court": "Tex.", "year": 1858}
    assert embedding_input("{name} | {court} | {year}\n", meta, "body") == "Howth v. Franklin | Tex. | 1858\nbody"
    assert embedding_input("{name} | {court} | {year}\n", {"name": "X"}, "body") == "X |  | \nbody"
