# Gold-case codebook review — 2026-09-29

## Scope and rule

I reviewed the 36 distinct, resolved `brief-letting` and `treatise` cases after the deduplication used by `corpus_engine/evaluation/gold.py`. The source is each case's `raw_text` in `data/db/corpus.db`; the gold file is `data/gold/gold.jsonl` (SHA-256 `3a4011ee7409eccd4973cfcae971f8a97ab8d894029ac4331f6039eea9ddc9ee`). I compared the opinion's question, pertinent facts, and disposition with `domains/str-right-to-let/codebooks/mapper-v3.md` and the more explicit relevance examples in `reports/review-audit-brief.md`.

The relevance rule requires an opinion to bear on paid occupancy of another's dwelling or rooms, its legal character, or its regulation. A citation about another subject does not qualify merely because it uses *rent*, *lease*, *board*, *hotel*, or *zoning*. These are relevance recommendations, not human adjudications or edits to the gold file or ledger. The corpus text has not been checked against page images. The 2026-09-12 evaluation is the comparison baseline, not a newly generated evaluation of the current ledger.

**Result:** 12 clear in-scope cases, 2 boundary cases to adjudicate, and 22 out-of-scope cases. Of the 12 clear cases, 10 were already marked relevant by the cycle 004 evaluation. One was unsignaled (*Cummins*); one was read but marked irrelevant (*Shearman*). If both boundary cases are included, *Ruhl* and *Fox Meadow* add two more unsignaled cases. The other five unsignaled gold cases appear out of scope under the codebook.

## Brief-derived cases (9)

| Case ID | Gold citation and case | Review | Basis in opinion |
|---:|---|---|---|
| 2273220 | 12 S.W.2d 543, *Brown v. Johnson* | Out | Whether a cropper was an agricultural tenant for a crop lien; the land was cultivated for cotton, not occupied as a dwelling. |
| 2255813 | 312 S.W.2d 632, *Smith v. Decker* | Out | Bail-bond statute and bail-bond business; no dwelling letting. |
| 2257077 | 322 S.W.2d 516, *Southampton Civic Club v. Couch* | **Clear in** | Homeowners rented spare rooms to student lodgers; the court held that the covenant did not prohibit it (corpus page map: 159 Tex. 468). |
| 8251008 | 178 S.W. 628, *Holmes v. Coalson* | Out; historical context only | The 32 three-room rental houses and weekly prices were the subject of a representation in a land-exchange fraud/venue dispute. The court did not decide the legality or character of the occupants' tenancies. |
| 2284727 | 240 S.W. 896, *Coalson v. Holmes* | Out; historical context only | Same 32-house transaction; this appeal resolves venue and fraud pleading/proof, not a question about paid dwelling occupancy. |
| 10223945 | 183 S.W.2d 996, *Latimer v. Hess* | Out | Express easement in an alley and constructive notice under recorded deeds. |
| 2204609 | 65 Tex. 723, *Ruhl v. Kauffman & Runge* | **Boundary: include as contextual letting evidence** | The court held that renting particular rooms in the family's cottage did not defeat the property's homestead status (corpus page map: 65 Tex. 735). The rental is expressly weighed in the holding, but the case does not decide a tenant's rights or a rental restriction. |
| 11293268 | 134 S.W. 373, *Stark v. Coe* | Out | A leased railroad right-of-way used for a corn-shelling plant that injured nearby homes; it is not a lease of the homes. |
| 2121245 | 20 Tex. 96, *Gouhenant v. Cockrell* | Out | Homestead abandonment; the owner's temporary boarding and rented room elsewhere are evidence of residence, not the legal subject of the decision. |

## Treatise-derived cases (27)

| Case ID | Gold citation and case | Review | Basis in opinion |
|---:|---|---|---|
| 2032745 | 5 Cow. 253, *Trovinger v. M'Burney* | Out | Promise to pay for a daughter's and children's board and care; no paid right to occupy rooms is examined. |
| 1818197 | 17 Serg. & Rawle 138, *Brown v. Sims* | Out | Distress of tobacco stored in a merchant's warehouse. |
| 8877300 | 5 Whart. 9, *Riddle v. Welden* | **Clear in** | Whether a boarder's goods in occupied rooms could be distrained for the boarding-house keeper's rent. |
| 674442 | 1 Hill & Den. 565, *Matthews v. Stone* | **Clear in** | Whether the statutory protection for a boarder's goods covered furniture used by the boarding-house tenant. |
| 484038 | 1 Denio 602, *Wilson v. Martin* | **Clear in** | Agreement for rooms and board in a boarding house; court distinguished that arrangement from a lease and decided payment consequences. |
| 1283545 | 2 E.D. Smith 148, *Willard v. Reinhardt* | **Clear in** | Court decided whether temporary accommodations for emigrants made the operator an innkeeper rather than merely a boarding-house keeper, affecting baggage liability. |
| 1326234 | 3 Duer 464, *Howard v. Doolittle* | Out | Long lease of a hotel building to its operators and allocation of structural repair cost; no paid occupancy by guests is in issue. |
| 2121343 | 20 Tex. 798, *Howth v. Franklin* | **Clear in** | Court distinguished occasional paid accommodation of travelers by farmers from holding out a house as an inn; that classification determined liability. |
| 1393244 | 7 Rob. 561, *Ambler v. Skinner* | **Clear in** | Occupant claimed boarder status in a leased dwelling; court considered whether a boarder could use the rooms for a dental business or was claiming a different tenancy right. |
| 4809400 | 1 Lans. 484, *Cady v. McDowell* | **Clear in** | Private householder took a family to board for compensation; court decided whether he was a statutory boarding-house keeper with a lien. |
| 434759 | 72 Pa. 285, *Bussman v. Ganster* | Out | Lease of land and a store-house, followed by fire and a commercial rent dispute. |
| 1031220 | 71 Pa. 429, *Moore v. Weber* | Out | Repair duties for a building used to make and sell hats. |
| 510888 | 52 N.Y. 512, *Witty v. Matthews* | Out | Fire, repairs, and a lease of the City Assembly Rooms; no dwelling occupancy. |
| 1603751 | 10 Daly (N.Y.) 493, *Cummins v. Hanson* | **Clear in — retrieval miss** | A seven-month contract for rooms *with board* at a weekly price; court fixed damages when the occupant left after two weeks (corpus page map: 10 Daly 494). The evaluation calls this case unsignaled. |
| 1604856 | 11 Daly (N.Y.) 234, *Korn v. Schedler* | Out | Loss of property while dining at a restaurant; innkeeper status is inferred from a liquor license, but no paid lodging is at issue. The human withdrawal in the evaluation is consistent with this reading. |
| 2211876 | 107 N.Y. 610, *Smith v. Rector of St. Philip's Church* | **Clear in** | Owner of an apartment building let units by the month; court held the superior lessor's knowing acceptance of rent prevented forfeiture for that use. |
| 3515356 | 6 N.Y.S. 413, *Oliver v. Moore* | **Clear in** | Householder let rooms with board for a fixed term; court decided that the agreement was a lease and addressed rent after the occupant died. |
| 2293673 | 155 N.Y. 120, *Reynolds v. Van Beuren* | Out | Roof signboard advertising license and injury from a falling sign. The lease/license vocabulary concerns roof access, not dwellings. |
| 357438 | 28 Misc. 184, *O. J. Gude Co. v. Farley* | Out | Advertising sign on a tenement's roof; the possible sublease concerned the roof, not living quarters. |
| 1819919 | 42 Misc. 217, *Shearman v. Iroquois Hotel & Apartment Co.* | **Clear in — reader false negative to review** | Court held that a year-long unfurnished apartment lease created a tenant, not a lodger, so the operator had no lodging-house lien on the furniture (corpus page map: 42 Misc. 221). The evaluation says the reader marked it irrelevant without human reversal. |
| 2301769 | 169 N.Y. 377, *Presby v. Benjamin* | Out; characterization context only | Court distinguished an absent tenant's caretaker/servant from a possible subtenant. It did not establish compensated occupancy by the caretaker; a jury still had to decide what arrangement existed. |
| 5020472 | 233 A.D. 250, *Fox Meadow Estates v. Culley* | **Boundary: include if apartment-development restrictions are in scope** | Developer was denied permission to construct two apartment houses in a single-family zone; the court upheld the zoning decision (corpus page map: 233 A.D. 251). This regulates prospective apartment-house use, but not room letting, lodging, or an existing paid occupancy. |
| 671350 | 89 Pa. Super. 543, *Junge's Appeal* | Out | Zoning variance concerning foundation/porch placement and yard setbacks, not letting. |
| 1280319 | 154 La. 271, *State ex rel. Civello v. New Orleans* | Out | Zoning permit for a grocery store. |
| 1264867 | 161 La. 1103, *State ex rel. Palma v. New Orleans* | Out | Zoning permit for a meat market. |
| 1262356 | 162 La. 202, *Roberts v. New Orleans* | Out | Zoning permit for a motion-picture theater; boarding houses and hotels appear only as comparator uses. |
| 1253769 | 166 La. 776, *Sampere v. New Orleans* | Out | Business-use zoning and building setbacks; no letting of living quarters. |

## Consequences for the benchmark

- The **10/36 recovery** figure mixes two clear, unrecognized in-scope cases with 22 cases outside the current relevance rule and two scope boundaries. It is not an estimate of either corpus recall or embedding quality.
- The clear failures needing separate attention are *Cummins* (candidate retrieval) and *Shearman* (reader judgment). *Ruhl* and *Fox Meadow* depend on a documented scope choice before they can be counted as misses.
- Several off-scope cases are also named as anchors in `ontology/ontology.yaml`: *Howard* (hotel repairs), *Witty* (assembly rooms), *Reynolds* (roof sign), and *Civello* (grocery zoning). Their anchor status should not override the current codebook; it explains why the gold benchmark and retrieval hypotheses may have drifted from the intended construct.
- A revised benchmark should preserve the original gold file and record case-level inclusion/exclusion decisions with reasons and reviewer identity, as ADR-0003 requires. A genuinely held-out retrieval set and a blind sample of unretrieved cases remain separate validation tasks.
