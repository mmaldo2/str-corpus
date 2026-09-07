"""What a quote is offered in support of - the one definition, upstream of everything.

The reader's gate (`corpus_engine.reader.gate`), the ledger's `drop_quote` cascade
(`corpus_engine.ledger.fold`) and the legacy verification pipeline (`corpus_engine.verification`)
must never disagree about which judged fields a quote supports: the gate decides what leaves
the driver, the fold decides what survives a dropped quote, and a divergence between them
would null a field on one path and keep it on the other.

It lived in `corpus_engine.ledger.fold` until the final review of slice 2 (M4): the reader is
UPSTREAM of the ledger, and a reader module importing the ledger to read its own response is
the dependency the wrong way round. The function is the same one; only its home moved, and
`fold` still re-exports it so `from corpus_engine.ledger.fold import quote_supports` keeps
working for callers (and tests) that learned it there."""
from __future__ import annotations


def quote_supports(quote: dict) -> tuple[str, ...]:
    """Which judged fields a quote is offered in support of, whichever shape it arrived in.

    mapper-v1 wrote a bare string; mapper-v3's schema makes `supports` an array, and a set
    literal over the raw value (`{q.get("supports") for q in quotes}`, which is what the fold
    did) raises `unhashable type: 'list'` on the first drop_quote against an admitted
    cycle-004 record - taking the whole `Ledger.apply` with it."""
    s = quote.get("supports")
    if isinstance(s, str):
        return (s,) if s else ()
    if isinstance(s, (list, tuple, set)):
        return tuple(x for x in s if isinstance(x, str) and x)
    return ()
