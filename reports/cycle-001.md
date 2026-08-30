# Cycle 001 — Findings Report

**Run:** cycle-001-shard-01 + cycle-001-shard-02 · **Date:** 2026-08-30
**Reducer:** Fable (this session), consuming verified extraction JSON only.

> ⚠️ **Nothing in this report is work-product ready.** Every case below
> requires the manual citator gate before use: `[ ] citator-checked`.
> Extraction quotes are verbatim-verified against source text; holdings are
> AI summaries pending human review.

---

## 1. Metrics

### Retrieval (shard recall vs. gold set)
| Tier | Recall | Detail |
|---|---|---|
| **brief-letting (HEADLINE)** | **5/15 = 33.3%** | letting-domain cites from the Zaatari briefs |
| brief-all (secondary) | 13/63 = 20.6% | incl. out-of-domain constitutional doctrine |
| treatise (secondary) | **21/29 = 72.4%** | the truer lexicon probe |

The embedding selectors drove the jump (treatise 24%→72%, brief-letting
13%→33% over FTS-only). Per-miss postmortems in §6.

### Corpus / signals
1,301,147 unique cases indexed (3,882,534 chunks). 30 selectors produced
**12,919 signals over 11,191 distinct cases**; 630 batches emitted, **40
mapped** (6.3% of candidates — the sprint-one budget cap, not a completeness
claim).

### Extraction & verification
712 cases read → **201 relevant** (28.2% precision of mapped candidates).
Quote gate: **552 verified exact, 28 verified-fuzzy (human queue), 2
dropped**; 688/712 records fully clean, **0 invalid**. No unverified quote
passed to this report.

### Cross-model agreement
4 batches (72 cases) re-read by Codex: **35 field-level disagreements**
(~16% of 216 field comparisons), concentrated in `polarity` on borderline
regulatory cases. All routed to the human-review queue (§7).

### Cost
~4.94M input / 1.07M output tokens across 40 Sonnet batches ≈ **6.9k in /
1.5k out per case**. (Subscription-billed; one usage-limit interruption,
resumed cleanly from cache.)

### End-to-end recall
3/61 brief-tier gold cases survived Map with `relevant: true` — low because
only 6.3% of signal-bearing cases were mapped and most brief-tier gold is
doctrine-domain (correctly `relevant: false` for the letting schema). The
meaningful end-to-end number arrives when the batch budget expands.

---

## 2. The Ledger

201 relevant cases, 1799–2019, all four states:

| Polarity | n |
|---|---|
| **Favorable** | 108 |
| Adverse | 45 |
| Mixed | 28 |
| Unsupported (polarity nulled by quote gate) | 20 |

### The level-of-generality evidence table (favorable cases)
| who \ duration | nights | weeks | months | unclear | Σ |
|---|---|---|---|---|---|
| **householder** | **12** | 3 | 14 | 20 | **49** |
| commercial operator | 9 | 8 | 20 | 18 | 55 |
| unclear | 1 | 0 | 0 | 3 | 4 |

**49 favorable householder cases** — ordinary people letting rooms or
dwellings in their own homes, courts treating it as lawful — is the direct
answer to the "no tradition" framing. The 12 householder-×-nights cases are
the highest-value stratum and first in the review queue.

---

## 3. Doctrinal lines (cross-shard genealogies)

1. **Boarder-property / distress-and-lien line (1799–1890s).** From 1 Lock.
   Rev. Cas. 307 (N.Y. 1799) through *Riddle v. Welden*, 5 Whart. 9 (Pa.
   1839) (boarder's effects exempt from distress — a treatise anchor,
   recovered and extracted favorably) into the N.Y. 1860 boarding-house lien
   act cases. Boarding was ordinary enough that legislatures built lien and
   exemption law around it — a tradition of *accommodation*, not
   prohibition.
2. **Lodger vs. tenant / exclusive possession (1845–1951).** *Wilson v.
   Martin*, 1 Denio 602 (1845) → *Oliver v. Moore* (1889, triple-reported,
   deduped) → 238 S.W.2d 614 (Tex. 1951) (exclusive-possession test stated
   as black letter). Courts spent a century *classifying* short occupancies
   — never questioning their lawfulness.
3. **Householder vs. innkeeper status (1858–1930s).** *Howth v. Franklin*,
   20 Tex. 798 (1858): strict innkeeper duties attach only to one who holds
   himself out publicly; the householder taking guests is a distinct,
   lesser-regulated category. This is the era's own version of the
   homestay/hotel line.
4. **The covenant line — the modern fight's direct ancestor (1867–2019).**
   Taking boarders held NOT to breach dwelling-only covenants: 30 N.Y.
   Super. Ct. 561 (1867); 158 N.Y.S. 895 (1916); 205 A.D. 112 (1923); 288
   S.W. 180 (Tex. Comm'n App. 1926); widow letting 15 of 16 rooms still
   "dwelling purposes," 114 Misc. 106 (1921). Midpoint: *Southampton Civic
   Club* line (Tex. 1958) — incidental renting fine, rooming-house *as a
   business* not. Endpoint: *Tarr v. Timberwood Park*, 556 S.W.3d 274 (Tex.
   2018) ("residential purposes" does not bar short-term leasing) vs. *Slice
   of Life v. Hamilton Twp.*, 207 A.3d 886 (Pa. 2019) (purely transient
   operator-absent rental excluded). The entire modern battle is a
   restatement of this 150-year-old line.
5. **Early short-duration letting.** 119 La. 1025 (1907): owner leased his
   lakeside camp "to all comers, including for single days" — litigated
   without anyone doubting he could. 23 Misc. 698 (1898): $1.25/week hotel
   occupant; 2 Daly 15 (1867): 25¢/night lodging house. Duration-based
   letting at every price point, every era.
6. **The adverse file (as designed).** Pa. lodging-house licensing act of
   1895 upheld (1 Pa. Super. 578; 180 Pa. 47); *Lombardo* (Tex. 1934)
   sustaining zoning; Long Beach one-housekeeping-unit ordinances (279 N.Y.
   167 (1938)); modern enforcement (18 Misc. 3d 381 (2007); 47 Misc. 3d 723
   (2014)). Note the shape: a tradition of *licensing and districting* —
   regulation, not prohibition — which is itself the §2.3 rebuttal frame.

---

## 4. Ontology / lexicon discoveries (flywheel input)

New period terms observed by workers (top): **"one housekeeping unit"**
(zoning term of art, Long Beach line), **"tourist camp / court / cabin /
lodge / house"**, **"light housekeeping"**, **"table boarders"**, **"hotel
garni"**, **"emigrant boarding house"**, **"residence clubs"**, **"family
hotel"**, **"trailer court" / "auto camps" / "motel"**, **"family care"**.

### Proposed selectors for cycle 002 (Planner + human to author)
- `housekeeping-unit-31`: "one housekeeping unit" / "single housekeeping
  unit" — the zoning-era hinge phrase (1930-1970 focus).
- `tourist-expansion`: bump tourist-home-15 with "tourist camp", "tourist
  court", "tourist cabin", "tourist lodge", "auto camp", "motel" (1930-1970,
  1970-2020).
- `boarding-variants`: "table boarders", "emigrant boarding house",
  "furnished room house".
- Postmortem-driven: use-zoning vocabulary for the *Spann*/*Lombardo* line
  (brief-tier misses).

---

## 5. Duplicates reconciled
Oliver v. Moore (3 parallel reports), Cromwell v. Stephens (2), 164 A.D.
577 = 150 N.Y.S. 94, and the La. App. stair-collapse pair — merged in the
ledger counts above; all quotes retained under the official-reporter entry.

## 6. Gold-set miss postmortems (headline tier)
10 brief-letting misses remain. Pattern: Texas constitutional/zoning
authority (*Spann*, *Lombardo*, *City of West University Place*) whose
letting relevance lives in the briefs' framing, not lodger vocabulary —
selector fix proposed above; 2 misses are pre-S.W. Texas Reports cases where
embedding signals fell below top-k in dense partitions (raise `top_k` for
Tex. pre-1900, or add an era-scoped FTS variant).

## 7. Human-review queue
1. 28 verified-fuzzy quotes (OCR tolerance) — eyeball against scans.
2. 35 cross-model disagreements (4 batches) — adjudicate; polarity-heavy.
3. 20 records with quote-gate-nulled polarity — re-map or discard.
4. 12 householder-×-nights favorable cases — priority citator + read.
5. `data/gold/needs-human.md` — Ladd briefs, RECAP token, PACER list.

## 8. Citator gate
Every case referenced above: `[ ] citator-checked` — MANDATORY before any
use in work product. None checked as of this report.

## 9. Sprint-one acceptance (§13) status
- [x] CAP data ingested (4 states, era partitions, page maps, versioned norm)
- [x] FTS (stemmed+raw) + pinned-model embeddings (97b0c614be4d)
- [x] gold.jsonl ≥40 resolved (92) + needs-human.md
- [x] selectors.yaml v1 ≥25 active (30) — human-reviewed & approved
- [x] shard.py deterministic; provenance; coverage matrix; no-op re-runs
- [x] Capped Map run (40 batches; every case accounted)
- [x] verify_quotes.py gating Reduce; zero unverified quotes downstream
- [x] cycle-001.md (this report)
- [x] Reproducible from README on a clean machine
