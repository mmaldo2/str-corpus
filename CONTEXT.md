# Right-to-Let Corpus

A research instrument that recovers, from the complete historical case-law
record, the evidence that ordinary owners let rooms and dwellings for short
periods for pay, and that courts treated this as lawful. The first and
governing use is a litigation-grade evidentiary record for a federal
history-and-tradition claim about short-term rentals. The engine is meant to
be reusable for other "what does the historical legal record actually say
about X" questions.

## The claim

**Right to let**:
The owner's right to temporarily part with possession of their dwelling, or
part of it, for compensation. The "stick" in the bundle of property rights
that the project is about.
_Avoid_: right to rent, right to host, STR right

**Householder**:
An owner or their family letting part of the dwelling they themselves occupy.
The core tier of the tradition showing.
_Avoid_: homeowner, resident host

**Non-resident owner**:
An owner of a single dwelling letting the whole of it while not occupying it,
such as a summer cottage or a house let while away. The second tier of the
showing, and the profile of most modern STR plaintiffs.
_Avoid_: investor, absentee landlord

**Commercial operator**:
A person or enterprise letting as a business: hotels, boarding houses run as
enterprises, operators of multiple properties. Outside both tiers of the
showing.

**Level of generality**:
The framing fight over how narrowly the asserted right is described. The
opponent's framing is a novel commercial right; the project's framing is a
householder's ancient right to let for short periods.

**Tradition evidence**:
Historical cases showing the practice of letting and how courts treated it.
Distinct from the argument-side file.

**Argument-side file**:
The modern cases a federal brief is framed with: the level-of-generality line,
the history-and-tradition methodology cases, and the current STR decisions.
Never counted as tradition evidence.

## What is judged about a case

**Relevance**:
Whether a case bears on compensated occupancy of another's dwelling or rooms,
its legal character, or its regulation. A passing mention is not relevance.

**Polarity**:
Whether a case is favorable, adverse, or mixed for the owner's right to let.
Judged from the owner's side only. An outcome that protects an occupant
against the owner is adverse.
_Avoid_: pro-tenant, pro-landlord, outcome

**Who was letting**:
Householder, non-resident owner, commercial operator, or unclear.

**Duration**:
The length of the occupancy actually at issue: nights, weeks, months, or
unclear.

**Under thirty days**:
Whether the occupancy at issue was shorter than thirty days. Yes, no, or
unclear. Exists because the opponent's framing is "under thirty days."

**Characterization**:
How the court classified the arrangement: lease, license, lodging,
innkeeping, or other.

**Restriction nature**:
On an adverse case, what kind of restriction was upheld: licensing,
conditions, zoning exclusion, or outright prohibition. Exists because a
tradition of regulating letting is not a tradition of prohibiting it.

**Verified quote**:
A passage the reader extracted that matches the source text verbatim or
within a fixed tolerance for OCR noise, with its reporter page. A claim about
a case is only as good as its verified quote.
_Avoid_: citation, snippet

**Pin-cite check**:
Confirmation of a verified quote against the scanned page image of the
printed reporter. Applied only to quotes destined for work product.

## The record

**Ledger**:
The accumulated set of relevant cases with their judged fields, verified
quotes, and review history. The system of record.
_Avoid_: results, output, database

**Ledger record**:
One case's entry in the ledger.

**Review tier**:
Whether a ledger record's judgments have been confirmed by a human
(human-reviewed) or rest on machine readers only (machine-only). Every count
is reported by tier, never blended.

**Adjudication**:
A human's saved decision on a ledger record or one of its fields. The human's
decision is the record; every machine recommendation is a recommendation only.

**Tradition matrix**:
The count of favorable cases by era, region, letting tier, and duration. The
project's definition of done is a matrix with no empty cells.
_Avoid_: evidence table, coverage table

**Manifest**:
The per-cycle account of every case read, with its outcome, so that "every
case was accounted for" can be checked from the repository alone.

**Two-tier count**:
Any published number about the ledger, stated separately for human-reviewed
and machine-only records.

## Finding cases

**Corpus**:
The complete set of reported opinions ingested for the target jurisdictions
and eras.

**Era partition**:
One of the fixed date ranges the corpus is cut into: pre-1860, 1860-1900,
1900-1930, 1930-1970, 1970-2020.

**Selector**:
A versioned, human-reviewed retrieval hypothesis: a claim that cases about
the practice can be found with a particular period phrase, proximity pattern,
semantic query, or graph relation. The falsifiable artifact of the method.
_Avoid_: query, search, filter

**Adverse selector**:
A selector built to find the opposing record deliberately.

**Signal**:
One selector's hit on one case, with the matched text and its provenance.

**Coverage**:
The record of which selector versions have been run over which era and
jurisdiction partitions. What makes a re-run pay only for the difference.

**Shard**:
The deterministic act of running uncovered selectors and grouping the
resulting candidates into batches.

**Batch**:
A group of candidate cases handed to one reader in one request.

**Citation graph**:
The record of which cases cite which. Used to reach cases whose vocabulary
no selector catches.

**Seed set**:
The verified favorable cases and anchor cases from which a citation-graph or
relevance-feedback selector expands. Recorded by hash so the expansion is
reproducible.

**Ontology**:
The versioned map from a legal concept to its period-specific surface forms
and anchor cases. The reusable vocabulary asset.

**Concept**:
A named doctrinal idea in the ontology, such as lodger status or the license
versus lease distinction.

**Surface form**:
A period phrase by which a concept appears in the record.

**Anchor case**:
A case a treatise or brief cites for a concept.

**Lexicon**:
The set of surface forms in use across selectors. Informal collective term.

## Reading cases

**Reader**:
A model that reads a batch and produces an extraction record per case.
_Avoid_: mapper, worker, extractor, LLM

**Checker**:
A model from a different family that re-reads a sample and whose
disagreements route cases to human review.

**Extraction record**:
A reader's structured judgment of one case: the judged fields above plus
quotes.

**Quote gate**:
The deterministic step that verifies every quote and voids any field whose
supporting quote fails.

**Remap**:
A second reading of a case whose fields were voided by the quote gate.

**Codebook**:
The frozen definition of every judged field and the reader instructions that
implement it. Changed only with a version bump and a stability check.

**Stability check**:
Re-reading a fixed sample of cases after any codebook change and reporting
agreement, before the new codebook is used.

## Measuring the method

**Gold set**:
Cases known in advance to be relevant, from briefs and treatises, against
which recall is measured.

**Brief tier**:
Gold-set cases harvested from litigation briefs. The headline recall
denominator.

**Treatise tier**:
Gold-set cases from treatise lodger and boarder chapters. Reported
separately because they also seed the lexicon.

**Development set**:
The part of the gold set selectors may be tuned against.

**Held-out set**:
The part of the gold set never used for tuning. The only honest basis for a
recall claim.

**Recall gate**:
The rule that a selector change is accepted only if gold-set recall does not
fall.

**Certification**:
A recall estimate from a blind sample of the cases the method did not
retrieve, with human adjudication. Distinct from gold-set recall.

**Methods appendix**:
The generated statement of corpus snapshot, selectors, models, thresholds,
counts per stage, and reviewer agreement for a run or cycle.

## Organizing the work

**Cycle**:
One pass of planning selectors, sharding, reading, verifying, reviewing, and
synthesizing, ending in a cycle report and ledger update.

**Run**:
One execution of a stage within a cycle, identified by name.

**Domain**:
Everything specific to one research question: its ontology, selectors,
codebook, gold set, jurisdictions, and eras. The engine is domain-agnostic.
