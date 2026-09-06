# Reader-model measurement v2

Run 2026-09-05 by `tools/measure_reader.py` against experiment kit v2 under
codebook `mapper-v3`, on the bar pre-registered in the slice-1 spec (section 8,
decision D4) before any read. Five candidates — two of them on the user's Claude
subscription through the Claude Code CLI — one OpenRouter ceiling, every response
cached.

- Kit: `data/reader/kit-v2/kit.json`, sha256
  `6914c0d243fec3a5f268788f3bd571a1c7bf19d5432c49dc805296184f65686d`
  (23 batches, 195 cases: 155 human-adjudicated, 40 machine-judged irrelevant —
  the same 195 cases as kit v1, relabelled from the patched ledger).
- Codebook: `mapper-v3`, sha256
  `f920166813144f09d3a8a8de575eb860dbcce18a42b46b2270b4b17cc1a52752`.
- Response schema: sha256 `be8cb3909d96…` for every candidate except
  `openai/gpt-5.6-terra`, which was measured under the `openai-strict` dialect of
  the same schema, sha256 `df22ed51d8ac…` (see Process disclosures).
- Settings, fixed before the runs: batch size 18, reasoning effort `low`,
  `max_tokens` 64000, read timeout 1500 s — for every candidate
  (`effort_by_candidate`, `read_timeout_by_candidate` in the manifest).
- Manifest: `data/reader/measurement-v2/manifest.json`.
- Stability record: `domains/str-right-to-let/codebooks/stability/f9201668….json`.
- Raw responses: `data/reader/cache/` (gitignored). The manifest records the cache
  key of every unit behind every score under `cache_keys`. Regenerate the derived
  records at any time, without spending anything, with
  `.venv\Scripts\python tools\measure_reader.py --annotate-only` (see Reproduction
  for what that adds).
- Measurement v1 (`reports/reader-measurement.md`, `data/reader/measurement-v1/`)
  is untouched.

## Result

**Winner: `google/gemini-3.7-flash`**, routed by OpenRouter (closed weights, so no
provider or precision pin; the endpoint reported itself as "Google"), reasoning
effort `low`. Written to `domains/str-right-to-let/domain.yaml` (`reader.model`)
exactly as the tool printed it.

**Rule applied: _no survivor reached 0.85 macro agreement; the highest-agreement
survivor was chosen and the shortfall is disclosed._** Best surviving macro
0.8363. This is the fallback branch of the pre-registered rule, as in v1 — but the
shortfall is now 0.014 rather than 0.14.

**The user's stated preference is a subscription reader, and this pin is not one.**
`claude-cli/claude-opus-5` scored macro 0.8119, **0.0243 behind the winner — 2.4
points, just outside the 0.02 subscription tie-break window that D4 fixed in
advance.** The tie-break was evaluated and did not fire. Opus reads at zero
marginal cost, was one of two candidates with perfect quote fidelity, and returned
the most fully-judged records in the field (168 of 195). **Overriding the pin to
Opus is the user's call, and this report does not make it**; the pin stands where
the pre-registered rule put it unless the user says otherwise.

## The bar (pre-registered, spec D4)

Fixed in the spec before any read, and applied unrounded:

1. **Fidelity floor 0.97** — share of quotes that verified against the case text.
2. **Decided-rate floor 0.90 per bar field** — the share of reference-decided cases
   on which the reader, after the quote gate, gave a decided answer.
3. **Agreement bar 0.85 macro** — the mean of `agreement_decided` over `relevant`,
   `polarity`, `who_was_letting`, each computed only over cases where *both* sides
   are decided.
4. **Subscription tie-break** — among survivors, a subscription candidate within
   0.02 of the best macro wins, because its read costs nothing.
5. **Shortfall rule** — if no survivor clears 0.85, the highest-agreement survivor
   wins and the shortfall is disclosed rather than the bar being lowered.

Polarity and `who_was_letting` are scored only where the reference marks the case
relevant *and* the reader does too. That is new in v2 and is the single largest
change to what these numbers mean (see "What changed since v1").

## Candidates

"Pin as served" is what actually answered, not what was asked for. Each field
column is **decided rate / agreement among decided**. Machine-irrelevant is the
share of the 40 already-irrelevant rows the reader also called irrelevant.
`accepted` counts records that parsed and came back from the gate with a decided
`relevant`, including `partial`; `(full)` counts those that kept every judged
field. Spend is what OpenRouter charged for that candidate's own units; the two
subscription candidates are **UNPRICED** — the list-price equivalent is recorded
beside them and **is not a charge**.

| model pin as served | fidelity | relevant | polarity | who_was_letting | macro | mach-irrel | schema | accepted (full) | cost/accepted | spend | wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `google/gemini-3.7-flash@-:-` **(winner)** | 1.0000 | 1.00 / 0.910 | 1.00 / 0.756 | 1.00 / 0.843 | **0.8363** | 1.000 | 1.000 | 195 (149) | $0.0051 | $0.99 | 522 s |
| `z-ai/glm-5.3@AkashML:fp8` (eliminated) | 0.9950 | 1.00 / 0.865 | **0.898** / 0.792 | 1.00 / 0.897 | 0.8512 | 0.950 | 1.000 | 195 (154) | $0.0087 | $1.70 | 1786 s |
| `claude-cli/claude-opus-5@claude-cli:-` | 1.0000 | 1.00 / 0.897 | 0.992 / 0.773 | 1.00 / 0.766 | **0.8119** | 0.850 | 1.000 | 195 (168) | UNPRICED | $0.00 (list $15.01) | 1198 s |
| `claude-cli/claude-sonnet-5@claude-cli:-` | 0.9755 | 1.00 / 0.735 | 0.947 / 0.798 | 1.00 / 0.859 | **0.7973** | 1.000 | 1.000 | 195 (128) | UNPRICED | $0.00 (list $7.81) | 1639 s |
| `openai/gpt-5.6-terra@-:-` | 0.9931 | 1.00 / 0.877 | 0.954 / 0.680 | 1.00 / 0.800 | **0.7858** | 0.925 | 1.000 | 195 (145) | $0.0134 | $2.61 | 597 s |

Bold macro marks the four survivors eligible to win; the bold decided rate is the
one number that eliminated a candidate.

**Every column but `wall` is read straight out of the manifest.** `wall` is
field-run wall clock, taken from the run console rather than from the manifest: the
final merge pass replayed four of the five candidates from cache, so the manifest's
`wall_seconds` (0.8–1.3 s) is replay time and says nothing about how long the reads
took. The four field-run figures are not recoverable from the manifest or the cache
and are reported here on the run log's authority alone; GPT's 597 s is its own
strict-dialect run, which was live.

- **Eliminated: `z-ai/glm-5.3`**, on the pre-registered decided-rate floor —
  `polarity` 0.8983 against 0.90. The manifest records the reason per candidate
  under `eliminated_by_candidate`.
- **Skipped: none.** Both subscription candidates found the CLI (version 2.1.258
  (Claude Code)); the one open-weight candidate pinned to a named fp8 endpoint
  (AkashML), fallbacks disabled.
- **Failed: none, in the end.** `openai/gpt-5.6-terra` failed all 23 units in the
  field run on a schema rejection and was re-run alone under a strict schema
  dialect; see Process disclosures. The manifest's `failed` map still carries that
  field-run entry beside GPT's completed score, because failure records merge per
  candidate and were not cleared by the successful re-run.
- **Not run: none.** The budget was never exhausted.
- **Missing records: none anywhere in the field.** Every candidate returned all 195
  records at schema compliance 1.000 — no unparseable unit, no split-retry loss.
  That is new since v1, where two candidates lost units outright.

### The elimination deserves a plain statement

**The only candidate in the field that cleared the 0.85 agreement bar was
eliminated before the bar was consulted.** `z-ai/glm-5.3` scored macro 0.8512 and
went out on `polarity` decided rate 0.8983 — short of the 0.90 floor by 0.0017,
which is **one case out of 118**. The floor is pre-registered, it is compared
unrounded (0.8983 does not become 0.90), and it exists to stop a reader buying
agreement by declining to answer: GLM declined 12 of 118 polarity questions where
the winner declined none. Applying it as written is the honest thing to do and is
what the tool did. It is also true that one case separates the field's best
agreement score from disqualification, so the ordering at the top of this table
should be expected to move if the measurement is re-run.

### Reading the result

The field is much tighter than v1: four of five candidates land between 0.786 and
0.851 macro, where v1 spread from 0.46 to 0.71. `relevant` agreement runs
0.735–0.910 and `polarity` 0.680–0.798. Polarity is still the hardest field, but it
is no longer the field where readers collapse. The decided rates carry the other
half of the story: every reader answered `relevant` and `who_was_letting` on every
case it was asked about, and every decided-rate miss in the whole measurement is on
`polarity`.

Cost never entered the decision — the cost tie-break only applies among candidates
at or above the agreement bar, and there were none. For scale, the winner costs
$0.0051 per accepted record, so the 195-case kit costs about $0.99 and a 2,000-case
cycle projects to roughly $10 at 18-case batches. On the strict denominator
(records that kept every judged field, 149 of 195) that becomes $0.0066.

`who_was_letting` is scored but **never quote-gated** — it is a bar field in
`measure.BAR_FIELDS` and is not in `domain.yaml`'s `reader.judged_fields`, so a
reader's answer there is compared with the reference without having to carry a
surviving quote. Unchanged from v1, and worth re-reading beside the reference note
below.

## The reference these scores are measured against

Kit v2 holds the same 195 cases as kit v1 with labels re-derived from the ledger
after two rounds of user adjudication and one model-consensus pass:

- **Page 1 (contested polarity and who_was_letting, Task 5): 82 decisions** — on
  `polarity`, 37 adopt and 4 keep; on `who_was_letting`, 36 adopt, 2 keep, 1 set
  and 2 `unsure`. 261 ledger patches, replayed clean.
- **The 4-of-5 model consensus on never-reviewed `who_was_letting` labels (D3,
  Task 6): 70 cases settled by consensus, 28 sent to a second review page**, 53
  skipped as already reviewed and 3 as irrelevant. The consensus **confirmed every
  one of the 70 existing labels — it changed no value at all**, so its 140 patches
  record a machine basis and nothing else.
- **Page 2 (the 28 split cases, Task 7): 28 decisions** — 19 keep, 6 adopt, 3 set;
  27 patches, again no change to the published counts.
- **Excluded fields (D6): 3 cases**, each excluded for one field only and still in
  the kit for fidelity and for its other fields — `937195` and `1177933` on
  `who_was_letting` (the two `unsure` marks), `2186819` on `characterization`.

Net effect on the corpus counts: **relevant 710 → 693** (human-reviewed 150 → 133,
machine-only 560 unchanged), favorable 367 unchanged, **favorable householder
138 → 137**. Within kit v2's 155 human rows that shows up as 22 rows now marked
`relevant: false` where v1 had 5 — 17 cases the user judged irrelevant on page 1.

**A caveat about what "agreement" means here.** 133 of the 693 relevant cases are
human-reviewed, and on `who_was_letting` most of the kit's reference values were
either set by a 4-of-5 model consensus or confirmed by it. Agreement with the
reference on that field is therefore partly agreement with an earlier generation of
models, not with an independent human judgment. The v1 diagnostic
(`scratchpad/polarity-diag/report.md`, section 7 finding 5) made the same point
more sharply about v1's reference, and the adjudication rounds above have only
partly answered it.

## Selection

```
winner:     google/gemini-3.7-flash
rule:       highest macro agreement among survivors; no survivor reached 0.85
            (shortfall disclosed)
shortfall:  true
best_macro: 0.8363
survivors:  claude-cli/claude-opus-5, claude-cli/claude-sonnet-5,
            google/gemini-3.7-flash, openai/gpt-5.6-terra
eliminated: z-ai/glm-5.3 — decided rate below the 0.90 floor: polarity 0.8983
```

The subscription tie-break was live and was evaluated. It did not fire: the best
subscription macro (Opus, 0.8119) sits 0.0243 below the winner and the window is
0.02. Had Opus scored 0.0043 higher, it would have won the tie-break outright
under the same rule, including in this shortfall branch (the plan-writer's
resolution: the reason for the tie-break — a subscription read costs nothing —
does not change when nobody clears the bar).

## The winner's checks

### Batch-size pair

The same kit read by the winner in 5-case batches instead of 18, to test
long-context drift.

| | fidelity | relevant | polarity | who_was_letting | macro | accepted (full) | cost/accepted | spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 18-case batches | 1.0000 | 1.00 / 0.910 | 1.00 / 0.756 | 1.00 / 0.843 | **0.8363** | 195 (149) | $0.0051 | $0.99 |
| 5-case batches | 1.0000 | 1.00 / 0.852 | 1.00 / 0.752 | 1.00 / 0.838 | 0.8139 | 195 (163) | $0.0054 | $1.06 |

No long-context penalty at 18 cases; the same finding as v1, from a different
winner. Smaller batches keep more records fully judged (163 vs 149) but agree
*less* (−0.0224 macro, almost all of it on `relevant`) and cost slightly more.
**18-case batches stand**, which is what the sharding already produces.

### Stability of `mapper-v3` (winner, 50-case sample)

Two independent reads of `data/reader/kit-v2/sample-50.json`, self-agreement per
field **over the cases decided in both reads**, bar 0.90:

| field | self-agreement (decided) | at bar | second-read decided rate |
| --- | ---: | --- | ---: |
| `polarity` | 0.97 | yes | **0.72** |
| `who_was_letting` | 0.94 | yes | **0.72** |
| `relevant` | 0.92 | yes | 1.00 |

**`mapper-v3` is recorded as stable** (`"stable": true` in
`domains/str-right-to-let/codebooks/stability/f9201668….json`). That is a real
improvement on `mapper-v2`, which failed this check at 0.82 on `polarity`, and it
is the finding that most licenses using this reader at all.

**But the decided-rate column is a caveat that must be read with it.** On the
second read of the same fifty cases, at the same settings, Gemini gave a decided
`polarity` and `who_was_letting` on only 72% of the cases it decided on the first
read — because it called those cases irrelevant the second time, and an irrelevant
case has no polarity to compare. So: *when Gemini decides a case is relevant twice,
it says the same thing about it both times (0.94–0.97). Whether it decides the case
is relevant at all is much less consistent.* The flat agreement over all fifty cases
— counting a changed relevance call as a disagreement — is `relevant` 0.92,
`polarity` 0.90, `who_was_letting` 0.88, recorded in the manifest as
`stability_flat_agreement`. The stability bar is defined on decided answers (spec
section 8), so the record says stable, and that is the right reading of the rule;
the instability is in the relevance call and it is not small.

## Spend

| | |
| --- | ---: |
| Slice ceiling (D5) | $15.00 |
| Ceiling actually granted at launch | **$10.00** |
| Two one-batch dry runs | $0.02 |
| Field run (five candidates + the winner's checks) | $4.02 |
| GPT re-run under the strict schema (+ merged rescoring) | $2.87 |
| **Total OpenRouter charged for the task** | **$6.91** |
| OpenRouter credits after the last run | $3.55 |

The ceiling was **lowered from D5's $15 to $10 before anything was bought**,
because the OpenRouter balance was $10.49 when the first dry run was attempted and
the tool refuses to start with a ceiling above the balance. A later launch at $15
was refused again at a $6.42 balance and relaunched at $10. Nothing in the
measurement stopped on budget: $3.09 of the granted ceiling was never spent.

Per-candidate spend is in the manifest under `spend_by_candidate`. Summing it gives
**$6.35 against $6.91 charged — $0.56 attributed to no candidate**:

| | |
| --- | ---: |
| Attributed to candidates (incl. the 5-case pair) | $6.35 |
| The winner's two stability reads, recorded as $0.00 (see below) | $0.50 |
| The gemini dry run, recorded before dry-run spend was tracked | $0.02 |
| Reconciliation residual at process exit | $0.04 |
| **Charged** | **$6.91** |

Two attribution defects, neither of which changes the total (which is measured from
the `/credits` delta, not summed from the parts):

1. **The two stability reads cost $0.23 and $0.27 and are recorded as $0.00.** The
   GPT re-run replayed them from cache and overwrote the field run's figures with
   the zero a fully-cached replay computes. The money was really spent and is in
   the total; it is simply no longer tied to those two keys.
2. **$0.26 of GPT's charges is attributed to GLM.** GLM's kit run was charged
   $1.4398 live in the field run. In the merge pass its units were all cache hits,
   but the `/credits` delta measured across that replay was $0.2560 — GPT's
   generations settling late — and the new pricing rule added it to GLM's recorded
   figure, giving the $1.70 in the table above. GLM's own generation cost $1.44;
   GPT's real cost is nearer $2.87 than the $2.61 shown. The swap is between two
   candidates, neither of which won, and neither figure is near a decision
   threshold.

### The subscription side, which is not a charge

| | |
| --- | ---: |
| Subscription units bought | **46 of a 137-unit process ceiling** (Sonnet 23, Opus 23) |
| Wall clock for the two kit passes | ~47 min (Sonnet 1639 s, Opus 1198 s — run log) |
| List-price equivalent, Sonnet over the kit | $7.81 — **not charged** |
| List-price equivalent, Opus over the kit | $15.01 — **not charged** |
| Dollars charged | **$0.00** |

Both subscription candidates ran to `stop: done` well inside the unit and
wall-clock ceilings, with no usage-limit throttle observed. A 6-case batch cost
Sonnet ~41.9k input and ~5.8k output tokens (a list-price $0.16), which is what the
$7.81 and $15.01 figures scale from. `priced: false` is recorded beside them in the
manifest so the list price can never be summed into a spend total. No
`ANTHROPIC_API_KEY` was present in the subprocess environment: the reads went
through the subscription, as ADR-0007's 2026-09-05 amendment records the user
directed. The licence question that amendment raises is not re-argued here.

The units figure is the count of distinct subscription units this measurement
bought, re-derived from the manifest's `cache_keys` map (23 for each of the two
candidates) — **not** the manifest's `subscription_budget.units_used`, which reads
`0`. That zero is a defect and not a measurement: `subscription_budget` is a
whole-manifest field, and the final merge pass made no subscription call at all
(every subscription unit replayed from cache), so it wrote its own zero over the
field run's counter. `merge_manifest` now keeps the highest count any process
reached, so a later merge cannot erase it again. An earlier draft of this report
said "45 (Sonnet 22, Opus 23)", which was the field-run process's own counter —
Sonnet's first batch having been bought by dry run 2 rather than by the field run.
That number is not recoverable from the manifest or the cache and has been replaced
by the one that is.

## Process disclosures

**1. Two one-batch dry runs passed before any field spending.** Both over
`kit-v2-batch-001` (6 cases):

| | records | quotes dropped | nulled fields | schema | spend | wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `google/gemini-3.7-flash` | 6 ok | 0 | none | accepted | $0.019 | 13.5 s |
| `claude-cli/claude-sonnet-5` | 6 ok | 0 | none | accepted | $0.00 (list $0.16) | 50.5 s |

Both parsed on the first ask, with `supports` arrays naming `polarity`, polarity
values inside the v3 vocabulary, and irrelevant records nulling polarity and
`who_was_letting` rather than saying `"irrelevant"` — the four things mapper-v3 was
rewritten to produce. The Sonnet run additionally confirmed the CLI transport, the
unpriced accounting, and that no Anthropic API key was passed.

**2. `openai/gpt-5.6-terra` failed all 23 units in the field run, at $0**, on an
HTTP 400 from OpenAI's structured-output validator: the default schema uses `if` /
`then` and optional properties, which OpenAI's strict dialect rejects. It was
re-run alone under an `openai-strict` variant of the *same* schema —
`additionalProperties: false` everywhere, every property required with the
previously-optional ones made nullable, no `if`/`then`/`else`, enum vocabularies
untouched (commit `5092ae5`). **GPT is therefore the only candidate measured under
a different schema dialect than the rest of the field.** The transform is
structural, the quote gate is unchanged, and GPT finished last among survivors
anyway, but the asymmetry is real and is recorded rather than smoothed over. It had
a second, purely mechanical consequence, now fixed: the manifest as first written
listed **zero units for GPT** under `cache_keys`, because the key derivation hashed
the default dialect's schema sha for every pin while GPT's responses were keyed
under the strict one. The derivation now asks `driver.schema_for` which dialect the
pin was actually sent, exactly as the driver asks it, and
`--annotate-only` fills GPT's map with the 25 keys that were always on disk. GPT's
score is traceable to its responses through the manifest like every other
candidate's; the dialect asymmetry itself remains.

**3. The winner's first batch was a cache hit** from dry run 1 — the same pin, the
same codebook, the same schema, the same unit. One of the winner's 23 kit units was
therefore generated before the field run rather than during it. Same settings, no
content difference.

**4. Two tooling fixes landed between the field run and the GPT re-run**
(commits `9ef2d6c`, `7ce444c`), neither of which touched a stored response:

- *The subscription tie-break was generalised to pin labels.* It was reported
  mid-run as "dead". **It was not dead in this measurement**: the manifest keys
  scores by bare model id and the tool passed bare model ids, so the two matched
  and the tie-break was evaluated exactly as described above. The bug was latent —
  a caller keying scores by pin label would have matched nothing — and the fix
  makes either spelling match. The correction is recorded here because the
  mid-run diagnosis is in the ledger and is wrong.
- *Dry-run spend is now recorded, and a cache hit no longer forces `UNPRICED`.*
  Before the fix, one replayed unit was enough to void a perfectly good
  `/credits` reading, which is why the winner was printed mid-run as
  `[UNPRICED] cpa=inf` against $0.99 of real, reconciled spend. The table above is
  the post-fix pricing. The same fix is what re-priced GLM, with the side effect
  described under Spend.

**5. Every score in the table was recomputed in one merged pass** over the whole
field, from cache, under one scoring code path — no candidate is carrying a score
computed by an older version of `score_candidate`.

## Limitations

1. **Nobody met the agreement bar.** Best macro 0.8363 against 0.85. The shortfall
   is smaller than v1's by an order of magnitude, but the pre-registered bar was
   still not met, and the winner should be read as "best available under
   `mapper-v3`", not as "measured fit for the task".
2. **The winner's relevance call is not reproducible run-to-run.** Two reads of the
   same fifty cases at the same settings decided `relevant` differently often
   enough to drop the second read's polarity/who decided rate to 0.72. Agreement
   *given* a stable relevance call is 0.94–0.97. Anything downstream that treats a
   Gemini `relevant: false` as settled is treating a coin-flip as a finding; the
   checker sampling exists for exactly this.
3. **The bar's own decided-rate floor eliminated the field's best agreement
   score**, by one case out of 118. See the plain statement above.
4. **The user's preferred reader is 0.0243 away and lost on 0.0043 of tie-break
   window.** That is a defensible application of a rule fixed in advance; it is not
   evidence that Opus reads this corpus worse in a way that matters at 2.4 points
   on a 195-case kit with a partly model-derived reference. The user may override
   the pin.
5. **`accepted` counts partial records**, so cost per accepted record is a lower
   bound (v1 Concern 8, spec §2 as amended). `accepted_full` is in the table and in
   the manifest; on the strict denominator the winner costs $0.0066 per record.
6. **GPT's schema dialect differs from the field's** (disclosure 2). Its units are
   traceable through the manifest's cache-key map again, but it is still the one
   candidate measured under a schema the others were not sent.
7. **$0.56 of $6.91 is attributed to no candidate**, with $0.50 of that a known
   overwrite of the stability reads' figures (see Spend).
8. **`who_was_letting` is scored but not quote-gated**, and much of its reference is
   model consensus rather than human judgment (see The reference).
9. **The served provider is still a measured output, not an input**, for pinned
   open-weight candidates (v1 Concern 3). Only GLM was open-weight here; it
   resolved to AkashML at fp8, recorded in the pin label.
- **`cache_key_coverage.cache_files` counts this measurement's distinct cache files**, not
  the shared cache directory's total, since the directory now holds two measurements
  (v1: 364 files; v2 adds its own). The v1 manifest reproduces its original `{364, 0}`
  under this definition; before the final fix wave the field meant the directory total.

## What changed since v1, and what it did

Measurement v1 (2026-09-04/05) scored ten candidates on kit v1 under `mapper-v2`
and found `polarity` collapsing across the board — the winner at 0.639, Sonnet at
0.045 — with `mapper-v2` failing its own stability check on that field (0.82).
The offline diagnostic in `scratchpad/polarity-diag/report.md` decomposed that
result and found, in order of size: the quote gate nulling polarity on cases where
no quote named it (108 of 155 for Sonnet), the relevance threshold leaking into the
polarity field (requirement 4 forced `polarity: "irrelevant"` whenever the reader
said `relevant: false`), an undefined and unreachable `mixed` class, and only then
genuine sign errors — 9 of 155 for the winner. Stripping the first three away left
every serious candidate at 0.89–0.93 on the actual owner-won/owner-lost question.

Four changes followed, and all four are in this measurement:

1. **`irrelevant` is no longer a polarity value.** An irrelevant record nulls
   polarity and `who_was_letting`. The vocabulary is `favorable | adverse | mixed`
   with a single source (`schema.POLARITY_VALUES`), shared by the codebook, the
   schema and the scorer.
2. **`mixed` is defined operationally**, with a worked example and a tie-break rule,
   plus the previously missing rule for an owner who wins on a ground that never
   touches the right to let.
3. **`supports` is an array**, the codebook shows a quote naming `polarity`, and the
   erasure rule is stated in the codebook rather than left implicit in the gate.
4. **Scoring separates deciding from agreeing.** `decided_rate` and
   `agreement_decided` are reported per field; polarity and `who_was_letting` are
   scored only where both sides say relevant, so a relevance disagreement is counted
   once rather than three times.

The five candidates common to both measurements moved like this. **These are not
like-for-like numbers** — the codebook, the reference labels and the scoring rule
all changed, and the v2 figures are agreement among decided answers rather than
agreement over all rows — so read the column as "the same reader, re-measured after
the diagnosis", not as a delta:

| candidate | polarity v1 | polarity v2 | macro v1 | macro v2 |
| --- | ---: | ---: | ---: | ---: |
| `claude-sonnet-5` | 0.045 | 0.798 | 0.4624 | 0.7973 |
| `claude-opus-5` | 0.639 | 0.773 | 0.7075 | 0.8119 |
| `gemini-3.7-flash` | 0.527 | 0.756 | 0.6509 | 0.8363 |
| `gpt-5.6-terra` | 0.594 | 0.680 | 0.6860 | 0.7858 |
| `glm-5.3` | 0.574 | 0.792 | 0.6860 | 0.8512 |

Sonnet's 0.045 → 0.798 is the diagnosis being confirmed: its v1 score was a
`supports`-formatting failure that the gate converted into 108 nulls, not a
doctrinal disagreement, and it is the clearest evidence that v1's polarity column
was measuring the codebook rather than the readers. Note also that the two
subscription candidates were not in v1's field under a CLI transport at all —
v1's `claude-sonnet-5` and `claude-opus-5` ran on API keys through OpenRouter.

The stability picture changed with it: `mapper-v2` was **not stable** (`polarity`
0.82), `mapper-v3` **is** (0.97 on decided answers), with the relevance-call caveat
above. The v1 report's headline warning — that no cycle-004 polarity should be
treated as settled without the checker — is softened but not withdrawn.

Also new since v1, and worth noting because they are cheap wins: no candidate lost
a single record to an unparseable response (v1 lost 7 records for Gemini and 2 for
Haiku), and no candidate fell below the fidelity floor (v1 eliminated three).

## Reproduction

Everything below is offline except where marked. **The measurement is finished and
paid for.** Re-running a candidate re-buys any unit not already in
`data/reader/cache/`.

Recompute this manifest's derived records — no request, no spend:

```
.venv\Scripts\python tools\measure_reader.py --annotate-only
```

It reads the key composition off the manifest (`cache_key_version`, `v2` here) and
addresses the cache the way the run did, strict dialect included. **It reproduces
the committed manifest byte for byte**, which is the check it exists to be: the
annotation has already been applied, so a re-run is a no-op against git. What it
added over what the run wrote was `accepted_by_candidate`, `cache_key_coverage`,
`cache_key_version`, `discarded_spend_by_candidate`, `note`, `spend_attribution`,
`superseded_cache_keys`, and — inside `cache_keys` — GPT's 25 units and the
winner's `:b5` / `:stab1` / `:stab2` maps, none of which the run recorded. No score,
spend or selection value moved, and `accepted_by_candidate` reproduces what the paid
run scored for all five candidates (`matches_the_run` true throughout).

The same command against `data/reader/measurement-v1` (with v1's three flags, below)
reproduces that manifest byte for byte too, addressing its cache with the frozen
Stage 3A key. Neither can be pointed at the other's cache by accident.

Do the same for measurement v1, which needs its own codebook and kit passed
explicitly now that `domain.yaml` names v3/v2 (still no request, no spend):

```
.venv\Scripts\python tools\measure_reader.py --annotate-only ^
  --measurement-dir data/reader/measurement-v1 ^
  --codebook mapper-v2 ^
  --kit-path data/reader/kit-v1/kit.json ^
  --stability-sample data/reader/kit-v1/sample-50.json
```

The commands that produced this report, in order. **These spend money and
subscription units:**

```
:: dry run 1 - the cheapest OpenRouter candidate, one batch
.venv\Scripts\python tools\measure_reader.py --dry-run google/gemini-3.7-flash --max-usd 10

:: dry run 2 - Sonnet through the Claude CLI, one batch, no dollars
.venv\Scripts\python tools\measure_reader.py --dry-run claude-cli/claude-sonnet-5 --max-usd 10

:: the field run - five candidates over kit v2, then the winner's checks
.venv\Scripts\python tools\measure_reader.py --max-usd 10 --prior-spend-usd 0.02

:: the merge pass, after the strict-schema fix landed - the whole field again, not
:: --only: GPT was live under the new dialect and the other four replayed from cache
.venv\Scripts\python tools\measure_reader.py --max-usd 10
```

The last line is the bare command, run over all five candidates, and it is what
produced this manifest. An earlier draft printed it as `--only
openai/gpt-5.6-terra`, which cannot have: `--only` filters the candidate list to
one, so nothing but GPT's score and spend could have changed, yet the manifest
records replay wall times for Gemini, Opus and Sonnet and a $0.2560 credits delta
added to GLM in that same pass (Spend, defect 2). Following the `--only` line and
diffing the result would leave a reader unable to account for four candidates.

`--max-usd` is the whole slice's OpenRouter ceiling and may not exceed $15 (D5);
$10 is what was granted here. Omit `--prior-spend-usd` and the tool reads what has
already been spent off the existing manifest. That ceiling is enforced **per
manifest directory** — prior spend is read only from the manifest the run writes —
so the slice deliberately uses one directory, and a paid run pointed anywhere but
`data/reader/measurement-v2` is refused unless `--allow-measurement-dir` is passed
with it.

## Where this is recorded

- `domains/str-right-to-let/domain.yaml` — `reader.model`, with the rule that fired
  and the date in a comment beside it.
- `domains/str-right-to-let/codebooks/stability/f9201668….json` — the mapper-v3
  stability record.
- `docs/adr/0007-llm-access-is-provider-neutral-and-model-choice-is-measured.md` —
  the result note under the 2026-09-05 amendment.
- `reports/handoff-cycle-004.md` item 7.
- `data/reader/measurement-v2/manifest.json` — everything above, machine-readable.
