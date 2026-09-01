---
status: accepted
date: 2026-09-01
---

# The tradition matrix is the definition of done

The spec defined when sprint one was finished but never when the corpus
itself was; the only stopping rule in play was "precision has decayed."
We decided that the record is done when the tradition matrix (favorable
cases by era partition, region, letting tier, and duration) has no empty
cells at an agreed minimum count, with the gold-set recall gate as a
per-cycle guard and cycle-over-cycle convergence as a diagnostic only.

## Considered options

- Recall above a threshold plus precision below a floor: measures the
  method, not the showing a brief needs.
- Budget or calendar: arbitrary and indefensible under cross-examination.
- Convergence (a cycle adds no new doctrines): useful signal, but a
  corpus can converge while the founding era stays empty.

## Consequences

The matrix must be a first-class artifact derived from the ledger by one
function, not reconstructed by hand in reports. As of 2026-09-01 the
pre-1860 cells hold 2 favorable householder cases across four states,
which is why corpus scope (ADR-0008) now favors founding-era depth.
