# Round 5 first pass — the 13 records still carrying a `needs-review:<field>` flag

Queue: `runs/cycle-004-shard-01/review-round-5.json`, section E. One card per record;
each decides the single flagged field. Recommendations below are a first pass only —
the reviewer's decision is the record.

Rules relied on (quoted where used): `domains/str-right-to-let/codebooks/mapper-v3.md`
and the CONTEXT.md glossary. Two that do most of the work here:

- **Polarity.** "POLARITY IS JUDGED FROM THE PROPERTY OWNER'S RIGHT TO LET — never from
  the occupant's interests. A ruling that expands an occupant's or tenant's rights AGAINST
  the owner (rent control, eviction protection, 'permanent tenant' status, statutory
  tenancy, habitability duties) is ADVERSE unless it also affirms the owner's freedom to
  let." And: "Mixed means the same opinion both recognizes the owner's freedom to let on
  one point and restricts it on another, **and both are holdings rather than remarks in
  passing**. If only one side is a holding, follow the holding."
- **Characterization.** "how the COURT classified the arrangement: `lease` | `license` |
  `lodging` | `innkeeping` | `other`." Not how the arrangement looks to us — how the court
  labelled it.

A caution on the passages below: they are quoted from the store's **normalised** opinion
text, which is lower-cased and carries the OCR of the source. I have re-capitalised
sentence openings for readability. Treat them as pointers to the passage, not as
paste-ready verified quotes; a quote added to a record must be re-copied verbatim from
the raw text and re-verified.

---

## 937195 — Devonshire Associates v. Garrett, 190 Misc. 820 (N.Y. App. Term, 1st Dep't 1947)

**Flagged field:** `who_was_letting` — current value **`householder`**.
(Ledger: "reference v2: who_was_letting left unsure by the reviewer".)

A landlord brought holdover summary proceedings against apartment tenants who had taken
roomers into their apartments, charging breach of a lease covenant confining occupancy to
"a strictly private family dwelling apartment by said tenant, and the tenant's immediate
family only" and single-room-occupancy violations of Multiple Dwelling Law §§ 82 and 248.
The Appellate Term reversed and dismissed the petitions. On the covenant it found a waiver
by the conduct of the earlier owner: "the prior owner permitted the occupancy of the
apartments by roomers and thus expressly waived the covenant" — the building's own history
of roomer occupancy defeated the covenant the landlord now sought to enforce. On
illegality it pointed to a Department of Housing and Buildings letter saying an apartment
"now occupied by four roomers" was "not now in violation of sections 82 and 248 of the
Multiple Dwelling Law" — the roomer occupancy was lawful on its face. There was also
neither pleading nor proof supporting the thirty-day termination notice. The letting
actually protected, then, is the tenants' own taking-in of roomers into the apartments
they lived in.

**Recommendation: keep (`householder`). Confidence: medium.**
`who_was_letting` is "`householder` (owner/family letting part of their own dwelling)".
The persons who did the letting here are resident occupants sub-letting rooms in the
dwelling they themselves occupied — the householder tier the level-of-generality argument
runs on. Neither alternative fits: there is no hotel, boarding-house enterprise, or
multiple properties (`commercial_operator`), and the tenants are the opposite of an
absentee (`non_resident_owner`). The one wrinkle is that they hold as lessees, not owners;
a reviewer who reads "householder" as requiring title should go to `unclear`, not to
another tier. Note for the reviewer: the record's other fields describe the *landlord's*
side (polarity `adverse`, correctly, since the occupants won against the owner) while
`who_was_letting` describes the *tenants'* letting — that split is what made this card
hard, and it is worth confirming it is the intended reading.

---

## 11596913 — Gulf Shores Council of Co-Owners v. Raul Cantu No. 3 Family Ltd. P'ship, 985 S.W.2d 667 (Tex. App.—Corpus Christi 1999)

**Flagged field:** `characterization` — current value **`null`** (erased by the quote gate).

A family limited partnership bought three Port Aransas beach condominium units for
investment, put them in the association's rent pool, then withdrew them and hired an
outside rental manager. The council responded with a per-day fee on units rented outside
the pool and, later, an outright ban on outside leasing agents; the partnership won a jury
verdict declaring both unenforceable plus actual and exemplary damages for tortious
interference. The court of appeals reversed and rendered. It construed declaration § 5.02
— "Each apartment [unit] owner shall have an absolute right to lease or rent his apartment
upon such terms as he shall approve, subject to all provisions and restrictions applicable
to the project" — narrowly: "The ability to have tenants is guaranteed by the 'absolute
right' language", but the right is not "truly absolute", and it does not include choosing
one's own managing agent. It then found no evidence the fee or the ban was arbitrary,
capricious, or discriminatory, and awarded the association its unpaid assessments and
attorney fees.

**Recommendation: set `lease`. Confidence: medium.**
Under the rule that `characterization` records "how the COURT classified the arrangement",
the court's own vocabulary is uniformly leasehold: it construes a right "to lease or
rent", says the units "could be occupied by tenants", and adjudicates interference with
"existing rental contracts between the ... partnership and renters". It never reaches
lodging, innkeeping, or licence. The counter-consideration is factual, not doctrinal: the
actual occupants were short-stay vacationers charged a $15–$20 *per day* fee, registered
at an office and given maid service — an arrangement that looks like lodging. But the
codebook asks for the court's classification, and the court never made that one.

---

## 1613746 — YMCA of Pittsburgh Appeal, 4 Pa. D. & C.2d 186 (Allegheny C.P. 1954)

**Flagged field:** `polarity` — current value **`null`** (erased by the quote gate).

The county sought to tax the parts of five YMCA buildings given over to dormitories and
cafeterias, arguing that because residents paid for their rooms and meals those uses were
a commercial enterprise rather than a charity. The court held them exempt, choosing
*Salvation Army v. Allegheny County* over *YMCA of Germantown v. Philadelphia*. The
distinguishing facts it relied on were competitive and economic: "there was no advertising
of the dormitory facilities in any of the five buildings here involved, and no complaints
were heard from hotels or boarding houses that the dormitories were in competition with
them"; residents were screened low-income young men; rates averaged $3.64–$6.58 a week
against $2.50–$7 a *night* at downtown hotels; and the dormitories ran at an annual deficit
made up by the community chest. The occupancy classes cut both ways — "The permanent
classification included all those who occupied the rooms for two weeks or more and paid
rent on a weekly basis; transients being those whose occupancy was less than two weeks" —
but the overwhelming majority were permanent. Barber shop, bowling alleys, and
businessmen's health clubs followed as incidental.

**Recommendation: set `favorable`. Confidence: medium.**
Polarity is judged from the owner's right to let, and here the owner won *on the letting
itself*: the contested question was whether renting rooms for pay made the operation
commercial, and the court held it did not and refused to lay a tax on it. That is the
owner's letting "recognized, protected, or assumed as lawful" — and note the codebook's
own `restriction_nature` vocabulary counts `tax` as a species of restriction, so relief
from it is relief on the letting, not a win "on a ground unrelated to letting". Not
`mixed`: mixed requires that the same opinion also *restrict* the freedom to let as a
holding, and the Germantown rule (avowedly commercial dormitories are taxable) appears
here only as distinguished precedent. Flag for the reviewer: a holding that the operation
was *not* commercial sits awkwardly beside the record's `who_was_letting =
commercial_operator`; that field is not on this card but may deserve its own look.

---

## 10283820 — Scottish American Mortgage Co. v. Milner, 30 S.W.2d 582 (Tex. Civ. App.—Texarkana 1930)

**Flagged field:** `characterization` — current value **`null`** (erased by the quote gate).

A judgment creditor levied on the part of a Mt. Pleasant town lot occupied by the smaller
of two houses standing about eight feet apart. The debtor had bought the whole lot, moved
his family into the larger house at once, and left the smaller one in the hands of the
tenant already renting it — roughly three months, until the levy. He testified the renting
was a stopgap until he could borrow money to join the two buildings into one and "add more
room for boarders and roomers". The court affirmed judgment for the homestead claimant:
"Any temporary renting would not defeat the homestead right", the owner had a reasonable
time after purchase to take up occupancy of the whole lot, and whether the renting was
temporary was a jury question. It distinguished *McDonald v. Clark*, where "the renting of
the house was of a permanent and not temporary character", and the fenced-off,
long-rented-lot cases.

**Recommendation: set `lease`. Confidence: medium.**
The court treats the arrangement throughout as an ordinary tenancy — the small house was
"being at the time of the purchase rented, continued to be occupied by the tenant" — and
its whole analysis turns on the *duration* of that renting, not on any other legal
character. That is `lease` on the codebook's list; the boarders and roomers were only the
owner's unrealised plan, never the arrangement at issue, so `lodging` would code an
intention rather than a holding. Caveat the reviewer should weigh: the record has no
surviving quote supporting characterization (which is why it was erased), so a `set` here
rests on the reviewer's own reading; the "being at the time of the purchase rented"
sentence is available if a supporting quote is wanted. The honest alternative is `keep`
(leave null) on the ground that the court decided homestead abandonment and never
classified the letting at all.

---

## 12692177 — Lafayette Parish Sch. Bd. v. Imagine Mgmt., LLC, 270 So. 3d 694 (La. App. 3d Cir. 2019)

**Flagged field:** `holding_summary` — current value **`null`**.

A parish tax collector sued Imagine Management, LLC, Cajun Hostel, LLC, and their owner
Toby Dore in summary proceeding for about $4,000 in unpaid sales and hotel-occupancy taxes
on the Cajun Hostel, registered as a "hostel/guesthouse/bed and breakfast business" whose
dealer status rested on "furnishing sleeping rooms, cottages, or cabins at residential
locations ... to transient guests for a fee". No defendant filed any pleading; Dore
appeared pro se, and the trial judge, after hearing his unsworn testimony, said only "It's
very confusing. I'm going to deny your judgement", telling the collector to take it up on
appeal. The court of appeal held that testimony should never have been considered
(La. R.S. 47:337.61(2) bars defenses not filed before the hearing) and that the trial court
had therefore never ruled on the merits at all: "because the trial court herein failed to
issue a ruling on the merits of the summary sales tax proceeding brought by the collector,
this court has no jurisdiction to decide this appeal." Reversed and remanded for
rehearing; the tax liability itself is undecided.

**Recommendation: set** (`holding_summary`, free text). **Confidence: high.**

> A parish tax collector sued the operator of the Cajun Hostel — a hostel/guesthouse/
> bed-and-breakfast furnishing sleeping rooms to transient guests for a fee — and its
> owner personally for unpaid sales and hotel-occupancy taxes for June 2016 through
> September 2017. The court of appeal held that the trial court erred in considering the
> pro se owner's unsworn testimony, because La. R.S. 47:337.61(2) requires all defenses to
> be filed before the hearing, and that the trial court had never actually ruled on the
> merits of the summary tax proceeding, leaving the court of appeal without jurisdiction
> to decide the appeal. The judgment was reversed and the matter remanded for a rehearing,
> so the tax liability was left undecided.

Three sentences, as the codebook requires ("`holding_summary`: <= 3 sentences, plain
statement of the holding"). The reason for writing it from the disposition rather than the
facts: the record's quotes all come from the *collector's petition*, not from the court, so
a summary drawn from them would state a litigant's allegations as the holding, which the
codebook forbids ("record what the court said, not what a litigant would wish it said").
Relevance note: because nothing was decided about letting, a reviewer could reach for
`relevant: false` under "Procedural cases that merely mention a boarding house in passing
are `false`." I would not — the entire subject of the suit is the occupancy taxation of
short-term paid lodging, which is squarely "its regulation", not a passing mention.

---

## 5289134 — State v. Mack, 41 La. Ann. 1079 (La. 1889)

**Flagged field:** `holding_summary` — current value **`null`**.

Minnie Mack was convicted in the New Orleans recorder's court of refusing to obey the
mayor's order, under a city ordinance, to remove from No. 55 First Street, which she owned
and kept as a house of assignation. She argued the ordinance took her property without due
process. The Supreme Court affirmed: the city charter delegated power "to regulate houses
of prostitution and assignation", "to exclude such houses from certain limits" and "to
close the same", and requiring the keeper to remove was the only practical way of closing
one. Her ownership was no answer — "The ordinance under consideration does not deprive
defendant of her property; it simply prevents its use by her for purposes inconsistent
with public order and morals" — this being an exercise of "the police power of the State
... which subjects the most absolute rights of property to the condition that they shall
be so used as not to infringe the rights of others." Fine and imprisonment imposed after a
contradictory hearing satisfied due process, and reputation evidence was admissible.

**Recommendation: set** (`holding_summary`, free text). **Confidence: high** for the
summary; see the relevance note.

> Affirming the conviction of an owner-occupant who refused the mayor's order to remove
> from a house she kept as a house of assignation, the court held that the city's chartered
> power to regulate, exclude, and close such houses carried the power to require their
> occupants to leave, with fine and imprisonment as a competent sanction. That the keeper
> owned the house was no defense: the ordinance took no property but merely forbade a use
> of it inconsistent with public order and morals, an exercise of the police power to which
> even the most absolute rights of property are subject. Enforcement by a competent
> tribunal, after a contradictory hearing and on proof of the prohibited use, satisfied due
> process.

Relevance note the reviewer should settle: the reader already called this "borderline
relevant", and the borderline is real. The only compensated occupancy in the case is the
short-stay use of rooms in an assignation house, and the opinion never discusses letting
as such — it is a vice-suppression case. It stays `relevant: true` on my reading because
the relevance test asks whether the case bears on "compensated occupancy of another's
dwelling/rooms, its legal character, or its **regulation**", and this is police-power
regulation of exactly that, applied to an owner in her own house — the paradigm adverse
pattern the codebook names. If the reviewer reads the house of assignation as outside the
practice this corpus tracks, `{"field": "relevant", "decision": "set", "value": false}` is
the route.

---

## 10296227 — Dallas Hotel Co. v. Davidson, 12 S.W.2d 633 (Tex. Civ. App.—Beaumont 1928)

**Flagged field:** `holding_summary` — current value **`null`**.

A convention guest at the Adolphus Hotel in Dallas lost $65 in cash, a tie clasp, and a
$600 diamond stud from room 837 overnight, and sued for $683.25. The hotel invoked article
4592, which caps a keeper's liability for guests' valuables at $50 if it "keeps on the
doors of the sleeping rooms used by guests suitable locks or bolts and proper fastenings
on the transom and window of said room" and maintains a safe. The door had both a keyed
double lock (safe) and a night bolt (defective — its outside disc was loose and could be
turned open with a thumb); the guest used the bolt. The court agreed the statute demands
only one suitable lock *or* bolt, but held that a keeper who installs both "must see that
each and every lock and bolt so placed is suitable and safe", because their presence is an
invitation to the guest to rely on either. The hotel therefore fell outside the statutory
limitation, negligence followed as a matter of law, and the full judgment for the guest was
affirmed.

**Recommendation: set** (`holding_summary`, free text). **Confidence: high.**

> A guest at the Adolphus Hotel sued for $683 in cash and jewelry stolen from his room, and
> the hotel invoked article 4592's $50 cap for keepers who maintain a safe and "suitable
> locks or bolts" on guest-room doors. The court held that although the statute requires
> only one suitable lock or bolt, a keeper who chooses to install both must keep each of
> them suitable and safe; because the hotel's night bolt — the one the guest reasonably
> chose to use — was defective and could be opened from outside with a thumb, the hotel had
> not complied and could not limit its liability. Negligence followed as a matter of law
> and the guest's full judgment was affirmed.

Again three sentences per the codebook. The record's only quote is the text of article
4592 itself, so a summary built from the quotes alone would state the statute rather than
the holding; the holding is the construction placed on that statute against the keeper,
which is also what makes the record's `polarity = adverse` legible (regulation of the
lodging business sustained and applied against the operator).

---

## 2186819 — Langston v. Maxey, 74 Tex. 155 (Tex. 1889)

**Flagged field:** `characterization` — current value **`null`** (erased by the quote gate).

Maxey, sixty-nine and living on a Cleburne block he had bought in 1867, enjoined an
execution sale of the middle and east parts of his lot, on which stood two houses occupied
by his tenants. He had moved into a new house on the west portion in 1878 and rented out
the old one — first to Mrs. Pickett, who "wanted to keep boarders", with Maxey himself
boarding with her, then to a succession of monthly tenants at $12.50–$18 — and in 1879
built a further house "for the purpose of leasing it to tenants for the income to be
derived therefrom". The Supreme Court held the middle lot remained homestead, because he
kept using its cistern for the family's drinking water, but that the east lot did not: he
had built it to rent, never used it again, and the division fences sufficiently marked it,
which "evinces a permanent abandonment of the use of the lot ... for homestead purposes".
Reversed and remanded. Throughout, "In leasing the property the appellee reserved no
rights in the rented premises" — the letting itself is never questioned as unlawful, only
its homestead consequence.

**Recommendation: set `lease`. Confidence: high.**
Two reasons. First on the merits: the court's own language is leasehold from end to end —
"leasing it to tenants", "leased ever since its construction", "occupied by his tenants" —
and the arrangement it actually adjudicates is the letting of whole houses to monthly
tenants, which is `lease`, not `lodging` (the boarding-house episode is a side-fact about
Mrs. Pickett's business, not the arrangement at issue). Second, and more important
procedurally: **the ledger shows a human already decided this field** —
"characterization adjudicated -> lease (disagreement resolved, human-confirmed)" — and it
was later nulled by the fuzzy-quote-removal cascade ("quote removed: human judged fuzzy
match a real mismatch"), not by anyone changing their mind. Setting `lease` restores the
reviewer's own prior adjudication, and a supporting quote is already on the record ("...
which he testified he built for the purpose of leasing it to tenants for the income to be
derived therefrom").

---

## 5607484 — Yates v. Tessier, 5 La. App. 214 (La. Ct. App. 2d Cir. 1926)

**Flagged field:** `holding_summary` — current value **`null`**.

Texas-resident owners leased a Shreveport house to Mrs. Sledge and, at her request, put in
an extra window with a hinged wire screen that sat in the frame but was fastened by neither
nail nor hook. "Mrs. Sledge sublet a part of the leased premises, which included the room
in which the window in question was located, to the plaintiffs", who put a bed against the
window; their three-year-old rolled against the screen, which swung out, and fell to the
ground, seriously injured. The parents sued the owners in tort and attached their property
as non-residents. The court affirmed judgment for the owners: even conceding the unhooked
screen was negligence and the proximate cause, Civil Code article 2716 puts repairs "to
windows, shutters, partitions ... locks and hinges, and everything of that kind" on the
tenant, so "it was the duty of the plaintiffs to have placed a hook on the screen and not
the duty of the defendants". It also upheld jurisdiction: an insufficient attachment bond
was amendable under Act 119 of 1916 and did not divest the court, and Act 215 of 1920
authorises attachment against non-residents on an unliquidated tort claim.

**Recommendation: set** (`holding_summary`, free text). **Confidence: high.**

> Parents of an injured child sued the non-resident owners of a Shreveport house in tort
> after the child rolled against an unfastened window screen and fell; the room was in a
> part of the premises that the owners' lessee had sublet to the plaintiffs. The court
> affirmed judgment for the owners, holding that under Civil Code article 2716 fastening
> the screen with a hook was a repair chargeable to the tenant rather than to the lessor,
> so the owners were not liable even assuming the unfastened screen was negligence and the
> proximate cause of the injury. It also held that the court had jurisdiction in rem
> despite an insufficient attachment bond, which Act 119 of 1916 allowed to be amended, and
> that attachment lies against non-residents on an unliquidated tort claim.

Note for the reviewer, outside this card's field: `who_was_letting` currently reads
`householder`, but the opinion says the lessors "were residents of the State of Texas" and
the premises were let entire to Mrs. Sledge — that looks like `non_resident_owner` on the
codebook's definition ("owner of a single dwelling who does not live there"). The
householder in this case is Mrs. Sledge, who sublet part of the dwelling she occupied. If
the reviewer agrees, that field needs its own card.

---

## 7664513 — Peters v. Kelly, 113 N.Y.S. 357 (N.Y. App. Div. 1st Dep't 1908)

**Flagged field:** `polarity` — current value **`null`** (erased by the quote gate).

Kelly owned a New York tenement — a brick building in front, a small frame house behind —
and her agent let three second-floor rooms in the rear house to O'Hara, reached by an
outside stairway and landing. A visiting sister-in-law stepped onto the landing, which gave
way. The trial court dismissed her negligence complaint for want of proof that the landlord
retained control of the landing; the Appellate Division reversed and ordered a new trial.
Its reasoning turns on the scope of the demise: on the agent's evidence of what was let,
"This evidence did not show a hiring of the yard adjacent to the house, and the stairway
and the landing, together with the rooms, but only a hiring of the rooms themselves."
Control of what was not let stayed with the owner, and with it a duty: "Having retained
such control, it became her duty to exercise reasonable care to keep the stairway and
landing in suitable repair for use" — a duty that "did not depend upon contract, but was
one which the law raised without special agreement."

**Recommendation: set `adverse`. Confidence: medium.**
The codebook's polarity rule lists "habitability duties" among the rulings that expand
occupant-side rights against the owner and are therefore ADVERSE "unless it also affirms
the owner's freedom to let." This is that pattern in its 1908 form: the narrower the
hiring, the more the owner retains, and the more she retains the more the law puts on her
without her agreement. Nothing in the opinion affirms her liberty to let on her own terms —
letting rooms is simply assumed lawful in passing, and the codebook is explicit that a
remark in passing is not a holding. The competing call is `keep` (leave null) on the view
that a premises-liability case decides nothing at all about the right to let; I think that
understates it, because the duty is derived directly from how much of the dwelling was let,
but a reviewer who wants polarity reserved for cases that actually adjudicate letting
rights would be within the rules. Note that the ledger's own reader called this "favorable
at low relevance" precisely for the assumption-in-passing reason — the reasoning the
polarity re-review of 2026-09-01 was meant to close off.

---

## 1177933 — Wasserstein v. Gabel, 52 Misc. 2d 199 (N.Y. Sup. Ct., Kings County 1966)

**Flagged field:** `who_was_letting` — current value **`unclear`**.
(Ledger: "reference v2: who_was_letting left unsure by the reviewer"; `relevant` and
`polarity` were separately adjudicated by a human — relevant `True`, polarity `mixed`.)

An article 78 proceeding. "The premises here, formerly occupied as a rooming house, were
altered and converted into a five-family class A multiple dwelling" in 1961, and the
landlords applied to decontrol the newly created units. Their proof was late; by the time
the file was complete the regulation had been amended to bar decontrol of units "resulting
from conversion after April 30, 1962 of rooming house accommodations or of single room
occupancy accommodations", and an inspection found the building in disrepair. The
administrator refused decontrol. The court remanded for de novo consideration, doubting the
amendment applied at all — "I seriously doubt whether the amendment under subdivision d of
section 11 justifies the administrator in exercising her discretion because the conversion
was from a rooming house", since this conversion plainly predated April 30, 1962 — and
adding that emergency rent legislation is "not to be extended beyond the evil sought to be
curbed", while other agencies exist to police substandard housing.

**Recommendation: set `commercial_operator`. Confidence: low.**
The opinion never says whether the landlords live in the building, so `unclear` is
defensible and is where the reviewer left it. Against that, the codebook says to use
`unclear` "only after actually looking", and looking yields something: what was let was
first a rooming house and then a five-unit class A multiple dwelling held wholly for rent
income, with ownership changing hands mid-proceeding. That is a letting enterprise on the
`commercial_operator` branch ("boarding house run as enterprise"), and it cannot be
`non_resident_owner`, which the codebook confines to the "owner of a **single dwelling**
who does not live there". The taxonomy fits imperfectly — one building, five units, no
hotel — which is why this is low confidence; if the reviewer thinks `commercial_operator`
should be reserved for hotels and boarding houses proper, `keep` (`unclear`) is the right
answer and this record simply has no better tier available.

---

## 3313366 — Abright v. Shapiro, 92 A.D.2d 452 (N.Y. App. Div. 1st Dep't 1983)

**Flagged field:** `polarity` — current value **`mixed`**. Left `unsure` by three prior
first passes (rounds 2, 3b, 4), with the reviewer's own note each time that the merits are
deferred.

Landlords of a 109-unit building at 40 East 89th Street let 45 apartments to 52 doctors and
therapists under leases providing that occupancy is "for professional use only", with riders
holding the landlords harmless for the non-conforming use. The Department of Buildings then
cited the landlords, because professional use violated the certificate of occupancy and the
class A residential zoning; the landlords served 30-day termination notices; 35 tenants sued
for a declaration that they are rent stabilized plus about $50,000 in overcharges, and
stopped paying rent. The landlords moved for partial summary judgment for $186,545 in rent
or use and occupancy and for an injunction. The Appellate Division affirmed the denial of
summary judgment, because the zoning resolution permits medicine and psychology as accessory
"home occupations" within 25% of the floor area, so "There is a question of fact as to
whether the professional use of these apartments is merely peripheral to a primary
residential use". It expressly deferred everything else: "the question of plaintiffs' alleged
overpayments, as well as defendants' right to an injunction against continued use and
occupancy of the apartments for professional purposes, must await a trial of the facts." It
modified only to condition the denial of the injunction on the tenants paying current rent
and arrears, "if only to maintain the status quo until rendition of a final judgment".

**Recommendation: set `null`** — an affirmative "this opinion fixes no polarity", written as
`{"field": "polarity", "decision": "set", "value": null}`. **Confidence: medium-high.**
`mixed` cannot stand on the codebook's own terms: "Mixed means the same opinion both
recognizes the owner's freedom to let on one point and restricts it on another, **and both
are holdings rather than remarks in passing**." Here neither side is a holding. The denial of
summary judgment decides only that a fact question exists; the interim payment condition is
expressly status-quo relief pending final judgment and, if anything, runs the landlords' way.
Nor is there a holding in the other direction: the landlords' entitlement to an injunction is
deferred in terms. That leaves `null` — the reading the reviewer's own three notes have been
circling. Setting it (rather than a fourth `unsure`) also clears the three stacked
`needs-review:polarity` flags this record carries. `unsure` remains available, but a fourth
pass is unlikely to find what three did not: the opinion simply does not decide the question.

---

## 6924541 — Salafian v. Gabriel, 146 So. 3d 753 (La. App. 4th Cir. 2014)

**Flagged field:** `characterization` — current value **`null`**. Left `unsure` in round 4.

Salafian rented a room in a building owned by the Islamic Association of Arabi, obtaining his
key and arranging payments through an association member. Another renter, Gabriel — who had
rented rooms there off and on for fifteen to twenty years and was known as cordial — beat him
unconscious with a laptop; he was found hours later and spent two and a half months in
hospital. He sued the association and the member, alleging they knew of Gabriel's violent
propensities. The court of appeal affirmed summary judgment for the defendants. It first held
the parties' status could not be resolved on summary judgment but did not need to be: "a
determination of this factual dispute is not material to the issue before us", since "the
relationship between Mr. Salafian and the defendants were either that of a business and its
customer or an innkeeper and its guest", and the defendants prevailed even under the higher
innkeeper standard. On the *Posecai* balancing test there was no evidence of prior crime on
the premises or of any knowledge of Gabriel's propensities, so no duty to protect against the
criminal act of a third person arose.

**Recommendation: keep (`null` stands — affirmatively leave empty). Confidence: high.**
`characterization` is "how the COURT classified the arrangement", and this court deliberately
declined to classify it. It named the hotel-or-dormitory dispute and put it aside as
immaterial; it corrected the trial court for even appearing to find that Salafian was a tenant
("To the extent the trial court made a factual finding that Mr. Salafian was a tenant, we find
that the trial court erred"); and it reasoned in the alternative ("either ... or"), assuming
the innkeeper standard only *arguendo*. Assuming a standard in order to dispose of a case is
not classifying the arrangement, so `innkeeping` would over-read the opinion and `lodging` has
no footing at all. This matches the reviewer's own round-4 note in substance; `keep` records
that conclusion and clears the flag, where a fourth `unsure` would leave the record waiting
for a read that has now been done three times.

---

## Summary table

| Case id | Field | Recommendation | Confidence |
|---|---|---|---|
| 937195 | who_was_letting | keep (`householder`) | medium |
| 11596913 | characterization | set `lease` | medium |
| 1613746 | polarity | set `favorable` | medium |
| 10283820 | characterization | set `lease` | medium |
| 12692177 | holding_summary | set (text above) | high |
| 5289134 | holding_summary | set (text above) | high |
| 10296227 | holding_summary | set (text above) | high |
| 2186819 | characterization | set `lease` | high |
| 5607484 | holding_summary | set (text above) | high |
| 7664513 | polarity | set `adverse` | medium |
| 1177933 | who_was_letting | set `commercial_operator` | low |
| 3313366 | polarity | set `null` | medium-high |
| 6924541 | characterization | keep (`null`) | high |

No card is recommended for `relevant: false`. Two came close and are flagged in place —
5289134 (State v. Mack: a vice-suppression case whose only letting is the short-stay use of
an assignation house) and 12692177 (Imagine Management: a purely jurisdictional disposition,
though the subject of the suit is occupancy tax on a hostel).

Fields noticed as questionable while reading, on records whose flagged field is something
else — offered as observations, not decisions: 5607484 `who_was_letting = householder` where
the lessors were Texas non-residents letting the whole house; 1613746 `who_was_letting =
commercial_operator` on a record whose holding is that the operation was not commercial.
