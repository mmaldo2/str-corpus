---
status: accepted
date: 2026-09-01
---

# Methodology defensibility is a hard requirement: frozen codebook, stability checks, generated methods appendix, planned certification, page-image pin-cite gate

The record may be presented in court with its method, and the corpus
linguistics, empirical legal studies, and technology-assisted-review
literatures converge on what a defensible computational survey must show:
a frozen corpus snapshot, every query and model version logged, a codebook
frozen before coding, multiple coders with reported agreement, recall
against a gold set plus a blind sample of what the method did not retrieve,
and counts stated as lower bounds. We decided to build these in rather than
reconstruct them later: schema v2 plus reader prompt v2 form a frozen
codebook, changed only with a version bump and a prompt-stability check on
a fixed fifty-case sample; a methods appendix is generated from run
metadata (corpus manifest hash, selector strings and versions, model and
provider and quantization, thresholds, dates, hit funnel per stage,
reviewer agreement, two-tier counts); the ledger manifest records each read
case's stratum so a later certification pass, a classifier-stratified
blind sample of unretrieved cases with human adjudication, can reuse earlier
reads; and every quote destined for work product passes a pin-cite check
against the scanned page image on static.case.law using a vision model
chosen by a small transcription-fidelity test.

## Considered options

- Rely on gold-set recall and the precision knee alone: the knee is a
  heuristic courts have accepted as stopping evidence but not as a recall
  bound; a competent opposing expert attacks it first.
- Certify every cycle: unaffordable; certifying once breadth exists, with
  earlier reads counting, is the same evidence at a fraction of the cost.
- Wholesale re-OCR of the corpus with vision models: rejected; historical
  transcription studies show vision models silently modernize archaic
  spellings, which is the opposite of what a verbatim gate needs.

## Consequences

The user doubts most opposing counsel could mount these attacks; the
requirement stands anyway because the same artifacts are what the record's
first consumer needs to show non-technical colleagues. No court has yet
accepted or rejected an LLM-assisted case survey; the framing is LLM as
classifier validated against human coding, never LLM as oracle.
