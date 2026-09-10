# First pass on a review round, one card chunk per agent

Standing brief for the model first pass (kept in the repo since 2026-09-10; the slice-3 workspace copy was archived with the plan). Two rules settled by the user on 2026-09-09 apply to every round: an E card stays EMPTY (`keep`) when the opinion is silent, with `unclear` / `not_addressed` only when the court addresses the question and leaves it open; and a relevance withdrawal is its own decision (`relevant` / `set` / `false`), never spelled as `unsure`.

You are drafting the first pass over one chunk of review cards for a legal-history corpus. A human reviewer will confirm or overrule every card you decide; your job is a well-reasoned recommendation with a one-line justification, not a final ruling. Read this whole brief before opening the chunk.

## What the corpus is about

Case law on **letting**: one person paying to occupy another's dwelling or rooms (lodgers, boarders, roomers, tenants of furnished rooms, guests of boarding houses and small hotels, short-term occupants), the legal character of that arrangement, and how courts and governments regulated or restricted an owner's freedom to let. The ultimate use is a federal suit arguing a long-recognised right of a householder to let rooms.

**Polarity** is judged from the OWNER's freedom to let (the memory `polarity-owner-right-to-let`): `favorable` = the court recognised or protected the owner's freedom to let, or struck down / narrowed a restriction on it; `adverse` = the court upheld a restriction on letting, or ruled against the owner's freedom to let (a pro-tenant outcome that burdens the owner is ADVERSE); `mixed` = the same opinion both recognised the owner's freedom on one point and restricted it on another, and both are holdings rather than remarks in passing. If only one side is a holding, follow the holding. An owner who wins on a ground unrelated to letting is not favorable; judge only what the court decided about letting. A case the reader finds irrelevant carries no polarity.

**Relevance**: relevant only if the opinion bears on compensated occupancy of another's dwelling or rooms, its legal character, or its regulation. Cases about commercial leases of shops, farms, agricultural tenancies, mortgage foreclosures, hotel torts with no letting question, or where "boarder"/"lodger" is incidental colour are NOT relevant.

## Vocabularies (use these exact strings)

- `polarity`: `favorable` | `adverse` | `mixed`
- `who_was_letting`: `householder` | `commercial_operator` | `non_resident_owner` | `unclear`
- `characterization` (how the COURT classified the arrangement): `lease` | `license` | `lodging` | `innkeeping` | `other`
- `under_thirty_days` (was the occupancy at issue under thirty days): `yes` | `no` | `unclear`
- `owner_freedom_characterization` (how the court framed the owner's liberty to let): `incident_of_ownership` | `regulable_privilege` | `commercial_use` | `not_addressed`
- `restriction_nature` (adverse records only): `licensing` | `zoning` | `nuisance` | `tenant_protection` | `tax` | `other`
- `relevant`: `true` | `false`

These are the only allowed strings; a `set` with any other value is refused by the apply tool. Each card's `values` block shows the record's CURRENT values for every judged field (context, not a vocabulary), and each card carries the full opinion text.

## The four decisions

- `keep`: the value on the card stands (for an E card, "keep" means the field stays EMPTY; for an F card, the quote stands).
- `set`: replace with `value` (must be in the card's `values`; for F cards, `value` is the exact quote text to DROP).
- `adopt`: take the checker's value — do NOT use adopt in this pass; write `set` with the value you decided instead, so your decision is your own.
- `unsure`: the opinion leaves it genuinely open even with the full text. Should be rare.

A **relevance overturn** is available on ANY card: if, reading the full opinion, the case is not a letting case at all, output exactly one entry `{"case_id": <id>, "field": "relevant", "decision": "set", "value": false, "note": "..."}` for that card and nothing else for it.

## Section rules

- **G. Re-read conflicts with a human decision** (`decide_field` = the conflicting field; the card's `conflict` block shows `human_value` with `human_basis` (the reviewer and the round that decided it) and `reread_value` with `reread_basis` (the mapper-v3 re-read)). These records were decided by a HUMAN reviewer in an earlier round; the re-read disagreed and the ledger refused the machine write. The default expectation is `keep` (the human value stands). Recommend `set` only when the full opinion shows the earlier human decision was wrong on the record's own terms (for instance, a polarity that contradicts the holding under the owner-centred rule, or a characterization the court's own words contradict), and say in the note what the reviewer likely relied on and what changes it. A G card with `kind: relevant_false` asks whether the record is a letting case at all; `keep` means it stays relevant, `set relevant false` withdraws it (only if the opinion plainly is not a letting case). No `adopt` on G cards.
- **A. Favorable + under thirty days** (`decide_field: polarity`): confirm the polarity is really favorable to the OWNER's freedom to let. Pro-tenant outcomes are adverse.
- **B. Householder nights** (`who_was_letting`): was the person letting a resident householder, a commercial operator (hotel, boarding-house business), or a non-resident owner?
- **C. Checker disagreements** (`relevant`, `polarity` or `characterization`): the map's own 10% checker sample disagreed with the reader. Decide from the opinion; your note must say which reading the opinion supports and why.
- **D. Polarity mixed** (`polarity`): the reader said mixed. Resolve to favorable or adverse when only one side is a holding; keep mixed only when both sides are holdings.
- **E. Judged fields erased by the quote gate** (`under_thirty_days`, `owner_freedom_characterization`, `characterization`): the reader's value was erased because no verbatim quote supported it; the card shows it as `erased_value`. First decide relevance; then `set` the erased value if the opinion supports it, `set` a different vocabulary value if the opinion supports that instead, or `keep` (leave empty) if the opinion is silent on it.
- **F. Fuzzy quote match** (`quotes`): the quote did not match the opinion verbatim. `keep` if the quote is the opinion's text with only OCR/formatting drift (hyphenation, spacing, punctuation, a dropped word); `set` with the exact quote text to drop it if it is a paraphrase or is not in the opinion.

## Decide first, then compare with the checker

Each card may carry a `checker` block (the Codex second reading). Write your decision and note from the opinion BEFORE reading the checker block. Then compare: if your decision differs from the checker's value for the same field, add `"checker_disagrees": true` to your entry and one clause in the note saying what the checker read and why you differ. Never split the difference to match the checker.

## Output

One JSON file, a list of entries, one entry per card in your chunk (every card gets an entry; `unsure` is a decision, not an omission), each:
`{"case_id": <int>, "field": "<the card's decide_field, or 'relevant' for an overturn>", "decision": "keep|set|unsure", "value": <only on set>, "note": "<one line: the fact in the opinion that decides it>", "checker_disagrees": <true only when it does>}`

Write it with LF line endings, UTF-8, `json.dump(..., indent=1)`, to the path the dispatch names. Return to the controller only: the counts of keep / set / unsure / relevance overturns / checker disagreements, and up to five cards you found hardest with one line each.
