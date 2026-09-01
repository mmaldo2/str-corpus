---
status: accepted
date: 2026-09-01
---

# The citation graph comes from the CAP volume metadata, stored at ingest, and drives a one-hop selector

The corpus had no citation graph: the citations table holds each case's own
reporter citations, not the cases it cites. Building one with a citation
parser over 1.3M OCR opinions would be slow and error-prone. We found that
every raw volume's CasesMetadata.json already carries a resolved cites_to
list with CAP case ids, plus PageRank and OCR confidence. We decided to
store cites_to, PageRank, and OCR confidence as a permanent ingest stage,
backfill the existing corpus from the raw directory through the same code
path, and add a citation-graph selector type: one hop, both directions,
seeded from human-reviewed favorable records plus treatise anchors, with the
seed-set hash recorded in the coverage matrix so the expansion is
reproducible.

## Considered options

- eyecite over opinion text: needed only for sources without a resolved
  graph (English Reports, CourtListener post-2020), where it remains the
  fallback.
- Two hops: explodes on New York; one hop plus iteration across cycles gets
  the same reach with reviewable steps.
- Seed from all favorable records: would propagate machine-only errors.

## Consequences

PageRank becomes a free batch-priority signal. Citation expansion is the
mechanism that reaches pre-1860 cases through their later citations, and
the research literature ranks it second only to relevance feedback for
recall gain per unit cost.
