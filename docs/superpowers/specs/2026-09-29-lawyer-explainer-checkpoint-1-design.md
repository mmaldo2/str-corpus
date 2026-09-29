# Lawyer explainer, Checkpoint 1: design

Date: 2026-09-29. Status: approved by the user 2026-09-29 (amended the same day: old
guide dropped, explainer files kept outside git, no dollar figures). Branch:
`explainer/checkpoint-1`.

## 1. Purpose

Make the pipeline legible to the non-technical lawyers on the litigation team, and
show how it maps onto the established practice of corpus linguistics in litigation,
by abstracting without sacrificing accuracy.

### The brief (agreed in conversation)

Stated by the user:

- **Audience:** our litigation team (co-counsel and client lawyers).
- **Success:** after about ten minutes, a team lawyer can **explain the method onward**
  in their own words, to a judge, client, or co-counsel.
- **Setting:** they meet it **on their own, via a link**. It must explain itself.
- **Corpus-linguistics fluency:** they have **heard of it** (ordinary meaning, big text
  databases) but never run a study, so a short primer comes before the mapping.
- **Packaging:** approach A: a scroll-through explainer page now; a narrated video
  may be cut from the same script later (not in this spec).
- **Timing:** a **checkpoint snapshot taken before the audit**. The team reviews it
  before the user completes the audit; Checkpoint 2 follows the audit.
- **No old guides.** The Sept 14 guide (`reports/right-to-let-guide.html`) and the
  August attorney report are neither published nor referenced (user decision
  2026-09-29, reversing an earlier "publish the guide too"). Depth lives in expanders
  on the new page.
- **Outside git.** The GitHub repo is public, so the script, snapshot, sources record,
  and page live in a gitignored folder; only this spec and the snapshot tool are
  committed. The page's durable home is the private Artifact.
- **No dollar figures** (spend history or unit prices) in anything the team receives;
  models and routes are named neutrally.

Assumed and not corrected by the user:

- The page carries only a handful of numbers, each dated and tied to one ledger snapshot.
- Four limits are never abstracted away (section 7).

### The framing the page teaches

The pipeline has two lineages lawyers half-know:

1. **Corpus linguistics in litigation:** declared corpus, disclosed searches, period
   vocabulary found in context, a coding protocol fixed before coding, multiple coders
   with reported agreement, an explicit "unclear" bucket, counts as lower bounds.
2. **E-discovery document review (TAR):** ranking documents by likely relevance,
   first-level review checked by quality control and then attorneys, validation samples.

The portable one-liner: *a corpus-linguistics study of the case law, run at
document-review scale.* The departure from classic legal corpus linguistics is shown,
not blurred: the method codes **whole opinions for how courts treated letting**, not
word uses for ordinary meaning; the closest established name for that unit is
systematic content analysis of judicial opinions.

## 2. Deliverables

| # | Deliverable | Where | In git? |
|---|---|---|---|
| 1 | The script: every word on the page, each factual claim tagged to its source | `reports/explainer/script.md` | no |
| 2 | The numbers, generated from the ledger at the pinned snapshot | `reports/explainer/snapshot.json` | no |
| 3 | The snapshot tool and its fixture-only tests | `tools/explainer_snapshot.py`, `tests/` | yes |
| 4 | The page, Checkpoint 1, published as a private Artifact | `reports/explainer/method-explainer.html` | no |
| 5 | Provenance record: repo revision, ledger seq, sha256 of every source file the claims rest on | `reports/explainer/sources.md` | no |

`reports/explainer/` is added to `.gitignore` before any file is written there. The
printable one-page summary is part of deliverable 4 (a print stylesheet), not a
separate file.

## 3. The spine: five steps

One picture a lawyer could redraw on a napkin. Each step carries a plain description,
its corpus-linguistics name, its document-review name, and "how it is checked."

| Step | Plain terms | Corpus linguistics | Document review |
|---|---|---|---|
| 1. The library | About 1.8 million reported opinions from the 10 searched jurisdictions (Cal., Conn., D.C., La., Mass., N.J., N.Y., Ohio, Pa., Tex.), 1671-2019, one frozen snapshot of the Caselaw Access Project; the library also holds about 79 thousand federal and stray opinions outside these searches | The corpus | The collection |
| 2. The search | Period vocabulary ("lodger," "boarder," "furnished rooms") from treatises and usage in context, plus meaning-based and citation search, plus adverse searches built to find the opposing record; every search logged and versioned | Search queries, concordance | Search terms, predictive ranking |
| 3. The first read | An AI reader codes each opinion against a fixed codebook and must back each answer with a quote; the quote is machine-matched against the opinion text and an answer without a matching quote is erased | Coding under a protocol | First-level review |
| 4. The second look | A second AI from a different company re-reads samples; disagreements and priority records go to a person, whose decision no machine can overwrite | Multiple coders, agreement | QC and second-level attorney review |
| 5. The record | Every decision logged with who made it; counts split human-confirmed / machine-only, stated as lower bounds, tested against known cases and a random audit | Replicable reporting | Validation sample |

The loop back (findings feed new vocabulary into the next search cycle) is drawn as a
single return arrow, not a separate step.

## 4. Page structure (about ten minutes on the main path)

A checkpoint banner sits at the top: *Checkpoint 1 · ledger snapshot of September 12,
2026 (sequence 83,531) · before the audit.*

1. **The one-sentence version.** Draft: *"A corpus-linguistics study of American case
   law, run at document-review scale. Every AI judgment has to be backed by a quote
   checked against the opinion, and every human decision is on the record."* One line
   restates the question the record answers.
2. **Corpus linguistics in 60 seconds.** What it is in litigation (declare a corpus,
   show your searches, code what comes back, count), illustrated with a few real
   concordance lines for "lodger" pulled from this corpus with `pipeline/kwic.py`. The
   turn: same discipline, different question (what courts did about letting, not what
   a word meant). If time runs short this part shrinks to an expander.
3. **The five steps, with one case moving through them.** The diagram is pinned; a case
   card changes at each step (section 5). At step 4 a second case comes in: the one
   the process caught. Each step has a small "you already know this as…" label.
4. **How it lines up with corpus-linguistics practice.** The crosswalk (section 6).
5. **What the record can and can't say.** The numbers (section 8), lower bounds, the
   audit's status, and a short list of phrasings: "say *at least N reported cases*,
   not *every case*."
6. **Retell it.** A 30-second script and a 2-minute script, word for word, plus the
   diagram as a one-page download.
7. **Tough questions** (expander). Draft set:
   - *Isn't this just asking ChatGPT what the law was?* No: the AI is a coder bound by
     a codebook, every answer is quote-backed, and a second AI and people check it.
   - *What if the AI invented a quote or a case?* Cases come from the library, not
     from a model's memory; quotes are machine-matched against the opinion text. The
     text is a transcription; a check against scanned page images for quotes used in
     filings is designed but not yet run.
   - *How do you know you didn't miss cases?* We don't claim completeness: counts are
     lower bounds; the known-case benchmark and the unread-tail estimate say how much
     may be missing.
   - *What about cases the AI wrongly threw out?* Review checks what the AI kept, not
     what it discarded. In the benchmark, 17 known cases were judged "not about letting"
     by the reader and no person has re-checked them. A blind check of discarded and
     unretrieved cases is planned, not done.
   - *Couldn't the searches be rigged toward favorable cases?* Searches are logged and
     versioned, the codebook was fixed before coding, adverse searches run on purpose,
     and *In re Jacobs* shows a favorable-sounding case being withdrawn.
   - *What does "human-reviewed" mean?* A person made or confirmed the call on that
     record, sometimes by adopting an AI reviewer's recommendation; individual field
     values can still be the reader's.
   - *Has any court accepted this?* Each ingredient has precedent (corpus linguistics;
     technology-assisted review); no court has yet ruled on an AI-assisted case survey.
8. **Where this comes from.** The snapshot identifiers (date, ledger sequence, repo
   revision), a short glossary (pipeline term to plain term), and links to the
   published legal authorities cited. No links to repository files, the Sept 14
   guide, or the August pages; further depth lives in the page's own expanders.

## 5. The two cases

### The case that holds up: *Ackley & Dana v. Chamberlain*, 16 Cal. 181 (1860), case 2279220

A family residence on a mountain road kept its homestead exemption although its owner
"kept boarders and lodgers, and furnished accommodations to travelers": *"The keeping
of boarders and accommodation of lodgers and travelers were not inconsistent with the
main purpose…"* Its trail, from the ledger and `signals`:

- Found by keyword selector `boarder-core-03` and semantic selector
  `relevance-feedback-39` (run `cycle-004-shard-01`).
- Read by `claude-opus-5@claude-cli`; coded relevant, favorable, householder, nights,
  under thirty days yes, owner freedom `incident_of_ownership`, each supported by a
  verified quote (ledger seq 22083-22093).
- Map cycle 004 round 1: GPT Astra drafted the first pass; the user confirmed polarity
  and added a note; `review.status` human-adjudicated (seq 38534-38537).

The card must say that the field values are the reader's and a person confirmed them;
field provenance in the ledger is `reader` for every field.

### The case the process caught: *In re Jacobs*, 2 N.Y. Crim. 539 (N.Y. 1885), case 1167707

The Tenement House Cigar Act case. Lawyers know it as *In re Jacobs*, 98 N.Y. 98 (1885);
the page gives that citation alongside the corpus's reporter if the fact-check confirms
they report the same decision.

- Found by the adverse selector `adverse-embed-regulation-29`.
- The reader marked it relevant and favorable (relevance score 0.3, with its own note
  "Marginal… letting only appears in quoted dicta"), resting on a real quotation,
  verified within the OCR tolerance: a law making it a crime "for men either to live
  in, or rent, or sell their houses" would violate liberty (quoted from *Wynehamer*).
- The holding concerns cigar-making in tenement homes. In shard-02 round 3 the checker
  read it not relevant; Claude's first pass kept it; Astra's first pass withdrew it.
- The user withdrew it on the round 3b page (seq 81196-81200).

The point it makes: the language sounds ideal for the claim and the process threw it
out anyway, because a quoted line is not a holding about letting.

*Peet v. McGraw*, 25 Wend. 653 (1841), case 2026536 (a meaning-based match that turned
out to concern a lien for feeding horses) may appear in the primer as a word-sense
example if a real concordance line fits; it is not required.

## 6. The crosswalk

Rows are standards from the corpus-linguistics-in-law literature and the court cases
approving technology-assisted review; each row carries a verdict (**Matches**, **Goes
further**, or **Departs**) and a one-line reason. **Departs** rows are styled with the
same weight as **Matches** rows. Draft rows, subject to the fact-check (section 9):

| Standard | This method | Verdict |
|---|---|---|
| Declare the corpus and freeze it | One CAP snapshot; every volume file recorded with its hash | Matches |
| Disclose the searches | Every selector versioned and logged with where it ran; adverse searches run deliberately | Goes further |
| Fix the coding protocol before coding | The codebook is frozen and identified by its hash; a change needs a version bump and a stability re-check | Matches |
| Multiple coders, reported agreement | First-pass coders are AI models from two companies; disagreements go to a person; agreement reported (the audit will add the human benchmark) | Matches in structure; departs in who codes |
| An explicit "unclear" bucket | Unclear and mixed values; a field is left empty when no quote supports it | Matches |
| Coding a sample of lines | Whole opinions are read, tens of thousands of them, not a sample of lines; but a ranked tail of candidates remains unread | Goes further, with a stated limit |
| Show your work so others can replicate | Every decision logged with who made it; every count regenerated from the log | Goes further |
| Unit and question | Codes whole opinions for how courts treated letting, not word uses for ordinary meaning; the established name for this unit is content analysis of judicial opinions | Departs |
| Validate against what you missed (TAR) | Known-case benchmark and a random audit (in progress); no blind sample yet of discarded or unretrieved cases | Departs for now |
| Judicial track record | Corpus linguistics and TAR each have precedent; no court has ruled on an AI-assisted case survey | Departs |

Authorities to verify before use (none is cited from memory):
Lee & Mouritsen, *Judging Ordinary Meaning*, 127 Yale L.J. 788 (2018); Lee & Mouritsen,
*The Corpus and the Critics*, 88 U. Chi. L. Rev. 275 (2021); *People v. Harris*, 499
Mich. 332 (2016); Hall & Wright, *Systematic Content Analysis of Judicial Opinions*, 96
Calif. L. Rev. 63 (2008); *Da Silva Moore v. Publicis Groupe*, 287 F.R.D. 182 (S.D.N.Y.
2012); *Rio Tinto PLC v. Vale S.A.*, 306 F.R.D. 125 (S.D.N.Y. 2015); *In re Broiler
Chicken Antitrust Litigation* (N.D. Ill. 2018) (TAR validation protocol); optionally
*Snell v. United Specialty Insurance Co.*, 102 F.4th 1208 (11th Cir. 2024) (Newsom, J.,
concurring), used only as the contrast between an LLM as oracle and an LLM as coder.

## 7. Accuracy guardrails (acceptance criteria)

The page passes only if:

1. Counts are stated as **lower bounds**; nothing says or implies the record is complete.
2. **"Human-reviewed"** is defined where first used: a person made or confirmed the
   call on the record, sometimes adopting an AI reviewer's recommendation; field values
   may remain the reader's.
3. Quote verification is described as a match against the **transcribed text**; the
   page-image pin-cite check is described as designed, not done.
4. The AI is framed as **a coder whose work is checked against human coding**, never
   as an authority on what the law was (ADR-0009).
5. Every factual claim in the script has a source tag; every number comes from
   `snapshot.json`.
6. Every **Departs** row in the crosswalk is as prominent as the **Matches** rows.
7. Nothing implies a court has approved an AI-assisted case survey.
8. The benchmark is presented with its full breakdown (section 8), and review is
   described as checking what the AI kept, not what it discarded.
9. The audit is described as drawn and frozen but not yet read; no audit result and no
   model-versus-model agreement figure is presented as accuracy.
10. No dollar figures anywhere (spend history, unit prices, list-equivalent costs);
    models and routes are named neutrally (e.g. "Claude Opus," "a GPT model"), with no
    discussion of billing routes.
11. No reference to the Sept 14 guide, `attorney-report.html`, or the August artifacts.

## 8. Numbers

At most six figures on the page, all from `snapshot.json`, generated by
`tools/explainer_snapshot.py` at ledger view `as_of=83531` so the snapshot is
reproducible even after the ledger moves.

| # | Figure | Source | Today's value |
|---|---|---|---|
| 1 | Size of the library | `corpus.db` canonical (non-duplicate) cases in the 10 domain jurisdictions, plus the out-of-scope remainder | 1,795,165 in scope (1671-2019); 78,976 outside (mostly U.S.); 1,874,141 total |
| 2 | Opinions the AI readers read | Unique case ids with a reader verdict at seq 83531, cross-checked against the map manifests; re-reads never double-counted | to be computed |
| 3 | Relevant records, two tiers (with favorable and favorable-householder as subsets) | `open_ledger().view(as_of=83531).counts()` | 4,351 (1,509 / 2,842); favorable 1,954 (754 / 1,200); favorable householder 397 (161 / 236) |
| 4 | The audit | `runs/audit-cycle-004/sample-manifest.json` | 150 drawn from 2,842 machine-only relevant records, seed 20260912, not yet read |
| 5 | Known-case benchmark | `reports/evaluation-cycle-004.json` | 36 resolved known cases: 28 found and read, 10 kept as relevant; of the 26 lost, 8 never found by a search, 17 read and judged not relevant by the reader with no human re-check, 1 withdrawn by a person; 0.278 (interval 0.158-0.440) |
| 6 | Unread tail | `reports/evaluation-cycle-004.json` | an estimated 409-1,568 further relevant cases among the unread candidates, by scenario |

Figures 5 and 6 appear together under "what we know we're missing."

**Checkpoint 2** (after the audit is applied): re-run the tool at the new sequence,
replace the audit block with the result, refresh figures 3-6, republish to the same
URL, and update the banner.

## 9. Production process and review gates

1. **Script.** Draft `script.md` from this spec, every claim tagged
   (`[repo: path]`, `[ledger: query]`, `[auth: citation]`).
2. **Numbers.** Build `tools/explainer_snapshot.py` and generate `snapshot.json`. Tests
   use fixtures only, never the live ledger or gold files.
3. **Fact-check.** A fresh reviewer agent, without this conversation, checks every
   tagged claim against the repository and every authority against the actual source
   (web), and reports discrepancies. Fixes go into the script.
4. **User reviews the script.** No layout work before this approval.
5. **Page.** Built from the approved script and `snapshot.json` (the `artifact-design`
   skill governs the page contract). Verified in a browser at desktop and phone widths,
   in light and dark, and in print preview (the summary fits on one page).
6. **User reviews the page**, then it is published as a private Artifact; the user
   shares the link with the team.

## 10. Form

- One self-contained HTML page; works at phone width; light and dark.
- A legal-memo register: serif type, generous white space, dark ink with a single
  accent colour; no robot or brain iconography.
- The five-step diagram is inline SVG, a numbered line of stations. Desktop: pinned
  beside the text while the case card changes. Phone: collapses to a compact step
  indicator at the top.
- A "Print summary" button; the print stylesheet yields one page with the diagram, the
  30-second version, the crosswalk in brief, and the snapshot date.
- The script is written in short, speakable sentences so a later video can reuse it.

## 11. Out of scope

- The video (a later spec, reusing the script).
- Completing the audit, and any change to the ledger, selectors, codebook, or gold set.
- Publishing, committing, or referencing the Sept 14 guide.
- Deleting or editing the August artifacts ("The Right-to-Let Record", "Right-to-Let
  Corpus Engine"); the user may stop pointing people to them.

## 12. Open decisions

- **D1: today's gold-codebook review.** `reports/gold-codebook-review-2026-09-29.md`
  (untracked, model-authored, self-described as recommendations, not adjudications)
  classes 22 of the 36 benchmark cases as outside the relevance rule, 12 as clearly in
  (10 of them kept), and 2 as boundary. **Default:** the page presents the official
  10/36 with the breakdown in section 8 and does not cite the unadjudicated review. If
  the user adjudicates it before publication, the benchmark block is restated from the
  adjudicated result, with its own source.
- **D2: the Newsom concurrence.** Included only if the fact-check confirms the citation
  and that it fits the oracle-versus-coder contrast.
- **D3: *Peet v. McGraw* in the primer.** Only if a real concordance line fits.

## 13. As built (2026-09-29)

Where the published Checkpoint 1 differs from the design above, and why:

- **No Print button (section 10).** The Artifact viewer cannot open a print dialog. The one-page summary is an "At a glance" card in *Retell it*, with a print stylesheet; `reports/explainer/at-a-glance.pdf` is generated locally for forwarding.
- **Case cards sit inline under each step**, not swapped in by scrolling. The page must be complete without scrolling tricks, so the observer only highlights the active step.
- **Title: "How the Letting Record Was Built".** "The Right-to-Let Record" is the retired August page.
- **Fact-check rewrite (factcheck.md).**
  - The quote rule is stated as covering every coded finding except relevance, who was letting and duration.
  - "Human-reviewed" marks the record, not each answer.
  - The crosswalk standards are re-sourced to Lee & Mouritsen and to content-analysis practice; the multiple-coders row is "Departs for now".
  - "At least" is dropped: the unaudited machine-only records and duplicate reports can overcount.
  - Adverse and mixed counts were added; the snapshot tool counts them.
  - The main-path reading cap was relaxed from 2,300 to about 2,900 words.
- **Seven additions the user approved after review:**
  - concept search, naming Qwen3-Embedding-4B;
  - citation searches compared to a citator;
  - why the codebook asks what it asks;
  - reading spread across era and place, with its stopping rule;
  - the tradition grid;
  - reporter pages on quotes;
  - two new tough questions: how the AI reader was chosen, and whether review is a rubber stamp.
- **Restriction nature.** The page lists the codebook's real values. CONTEXT.md was corrected to match.
- **Published:** a private Artifact at https://claude.ai/artifact/7TBQRFaCjQBbADx9WQZ48C (version 2).
