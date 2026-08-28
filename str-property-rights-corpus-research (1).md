# Short-Term Rentals and the Right to Let: Legal Landscape, Source Compendium, and a Corpus Research Pipeline

**Prepared August 2026**

---

## 1. Executive Summary

Cities across the country are banning or severely restricting short-term rentals (STRs). These laws implicate a core stick in the property-rights bundle: the owner's right to temporarily alienate possession of their property for payment. This document does three things:

1. **Maps the current litigation landscape**, showing where constitutional challenges are winning and losing, with recent case examples through mid-2026.
2. **Compiles the sources and databases** needed to build the historical record of the right to let — the evidentiary foundation the winning theories demand.
3. **Explains a corpus research pipeline** — a computational method for systematically recovering historical case law that conventional legal search cannot find — and shows how the same infrastructure generalizes to future projects.

The central strategic insight: the constitutional tests that are actually winning STR cases (state retroactivity clauses, state due-process/"due course of law" clauses, and any future federal fundamental-rights claim under *Washington v. Glucksberg*'s "deeply rooted in history and tradition" standard) are **historical evidence tests**. They are won or lost on the depth and specificity of the historical record a litigant can assemble. That record exists — centuries of lodger, boarding-house, and short-letting law — but it is written in vocabulary no modern search query reaches. Recovering it is a language problem before it is a legal problem, which is exactly what corpus methods solve.

---

## 2. The Legal Landscape

### 2.1 The federal wall: takings and due process claims are losing

Federal challenges to STR restrictions have mostly failed, and the failures share a structure.

**Takings.** In *Nekrilov v. City of Jersey City*, the Third Circuit rejected takings, Contract Clause, and due process challenges to Jersey City's STR rollback, even though the plaintiffs had invested in reliance on an earlier ordinance that legalized short-term rentals.[^1] Applying the *Penn Central* regulatory-takings framework, the court reasoned that lost STR profitability is not a drastic diminution in property value where the properties retain other economically beneficial uses (including long-term rental at market rates), and it held that a municipal act legalizing a business activity does not vest the operator with a cognizable property right in the business's continuation.[^2]

The Fifth Circuit reached the same result on takings in *Hignell-Stark v. City of New Orleans*, holding that STR operators had no property interest in the renewal of their licenses.[^3] And in June 2026, in *Marfil v. City of New Braunfels*, the Fifth Circuit affirmed summary judgment for the city on due process and equal protection challenges to a residential-district STR ban, holding that Texas law recognizes no protected property interest in short-term leasing where the ordinance predated the owners' purchases, and that neighborhood-character rationales survive rational-basis review.[^4]

The pattern repeats in the district courts. A federal magistrate judge recommending dismissal of a challenge to Lafayette, Louisiana's STR ban wrote that the ordinance is a reasonable land-use restriction and that there is "no fundamental right to lease one's property for less than 30 days."[^5]

**The exception that proves the framework.** *Blakelick Properties, LLC v. Village of Glen Ellyn* (2025) shows the narrow path a federal-style takings claim can still travel: an owner bought in an unincorporated area with no STR restrictions, built a successful rental, and was then annexed and banned. The court found the *Penn Central* claim likely to succeed — the investment-backed-expectations prong had real content because the restriction postdated the investment.[^6] Timing and reliance, not the abstract right, did the work.

**Why the losses matter for research design.** Every one of these losses turns on a characterization question: *what right is at stake, described at what level of generality?* The Lafayette formulation — no fundamental right to lease for under 30 days — frames the right as narrow, commercial, and novel. That framing is an implicit historical claim: that short-duration letting is a recent invention with no pedigree. It is precisely the claim a deep historical record rebuts.

### 2.2 Where challenges are winning: state constitutions and structural federal claims

**Retroactivity — the Texas model.** In *Zaatari v. City of Austin* (Tex. App.—Austin 2019), the court struck Austin's ban on non-homestead STRs as unconstitutionally retroactive under Article I, Section 16 of the Texas Constitution.[^7] The reasoning is the template for the historical argument: the court described the ability to lease one's property as a fundamental privilege of property ownership — a settled, well-recognized right — and held that terminating existing STR operations upset settled expectations rooted in that right without a compelling justification.[^8] The court also struck the ordinance's assembly restrictions under strict scrutiny as infringing the Texas Constitution's assembly guarantee.[^7]

The Texas fight continues: Dallas's STR ban was enjoined by a district court, and by fall 2025 the city was petitioning the Texas Supreme Court to lift the injunction.[^9] Meanwhile, Texas intermediate courts are actively contesting the vested-rights question — the *Marfil* panel discussed *City of Dickinson v. Crystal Cruise Investments, LLC* (Tex. App. 2026), which reversed an injunction against an STR ordinance on the ground that a constitutionally protected right must be vested, not a mere expectancy.[^4] The intra-Texas tension between *Zaatari* and the *Dickinson* line is itself a research target.

**State due process / occupational liberty — the Pennsylvania model.** In *Ladd v. Real Estate Commission* (Pa. 2020), the Pennsylvania Supreme Court revived a challenge by a short-term vacation rental manager who was told she needed a full real-estate broker's license to continue her business. The court applied Pennsylvania's heightened rational-basis standard (from *Gambone*), which asks whether the law bears a "real and substantial" relationship to its purpose — a test with actual teeth, grounded in Article I, Section 1 of the Pennsylvania Constitution's protection of the rights of acquiring, possessing, and protecting property and pursuing one's own happiness.[^10] *Ladd* proceeded to trial in late 2025.[^11] Pennsylvania, Texas, and a handful of other states with meaningful state-constitutional review of economic regulation form the viable venue set for a fundamental-rights theory today.

**Structural federal claims.** Where federal claims have won, they are structural rather than rights-based. *Hignell-Stark I* held New Orleans's owner-residency requirement violated the dormant Commerce Clause because it discriminated against out-of-state operators and the city had nondiscriminatory alternatives.[^3] In October 2025, *Hignell-Stark II* held that restricting STR licenses to natural persons (excluding LLCs and corporations) failed even rational-basis review under the Equal Protection Clause, while permitting an operator-presence rule as construed narrowly.[^12] And in August 2026, the Fifth Circuit decided *Bodin v. City of New Orleans*, addressing challenges — including takings and Section 230 claims — to the city's one-STR-per-block lottery system and its platform-verification mandate.[^13] The New Orleans litigation saga (2019–present) is the richest single docket for harvesting briefing, and its takings claims continue to evolve to distinguish *Hignell-Stark I*.[^14]

**The legislative front.** State preemption is running in parallel: in 2026, Idaho and Indiana limited local governments' power to restrict STR numbers or operations, while preemption bills failed or remain pending in Colorado, Washington, and elsewhere.[^15] Litigation strategy and legislative strategy draw on the same historical record — a legislature deciding whether leasing is a protected incident of ownership is an audience for this research too.

### 2.3 The fundamental-rights claim and the level-of-generality battle

A substantive due process claim — federal or state — turns on *Glucksberg*'s requirement that the asserted right be carefully described and deeply rooted in history and tradition. *Dobbs* reconfirmed this as the governing methodology, and *Bruen* normalized courts weighing detailed historical record evidence. The claim is therefore decided at the framing stage:

- **The city's description:** "a right to operate an unlicensed hotel business in a residential zone." Novel, commercial, no tradition. This is the *Marfil*/Lafayette framing, and it wins for the government.
- **The property owner's description:** "a householder's right to let rooms or a dwelling for short periods for compensation." Under this description, the tradition is ancient, continuous, and specific: the common law's lodger and boarder categories, the license/lease distinction, colonial and nineteenth-century boarding-house practice, and courts treating the letting of one's property — for any duration — as an ordinary incident of ownership. *Moore v. City of East Cleveland* (zoning ordinance struck on history-and-tradition grounds protecting the household) is the federal anchor; *Belle Terre v. Boraas* is the adverse bookend.

Winning the framing battle requires evidence at the *specific* level: not "property rights are old," but "ordinary householders lawfully let rooms and dwellings for days and weeks, for pay, continuously across American history, and courts treated this as an incident of ownership." No one has assembled that record systematically. The reason is vocabulary.

**One honest caveat.** The same record that proves the tradition of letting also proves a tradition of *regulating* it — innkeeper law, lodging-house licensing. This is manageable (*Glucksberg* asks whether the practice was lawful, not unregulated, and a tradition of licensing is affirmative evidence against a power of prohibition), but the distinction must be drawn explicitly in briefing before opposing counsel draws it first. The pipeline below is designed to build the adverse-authority file alongside the favorable one.

---

## 3. The Vocabulary Problem

Nobody before roughly 2010 said "short-term rental." The historical record of this practice speaks in terms that have vanished from legal usage:

| Era | Characteristic vocabulary |
|---|---|
| English common law / colonial | *demise*, *to let*, *letting of lodgings*, *lodger*, *sojourner*, *tenancy at will*, *inmate*, *victualler* |
| 19th century | *boarding house*, *lodging house*, *furnished rooms/apartments*, *taking in boarders*, *roomers*, *transient guests* |
| Early zoning era (1920s–1970s) | *tourist home*, *guest house*, *paying guests*, *roomers and boarders*, *transient occupancy* |
| Doctrinal terms of art | *lodger vs. tenant*, *license vs. lease*, *exclusive possession*, *incident of ownership* |

A Westlaw query built from modern vocabulary returns nothing from these eras and produces the false impression that the record is thin — which is how "no fundamental right to lease for less than 30 days" gets written without any engagement with two centuries of lodger law. The most valuable stratum may be the early-zoning-era cases: courts after *Euclid* repeatedly confronted whether taking in paying guests was compatible with residential zoning — the closest structural analogue to today's STR fights — and that body of law is invisible to modern search precisely because of term drift.

Recovering the record therefore requires (a) systematically reconstructing the historical lexicon, and (b) searching complete historical case corpora with that lexicon rather than with modern terms. That is the pipeline in Section 5.

---

## 4. Source and Database Compendium

### 4.1 Primary case-law corpora (bulk, machine-readable)

| Source | Coverage | Access |
|---|---|---|
| **Caselaw Access Project (CAP)** — Harvard Law Library Innovation Lab | All official, book-published U.S. state and federal case law through 2020 — roughly 6.7–6.9 million cases across 360 years, digitized from 40 million pages, with reporter pagination preserved | Free bulk download, CC0 license, via case.law and Hugging Face (`free-law/Caselaw_Access_Project`)[^16] |
| **CourtListener (Free Law Project)** | 9–10 million decisions from 2,000+ courts; claims coverage of more than 99% of precedential published U.S. case law; continuously updated; incorporates and cleans CAP data | Free bulk CSV exports, PostgreSQL replication, and REST API[^17] |
| **RECAP Archive (CourtListener)** | Federal court filings from PACER — including the party and amicus briefs in the STR cases above | Free search and retrieval[^18] |
| **English Reports (1220–1867)** | The pre-American common law: the full nominate reports, including the foundational lodger and innkeeper cases | Free via CommonLII |
| **State session laws and municipal codes** | Lodging-house licensing acts, colonial statutes, early STR-relevant ordinances | HeinOnline (subscription); state archives; HathiTrust |

*CAP is the workhorse: a complete, legally unencumbered, locally indexable corpus of American case law with page-level citations — exactly what brief-grade research requires. CourtListener extends coverage past 2020 and supplies the citation graph.*

### 4.2 General-language and legal-linguistic corpora (for lexicon building)

| Source | Use |
|---|---|
| **BYU Law & Corpus Linguistics platform** (lawcorpus.byu.edu) — incl. **COFEA** (Corpus of Founding Era American English, ~95,000–126,000 texts, ~138 million words, 1760–1799) and **COEME** (Early Modern English) | Founding-era ordinary meaning; the platform is used by federal and state judges and appellate attorneys, which matters for methodological credibility in briefing[^19] |
| **COHA / COCA** (Corpus of Historical / Contemporary American English) | Diachronic usage 1810–present; tracking term drift (*let* → *rent* → *host*) |
| **Google Books Ngram / HathiTrust** | Frequency-over-time for candidate terms; full-text retrieval of treatises and practice manuals |
| **Founders Online, Evans/TCP Early American Imprints** | Founding-era primary sources (also COFEA's underlying sources) |

Corpus linguistics is now an established interpretive methodology — endorsed by the Michigan Supreme Court in *People v. Harris* (2016) and cited in judicial opinions across federal and state courts — so the method itself, not just its findings, can be defended in briefing.[^20]

### 4.3 Doctrinal and historical secondary sources (seed vocabulary and seed cases)

- **Blackstone, *Commentaries*, Book II** — estates less than freehold; the classical statement of leasing as an incident of ownership.
- **Kent's *Commentaries*; Tiffany, *Real Property*; Wood, *Landlord and Tenant*; Taylor, *Landlord and Tenant*; Schouler, *Bailments*** — the treatise tradition is a hand-built ontology of each era: period-correct terminology plus citations to leading cases. The landlord-tenant treatises' lodger/boarder chapters are the single highest-yield starting point.
- **West Key Number System** — topics: Landlord & Tenant; Innkeepers; Licenses; Zoning & Planning. **ALR annotations** on boarders/roomers in residential districts.
- **Law review literature** on law and corpus linguistics (Lee & Mouritsen, *Judging Ordinary Meaning*) and on STR constitutional litigation.

### 4.4 Validation and litigation-support tools

- **Citators (KeyCite / Shepard's, or Midpage/CoCounsel-class research tools)** — mandatory good-law check before anything enters work product. Open citation graphs show *that* a case was cited, not that it survives; treat citator validation as a final gate on the shortlist.
- **Advocacy-organization dockets** — Texas Public Policy Foundation (*Zaatari*, *Marfil*), Institute for Justice (*Ladd*), Pacific Legal Foundation, Southeastern Legal Foundation — for briefs, amicus networks, and live case pipelines.[^21]

---

## 5. The Corpus Research Pipeline

### 5.1 The idea, in plain English

The pipeline treats "find the historical case law" as two linked problems: **learn the historical language, then search with it.** Concretely:

1. **Seed the lexicon.** Start with the vocabulary in the treatises — the lodger/boarder chapters of the landlord-tenant literature give a few dozen period terms and a few hundred leading cases essentially for free.
2. **Expand the lexicon with corpus tools.** Run those seed terms through the historical language corpora (COFEA, COHA, Google Books). Concordance views show each term in context; collocation analysis reveals the words that travel with it (*"furnished" + "rooms," "taking in" + "lodgers"*), surfacing synonyms and era-specific variants a lawyer would never guess. Frequency-over-time charts show when terms rise and fall — a map of the vocabulary drift itself.
3. **Search the complete case-law record.** Index the Caselaw Access Project and CourtListener data locally, partitioned by era and jurisdiction. Search with the expanded historical lexicon using both exact-term retrieval and semantic (meaning-based) retrieval, so a case about "paying guests in a private dwelling" surfaces even when no seed term appears verbatim.
4. **Read at scale with AI agents.** Each candidate case is read by an AI agent that fills out a structured form: era, jurisdiction, who was letting (ordinary householder vs. commercial operator), duration of occupancy, how the court characterized the arrangement (lease, license, lodging), the holding, and — critically — verbatim supporting quotations with reporter page numbers. Every characterization must be backed by a quotation that appears word-for-word in the source text; any extraction that fails that check is discarded automatically. Fields like "who was letting" and "duration" are not incidental — they are what the *Glucksberg* level-of-generality fight demands.
5. **Feed findings back and repeat.** New terms discovered in the retrieved cases go back into the lexicon; the citation graph expands the net (a 1950 case citing an 1850 lodger case is findable through citations even when the vocabulary has fully turned over). The loop runs until it stops producing new material.

Human lawyers enter at the right altitude: not reading ten thousand candidates, but reviewing structured summaries, adjudicating the cases where independent AI readers disagree, and doing the doctrinal synthesis and citator validation that machines should not be trusted with.

### 5.2 Why this project needs it

- **The dispositive evidence is unreachable by conventional search.** The winning legal theories are historical-evidence tests, and the evidence is written in dead vocabulary. This is not a productivity enhancement to normal research; it is the only practical way to do the research at all.
- **Scale.** The relevant record spans every American jurisdiction over two centuries, plus the English inheritance. No associate team reads that. An agent fleet does, in days.
- **Verifiability.** Litigation demands pin-cite fidelity. The pipeline's quote-verification gate produces brief-grade citations by construction, and its recall can be measured: harvest the historical citations from the existing STR briefs (*Zaatari*, *Nekrilov*, *Hignell-Stark*, *Ladd*, *Bodin*) as a gold-standard test set, and confirm the system finds what expert lawyers already found before trusting what it finds beyond them. The marginal value is precisely the cases *not* already in those briefs.
- **Both sides of the ledger.** Running the pipeline with inverted targets (licensing upheld under the police power, boarding houses treated as commercial intrusions) builds the adverse-authority file on the same infrastructure — required for candor and for anticipating the opposition.
- **Byproducts.** Because jurisdiction is a first-class field, the output doubles as a state-by-state matrix of historical authority, state constitutional text (retroactivity clauses, inherent-rights clauses), and judicial receptivity — directly usable for venue selection and litigation targeting.

### 5.3 Execution with agent harnesses

The pipeline maps cleanly onto modern agent tooling (e.g., Claude Code, Codex):

- **Infrastructure agent (one harness, supervised):** corpus ingestion; era/jurisdiction-partitioned full-text and vector indexes (SQLite/FTS5 or DuckDB scale is sufficient); concordance and collocation utilities exposed as command-line tools other agents can call.
- **Extraction fleet (parallel agents):** map-reduce over retrieved candidates with the structured schema; strict JSON output; automatic verbatim-quote validation against source text.
- **Cross-model agreement:** running extractions through two independent model families and flagging disagreements is a cheap quality signal — the disagreement set is exactly where human review is highest-value.
- **Evaluation harness first:** build the gold-set recall benchmark before the retrieval stack, and measure every retrieval change against it. Retrieval failure is silent; the benchmark makes it visible.
- **Humans at the doctrine layer:** claim framing, synthesis, citator validation, and final work product remain human tasks with machine-prepared inputs.

### 5.4 Generalization: a reusable research capability

Nothing in the pipeline is specific to short-term rentals. Its components — bulk legal corpora, a historical-lexicon builder, hybrid retrieval, schema-driven agent extraction with quote verification, and a recall benchmark — form a general instrument for any question of the form *"what does the historical legal record actually say about X?"* Natural next applications:

- **Any *Glucksberg*/*Bruen*-style historical inquiry** — tradition-and-history analysis is now the governing methodology across multiple constitutional domains, and it runs on exactly this kind of evidence.
- **Other bundle-of-sticks disputes** — accessory dwelling units, home-based businesses, agricultural and water rights, rent control's historical treatment.
- **State constitutional excavation** — recovering the interpretive history of inherent-rights, retroactivity, and due-course-of-law clauses state by state.
- **Term-drift problems generally** — any doctrine whose vocabulary has turned over (e.g., historical analogues to platform intermediaries, insurance, or occupational licensing).

Each new project reuses the infrastructure and adds a domain lexicon and a gold set — the marginal cost of the second project is a fraction of the first. The ontology built along the way (concept → era-specific surface forms → anchor cases) compounds: it is a durable research asset, not a disposable query log.

---

## 6. Recommended First Sprint

1. Stand up CAP + CourtListener indexes for three or four target states (Texas, Pennsylvania, Louisiana, plus one Zaatari-adjacent venue) and the regional reporters, era-partitioned.
2. Pull the STR litigation briefs from RECAP (*Zaatari*, *Nekrilov*, *Hignell-Stark*, *Marfil*, *Bodin*, *Ladd*) and harvest their historical citations into the gold set.
3. Seed the lexicon from the lodger/boarder chapters of Wood, Taylor, and Tiffany; build KWIC/collocation tooling over COFEA and COHA for expansion.
4. Run the first retrieval-and-extraction loop against the gold set; report recall; iterate.

---

## References

[^1]: *Nekrilov v. City of Jersey City*, No. 21-1786 (3d Cir. Aug. 16, 2022) (precedential), https://law.justia.com/cases/federal/appellate-courts/ca3/21-1786/21-1786-2022-08-16.html; slip op. at https://www2.ca3.uscourts.gov/opinarch/211786p.pdf.
[^2]: Robert Thomas, *Jersey City Short Term Rental Regulation Not a Regulatory Taking*, Lexology (Aug. 25, 2022), https://www.lexology.com/library/detail.aspx?g=14837382-d005-4961-80eb-97eb1bea5c28 (analyzing the Third Circuit's Penn Central application and remaining-uses reasoning).
[^3]: *Hignell-Stark v. City of New Orleans*, 46 F.4th 317 (5th Cir. 2022), https://www.ca5.uscourts.gov/opinions/pub/21/21-30643-CV0.pdf; case summary at https://law.justia.com/cases/federal/appellate-courts/ca5/21-30643/21-30643-2022-08-22.html.
[^4]: *Marfil v. City of New Braunfels*, No. 25-50025 (5th Cir. June 18, 2026), https://www.ca5.uscourts.gov/opinions/pub/25/25-50025-CV0.pdf; summary at https://law.justia.com/cases/federal/appellate-courts/ca5/25-50025/25-50025-2026-06-18.html (no protected property interest in short-term leasing under Texas law; rational-basis review satisfied; discussing *City of Dickinson v. Crystal Cruise Investments, LLC* (Tex. App.—Houston [1st Dist.] 2026) on vested rights).
[^5]: Claire Taylor, *Lawsuit Challenging Lafayette's Short-Term Rental Ban Should Be Dismissed, Federal Judge Says*, The Advocate (Feb. 2026), https://www.theadvocate.com/acadiana/news/courts/lawsuit-challenging-lafayette-s-short-term-rental-ban-should-be-dismissed-federal-judge-says/article_37d684a9-d94e-4bf7-8204-feac5fb6a8b6.html.
[^6]: *Short-Term Rental Bans Are Back in the Takings Spotlight* (discussing *Blakelick Properties, LLC v. Village of Glen Ellyn*), Frost Brown Todd (June 17, 2025), https://frostbrowntodd.com/short-term-rental-bans-are-back-in-the-takings-spotlight/.
[^7]: *Zaatari v. City of Austin*, No. 03-17-00812-CV (Tex. App.—Austin Nov. 27, 2019, pet. denied), https://caselaw.findlaw.com/court/tx-court-of-appeals/2033381.html.
[^8]: The Law Offices of Ryan Henry, *Austin Court of Appeals Holds Austin's Short-Term Rental Regulations Unconstitutional* (Dec. 6, 2019), https://rshlawfirm.com/2019/12/06/austin-court-of-appeals-holds-austins-short-term-rental-regulations-unconstitutional-assembly-clause-also-declared-fundamental-right-entitled-to-strict-scrutiny/; Texas Public Policy Foundation, *Texas Third Court of Appeals Affirms TPPF Win in Short-Term Rental Lawsuit*, https://www.texaspolicy.com/press/texas-third-court-of-appeals-affirms-tppf-win-in-short-term-rental-lawsuit.
[^9]: Rent Responsibly, *How Short-Term Rental Bans Backfire* (Jan. 2026), https://www.rentresponsibly.org/how-short-term-rental-bans-backfire/ (Dallas injunction and Texas Supreme Court petition; Maui phase-out and owner suits; New Orleans platform litigation).
[^10]: *Ladd v. Real Estate Commission*, 33 MAP 2018 (Pa. 2020), https://law.justia.com/cases/pennsylvania/supreme-court/2020/33-map-2018.html; Nochumson P.C., *Short Term Rental Broker — Constitutional?* (Mar. 2021), https://nochumson.com/rental-broker-requirement-is-constitutional/ (Article I, § 1 and the *Gambone* real-and-substantial-relationship standard).
[^11]: Pennsylvania Association of Realtors, *Trial Result Could Impact Pennsylvania Real Estate Activity* (Nov. 2025), https://www.parealtors.org/blog/trial-result-could-impact-pennsylvania-real-estate-activity/.
[^12]: Sher Garner (SNW Law), *Fifth Circuit Deals Further Blow to New Orleans STR Laws* (Oct. 8, 2025), https://www.snw.law/fifth-circuit-deals-further-blow-to-new-orleans-str-laws (equal protection holding on natural-persons requirement; narrowed operator-presence construction surviving dormant Commerce Clause review).
[^13]: *Bodin v. City of New Orleans*, No. 25-30524 (5th Cir. Aug. 5, 2026), https://law.justia.com/cases/federal/appellate-courts/ca5/25-30524/25-30524-2026-08-05.html.
[^14]: Order and Reasons, No. 2:25-cv-00329 (E.D. La. Sept. 8, 2025), https://content.govdelivery.com/attachments/LANOLA/2025/09/08/file_attachments/3382056/Doc.%2047%20Order%20and%20Reasons.pdf (distinguishing the takings theory from *Hignell-Stark*).
[^15]: Rent Responsibly, *Spring 2026 State Short-Term Rental Bills* (Apr. 2026), https://www.rentresponsibly.org/spring-2026-state-short-term-rental-bills/.
[^16]: Caselaw Access Project, https://case.law/; Hugging Face dataset, https://huggingface.co/datasets/free-law/Caselaw_Access_Project; Library of Congress, *CourtListener and Caselaw Access Project*, https://guides.loc.gov/free-case-law/courtlistener-and-caselaw-access-project (scope: all official, book-published U.S. case law through 2020).
[^17]: Free Law Project, *Legal Data Resources*, https://free.law/datasets/; FLP Wiki, *Bulk Legal Data*, https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data.
[^18]: CourtListener RECAP Archive, https://www.courtlistener.com/recap/.
[^19]: BYU Law & Corpus Linguistics, https://lawcorpus.byu.edu/; COFEA design description, https://lcl.byu.edu/projects/cofea/; BYU Law, *10th Annual Law and Corpus Linguistics Conference* (Oct. 2025), https://www.prnewswire.com/news-releases/byu-law-hosts-10th-annual-law-and-corpus-linguistics-conference-marks-a-decade-of-growth-in-how-the-law-interprets-language-302590013.html.
[^20]: National Endowment for the Humanities, *Corpus Linguistics Is Changing How Courts Interpret the Law* (2025), https://www.neh.gov/article/corpus-linguistics-changing-how-courts-interpret-law; LawSites, *New Corpus Linguistics Platform Lets Legal Researchers Explore the Meanings of Words and Phrases* (2018), https://www.lawnext.com/2018/09/new-corpus-linguistics-platform-lets-legal-researchers-explore-meanings-words-phrases.html (*People v. Harris* endorsement).
[^21]: E.g., Southeastern Legal Foundation, *Marfil v. City of New Braunfels* (amicus), https://www.slfliberty.org/case/marfil-v-city-of-new-braunfels/; Institute for Justice, *Pennsylvania Property Management* (*Ladd*), https://ij.org/case/pennsylvania-property-management/.
