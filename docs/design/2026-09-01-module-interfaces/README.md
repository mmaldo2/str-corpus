# Module interfaces — design-it-twice record, 2026-09-01

Three candidate interfaces were designed in parallel for each load-bearing
module (selector engine, ledger, reader driver), compared on depth,
locality, and seam placement, and a hybrid approved by the user. The nine
candidates are the `design-*.md` files beside this README. This file is
the approved result and is the spec the Stage 1-3 implementation plans
argue from. Vocabulary: `CONTEXT.md` and the codebase-design skill
(module, interface, seam, adapter, depth, leverage, locality).

## Selector engine (approved hybrid)

Base: `design-selector-3-common.md`. Additions from the others:

- Surface: `shard(store, domain, run_id, *, dry_run, stamp, embedder)`
  and `attribution(store, case_ids)` are the common calls; `plan`,
  `pack_batches`, `probe` are the rarer ones. `dry_run=True` writes nothing
  and still returns batches as data (from design 1).
- Coverage rows carry a retriever **fingerprint** (from design 2): for
  lexical selectors the index version; for embedding selectors the
  `(model, revision, dim, quant)` of every partition in scope; for graph and
  feedback selectors the seed-set hash. A covered unit whose fingerprint
  differs is a `CoverageConflict` unless forced; an embedding selector over
  partitions with differing fingerprints is a `Skip`, never silently mixed.
  Coverage PK becomes `(selector_id, selector_version, partition_key,
  fingerprint)`; the migration happens once, in Stage 2.
- A **SeedResolver** port (from design 2) supplies seed sets so the engine
  never imports the ledger module. Adapters: ledger-backed, frozen mapping.
- Embedding search is scoped to the union of the selector's in-scope
  partitions, not the whole corpus (design 3).
- Ranking is a separate stage applied only in batch packing; signals are
  never truncated (all three).
- Two findings fixed as a logged engine version bump: `np.argsort` at
  `shard.py:220` is not stable (use `kind="stable"` + `chunk_id`
  tiebreak); already-read exclusion becomes the default.
- `kwic`/`colloc`/`freq` stay a separate concordance module.

## Ledger (approved hybrid)

Base: `design-ledger-1-minimal.md`. Additions:

- Surface: `open_ledger(root, name, domain)`, `Ledger.view(as_of)`,
  `Ledger.apply(patches, note, dry_run)`. No ports; the filesystem is its
  own test stand-in (tmp_path). Git is reached by subprocess for
  `as_of=<rev>`.
- Ops: `admit`, `set`, `append`, `drop_quote`, `migrate`.
- Governance table (from design 2): judged fields change only under a
  `Basis` with `reviewer` or `(model, prompt_version, run_id)`; curatorial
  fields (`review.flags`, `review.notes`, `review.status`, `citator_status`)
  accept any basis including `rule_id`; identity fields only under
  `migrate`; review tier is derived, never stored.
- Support rule and retraction cascade (from design 2): a non-null judged
  value needs a quote whose `supports` names it; `drop_quote` nulls any
  judged field left unsupported and records `nulled_fields`. The bootstrap
  replay runs with the cascade off for byte fidelity; the one record the
  cascade would change (Shvekh, 12315742) is fixed afterwards by an explicit
  logged patch routed to human review.
- Accounting invariant (from design 2): every case admitted to a cycle is
  in that cycle's manifest, and the manifest length equals the verified
  extraction count for the cycle's runs. Expected to fail for cycles 1-3
  until the manifest backfill lands; written first as an xfail.
- Counts and matrix (from design 3): `TierCount(human_reviewed,
  machine_only)` with no total, `as_claim(noun)` rendering, `matrix()` with
  `empty_cells()`.
- Manifest is a second projection of the same log inside the module.
- Record order: the log persists admission order; rendering sorts by
  `(year or 0)` with stable admission-order tiebreak, matching the files.

## Reader driver (approved hybrid)

Base: `design-reader-2-ports.md`. Additions:

- Surface: `Reader(provider, cases, log, sleep).read(plan) ->
  ReadingOutcome`, plus `agreement(a, b, fields)`, plus plan constructors
  as plain functions (from design 3): `plan_batch_extraction`,
  `plan_reread`, `plan_judgment`.
- Ports: `Provider` (true external; adapters OpenRouter, Anthropic Batch,
  subprocess CLI transitional, recorded cassette, scripted) and
  `CaseSource` (SQLite store, inlined text for the experiment kit,
  mapping for tests). Sleep and clock are injected callables, not ports.
- Budget and stop reason (from design 3): `Budget(max_usd, max_units,
  max_wall_seconds)`, `StopReason`, and a literal `resume_command` on the
  outcome.
- Pre-flight checks (from design 1): norm-version match and codebook
  stability-check pass before the first request; checker sampling by
  stable hash of group id.
- Codebooks are data under `domains/<domain>/codebooks/`; the quote gate
  runs inside the driver; cache identity is content-keyed
  (`sha256(codebook sha | model pin | group | case ids | rendered prompt)`).

## Characterization fixtures shared by all three

- Golden reader prompts for ten cycle-003 batches, captured at the
  pre-refactor commit (Stage 1, Task 1).
- Signals and coverage tables as of the end of cycle 003, plus the
  referenced case rows' metadata, frozen into `tests/fixtures/`.
- The explicit already-read exclusion set at cycle-003 shard time.
- `tests/fixtures/corpus-tiny.db`: a few hundred cases with full text,
  page maps, FTS tables, and chunk vectors.
- Digests of `data/ledger/*.jsonl`, `data/adjudications/*.json`, and every
  `runs/*/verified/` file.
