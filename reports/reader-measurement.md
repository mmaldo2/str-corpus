# Reader-model measurement v1

Run 2026-09-04/05 by `tools/measure_reader.py` against the frozen experiment kit,
under the bar pre-registered in ADR-0007. Ten approved candidates, one shared
budget, every response cached.

- Kit: `data/reader/kit-v1/kit.json`, sha256
  `b393f2863feef6c9f1810c2bdeb2af983f695aa9d64604ab3db8be364160891f`
  (23 batches, 195 cases: 155 human-adjudicated, 40 machine-judged irrelevant).
- Codebook: `mapper-v2`, sha256
  `59186f4244629570f45436acb052da76df850e22e335c0a2628c464c75321c10`.
- Manifest: `data/reader/measurement-v1/manifest.json`.
- Stability record: `domains/str-right-to-let/codebooks/stability/59186f42….json`.
- Raw responses: `data/reader/cache/` (gitignored — 364 files, ~$38.82 of purchased
  generations). The manifest records the cache key of every unit behind every score
  under `cache_keys`, so a score can be traced to the exact responses that produced
  it; the 33 responses of the superseded Baidu purchase are keyed separately under
  `superseded_cache_keys`. All 364 files are accounted for
  (`cache_key_coverage.unaccounted: 0`). Regenerate these records at any time, without
  spending anything, with `.venv\Scripts\python tools\measure_reader.py
  --annotate-only`.

## Result

**Winner: `anthropic/claude-opus-5`**, served by "Claude Platform on AWS",
reasoning effort `low`. Written to `domains/str-right-to-let/domain.yaml`
(`reader.model`).

**Rule applied: _no survivor reached 0.85 macro agreement; the highest-agreement
survivor was chosen and the shortfall is disclosed._** This is the fallback
branch of the pre-registered rule, not its main branch. The main branch —
cheapest cost per accepted record among survivors at or above 0.85 — never
opened, because the best candidate in the field reached 0.7075. **A shortfall is
disclosed: the measurement did not find a model that meets the agreement bar.**

## Candidates

Fidelity floor 0.97; agreement bar 0.85 macro over `relevant`, `polarity`,
`who_was_letting`. "Pin as served" is what actually answered, not what was asked
for. Agreement is against the 155 human-adjudicated rows; machine-irrelevant is
the share of the 40 already-irrelevant rows the reader also called irrelevant.
Spend is what OpenRouter charged for that candidate's own units.

Wall is the wall time of the scoring pass, which for a candidate whose units were
already in the response cache is the cache replay and not the generation. Only the
four candidates that generated during the final pass carry a meaningful wall time;
the rest are marked "(cached)" and their original generation time was not recorded
in the manifest.

| model pin as served | quote fidelity | relevant | polarity | who_was_letting | macro | machine-irrelevant | schema | accepted | cost/accepted | spend | wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `anthropic/claude-opus-5` **(winner)** | 0.9975 | 0.916 | 0.639 | 0.568 | **0.7075** | 0.850 | 1.000 | 195 | $0.0498 | $9.71 | (cached) |
| `openai/gpt-5.6-terra` | 0.9959 | 0.923 | 0.594 | 0.542 | **0.6860** | 0.825 | 1.000 | 195 | $0.0160 | $3.13 | (cached) |
| `z-ai/glm-5.3` @ Reka, fp8 | 0.9983 | 0.794 | 0.574 | 0.690 | **0.6860** | 0.950 | 1.000 | 195 | $0.0081 | $1.58 | (cached) |
| `google/gemini-3.7-flash` | 1.0000 | 0.777 | 0.527 | 0.649 | **0.6509** | 0.950 | 0.964 | 188 | $0.0059 | $1.11 | (cached) |
| `deepseek/deepseek-v4-flash` @ StreamLake, fp8 | **0.8988** | 0.845 | 0.503 | 0.516 | 0.6215 | 0.900 | 1.000 | 195 | $0.0006 | $0.12 | 2405s |
| `qwen/qwen3.8-27b` @ Reka, fp8 | 0.9951 | 0.768 | 0.413 | 0.471 | **0.5505** | 0.950 | 1.000 | 195 | $0.0026 | $0.50 | 1928s |
| `deepseek/deepseek-v4-pro` @ StreamLake, fp8 | **0.9228** | 0.639 | 0.452 | 0.477 | 0.5226 | 0.950 | 1.000 | 194 | $0.0032 | $0.62 | 4228s |
| `minimax/minimax-m3` @ DeepInfra, fp8 | 0.9953 | 0.832 | 0.194 | 0.510 | **0.5118** | 0.800 | 1.000 | 195 | $0.0030 | $0.58 | (cached) |
| `anthropic/claude-haiku-4.5` | **0.9274** | 0.825 | 0.149 | 0.506 | 0.4935 | 0.750 | 0.990 | 191 | $0.0091 | $1.75 | (cached) |
| `anthropic/claude-sonnet-5` | 0.9911 | 0.729 | 0.045 | 0.613 | **0.4624** | 0.900 | 1.000 | 193 | $0.0193 | $3.73 | (cached) |

For scale, the two slowest generations observed in the run logs were
`deepseek/deepseek-v4-pro` at 4228s and `minimax/minimax-m3` at 2188s for the
23-batch kit; the Anthropic and Google candidates ran in the low tens of minutes.

Bold fidelity marks the three eliminated below the floor; bold macro marks the
seven survivors that were eligible to win.

- **Eliminated on quote fidelity:** `anthropic/claude-haiku-4.5` (0.9274),
  `deepseek/deepseek-v4-pro` (0.9228), `deepseek/deepseek-v4-flash` (0.8988).
- **Survivors:** opus-5, gpt-5.6-terra, glm-5.3, gemini-3.7-flash, qwen3.8-27b,
  minimax-m3, sonnet-5.
- **Skipped: none.** Every open-weight candidate had a bf16 or fp8 endpoint.
- **Failed: none.** Every candidate completed the whole kit.
- **Not run: none.** The budget was never exhausted.

Two candidates lost a single unit to an unparseable response that also failed the
split retry: `claude-haiku-4.5` on `kit-v1-batch-004` (2 records missing) and
`gemini-3.7-flash` on `kit-v1-batch-012` (7 records missing). That is what their
schema compliance below 1.000 records; those records are excluded from agreement
rather than counted as disagreements.

### Reading the result

Cost was never the deciding quantity, because the cost tie-break only applies
among candidates at or above the agreement bar and there were none. Had the bar
been met, `deepseek/deepseek-v4-flash` at $0.0006 per accepted record would have
won on cost — it is 83× cheaper than the winner. The winner costs $0.0498 per
accepted record, so a 195-case kit costs about $9.71 and a 2,000-case cycle
projects to roughly $100.

Two things that number does not say. An **accepted** record is one that parsed and
came back from the quote gate with a decided `relevant` field, which includes
`extraction_status: "partial"` — a record that lost one or more judged fields to the
gate — so cost per accepted record is a lower bound on the cost of a fully judged
record (spec §2, amended 2026-09-05; Concern 8). And **`who_was_letting` is scored
but never quote-gated**: it is one of the three bar fields in `measure.BAR_FIELDS`
and is not in `domain.yaml`'s `reader.judged_fields`, so a model's answer there is
compared against the human label without having to carry a surviving quote.

The field separates on `polarity`, not on relevance. Every candidate identifies
relevance reasonably well (0.639–0.923) and struggles on polarity (0.045–0.639).
Polarity is the field the project has already had to correct once: it is defined
against the *owner's right to let*, so a pro-tenant outcome is adverse, and that
inversion is exactly what a reader gets wrong when it reads "polarity" as
"sympathetic". `claude-sonnet-5` at 0.045 on polarity is not noise: it is close to a
systematic inversion, and it is the reason a model that reads relevance well
(0.729) finishes last overall.

## Batch-size pair (winner only)

The same kit read by the winner in 5-case batches instead of 18-case batches,
to test long-context drift.

| | quote fidelity | relevant | polarity | who_was_letting | macro | machine-irrelevant | accepted | cost/accepted | spend | wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 18-case batches | 0.9975 | 0.916 | 0.639 | 0.568 | 0.7075 | 0.850 | 195 | $0.0498 | $9.71 | (cached) |
| 5-case batches | 0.9987 | 0.910 | 0.645 | 0.510 | 0.6882 | 0.875 | 195 | $0.0465 | $9.06 | 1744s |

No long-context penalty at 18 cases. Smaller batches buy a hair more quote
fidelity (+0.0012) and are marginally cheaper (−$0.65 over the kit, because
smaller units waste fewer output tokens on retries), but macro agreement is
slightly *worse* (−0.0193), driven entirely by `who_was_letting` (−0.058).
Nothing here justifies moving off 18-case batches, which is what the sharding
already produces.

## Stability check (winner, codebook `mapper-v2`)

Two independent reads of the frozen fifty-case sample
(`data/reader/kit-v1/sample-50.json`), self-agreement per judged field, bar 0.90:

| field | self-agreement | at bar |
| --- | ---: | --- |
| `relevant` | 0.96 | yes |
| `who_was_letting` | 0.94 | yes |
| `polarity` | **0.82** | **no** |

**`mapper-v2` is NOT stable.** Recorded as `"stable": false` in
`domains/str-right-to-let/codebooks/stability/59186f42….json`.

This is the headline caveat of the whole measurement and it should be read
before the winner is. `reader.model` is set as the rule directs, but the codebook
the winner reads under is not yet reproducible on `polarity`: the same model, at
temperature 0, on the same fifty cases, changes its polarity answer roughly one
time in six. That is the same field that separated the candidate field, and the
two facts are almost certainly one fact — `polarity` as `mapper-v2` currently
defines it is under-specified, not merely hard.

Revising the codebook is Stage 3B's work, not this task's. Until it is done, no
cycle-004 polarity produced by this reader should be treated as settled without
the checker, and a `mapper-v3` will need its own stability run and its own
measurement of the winner (the model choice above is measured against `mapper-v2`
and does not automatically carry).

## The gate rule changed mid-measurement

The crash above was fixed by *relaxing* the acceptance criterion, and that deserves
stating plainly rather than being filed as a bug fix.

Before `dfd6c06`, each judged field needed its own verified quote: a quote named one
field in `supports`, and a field with no quote of its own was voided. After it, one
verified quote may name several fields, and all of them stand. In the limit a single
verified quote naming all six judged fields leaves nothing voided.

Why the looser rule is the right one: a single passage routinely does establish two
things at once — "the lodger has no estate, and the landlord may re-enter at will"
carries both the characterization and the polarity — and forcing the model to quote
the same sentence twice measures compliance with a formatting convention rather than
fidelity to the text. The strict alternative (treat a non-string `supports` as
supporting nothing) would also have fixed the crash, so this was a choice.

What it does **not** do: it cannot admit a quote that fails verification.
`verify_quote` still runs first and only quotes already kept are consulted for what
they support. And it cannot inflate quote fidelity, which is `kept / (kept + dropped)`
over quotes, each counted once however many fields it names.

Effect on the results: **none on the winner, and none on any ranking.** The change was
made before the final scoring pass, and that pass re-gated every candidate from cache
under the new rule, so all ten were scored on identical terms. `deepseek-v4-flash`,
the only candidate observed to emit list-valued `supports`, fell at the fidelity floor
either way (0.8988 against 0.97). The residual caveat is that the rule was relaxed
after the field had begun and after seeing one candidate's output, and a looser
per-field rule can only help a model that reports multi-field support — so the honest
reading is that this measurement scored under the relaxed rule throughout, not that
the rule made no difference to anyone.

## Spend

| | |
| --- | ---: |
| Approved ceiling | $50.00 |
| First attempt, 2026-09-04 (truncated at `max_tokens` 16000, discarded) | $2.85 |
| Measurement proper (`--max-usd 47`) | $38.82 |
| **Total charged for the task** | **$41.67** |
| OpenRouter credits after the run | $11.00 |

Within the ceiling with $8.33 to spare. The `--max-usd 47` flag is not the approved
ceiling: it is $50 less the first attempt already charged for. The manifest records
both (`approved_ceiling_usd: 50.0`, `discarded_attempts_usd: 2.85`) so the flag value
is not mistaken for the envelope. The measurement proper breaks down as $23.79 spent
by the process that was killed mid-run (its work survived in the response cache and
was not re-bought) and $15.03 by the process that finished.

**Not all of it is attributable to a candidate.** Summing `spend_by_candidate` gives
**$36.82 against $38.82 charged — $2.00 (5.2%) attributed to no candidate at all**:

| | |
| --- | ---: |
| Attributed to candidates | $36.82 |
| Superseded purchase: `deepseek-v4-pro` @ Baidu | $1.51 |
| Residual, localised to the `claude-opus-5` 5-case run | $0.50 |
| Rounding across the two spend sources | −$0.01 |
| **Charged** | **$38.82** |

The **superseded purchase** is the provider flip in Concern 3: `deepseek-v4-pro` was
first bought in full at Baidu, then re-bought at StreamLake when the pin resolved
differently. Its cost figure in the table above is the StreamLake run only — the
scored one — which is correct, but it left $1.51 of real money recorded nowhere. The
manifest now records it as `discarded_spend_by_candidate`, with the 33 superseded
responses keyed under `superseded_cache_keys` so the discarded money is tied to the
same evidence as the money that bought a score.

The **residual $0.50** is the whole of the driver-versus-charged gap, and it runs in
the opposite direction to what one would expect: for the `claude-opus-5` five-case
run the driver's sum of per-response `usage.cost` came to $9.5623 while the credits
delta for the same run was $9.0629, i.e. **driver-tracked exceeded what was charged**.
An earlier draft of this report explained the gap as responses billed but unusable and
so never recorded — that would push tracked *below* charged and is the wrong sign; it
has been corrected here and in `reconcile()`'s docstring, which carried the same
backwards claim. Why the two sources disagree on that run is **unexplained**: no
per-response billing detail is retained beyond `usage.cost`, so it cannot be settled
from what was kept. The ceiling was enforced on the credits delta throughout, so the
discrepancy never affected how much could be spent.

Per-candidate spend is in the manifest under `spend_by_candidate`. Note that
`anthropic/claude-opus-5` accounts for $9.71 of the candidate spend and a further
$14.99 for its batch-size pair ($9.06) and two stability reads ($2.46 each):
the winner's follow-ups cost more than the other nine candidates combined.

## Decisions recorded

- **Checker stays Codex, invoked through the Codex CLI**, at the user's
  direction. The controller's concern is recorded: the CLI route is the one
  ADR-0007 moved *away* from for readers, and Anthropic-style subscription terms
  reserving CLI credentials for interactive use may have an OpenAI analogue that
  applies here. The reader is now on API-key access; the checker is not, and that
  asymmetry is deliberate but unverified against OpenAI's terms.
- **The quantization pair was replaced by pinning.** ADR-0007 asked for one
  fp8-versus-fp4 pair. Instead every open-weight candidate is pinned to a named
  provider serving bf16 or fp8 with fallbacks disabled, so no candidate runs at an
  unrecorded precision and the pair has nothing to isolate. What the pin cannot
  hold is *which* provider: the endpoint list is order-dependent, and
  `deepseek/deepseek-v4-pro` resolved to Baidu on one run and StreamLake on the
  next. Both served fp8, so the precision guarantee held, but the served endpoint
  is a measured output, not an input — see Concerns.
- **The batch-size pair was run on the winner only**, not on two candidates.
  At $9-10 a pass on the winner, a second pair would have cost more than the
  finding is worth, and the pair's purpose is to validate the batch size the
  winner will actually run at.
- **The no-survivor rule was exercised.** It is pre-registered: if nobody clears
  the agreement bar, the highest-agreement survivor is chosen and the shortfall
  is disclosed rather than the bar being quietly lowered. That is what happened.
- **Reasoning effort was pinned to `low` for every candidate.** Left at each
  provider's default, effort is not a recorded quantity but a per-family
  accident: the 2026-09-04 first attempt saw ~530 output tokens per case from one
  family and ~3,700 from another, a five-fold cost difference measuring provider
  defaults rather than models, and at 18 cases a batch it truncated responses at
  `max_tokens` 16000 (raised to 64000, which must cover billed reasoning tokens).
  Effort is carried on `ModelPin.extra` and sent as OpenRouter's `reasoning`
  control, which normalizes to each provider's own knob. Every score in this
  report was produced at effort `low`; the earlier default-effort attempt was
  discarded with a fresh cache before the measurement began.

## Concerns

1. **`mapper-v2` is not stable on `polarity` (0.82 against a 0.90 bar).** See
   above. This is the finding that most limits what the measurement licenses.
2. **The agreement bar was missed by every candidate, by a wide margin** (best
   0.7075 against 0.85). Two readings are available and this measurement cannot
   separate them: the models are genuinely not good enough at this task, or
   `mapper-v2` asks for judgments it does not define sharply enough to agree
   with. The stability failure is evidence for the second. Re-running the
   measurement after a codebook revision is the way to tell, and until then the
   winner should be read as "best available under `mapper-v2`", not as "measured
   fit for the task".
3. **The served provider is not reproducible for pinned open-weight models.**
   `pin_for` walks OpenRouter's endpoint list and takes the first bf16/fp8 match,
   and that list reorders between calls; `deepseek/deepseek-v4-pro` was measured
   at Baidu and re-measured at StreamLake. Precision is pinned, provider is not.
   Because the response cache is keyed on the pin label, a reordering also
   silently invalidates that candidate's cache and re-buys the run. A named
   provider should be recorded per candidate in `domain.yaml` once chosen.
4. **The response cache key distinguishes neither reasoning effort nor
   `max_tokens`.** `ResponseCache.key` hashes the pin *label*
   (`model_id@provider:precision`) plus the codebook sha, unit id, case ids and
   prompt. `ModelPin.extra` is not in it, and neither are the request's generation
   parameters. Two consequences, both avoided here by hand rather than by the code:
   two runs at different efforts collide; and `max_tokens` moved 16000 → 64000 in
   `4f2d9dc`, so had the earlier cache not been cleared, the truncated
   16000-token responses would have been replayed as though they were 64000-token
   ones. Neither bit — every cache entry in this measurement was written after the
   2026-09-04 23:12 relaunch, at effort `low` and `max_tokens` 64000, which the
   timestamps confirm — but the next person to change either knob without clearing
   the cache will silently score stale responses. Both belong in the key; the key
   was deliberately left alone in this round because changing it would orphan the
   entire purchased cache, and fixing it is Stage 3B's.
5. **Two defects in our own code had to be fixed mid-measurement**, and both had
   been silently biasing results toward "the model failed":
   - `OpenRouterProvider` posted with a scalar 300 s timeout. `minimax/minimax-m3`
     emits 10k-33k output tokens per 18-case batch even at effort `low`, so its
     generations were aborted mid-flight; the abort surfaces as a transport error,
     so the retry schedule re-issued each one as a fresh billed generation and the
     unit failed after ~66 minutes having been paid for several times over. The
     read phase now has its own 1500 s ceiling (commit 546c1bf). MiniMax completed
     18 of its 23 units under the 300 s ceiling and the remaining 5 only after the
     change; its score above is the post-change measurement. Which ceiling each
     candidate generated under is now recorded per candidate in the manifest
     (`read_timeout_by_candidate`), attributed from that candidate's own cache-file
     mtimes against the commit: the seven Anthropic/Google/OpenAI/GLM/MiniMax
     candidates generated wholly or mostly under 300 s, while `deepseek-v4-pro`,
     `deepseek-v4-flash` and `qwen3.8-27b` generated under 1500 s, and `minimax-m3`
     (18 units at 300 s, 5 at 1500 s) and `glm-5.3` (24 and 1) straddle the change.
     Nothing here establishes that the three 1500 s candidates would have finished
     under 300 s — `deepseek-v4-pro` averaged 184 s a batch over a 4228 s run and its
     slowest batch is not recorded — so the change is a confound for them, bounded
     by the fact that it can only alter whether a long generation finishes, never
     the content of one that did.
   - The quote gate did `supported.add(quote["supports"])`, which raised
     `unhashable type: 'list'` when `deepseek/deepseek-v4-flash` reported one
     passage supporting two fields. `TypeError` is not `ReaderError`, so it
     escaped the driver's per-unit handler and killed the whole candidate; the
     measurement had recorded it as a failed model. A quote may now support
     several fields (commit dfd6c06), and the candidate completed and was
     eliminated on its own fidelity (0.8988), not on our crash. **This is a rule
     change, not only a crash fix** — see "The gate rule changed mid-measurement"
     below.
   Both are arguments for running the kit against a cheap candidate end-to-end
   before spending on the field.
6. **About 3% of the measurement's spend is unexplained, and the gap runs the
   opposite way to the obvious story.** Per-candidate spend is credits-derived,
   not provider-reported: `score()` prices each run from the `/credits` delta
   measured across it and falls back to the responses' own `usage.cost` only when
   the endpoint failed to answer, which is what the candidate table means by
   "spend is what OpenRouter charged for that candidate's own units". Over the
   final process the driver's tracked total came to **$15.54 against $15.03
   charged** — tracked *above* charged. Responses that are billed but unusable
   would push tracked *below* charged, so that mechanism cannot explain this; an
   earlier draft of this concern claimed it anyway and was wrong by a sign, the
   same error `reconcile()`'s docstring carried. The Spend section localises the
   whole of the residual to the `claude-opus-5` five-case run ($9.5623 tracked
   against a $9.0629 credits delta) and records it as unexplained: no
   per-response billing detail beyond `usage.cost` was kept, so it cannot be
   settled from what survives. The ceiling was enforced on the credits delta
   throughout, so the gap never affected how much could be spent.
7. **Four candidates' scores rest on fewer than 195 accepted records**, for two
   different reasons that should not be confused.
   - *Records that never arrived.* `gemini-3.7-flash` accepted 188 and
     `claude-haiku-4.5` lost 2 of its 4 this way: each lost one unit to an
     unparseable response that also failed its split retry (7 and 2 records
     respectively). Gemini's seven are 4.5% of the human reference, and it finished
     0.035 behind the third-place candidate.
   - *Records that arrived and were not decidable.* `deepseek-v4-pro` accepted 194
     and `claude-sonnet-5` 193 with **zero** missing records, and `claude-haiku-4.5`
     lost the other 2 of its 4 here: these records came back `extraction-invalid` —
     no quote survived verification, so every judged field was voided and the record
     was not accepted. (Re-gated offline from the purchased cache, no request and no
     spend: `case_id 832648` for `deepseek-v4-pro`; `948154` and `3787987` for
     `claude-sonnet-5`; two further records for `claude-haiku-4.5`. All still carry
     `relevant: true`. An earlier draft said the gate had voided `relevant`, which
     it cannot: `relevant` is not one of `domain.yaml`'s `reader.judged_fields` and
     `gate_record` nulls only those. They failed the acceptance filter on
     `extraction_status`, not on `relevant`.) That is the more interesting failure of
     the two — it is the gate doing its job, not the transport failing — and it is
     invisible in the schema compliance column, which counts records returned rather
     than records decided.
8. **`accepted` counts partial records, so cost per accepted record is a lower
   bound.** A record is accepted when it parsed and came back from the gate with a
   decided `relevant` field — `extraction_status` `ok` **or** `partial` — and
   `partial` is exactly the status of a record that lost one or more judged fields
   to the gate. So an accepted record is not necessarily a *usable* one, and the
   cost per accepted record in the tables above is a lower bound on the cost of a
   fully judged record. Spec §2 was amended on 2026-09-05 to the definition the
   measurement actually computed rather than the number being restated after the
   fact; re-scoring the cache on the stricter definition is Stage 3B's, and nothing
   here turns on it because the cost tie-break never opened. How wide the gap is, per
   candidate, is now in the manifest under `accepted_by_candidate`, re-derived offline
   from the purchased responses by `--annotate-only` (no request, no spend; its
   recomputed `accepted` reproduces every candidate's scored figure exactly, which is
   what licenses the rest of the row). It is wide: of the winner's 195 accepted
   records only **126 kept every judged field**, and across the field fully judged
   records run from 54 (`claude-haiku-4.5`) to 150 (`gemini-3.7-flash`). On the strict
   denominator the winner costs $0.0771 rather than $0.0498 per record.
