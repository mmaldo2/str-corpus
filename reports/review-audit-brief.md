# Audit pass brief: relevance, polarity, who was letting

Standing brief for the blind audit sample (spec §4.1). You are shown ONE card at a time, with
nothing but the case's identity and the full opinion text - no earlier reading, no checker, no
values from any prior pass. Read this whole brief before deciding a card.

## What the corpus is about

Case law on **letting**: one person paying to occupy another's dwelling or rooms (lodgers,
boarders, roomers, tenants of furnished rooms, guests of boarding houses and small hotels,
short-term occupants), the legal character of that arrangement, and how courts and governments
regulated or restricted an owner's freedom to let. The ultimate use is a federal suit arguing a
long-recognised right of a householder to let rooms.

**Polarity** is judged from the OWNER's freedom to let (the memory `polarity-owner-right-to-let`):
`favorable` = the court recognised or protected the owner's freedom to let, or struck down /
narrowed a restriction on it; `adverse` = the court upheld a restriction on letting, or ruled
against the owner's freedom to let (a pro-tenant outcome that burdens the owner is ADVERSE);
`mixed` = the same opinion both recognised the owner's freedom on one point and restricted it on
another, and both are holdings rather than remarks in passing. If only one side is a holding,
follow the holding. An owner who wins on a ground unrelated to letting is not favorable; judge
only what the court decided about letting. A case the reader finds irrelevant carries no
polarity.

**Relevance**: relevant only if the opinion bears on compensated occupancy of another's dwelling
or rooms, its legal character, or its regulation. Cases about commercial leases of shops, farms,
agricultural tenancies, mortgage foreclosures, hotel torts with no letting question, or where
"boarder"/"lodger" is incidental colour are NOT relevant.

## Vocabularies (use these exact strings)

- `polarity`: `favorable` | `adverse` | `mixed`
- `who_was_letting`: `householder` | `commercial_operator` | `non_resident_owner` | `unclear`
- `characterization` (how the COURT classified the arrangement): `lease` | `license` | `lodging` | `innkeeping` | `other`
- `under_thirty_days` (was the occupancy at issue under thirty days): `yes` | `no` | `unclear`
- `owner_freedom_characterization` (how the court framed the owner's liberty to let): `incident_of_ownership` | `regulable_privilege` | `commercial_use` | `not_addressed`
- `restriction_nature` (adverse records only): `licensing` | `zoning` | `nuisance` | `tenant_protection` | `tax` | `other`
- `relevant`: `true` | `false`

These are the only allowed strings.

## The decision

You see ONE card at a time: the case's citation, court and year, a CourtListener link, and the
full opinion text. Nothing else - no earlier reading, no checker. From the opinion alone:

1. `relevant`: true if the opinion bears on compensated occupancy of another's dwelling or rooms,
   its legal character, or its regulation; false otherwise (commercial leases of shops or farms,
   mortgage foreclosures, hotel torts with no letting question, "boarder" as incidental colour).
2. If relevant: `polarity` (favorable | adverse | mixed, judged from the OWNER's freedom to let;
   mixed only when both sides are holdings, otherwise follow the holding) and `who_was_letting`
   (householder | commercial_operator | non_resident_owner | unclear).

Each entry carries a one-line `note` quoting the fact in the opinion that decides it.

## Output

A JSON list. Relevant: exactly three entries, `{"case_id": <id>, "field": "relevant", "decision":
"set", "value": true, "note": "..."}`, then the same shape for `polarity` and `who_was_letting`.
Not a letting case: exactly one entry with `"field": "relevant", "value": false`. Unreadable
text: exactly one entry `{"case_id": <id>, "field": "relevant", "decision": "unresolved", "note":
"..."}`. Never `keep`, `adopt` or `unsure`; commit to a value.
