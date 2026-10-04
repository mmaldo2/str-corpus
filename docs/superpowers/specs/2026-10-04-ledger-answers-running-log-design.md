# Ledger answers and the running log (Gluck part 1) — design

Date: 2026-10-04. Status: approved in brainstorm (user), section by section. Part 1 of the work
on the attorney collaborator's questions; part 0 (readiness) is merged; parts 2-4 (codebook v4,
a new reading cycle, non-case sources) get their own specs. The repository is public: the
question definitions, the answers and anything tied to the collaborator's own writing stay in a
gitignored folder; this spec and the code are generic.

## 1. Goal

Answer the first five questions from the existing ledger, with no new reading, as entries in a
running log the collaborator can browse, comment on and ask about later. Every answer is
reproducible (stamped with the ledger seq, the date and the code commit), reports human-reviewed
and machine-only counts separately, breaks down by jurisdiction and era, and lists the cases with
every citation of the decision, preferred citation first.

## 2. Non-goals and standing rules

- No reading, no codebook change, no ledger writes.
- Two-tier counts are never blended (ADR-0002); `TierCount` already refuses `int()` and `+`.
- No dollar figures anywhere in the log.
- Question definitions and outputs live in `reports/gluck/` (`.gitignore` gains that line); only
  the engine is in git.
- Out of part 1: importing the collaborator's review columns (a later step, with reviewer identity
  per decision); re-picking which merged copy is canonical (section 10); any new selector.

## 3. Population and the case row

**Population:** counted records only — `relevant` true, in the cycle files, no `duplicate_of`
(the same rule as `tally._population`). Era is derived from `year` with the domain's era bounds.

**Case row** (one per decision; CSV column order):
`case_name`, `citations` (preferred first, `; `-joined), `year`, `era`, `jurisdiction`, `court`,
`who_was_letting`, `polarity`, `characterization`, `owner_freedom_characterization`,
`duration_of_occupancy`, `under_thirty_days`, `restriction_nature`, `holding_summary`,
`quote` (the first verified quote) and `quote_page` (its `reporter_page`), `review_tier`
(`human-reviewed` | `machine-only`, from `LedgerView.reviewed_ids()`), `case_id`, then four
blank columns for the collaborator: `reviewer_verdict` (agree | withdraw | correct),
`reviewer_field`, `reviewer_value`, `reviewer_note`.

Case name and court come from the corpus (`cases.name_abbreviation`, `cases.court`).

**Citation set:** the record's own cite; CAP's `citations` rows for that case (types
`parallel`, `nominative`, `vendor`); and the cites (with their `citations` rows) of every case
merged into it (`parallel_reports` loser -> winner). Order: first the cites whose reporter is on
the jurisdiction's preference list, in list order; then the rest alphabetically. The preference
lists live in `domains/str-right-to-let/domain.yaml` under `citation_preference`
(jurisdiction -> reporter abbreviations, official state reports first, e.g. N.Y.:
`N.Y.`, `N.Y.2d`, `A.D.`, `A.D.2d`, `Misc.`, `Misc.2d`, `Barb.`, then `N.Y.S.`, `N.Y. St. Rep.`).
The reporter of a cite is the text between the leading volume number and the trailing page.
CAP's `type = 'official'` label is not used: it marks each case's own cite in every reporter
(section 10).

## 4. The questions file

`reports/gluck/questions.yaml` (gitignored). Each question:

```yaml
- id: q1
  title: "<short title>"
  kind: records            # records | concordance
  population:              # every key ANDed; a list means any of
    polarity: [favorable]
    era: [pre-1860, 1860-1900]
    owner_freedom_characterization: [incident_of_ownership]
    who_was_letting: [householder, non_resident_owner]
  any_of:                  # optional OR block, each item a population mapping
    - duration_of_occupancy: [nights, weeks]
    - under_thirty_days: ["yes"]
  group_by: [characterization]          # the question's own grouping (summary table)
  earliest_per_jurisdiction: {restriction_nature: zoning}   # optional
  text_match:              # optional; turns the answer into a review list
    terms: ["season*", "summer", "cottage", "\"furnished house\""]
    in: [quotes, holding_summary, opinion]
  review_list: true        # optional; labels the answer "candidates for review, not a finding"
```

`text_match` keeps a population record when any term matches its quotes or holding summary
(case-insensitive; a trailing `*` is a prefix) or, with `opinion` listed, its opinion text through
FTS (`fts_raw` `MATCH`, restricted to the population's case ids).

Validation before any output: field names must be ledger record fields or `era`; values must be in
the mapper-v3 vocabulary (the `*_VALUES` constants the reader's response schema is built from,
`corpus_engine/reader/schema.py`) or the domain's era labels;
`group_by` fields likewise; an unknown key is an error. A typo can never yield a silently empty
answer.

**The five shipped definitions** (in the gitignored file; described here generically):
1. Favorable, pre-1860 and 1860-1900, owner freedom framed as an incident of ownership, letting
   tier householder or non-resident owner; grouped by characterization.
2. Favorable, and (duration nights or weeks, or under-thirty-days yes); grouped by era and
   letting tier.
3. Adverse; grouped by restriction nature and era; plus the earliest adverse zoning record per
   jurisdiction. The answer states that the codebook cannot yet express outright prohibition.
4. Concordance (section 5): "transient" near lodging terms; "thirty days" near occupancy, guest or
   hotel; "tourist home"; "short-term" / "short term".
5. Favorable, letting tier non-resident owner, with seasonal or whole-dwelling terms in the quotes,
   the holding summary or the opinion text; a review list, not a finding.

## 5. Concordance

`corpus_engine/concordance.py` (new, tested) holds the logic; `pipeline/kwic.py` stays the CLI and
gains:
- `--expr`: a raw FTS5 expression passed unquoted (`NEAR(transient lodging, 10)`, `lodg*`, `OR`);
  without it a multi-word term is quoted as a phrase, as today.
- `--stem`: use `fts_porter` instead of `fts_raw`.
- `freq --jur` and `freq --by jurisdiction` (era x jurisdiction grid).
- `--rate`: matches per 1,000 canonical opinions in the cell; denominators from one
  `GROUP BY era_partition, jurisdiction` over canonical cases per run (minutes on the live corpus).
- `earliest`: the N earliest canonical opinions matching, with year, cite, jurisdiction and one
  context line.

A concordance answer reports, per term: counts and rates by era, by era x jurisdiction, and the
five earliest uses. Matching is over canonical cases only (`is_duplicate_of IS NULL`).

## 6. Answer outputs

`tools/gluck_log.py run --question q1` (or `--all`) and `list`. Per run:
`reports/gluck/out/<YYYY-MM-DD>-<id>-<slug>/` with:
- `answer.html`: title; stamp (ledger seq, date, code commit, questions-file sha); the method line
  (the filter in plain words); summary tables (two-tier, jurisdiction x era, and the question's
  grouping); for review lists the "candidates for review, not a finding" label; the reading
  (section 8) when present; the standing caveats in one fixed wording:
  counts are lower bounds; machine-only precision is unmeasured until the audit is applied;
  nothing is citable before a citator check and a page-image pin-cite check.
- `cases.csv` (section 3 columns; UTF-8, LF).
- `summary.json` (the counts, the stamp, the filter) for later comparison between runs.
`reports/gluck/log.md` lists every run: id, title, stamp, output folder, and the Drive links once
published.

## 7. Publishing to Drive

Publishing is done by the agent with the Google Drive connector, not by the tool (a Python script
cannot call it):
- A "Gluck log" folder in the user's Drive, created once; the user shares it with the collaborator
  (or tells the agent to, via the share tool).
- Per answer: a Google Doc from `answer.html` and a Google Sheet from `cases.csv`, titled
  `<Qn> · <title> · seq <N> · <date>`; their ids go into `log.md`.
- The connector cannot edit a file in place: a re-run adds new dated files, and the superseded
  ones move to an "Older" subfolder.

## 8. The reading

Each answer may carry one short paragraph, "what this shows and what it does not", written by the
agent into `reports/gluck/readings/<id>.md` and included in `answer.html`. The data and tables
carry no interpretation. A reading gets one independent fact-check before it is published,
recorded in `reports/gluck/factcheck.md` (the project's standard for lawyer-facing material:
consistent, broad, not pedantic).

## 9. Testing

- Questions-file validation: unknown field, unknown value, unknown key, bad `group_by` -> error
  naming the problem.
- Population: copies with `duplicate_of`, irrelevant reads and out-of-file records excluded;
  two-tier counts never blended.
- Each filter shape (`population`, `any_of`, `era`, `earliest_per_jurisdiction`, `text_match`) on
  a temporary ledger and store.
- Citations: preference order; merged copies' cites included; a reprint never placed ahead of a
  listed official state report; unknown reporters after listed ones.
- Outputs: CSV header and blank reviewer columns; `answer.html` has the stamp, method line and
  caveats; `summary.json` round-trips.
- Concordance on the fixture corpus: `--expr` NEAR and prefix, `--stem`, `--jur`, `--by
  jurisdiction`, rates with denominators, `earliest`.
- Live smoke (skipped without the corpus): question 1 against the real ledger yields a non-empty
  two-tier summary.

## 10. Note: CAP's "official" label

CAP types each case's own cite `official` in every reporter (`2 N.Y. Crim. 539` and
`12 N.Y. St. Rep. 783` included), so the merge winner rule's "official reporter" tie-break
(readiness spec 6.4, rule 3) never decided anything: with no ledger copy, the lowest `case_id`
won. Reading is unaffected (same opinion text); citation display is handled by section 3's
preference order. Re-picking canonical copies by reporter is parked.

## 11. Parked

- Importing the collaborator's review columns into the ledger (needs reviewer identity per
  decision).
- Re-picking canonical copies by reporter preference (section 10).
- Bluebook formatting and string cites.
