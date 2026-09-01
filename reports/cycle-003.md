# Cycle 003 — Findings Report

**Run:** cycle-003-shard-01 (selectors v3) · **Date:** 2026-08-31/09-01
**Reducer:** Fable (this session), consuming verified extraction JSON only.

> ⚠️ **Nothing in this report is work-product ready.** Citator gate applies
> to every case. Quotes are verbatim-verified; characterizations await the
> human review queue (§7).

---

## 1. Metrics

### Retrieval (recall gate vs. post-hygiene baseline) — PASSED, decisively
| Tier | baseline | cycle 003 |
|---|---|---|
| **brief-letting (HEADLINE)** | 3/9 = 33.3% | **6/9 = 66.7%** |
| brief-all | 14/63 = 22.2% | 17/63 = 27.0% |
| treatise | 21/29 = 72.4% | **22/29 = 75.9%** |

*Gouhenant* and both *Holmes/Coalson* cases recovered — by `rent-houses-37`
(one period phrase from the miss postmortem) and the embedding depth bump.
Remaining misses: *Smith v. Decker*, *Latimer v. Hess* (no letting
vocabulary in the opinions; brief cites them for doctrine), *Ruhl*.

Selectors v3 (36 active): **5,761 new signals**; 630 batches of unread
cases after excluding 3,397 already mapped.

### Extraction & verification
150 batches approved; **150 mapped** — one batch failed JSON parsing on
three attempts and was mapped as two 9-case halves. **2,673 cases read →
~177 relevant (6.6%)** — precision falling as expected deeper into the
candidate pool (28% → 12% → 6.6% across cycles).
Quote gate: **443 exact, 37 fuzzy, 2 dropped; 0 invalid.**
Credits interruption mid-run; resumed from cache with no loss.

### Cross-model agreement
15 batches Codex-checked: **100 field disagreements** (~14%). Third-reader
recommendations generated.

---

## 2. The Ledger (cycle 003 additions, pre-adjudication)
175 relevant: **77 favorable / 35 adverse / 16 mixed / 47 polarity-nulled
(re-map queue)**. Jurisdiction: N.Y. 117, La. 26, Tex. 20, Pa. 12.

### Level-of-generality table (favorable, cycle 003 only)
| who \ duration | nights | weeks | months | unclear | Σ |
|---|---|---|---|---|---|
| **householder** | 0 | 5 | 12 | 12 | **29** |
| commercial operator | 2 | 4 | 12 | 21 | 39 |

---

## 3. Doctrinal lines — what cycle 003 added

1. **The Texas homestead-letting line (rent-houses-37 delivering).** 74 Tex.
   155 (1889) and 45 Tex. Civ. App. 159 (1907): "two rent houses built and
   let by a brother and sister on part of their family homestead did not
   work an abandonment of the homestead" — courts treating letting as
   compatible with, not destructive of, residential character. A favorable
   line the lexicon could not see until "rent houses" entered it.
2. **The gold case itself.** 55 N.Y. St. Rep. 145 (1893) — the duplicate
   report of 79 N.Y. Sup. Ct. 474: householder let her house "for a short
   two-week period." Now in the ledger with verified quotes.
3. **Householder letting under ordinary landlord-tenant law.** 68 Pa.
   Super. 593 (1918): "a householder who lets two rooms of his dwelling to
   tenants is treated under ordinary landlord-tenant law" — the practice as
   unremarkable. *In re Veeder*, 31 Misc. 569 (1900): a householder who
   occasionally lets rooms by the week keeps dwelling-owner status. 125
   Misc. 649 (1925): room-with-board let weekly. 217 La. 392 (1950):
   "sleeping rooms with kitchen privileges" under OPA registration.
4. **Camps again.** 140 La. 982 (1917): a lake-front "camp" rented to a
   club for several months — the Louisiana recreational-letting economy
   (cf. *Cristadoro*, 1907).
5. **Married-women's line continues.** 119 A.D. 663 (1907); 228 S.W. 989
   (Tex. 1921): an unmarried daughter's rooming house as separate property;
   8 La. App. 794 (1928): boarding-house earnings in community.
6. **Lessor-liability line (older, both ways).** 5 Tex. 11 (1849): merely
   renting a room is not "keeping" a gaming house; 5 Tex. Ct. App. 89
   (1878): leasing with knowledge of intended prostitution not "keeping a
   disorderly house"; 54 Tex. 388 (1881): ordinance criminalizing letting
   to prostitutes regardless of use struck — early Texas limits on
   regulating letting *by the character of the tenant*.
7. **Adverse / regulatory strata.** The 1920 emergency rent laws sustained
   as police power (194 A.D. 482); the Multiple Dwelling Law SRO enforcement
   line (1947–2017), pulled in by `sro-35` — dense, low letting value.
   Note **74 N.Y.2d 92 (1989)** (*Seawall Associates*): Local Law 9's SRO
   anti-conversion/compelled-rental scheme struck as a taking — the
   inverse right (government *compelling* letting) and a major New York
   property-rights precedent worth a human read regardless of polarity.

---

## 4. Lexicon / selector assessment

- `rent-houses-37`: high value, low volume — keep.
- `sro-35`: flooded the modern regulatory stratum (N.Y. 1980s–2017 SRO
  litigation); adverse-file value only. **Propose retiring or scoping to
  1930–1970** for cycle 004.
- `apartment-hotel-34`: moderate — hotel/tenant classification cases
  (mixed polarity). Keep one more cycle, review yield.
- `motel-near-36`: low yield this cycle; keep (cheap).
- Observed terms: "tenement affair", "double dwelling", "sleeping rooms with
  kitchen privileges", "special residence facility license".

### Strategic note for cycle 004
Precision has fallen 28% → 12% → 6.6% over three cycles with the same
four-state corpus: the lexicon's net is approaching its floor on this
corpus. Cycle 004 should shift effort per spec §12 — CourtListener sync
(post-2020 + citation-graph expansion selectors, which find cases by *who
cites whom* rather than vocabulary) and/or English Reports ingestion —
rather than a fourth deep read of the same pool. Remaining budget-worthy
work on the current corpus: the ~480 unread batches are low-density;
consider a signal-density floor (≥2 distinct selectors) before mapping.

---

## 5. Duplicates reconciled
55 N.Y. St. Rep. 145 = 79 N.Y. Sup. Ct. 474 (gold); 3 Liquor Tax Rep. 433
= 45 Misc. 97 (hotel/police); 129 A.D. 290 = 113 N.Y.S. 357 (rear rooms).

## 6. Gold-set miss postmortems
Three misses remain (§1). *Smith v. Decker* and *Latimer*: recommend
doctrine re-tag (no letting vocabulary; cited for characterization
doctrine). *Ruhl*: 36k-char commercial dispute with a two-room cottage
rental buried inside; only a citation-graph or a case-specific embedding of
its facts would find it — accept as a known miss.

## 7. Human-review queue (page: reports/review-queue-cycle-003.html)
- A: householder × nights — 0.
- B: 37 fuzzy quotes (26 mechanical-trivial; double-confirmed ones
  auto-accepted per policy).
- C: 100 disagreements with third-reader recommendations.
- D: 45 nulled → re-mapped; contested fields with recommendations.

## 8. Citator
`[ ] citator-checked` on every case. Pre-screen tooling available.
