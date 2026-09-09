r"""Re-read the relevant records of cycles 001-003 under mapper-v3 (spec section 6, D7/D8).

Two invocations, and only one of them costs anything:

  .venv\Scripts\python tools\reread_records.py --plan          # offline: the ids and the pool
  .venv\Scripts\python tools\reread_records.py --dry-run-batches 2
  .venv\Scripts\python tools\reread_records.py --max-wall-seconds 21600

`--plan` reads the ledger view and one SELECT and writes `case-ids.json` plus the batch files;
it constructs no provider. The read walks those batches through the SAME `MapRunner`, `Reader`,
response cache and Codex checker sample the map uses, so the manifest it writes is a
`map-manifest-v1` document and `tools/admit_map.py --reread` can re-derive every record from
the cache offline. Re-running the same command is how a re-read is resumed.

The cells are uncapped and the yield floor is switched off (`--threshold -1`): every one of the
693 records is already known relevant, so a quiet unit is not evidence that a cell has stopped
paying, and stopping early would leave old records short of the mapper-v3 fields this exists to
fill.

It never writes the ledger. `tools/admit_map.py --reread` is the admission (D9), and it is the
piece that keeps a re-read off a human decision.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                     # noqa: E402
from corpus_engine.domain import load_domain                                        # noqa: E402
from corpus_engine.ledger import open_ledger                                        # noqa: E402
from corpus_engine.mapper.cells import BatchSource, Cell, load_batches              # noqa: E402
from corpus_engine.mapper.runner import (DEFAULT_MAX_WALL_SECONDS, MapRunner,       # noqa: E402
                                         RunnerCaps, default_max_units)
from corpus_engine.mapper.yield_stop import WINDOW                                  # noqa: E402
from corpus_engine.reader.cache import ResponseCache                                # noqa: E402
from corpus_engine.reader.codebook import load_codebook                             # noqa: E402
from corpus_engine.reader.driver import Reader                                      # noqa: E402
from corpus_engine.reader.model import ModelPin                                     # noqa: E402
from corpus_engine.reader.providers.codex_cli import CodexCliProvider               # noqa: E402
from corpus_engine.reader.providers.factory import READ_TIMEOUT, provider_for       # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                            # noqa: E402
from corpus_engine.store import case_partitions                                     # noqa: E402
from corpus_engine.textnorm_version import NORM_VERSION                             # noqa: E402

RUN_ID = "cycles-001-003-reread"
CYCLES = ("cycle-001", "cycle-002", "cycle-003")
STORE_NORM_VERSION = f"v{NORM_VERSION}"
UNIT_SIZE = 18
# The line the manifest prints to resume this run. `MapRunner` spells the map's tool by
# default, and a re-read that told its operator to re-run `tools\map_reader.py` would send
# them at the cycle-004 pool.
RESUME_TOOL = "tools\\reread_records.py"
# `CellProgress.should_stop` fires when the window's relevant-accepted count is <= threshold.
# A count is never negative, so -1 is "never stop on yield" - stated as a constant rather than
# left as a magic argument, because switching the stop rule off is a decision (D7), not a knob.
NO_YIELD_STOP = -1
DRY_RUN_FIELDS = ("unit_id", "status", "cache_hit", "retried", "finish_reason", "status_counts",
                  "dropped_quotes", "nulled_fields", "relevant_accepted", "checker", "error")


def relevant_case_ids(view, cycles=CYCLES) -> list[int]:
    """The re-read scope (D7): every case admitted in those cycles that still stands relevant.
    Irrelevant records are not re-read - there is nothing in them to fill."""
    return sorted(cid for cid in view.state.order
                  if view.state.cycles.get(cid) in cycles
                  and view.state.in_file.get(cid)
                  and view.state.records[cid].get("relevant"))


def plan_batches(case_ids, meta, *, run_id: str, size: int = UNIT_SIZE) -> list[dict]:
    """18-case units, in case-id order, one unit per batch.

    Grouped by CELL first. A batch carries one `era_partition` and one `jurisdiction` -
    `render_unit` puts them in the prompt header and `admit._unit_for` reads them as scalars -
    so a unit spanning two cells would be a prompt that lies about what it holds. A case with
    no live store row (a duplicate marked since it was admitted) is left out; the caller
    compares the planned count against the scope.

    `signals` is empty: a re-read asks about a record the corpus already holds, and there is no
    retrieval provenance to show for it."""
    by_cell: dict[tuple[str, str], list[int]] = {}
    for cid in sorted(case_ids):
        if cid in meta:
            by_cell.setdefault(tuple(meta[cid]), []).append(int(cid))
    out: list[dict] = []
    n = 0
    for era, jur in sorted(by_cell):
        ids = by_cell[(era, jur)]
        for i in range(0, len(ids), size):
            n += 1
            out.append({"batch_id": f"{run_id}-batch-{n:03d}", "ranker_id": "",
                        "era_partition": era, "jurisdiction": jur,
                        "cases": [{"case_id": c, "era_partition": era, "jurisdiction": jur,
                                   "signals": []} for c in ids[i:i + size]]})
    return out


def reread_cells(batches) -> list[Cell]:
    """One uncapped cell per (era, jurisdiction), in key order. There are no rank scores to
    order by - these records are already in the corpus - so the order is the cell key's, which
    is at least the same on every machine."""
    by_cell: dict[tuple[str, str], list[str]] = {}
    for b in batches:
        by_cell.setdefault((b["era_partition"], b["jurisdiction"]), []).append(b["batch_id"])
    return [Cell(era, jur, tuple(sorted(ids)), len(ids), 0.0, uncapped=True)
            for (era, jur), ids in sorted(by_cell.items())]


def write_json(path: Path, doc) -> None:
    """LF, UTF-8, one trailing newline - explicit bytes, like every other artefact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))


def checker_pin(dom) -> ModelPin | None:
    c = dom.reader.checker
    return ModelPin(c["model_id"], c["family"], extra={"cli_model": c["cli_model"]}) if c else None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reread_records.py", description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--plan", action="store_true",
                    help="write case-ids.json and the batch files and stop; buys nothing")
    ap.add_argument("--dry-run-batches", type=int, default=None,
                    help="read the first N batches, print the parse / gate / checker "
                         "diagnostics, and stop")
    ap.add_argument("--max-units", type=int, default=None)
    ap.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    ap.add_argument("--sample-pct", type=int, default=None,
                    help="checker sample percentage (default: domain.yaml's checker_sample_pct)")
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    if a.dry_run_batches is not None and a.dry_run_batches < 1:
        sys.exit(f"--dry-run-batches {a.dry_run_batches} buys nothing; pass 1 or more")

    def log(msg):
        print(msg, flush=True)

    dom = load_domain()
    run_dir = ROOT / "runs" / a.run_id
    batches_dir = run_dir / "batches"
    if a.plan:
        view = open_ledger(domain=dom).view()
        ids = relevant_case_ids(view)
        conn = store.connect(ROOT / "data" / "db" / "corpus.db")
        meta = case_partitions(conn, ids)
        batches = plan_batches(ids, meta, run_id=a.run_id)
        write_json(run_dir / "case-ids.json",
                   {"run_id": a.run_id, "cycles": list(CYCLES), "as_of": view.as_of,
                    "case_ids": ids})
        batches_dir.mkdir(parents=True, exist_ok=True)
        for old in batches_dir.glob("batch-*.json"):
            old.unlink()
        for n, b in enumerate(batches, 1):
            write_json(batches_dir / f"batch-{n:03d}.json", b)
        planned = sum(len(b["cases"]) for b in batches)
        log(f"{len(ids)} relevant records in {', '.join(CYCLES)}; {planned} planned into "
            f"{len(batches)} batches over {len(reread_cells(batches))} cells -> {batches_dir}")
        if planned != len(ids):
            log(f"WARNING: {len(ids) - planned} cases have no live store row and are not in "
                f"the pool")
        return 0

    if not batches_dir.is_dir():
        sys.exit(f"no pool to read: {batches_dir} does not exist; run --plan first")
    batches = load_batches(batches_dir)
    cells = reread_cells(batches)
    if a.dry_run_batches is not None:
        first = cells[0]
        cells = [Cell(first.era, first.jurisdiction, first.batch_ids[:a.dry_run_batches],
                      min(a.dry_run_batches, first.cap_batches), 0.0, uncapped=True)]
        log(f"dry run: its cells are MERGED into {run_dir / 'map-manifest.json'}")

    cb = load_codebook(dom, dom.reader.codebook)
    provider, pin, why = provider_for(dict(dom.reader.model))
    if provider is None:
        sys.exit(f"cannot run the re-read: {why}")
    log(f"reader {pin.label}: {why}")
    checker = CodexCliProvider(dom.reader.checker["cli_model"]) if dom.reader.checker else None
    if checker is not None and not checker.is_available():
        sys.exit("codex cli not available; the checker sample is part of the read (D5)")
    conn = store.connect(ROOT / "data" / "db" / "corpus.db")
    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    source = StoreCaseSource(conn)
    caps = RunnerCaps(max_units=a.max_units if a.max_units is not None
                      else default_max_units(cells), max_wall_seconds=a.max_wall_seconds)
    sample_pct = a.sample_pct if a.sample_pct is not None else dom.reader.checker_sample_pct
    log(f"{len(cells)} cells, {sum(c.cap_batches for c in cells)} batches, "
        f"caps: {caps.max_units} reader units / {caps.max_wall_seconds:.0f} s, "
        f"yield stop OFF (threshold {NO_YIELD_STOP})")

    def factory():
        return Reader(provider, source, checker=checker, cache=cache, log=log, domain=dom,
                      store_norm_version=STORE_NORM_VERSION)

    runner = MapRunner(factory, cells, batch_source=BatchSource(batches_dir), cache=cache,
                       manifest_path=run_dir / "map-manifest.json", caps=caps, log=log,
                       codebook=cb, pin=pin,
                       checker_pin=checker_pin(dom) if checker is not None else None,
                       sample_pct=sample_pct,
                       run_id=a.run_id, extractions_dir=run_dir / "extractions",
                       window=WINDOW, threshold=NO_YIELD_STOP, depth_column="0.25",
                       era_depth={}, screen=None, families=dom.reader.families,
                       read_timeout_seconds=READ_TIMEOUT, resume_args=argv,
                       resume_tool=RESUME_TOOL,
                       flags={"reread": True, "dry_run_batches": a.dry_run_batches,
                              "sample_pct": sample_pct})
    try:
        out = runner.run()
    except KeyboardInterrupt:
        log(f"interrupted; the manifest of what was bought is {run_dir / 'map-manifest.json'}")
        return 130
    t = out.manifest["totals"]
    log(f"stop={out.stop} batches={t['batches_completed']} cases={t['cases_read']} "
        f"relevant={t['relevant_accepted']} irrelevant={t['irrelevant_accepted']} "
        f"failed={t['failed_units']} cases_lost={t['cases_lost']} units={out.units} "
        f"checker_units={out.manifest['process']['checker_units']} "
        f"wall={out.wall_seconds:.0f}s")
    if a.dry_run_batches is not None:
        for key in [c.key for c in cells if c.key in out.manifest["cells"]]:
            for unit in out.manifest["cells"][key]["units"]:
                log(json.dumps({f: unit[f] for f in DRY_RUN_FIELDS}, sort_keys=True))
    log(f"resume: {out.resume_command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
