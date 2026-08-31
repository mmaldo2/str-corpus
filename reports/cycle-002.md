# Cycle 002 — Findings Report

**Run:** cycle-002-shard-01 (selectors v2) · **Date:** 2026-08-31
**Reducer:** Fable (this session), consuming verified extraction JSON only.

> ⚠️ **Nothing in this report is work-product ready.** Citator gate
> (`[ ] citator-checked`) applies to every case. Quotes are verbatim-verified;
> characterizations await the human review queue (§7).

---

## 1. Metrics

### Retrieval (recall gate vs. cycle-001 baseline) — PASSED
| Tier | cycle 001 | cycle 002 |
|---|---|---|
| brief-letting (HEADLINE) | 5/15 = 33.3% | 5/15 = 33.3% (held) |
| brief-all | 13/63 = 20.6% | **14/63 = 22.2%** (+1: use-zoning line, selector zoning-power-residence-33) |
| treatise | 21/29 = 72.4% | 21/29 = 72.4% (held) |

Selectors v2 (33 active): 3 new + 2 version bumps produced **3,836 new
signals**; 653 batches of unread cases emitted after excluding the 714
already mapped (new `--exclude-mapped` plumbing: each cycle pays only for
unread material).

### Extraction & verification
150 batches approved; **150 mapped** (one batch needed a third attempt after
two JSON-parse failures). **2,683 cases read → 328 relevant (12.2%)** —
lower precision than cycle 001's 28%, as expected: gold-first ordering meant
cycle 001 consumed the densest candidates.
Quote gate: **908 exact, 51 fuzzy, 2 dropped; 0 invalid records.**

### Cross-model agreement
15 batches (270 cases) Codex-checked, records now saved: **119 field
disagreements** (~15% of comparisons — consistent with cycle 001). Third-reader
recommendations generated for all (§7).

### Cost
18.2M input / 2.85M output tokens across 149 Sonnet batches ≈ **6.8k in /
1.1k out per case** (consistent with cycle 001; output tokens per case fell
as the share of `relevant: false` records rose).

---

## 2. The Ledger (cycle 002 additions, pre-adjudication)

328 relevant: **159 favorable / 70 adverse / 47 mixed / 52 polarity-nulled
(re-map queue)**. Jurisdiction: N.Y. ~195, Pa. 58, La. 45, Tex. ~30. Era:
heaviest 1875–1925 (the lodging economy).

### Level-of-generality table (favorable, cycle 002 only)
| who \ duration | nights | weeks | months | unclear | Σ |
|---|---|---|---|---|---|
| **householder** | 1 | **11** | 17 | 29 | **58** |
| commercial operator | 12 | 8 | 28 | 46 | 94 |

**Cumulative (cycles 1+2, pre-adjudication of cycle 2): ~107 favorable
householder cases.** Cycle 002's householder finds skew to *weeks*-scale
letting — the 1890s–1910s "rooms by the week" cases — filling the middle of
the duration axis.

---

## 3. Doctrinal lines — what cycle 002 added

1. **The licensing question, answered by 1842.** 3 Hill & Den. 150 (N.Y.
   1842): keeping an inn or tavern at common law "is a lawful trade open to
   any citizen without a license; only the added privilege of selling
   spirituous liquors" required one. Direct historical authority that
   compensated lodging was a common right, with licensing attaching to
   liquor, not lodging. Pairs with the adverse 1811 New Orleans cabildo
   licensing case (1 Mart. (o.s.) 241) — the civil-law contrast.
2. **Whole-house weekly letting, 1893.** 79 N.Y. Sup. Ct. 474: a householder
   let her house "for a week or two at an agreed price," having declined a
   longer monthly term — a nineteenth-century vacation rental, enforced as an
   ordinary contract. Same era: 65 N.Y.S. 517 and 2 Liquor Tax Rep. 320
   (1900) — a homeowner letting rooms *by the week* does not lose the
   dwelling's private character; *Quigley v. Southwick* (1912) — a
   householder renting rooms weekly while living there is not an innkeeper.
3. **"Lawful and ordinary purpose."** 26 N.Y. Super. Ct. 327 (1865): letting
   furnished rooms to gentlemen for pay was the tenant's "assumed lawful and
   ordinary purpose in hiring the house." The characterization the
   level-of-generality argument wants, in the court's own words.
4. **The married-women's line (1854–1895).** A dense cluster of coverture
   cases (42 Barb. 310; 1 Monag. 305; 160 Pa. 60; 47 La. Ann. 768) in which
   courts protect a wife's boarding-house earnings as her separate estate —
   treating householder letting as a recognized livelihood worth legal
   protection. Unexpected, and useful: it shows the practice was
   *economically ordinary* enough to drive property-law reform.
5. **The tourist-camp line (1928–1957) — opened by tourist-home-15 v2.**
   1 S.W.2d 751 (Tex. 1928): an automobile tourist camp is not a nuisance
   per se; "a landowner has the right to use his property for such a lawful
   business." Then the zoning contest: 189 La. 521 (1938) enjoining a
   twelve-cabin camp under a residential covenant; 231 S.W.2d 471 (Tex.
   1950) rezoning for cabins; 43 Pa. D. & C. 301 (1941) tourist house vs.
   "private dwelling" covenant; 1950s motel-as-tourist-camp zoning cases.
   36 worker observations of "tourist camp" — the single richest new
   vocabulary vein. This is the exact structural analogue of the STR fight,
   one technology earlier.
6. **State due process against zoning definitions.** 152 Misc. 2d 997 →
   81 N.Y.2d 741 (1992): Mount Vernon's zoning definition of "boarding house"
   (any non-hotel building lodging four or more for hire) held facially
   unconstitutional under the state due process clause — a *Ladd*-style
   state-constitutional win on lodging regulation. High-value for the
   venue matrix.
7. **Modern covenant cases both ways.** 302 A.D.2d 497 (2003): a covenant
   barring "business" use incl. paying guests does not bar a homeowner's
   letting; 8 A.D.3d 812 (2004): 1966 R-1 ordinance permitted short-term
   rental; 148 A.D.3d 1306 (2017): HOA rules restricting short-term leasing.
   Adverse: 150 A.D.3d 562 (2017) (rent-stabilized Airbnb, 93 guests);
   246 So. 3d 754 (La. 2018); 726 So. 2d 435 (La. 1999, B&B permit denied).
8. **Adverse file growth.** Rent-control and multiple-dwelling enforcement
   (N.Y. 1946–1963) — a dense regulatory stratum; group-home/personal-care
   boarding-home exclusions (Pa. Commw. 1983–88); 210 A.D. 217 (1924): weekly
   roomer sublets are "business" use.

---

## 4. Ontology / lexicon discoveries

Top worker observations: **"tourist camp" (36)**, "tourist court",
"personal care boarding home", "apartment hotel", "family hotel",
"single room occupancy (SRO)", "three-quarter house", **"french flat"**,
"vacation rental", **"boarding tents"**, "motor courts", "residential hotel",
"rent pool".

### Proposed selectors for cycle 003
- `apartment-hotel-34`: "apartment hotel" OR "family hotel" OR "residential
  hotel" (1880–1970) — the extended-stay hotel line (Hancock v. Rand's
  descendants).
- `sro-35`: "single room occupancy" OR "rooming unit" (1930–2020) —
  modern regulatory stratum, adverse-candidate.
- `motel-near-36`: NEAR("motel" "residential district", 30) — the motel
  precision problem solved with proximity.
- Retire `sojourner-19` (near-zero yield, proper-name noise).

---

## 5. Duplicates reconciled
Quigley v. Southwick (2 reports); People v. Shkilky (2); Oliver-style
surrogate duplicates (60 Misc. 631 / 6 Mills Surr. 577); Higgins v. Hallock
line (3 reports); boarding-house lien chattel-mortgage trio (1889).

## 6. Gold-set miss postmortems
Headline tier unchanged at 5/15: the remaining 10 misses are
constitutional-doctrine citations (retroactivity, assembly) that lie
outside the letting schema by design — recommend re-tagging them
`domain: doctrine` in a gold-set hygiene pass rather than chasing them with
selectors that would degrade precision.

## 7. Human-review queue (page: reports/review-queue-cycle-002.html)
- A: householder × nights favorable — 1 case.
- B: 51 fuzzy quotes (32 machine-classified trivial OCR, 19 for judgment).
- C: 119 cross-model disagreements, each with third-reader recommendation.
- D: 48 polarity-nulled records → 44 re-mapped and re-verified (96 quotes,
  0 invalid; 4 records not returned by the re-map worker, carried to cycle
  003). Codex check contested 55 fields across 30 cases; 14 fully-agreed
  cases auto-accepted; contested fields listed with third-reader
  recommendations (48 of 55 — 7 unadjudicated, human decides directly).

## 8. Deferred
- Gold-set hygiene pass (domain re-tagging) before cycle 003 recall gate.
- Selector retirement/additions per §4 (Planner + human review).

## 9. Citator gate
`[ ] citator-checked` on every case. Pre-screen tooling
(`citator_prescreen.py`) available; run over cycle-002 priority cases after
adjudication (budget: 125 CL requests/day).

---

## Amendment — human adjudication complete (2026-08-31)

All 226 decisions applied (data/adjudications/cycle-002.json; ledger at
data/ledger/cycle-002.jsonl, 342 relevant cases: 185 favorable / 80 adverse
/ 65 mixed). 107 of 119 disagreement recommendations accepted (12 overridden
to reader A); 44 fuzzy quotes confirmed scan noise, 7 mismatch quotes
removed; 45 of 55 remap recommendations accepted.

**Cumulative record (cycles 1+2): 547 relevant cases, 1799-2019 —
306 favorable / 128 adverse / 99 mixed; 116 favorable householder cases
(12 nights / 15 weeks / 37 months).**
