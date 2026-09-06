r"""Read the cycle-004 candidate pool under the per-cell budget (spec section 6, D6/D9).

One detached process per invocation. It stops on its own unit or wall-clock ceiling, writes
the manifest from a finally, prints the resume line, and buys nothing the response cache
already holds - so re-running the SAME command is how a map is resumed.

It never writes the ledger. Admission is a separate tool over the same cache (D9).

The reader is the pinned subscription model, resolved from domain.yaml through
`provider_for(dict(dom.reader.model))` alone: this tool never constructs an OpenRouter
provider, never reads the credits endpoint and never needs a key (R1). The Codex checker is
sampled at domain.yaml's `checker_sample_pct`, and its calls are counted apart from the
reader units `--max-units` governs (R11).

  .venv\Scripts\python tools\map_reader.py --dry-run-batches 2 --cells "1930-1970|N.Y."
  .venv\Scripts\python tools\map_reader.py --max-wall-seconds 21600
"""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import replace as _replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                     # noqa: E402
from corpus_engine.domain import load_domain                                        # noqa: E402
from corpus_engine.mapper.cells import (DEPTH_COLUMNS, BatchSource, build_cells,    # noqa: E402
                                        load_batches, select_cells)
from corpus_engine.mapper.runner import (DEFAULT_MAX_WALL_SECONDS, MapRunner,       # noqa: E402
                                         RunnerCaps, default_max_units)
from corpus_engine.mapper.yield_stop import THRESHOLD, WINDOW                       # noqa: E402
from corpus_engine.reader.cache import ResponseCache                                # noqa: E402
from corpus_engine.reader.codebook import load_codebook                             # noqa: E402
from corpus_engine.reader.driver import Reader                                      # noqa: E402
from corpus_engine.reader.model import ModelPin                                     # noqa: E402
from corpus_engine.reader.providers.codex_cli import CodexCliProvider               # noqa: E402
from corpus_engine.reader.providers.factory import READ_TIMEOUT, provider_for       # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                            # noqa: E402
from corpus_engine.textnorm_version import NORM_VERSION                             # noqa: E402

RUN_ID = "cycle-004-shard-01"
STORE_NORM_VERSION = f"v{NORM_VERSION}"
# Printed for a dry run: the per-unit facts that say whether the read is working at all -
# did it parse, did the gate keep the quotes, did the checker agree.
DRY_RUN_FIELDS = ("unit_id", "status", "cache_hit", "retried", "finish_reason", "status_counts",
                  "dropped_quotes", "nulled_fields", "relevant_accepted", "checker", "error")


def checker_pin(dom) -> ModelPin | None:
    c = dom.reader.checker
    if not c:
        return None
    return ModelPin(c["model_id"], c["family"], extra={"cli_model": c["cli_model"]})


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="map_reader.py", description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--cells", default=None,
                    help='limit the run to these cells, "era|jurisdiction[,...]". The order is '
                         'always the cells\' own order, never the order they are typed in.')
    ap.add_argument("--dry-run-batches", type=int, default=None,
                    help="read the first N batches of the FIRST selected cell, print the parse / "
                         "gate / schema / checker diagnostics, and stop. Buys N units into the "
                         "same cache the full run replays for free.")
    ap.add_argument("--max-units", type=int, default=None,
                    help="READER-request ceiling for this PROCESS, checked between batches "
                         "(default: the selected cells' caps plus 10%%, printed before the run "
                         "starts). NOT exact: one read can buy the unit plus two split halves, "
                         "so a run can exceed it by at most 2 requests, once, when the last "
                         "batch it begins will not parse. Checker requests are counted "
                         "separately and are never capped by it.")
    ap.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--depth-column", default="0.25", choices=sorted(DEPTH_COLUMNS))
    ap.add_argument("--sample-pct", type=int, default=None,
                    help="checker sample percentage (default: domain.yaml's checker_sample_pct)")
    ap.add_argument("--screen", action="store_true",
                    help="run the fallback-reader relevance screen over a cell that stopped on "
                         "yield with cap remaining (D10). OFF by default and NOT implemented in "
                         "this slice: the flag is accepted, recorded in the manifest, and "
                         "constructs no provider of any kind.")
    ap.add_argument("--screen-max-usd", type=float, default=5.0)
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    if a.dry_run_batches is not None and a.dry_run_batches < 1:
        sys.exit(f"--dry-run-batches {a.dry_run_batches} buys nothing; pass 1 or more, or omit it")

    def log(msg):
        print(msg, flush=True)

    dom = load_domain()
    cb = load_codebook(dom, dom.reader.codebook)
    run_dir = ROOT / "runs" / a.run_id
    batches_dir = run_dir / "batches"
    if not batches_dir.is_dir():
        sys.exit(f"no batches to map: {batches_dir} does not exist")
    cells = build_cells(load_batches(batches_dir), era_depth=DEPTH_COLUMNS[a.depth_column])
    try:
        cells = select_cells(cells, a.cells)
    except ValueError as exc:
        sys.exit(str(exc))
    if not cells:
        sys.exit("no cells selected")
    if a.dry_run_batches is not None:
        first = cells[0]
        cells = [_replace(first, cap_batches=min(a.dry_run_batches, first.cap_batches))]
    if a.cells or a.dry_run_batches is not None:
        log(f"subset run: its cells are MERGED into {run_dir / 'map-manifest.json'}, never "
            f"written over it")
    if a.screen:
        log("--screen is accepted but not implemented in this slice; no screen provider is "
            "constructed and nothing will be screened. The flag is recorded in the manifest.")

    provider, pin, why = provider_for(dict(dom.reader.model))
    if provider is None:
        sys.exit(f"cannot run the map: {why}")
    log(f"reader {pin.label}: {why}")
    checker = CodexCliProvider(dom.reader.checker["cli_model"]) if dom.reader.checker else None
    if checker is not None and not checker.is_available():
        sys.exit("codex cli not available; the checker sample is part of the map (D5)")

    conn = store.connect(ROOT / "data" / "db" / "corpus.db")
    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    source = StoreCaseSource(conn)
    caps = RunnerCaps(
        max_units=a.max_units if a.max_units is not None else default_max_units(cells),
        max_wall_seconds=a.max_wall_seconds)
    log(f"{len(cells)} cells, {sum(c.cap_batches for c in cells)} capped batches, "
        f"caps: {caps.max_units} reader units (+2 worst case, see --help) / "
        f"{caps.max_wall_seconds:.0f} s")

    def factory():
        return Reader(provider, source, checker=checker, cache=cache, log=log, domain=dom,
                      store_norm_version=STORE_NORM_VERSION)

    runner = MapRunner(factory, cells, batch_source=BatchSource(batches_dir), cache=cache,
                       manifest_path=run_dir / "map-manifest.json", caps=caps, log=log,
                       codebook=cb, pin=pin,
                       checker_pin=checker_pin(dom) if checker is not None else None,
                       sample_pct=(a.sample_pct if a.sample_pct is not None
                                   else dom.reader.checker_sample_pct),
                       run_id=a.run_id, extractions_dir=run_dir / "extractions",
                       window=a.window, threshold=a.threshold, depth_column=a.depth_column,
                       era_depth=DEPTH_COLUMNS[a.depth_column],
                       screen=None, families=dom.reader.families,
                       read_timeout_seconds=READ_TIMEOUT, resume_args=argv,
                       flags={"cells": a.cells, "dry_run_batches": a.dry_run_batches,
                              "screen": bool(a.screen), "screen_max_usd": a.screen_max_usd,
                              "sample_pct": (a.sample_pct if a.sample_pct is not None
                                             else dom.reader.checker_sample_pct)})
    try:
        out = runner.run()
    except KeyboardInterrupt:
        # The manifest was already written from the runner's finally; say where, and leave.
        log(f"interrupted; the manifest of what was bought is {run_dir / 'map-manifest.json'}")
        return 130
    t = out.manifest["totals"]
    log(f"stop={out.stop} cells={t['cells_read']} batches={t['batches_completed']} "
        f"cases={t['cases_read']} relevant={t['relevant_accepted']} "
        f"irrelevant={t['irrelevant_accepted']} failed={t['failed_units']} "
        f"units={out.units} (map total {t['units']}) "
        f"checker_units={out.manifest['process']['checker_units']} "
        f"wall={out.wall_seconds:.0f}s")
    if a.dry_run_batches is not None:
        log(f"DRY RUN schema_sha={out.manifest['schema_sha']} "
            f"codebook={out.manifest['codebook_id']}@{out.manifest['codebook_sha'][:12]} "
            f"effort={out.manifest['effort']} max_tokens={out.manifest['max_tokens']}")
        for key in out.manifest["cell_order"]:
            cell = out.manifest["cells"][key]
            log(f"DRY RUN {key}: {cell['records']} records, "
                f"{cell['relevant_accepted']} relevant, {cell['irrelevant_accepted']} irrelevant, "
                f"failures={cell['failures']}")
            for unit in cell["units"]:
                log(json.dumps({f: unit[f] for f in DRY_RUN_FIELDS}, sort_keys=True))
        log(f"  extractions -> {run_dir / 'extractions'}")
    log(f"resume: {out.resume_command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
