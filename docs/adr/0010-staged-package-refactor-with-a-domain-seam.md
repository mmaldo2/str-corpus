---
status: accepted
date: 2026-09-01
---

# The pipeline becomes a package along the audited seams, staged, with everything domain-specific behind a domain directory

Nineteen scripts re-declared database paths, jurisdiction lists, and era
bounds independently; two copies of the LLM call and JSON parsing existed,
one without error handling; the quote verifier, the cleanest module, was
forked rather than imported; and only the two purest modules had tests. The
project also wants the engine reusable for other historical-record
questions. We decided on a package with these modules: corpus store
(connection, schema, paths, constants), ingest, indexer, selector engine,
reader driver, verification, review, ledger, evaluation, and a domain
loader; a domains directory holding the STR ontology, selectors, codebook
and prompts, gold set, jurisdictions, and eras, which the engine reads by
configuration and never imports by literal path; and a staged order in which
the modules cycle 004 depends on (store, domain, ledger, selector engine
with the new selector types, reader driver) come first and review and
evaluation follow while cycle 004 maps. Old scripts remain as thin wrappers
for one cycle.

## Considered options

- Minimal shared-module fix, scripts otherwise untouched: cheaper, but the
  ledger, selector-type, and provider-neutral decisions each require the
  corresponding seam anyway.
- Full plugin architecture for domains: premature with one domain; the
  directory-plus-config seam gives reuse at near-zero cost.

## Consequences

Safety net for refactoring before a large run: characterization tests that
reproduce cycle-003's batches from a dry-run shard, the verified files from
the stored extractions, and the ledgers from the stored adjudications, byte
for byte; unit tests for pure logic; recorded LLM fixtures; and a fixture
database of a few hundred cases so the suite runs on a fresh clone. Ingest
is parallelized (parse across cores, one writer) inside its module.
