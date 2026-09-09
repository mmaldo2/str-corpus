# Ranker v2: held-out data/eval/ranker-heldout-v2.jsonl, three-way evaluation, ship rule

**Trained at commit `04a3659`.** Training set: 2331 positives / 4170 negatives, both frozen slices excluded. Cross-validated `C` = 0.01 (mean AP 0.9211).

## 1. The held-out slice

- Path: `data/eval/ranker-heldout-v2.jsonl` (sha256 `4146d442e311...`, pinned in domain.yaml as `heldout_v2_sha256`).
- Rows scored: 293. Every row is a human relevance decision (D3): human-reviewed relevant positives, reviewer-overturned negatives.
- Because every row is human-decided, the reviewed view (`reviewed or label == 0`) is the whole slice, so **ap_reviewed equals ap_all** here and D6's two-view test is arithmetically one view. That is a property of a slice made only of human labels, not a defect in the rule.

### Per-stratum counts

| era \| jurisdiction \| label | n |
|---|---|
| 1860-1900|Cal.|0 | 2 |
| 1860-1900|Cal.|1 | 3 |
| 1860-1900|Conn.|0 | 1 |
| 1860-1900|Conn.|1 | 3 |
| 1860-1900|D.C.|0 | 1 |
| 1860-1900|D.C.|1 | 1 |
| 1860-1900|La.|0 | 1 |
| 1860-1900|La.|1 | 2 |
| 1860-1900|Mass.|1 | 2 |
| 1860-1900|N.J.|0 | 3 |
| 1860-1900|N.J.|1 | 2 |
| 1860-1900|N.Y.|0 | 3 |
| 1860-1900|N.Y.|1 | 10 |
| 1860-1900|Ohio|1 | 1 |
| 1860-1900|Tex.|1 | 3 |
| 1900-1930|Cal.|0 | 2 |
| 1900-1930|Cal.|1 | 4 |
| 1900-1930|Conn.|0 | 3 |
| 1900-1930|Conn.|1 | 1 |
| 1900-1930|D.C.|0 | 1 |
| 1900-1930|D.C.|1 | 1 |
| 1900-1930|La.|0 | 2 |
| 1900-1930|La.|1 | 3 |
| 1900-1930|Mass.|0 | 2 |
| 1900-1930|Mass.|1 | 2 |
| 1900-1930|N.J.|0 | 2 |
| 1900-1930|N.J.|1 | 4 |
| 1900-1930|N.Y.|0 | 3 |
| 1900-1930|N.Y.|1 | 11 |
| 1900-1930|Ohio|0 | 2 |
| 1900-1930|Ohio|1 | 3 |
| 1900-1930|Pa.|0 | 2 |
| 1900-1930|Pa.|1 | 3 |
| 1900-1930|Tex.|0 | 5 |
| 1900-1930|Tex.|1 | 4 |
| 1930-1970|Cal.|0 | 4 |
| 1930-1970|Cal.|1 | 14 |
| 1930-1970|Conn.|0 | 1 |
| 1930-1970|Conn.|1 | 2 |
| 1930-1970|La.|0 | 2 |
| 1930-1970|La.|1 | 6 |
| 1930-1970|Mass.|1 | 6 |
| 1930-1970|N.J.|0 | 2 |
| 1930-1970|N.J.|1 | 8 |
| 1930-1970|N.Y.|0 | 3 |
| 1930-1970|N.Y.|1 | 16 |
| 1930-1970|Ohio|0 | 2 |
| 1930-1970|Ohio|1 | 8 |
| 1930-1970|Pa.|0 | 3 |
| 1930-1970|Pa.|1 | 7 |
| 1930-1970|Tex.|0 | 3 |
| 1930-1970|Tex.|1 | 4 |
| 1970-2020|Cal.|0 | 1 |
| 1970-2020|Cal.|1 | 9 |
| 1970-2020|Conn.|0 | 1 |
| 1970-2020|Conn.|1 | 5 |
| 1970-2020|D.C.|0 | 1 |
| 1970-2020|La.|0 | 1 |
| 1970-2020|La.|1 | 4 |
| 1970-2020|Mass.|0 | 1 |
| 1970-2020|Mass.|1 | 8 |
| 1970-2020|N.J.|0 | 1 |
| 1970-2020|N.J.|1 | 9 |
| 1970-2020|N.Y.|0 | 4 |
| 1970-2020|N.Y.|1 | 22 |
| 1970-2020|Ohio|0 | 1 |
| 1970-2020|Ohio|1 | 4 |
| 1970-2020|Pa.|0 | 2 |
| 1970-2020|Pa.|1 | 8 |
| 1970-2020|Tex.|0 | 1 |
| 1970-2020|Tex.|1 | 2 |
| pre-1860|Cal.|1 | 1 |
| pre-1860|La.|0 | 1 |
| pre-1860|La.|1 | 2 |
| pre-1860|Mass.|0 | 1 |
| pre-1860|Mass.|1 | 2 |
| pre-1860|N.J.|0 | 1 |
| pre-1860|N.J.|1 | 2 |
| pre-1860|N.Y.|0 | 3 |
| pre-1860|N.Y.|1 | 3 |
| pre-1860|Ohio|1 | 1 |
| pre-1860|Pa.|0 | 1 |
| pre-1860|Tex.|1 | 1 |

## 2. Average precision on the held-out slice

| Ranker | ap_all | ap_reviewed | p50_all | p200_all |
|---|---|---|---|---|
| classifier:v2 | 0.8274 | 0.8274 | 0.820 | 0.800 |
| classifier:v1 | 0.8319 | 0.8319 | 0.860 | 0.780 |
| fusion:v1 | 0.7860 | 0.7860 | 0.760 | 0.755 |

## 3. Ship rule (D6)

> classifier v2 ships as `ranking.default` only if its average precision exceeds fusion's on BOTH views (all held-out reads, human-reviewed reads). No margin.

- ap_all: 0.8274 vs fusion 0.7860 - passes
- ap_reviewed: 0.8274 vs fusion 0.7860 - passes

**Outcome: classifier:v2 SHIPS** under D6's rule as written, which compares the classifier against fusion only.

### What the rule does not compare, and the state of domain.yaml

D6's rule is classifier-against-fusion, and against fusion v2 wins on both views. Against **v1** it does not: classifier:v1 on the same slice scores **0.8319 vs v2's 0.8274** - v2 is 0.0045 BELOW the model it would replace (the table in section 2 has both numbers; this is the sentence they add up to).

The two numbers are not quite like for like. 32 of the 293 held-out v2 rows were labelled before v1 was trained, so v1 saw them as training data and its 0.8319 is mildly optimistic; v2 excluded both frozen slices, so its 0.8274 is clean. The gap is therefore smaller than it looks, and possibly the other way round - but it is not a measured v2 win, and nothing here measures it.

**`ranking.classifier_version` is NOT moved.** domain.yaml still pins `v1`, and the tail map runs on v1's ordering under the same budget unless and until the user decides otherwise. That key is the operative pin - `--ranker classifier:v2` does not override it (`load_ranker` now refuses a suffix that disagrees with it rather than silently loading v1) - so this report records a ship rule that passed and a ship that has not been made. The decision is the user's and is still open.

## 4. Per-cell AP (the evaluated classifier)

| Cell | n | ap | p50 |
|---|---|---|---|
| 1860-1900|Cal. | 5 | 0.9167 | 0.600 |
| 1860-1900|Conn. | 4 | 0.6389 | 0.750 |
| 1860-1900|D.C. | 2 | 1.0000 | 0.500 |
| 1860-1900|La. | 3 | 0.5833 | 0.667 |
| 1860-1900|Mass. | 2 | 1.0000 | 1.000 |
| 1860-1900|N.J. | 5 | 0.3667 | 0.400 |
| 1860-1900|N.Y. | 13 | 0.9273 | 0.769 |
| 1860-1900|Ohio | 1 | 1.0000 | 1.000 |
| 1860-1900|Tex. | 3 | 1.0000 | 1.000 |
| 1900-1930|Cal. | 6 | 0.6792 | 0.667 |
| 1900-1930|Conn. | 4 | 1.0000 | 0.250 |
| 1900-1930|D.C. | 2 | 0.5000 | 0.500 |
| 1900-1930|La. | 5 | 0.8667 | 0.600 |
| 1900-1930|Mass. | 4 | 0.7500 | 0.500 |
| 1900-1930|N.J. | 6 | 0.8042 | 0.667 |
| 1900-1930|N.Y. | 14 | 0.9488 | 0.786 |
| 1900-1930|Ohio | 5 | 0.8056 | 0.600 |
| 1900-1930|Pa. | 5 | 0.6389 | 0.600 |
| 1900-1930|Tex. | 9 | 0.8304 | 0.444 |
| 1930-1970|Cal. | 18 | 0.8924 | 0.778 |
| 1930-1970|Conn. | 3 | 0.8333 | 0.667 |
| 1930-1970|La. | 8 | 0.9484 | 0.750 |
| 1930-1970|Mass. | 6 | 1.0000 | 1.000 |
| 1930-1970|N.J. | 10 | 0.9415 | 0.800 |
| 1930-1970|N.Y. | 19 | 0.8709 | 0.842 |
| 1930-1970|Ohio | 10 | 0.8339 | 0.800 |
| 1930-1970|Pa. | 10 | 0.8598 | 0.700 |
| 1930-1970|Tex. | 7 | 0.7708 | 0.571 |
| 1970-2020|Cal. | 10 | 0.9060 | 0.900 |
| 1970-2020|Conn. | 6 | 0.8100 | 0.833 |
| 1970-2020|D.C. | 1 | 0.0000 | 0.000 |
| 1970-2020|La. | 5 | 0.8875 | 0.800 |
| 1970-2020|Mass. | 9 | 0.9318 | 0.889 |
| 1970-2020|N.J. | 10 | 0.9889 | 0.900 |
| 1970-2020|N.Y. | 26 | 0.8172 | 0.846 |
| 1970-2020|Ohio | 5 | 1.0000 | 0.800 |
| 1970-2020|Pa. | 10 | 0.8106 | 0.800 |
| 1970-2020|Tex. | 3 | 1.0000 | 0.667 |
| pre-1860|Cal. | 1 | 1.0000 | 1.000 |
| pre-1860|La. | 3 | 0.5833 | 0.667 |
| pre-1860|Mass. | 3 | 0.5833 | 0.667 |
| pre-1860|N.J. | 3 | 0.8333 | 0.667 |
| pre-1860|N.Y. | 6 | 0.7222 | 0.500 |
| pre-1860|Ohio | 1 | 1.0000 | 1.000 |
| pre-1860|Pa. | 1 | 0.0000 | 0.000 |
| pre-1860|Tex. | 1 | 1.0000 | 1.000 |

