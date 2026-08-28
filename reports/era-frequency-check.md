# Era-partition frequency check (Amendment A8) — 2026-08-28

Seed-term document frequencies per era partition, from the raw FTS index
over 1.75M non-duplicate-inclusive docs (four states). Run:
`python pipeline/kwic.py freq ...` after full ingest.

| term | pre-1860 | 1860-1900 | 1900-1930 | 1930-1970 | 1970-2020 |
|---|---|---|---|---|---|
| lodger | 24 | 80 | 64 | 45 | 38 |
| boarder | 39 | 170 | 207 | 131 | 120 |
| roomer | 0 | 0 | 46 | 109 | 40 |
| sojourner | 22 | 24 | 32 | 10 | 80 |
| boarding house | 133 | 490 | 782 | 323 | 205 |
| lodging house | 6 | 84 | 199 | 86 | 51 |
| furnished rooms | 1 | 46 | 54 | 33 | 9 |
| paying guests | 0 | 0 | 3 | 23 | 29 |
| tourist home | 0 | 0 | 0 | 16 | 29 |
| transient guests | 4 | 11 | 44 | 19 | 24 |
| taking in lodgers | 0 | 0 | 0 | 1 | 0 |
| roomers and boarders | 0 | 0 | 4 | 12 | 0 |
| incident of ownership | 10 | 33 | 29 | 48 | 47 |
| short-term rental | 0 | 0 | 0 | 0 | 26 |

## Findings

1. **The vocabulary-drift thesis is confirmed in-corpus.** "roomer" is a
   zoning-era word (peaks 1930-1970); "tourist home"/"paying guests" begin
   ~1900-1930; "short-term rental" exists only 1970-2020. Modern-vocabulary
   search over the historical strata would find nothing — as argued.
2. **Era boundaries hold for v1.** Term regimes align with the partitions
   (antebellum sparse; lodging economy 1860-1930; zoning vocabulary
   1900-1970). No re-cut proposed; revisit after cycle-001 extraction data.
3. **"taking in lodgers" has ONE exact-phrase hit in four states** — the
   flagship spec phrase is rare on the ground. Selector design must lean on
   variant ORs, NEAR queries, and embedding selectors, as v1 does.
4. **"sojourner" spikes 1970-2020 (80)** — likely proper-name/biblical usage
   (e.g., "Sojourner Truth", org names), confirming the CHANGELOG's
   precision concern; era scope on sojourner-19 (pre-1900 only) is right.
5. Aggregate FTS yield across seed vocabulary is roughly 3-5k candidate
   cases before embedding selectors — comfortably above the 40-batch cap;
   signal-density prioritization will matter from cycle one.
