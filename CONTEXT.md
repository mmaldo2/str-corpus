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
against the owner is adverse. Mixed means the same opinion both recognizes
the owner's freedom to let on one point and restricts it on another, and
both are holdings rather than remarks in passing; an owner who wins on a
ground unrelated to letting is not favorable. A case the reader finds
irrelevant carries no polarity.
_Avoid_: pro-tenant, pro-landlord, outcome, irrelevant-as-a-polarity

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

**Provenance**:
Who decided a field on a record: human, reader, or rule. Tracked per field and
sticky at human — a rule that later withdraws the value does not un-make the
judgment.
_Avoid_: source, origin

**Conflict**:
A machine write that disagrees with a human decision. Never applied: the human
value stands, the attempt is recorded, and the record is flagged so the
disagreement reaches a review card.
_Avoid_: mismatch, error

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

**Candidate pool**:
The full set of unread, signal-bearing cases a shard produces, before ranking
or batching. What a ranker scores, and what held-out coverage is measured
against.

**Ranker**:
A scoring function over the candidate pool, ordering cases by estimated
relevance so readers see the most promising cases first within a batch.
Distinct from a selector: a ranker does not decide which cases enter the
pool, only how they are ordered once they are in it.

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

**Plan**:
The frozen description of one reading job: its kind, its ordered units, the
codebook, the model pin, the budget, and the worker. Built once and then
executed; a resumed run re-executes the same plan.

**Unit**:
One request's worth of a plan: the case ids read together in a single
prompt, with the batch metadata the codebook renders. A batch is the usual
unit; a re-read or a judgment is a unit of one.

**Extraction record**:
A reader's structured judgment of one case: the judged fields above plus
quotes.

**Accepted record**:
An extraction record that came back through the quote gate with a decided
`relevant` field. The denominator of cost per accepted record, and the only
kind of record that reaches the ledger.

**Quote gate**:
The deterministic step, inside the reader driver, that verifies every quote
against the case text and voids any judged field whose supporting quote
fails. Nothing unverified leaves the driver.

**Remap**:
A second reading of a case whose fields were voided by the quote gate.

**Codebook**:
The frozen definition of every judged field and the reader instructions that
implement it. Identified by the sha256 of its file, which is what its
stability record is filed under. Changed only with a version bump and a
stability check.

**Stability check**:
Re-reading a fixed sample of cases after any codebook change and reporting
agreement, before the new codebook is used.

**Reference set** (the kit):
The frozen bundle a model measurement runs against: the batches, the case
texts inlined so the measurement never touches the store, and the answers
to compare against (human-adjudicated rows, plus rows the method already
judged irrelevant). Sha-pinned in `domain.yaml` and never edited; a change
means a new kit version.

**Map**:
One pass of the reader over a cycle's ranked candidate pool under a
budget; produces accepted records and a map manifest.
_Avoid_: run, crawl

**Cell**:
An era x jurisdiction slice of the candidate pool; the unit the budget is
set on.

**Yield**:
Relevant accepted records per completed batch in a cell; the quantity the
stop rule watches.

**Admission**:
Turning a map's accepted records into machine-only ledger records with
reader basis.
_Avoid_: import, load

**Review queue**:
The priority-ordered set of admitted records a human decides on in one
round; six sections, capped.
_Avoid_: backlog

**Screen**:
An optional relevance-only pass by the fallback reader over a cell's
remainder.

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

**Labelled read**:
A case with a known outcome — relevant or not — usable to train or evaluate
a ranker. Comes from either a human adjudication or a machine extraction
verdict; which one it is determines whether it belongs to the reviewed
view.

**Held-out slice**:
The frozen sample of labelled reads a ranker is scored against and never
trained on. Distinct from the held-out set above: a held-out slice is drawn
from labelled reads, not the gold set, and is pinned by file hash rather
than by role in a tuning split.

**Reviewed view**:
The subset of a held-out slice restricted to human-reviewed positives plus
every negative. Because negatives come from machine extraction verdicts
rather than human adjudication, the reviewed view is not itself fully
human-reviewed — only its positives are.

**Ship rule / bar**:
The pre-registered comparison that decides whether a new ranker replaces
the current default (the ship rule) or whether an alternative ranker is
worth the cost of adopting (the bar). Both are fixed before measurement and
applied regardless of which side wins.

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
