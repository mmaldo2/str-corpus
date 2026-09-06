r"""Turn a finished map into ledger patches (spec section 8, D9).

Offline: it reads the map manifest, the batch files, the response cache and the store, and
makes no request of any kind. It is the ONLY thing in this slice that writes the ledger; the
map runner never does, so a map can be re-read and re-admitted independently.

  .venv\Scripts\python tools\admit_map.py --dry-run
  .venv\Scripts\python tools\admit_map.py --apply

`--dry-run` folds the whole patch set onto a deep copy of the ledger's head state, prints the
per-cell admit counts and the published counts before and after, and writes nothing at all.
`--apply` refuses a run id that already has patches in the ledger unless `--force`: every
admission appends `review.notes` lines, so a second pass under the same id would duplicate
the reader's note and the checker's verdict on every record the first pass admitted.
"""
from __future__ import annotations
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                  # noqa: E402
from corpus_engine.domain import load_domain                                     # noqa: E402
from corpus_engine.ledger import LedgerView, open_ledger                         # noqa: E402
from corpus_engine.ledger.fold import apply_patch                                # noqa: E402
from corpus_engine.mapper.admit import (basis_for, counts_by_cell, patches_for,  # noqa: E402
                                        records_from_manifest)
from corpus_engine.mapper.cells import BatchSource                               # noqa: E402
from corpus_engine.reader.cache import ResponseCache                             # noqa: E402
from corpus_engine.reader.codebook import load_codebook                          # noqa: E402
from corpus_engine.reader.providers.factory import cli_pin                       # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                         # noqa: E402

RUN_ID = "cycle-004-shard-01"


def run_id_already_applied(view, run_id: str) -> bool:
    """Whether this run id already has patches in the ledger. Refused by default: a second
    admission would re-append every `review.notes` line the first one wrote."""
    return any(p.basis.run_id == run_id for p in view.patches)


def _view_with(view: LedgerView, patches, judged) -> LedgerView:
    """The view this patch set WOULD produce, folded onto a deep copy of head. Never handed
    back to a caller that writes: it exists so `--dry-run` can print an after-count."""
    trial = copy.deepcopy(view.state)
    for p in patches:
        apply_patch(trial, p, judged=tuple(judged), cascade=p.cascade)
    return LedgerView(view.name, view.as_of, trial, list(view.patches) + list(patches),
                      view.domain)


def _summary(view: LedgerView) -> str:
    """The published counts, and only through `view.counts()` - two-tier, never blended by
    this tool (ADR-0002)."""
    rel = view.counts().total
    fav = view.counts(polarity="favorable").total
    hh = view.counts(polarity="favorable", who_was_letting="householder").total
    return (f"relevant {rel.as_claim('records')} | favorable {fav.as_claim('records')} | "
            f"favorable householder {hh.as_claim('records')}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="admit_map.py", description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--manifest", default=None, help="default: runs/<run-id>/map-manifest.json")
    ap.add_argument("--batches", default=None, help="default: runs/<run-id>/batches")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the per-cell counts and the published counts before/after, and "
                         "write nothing")
    ap.add_argument("--apply", action="store_true", help="write the patches to the ledger")
    ap.add_argument("--force", action="store_true",
                    help="admit even though this run id already has patches in the ledger")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if a.dry_run == a.apply:
        sys.exit("pass exactly one of --dry-run or --apply")

    dom = load_domain()
    run_dir = ROOT / "runs" / a.run_id
    manifest_path = Path(a.manifest) if a.manifest else run_dir / "map-manifest.json"
    if not manifest_path.exists():
        sys.exit(f"no map manifest at {manifest_path}; nothing to admit")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cb = load_codebook(dom, manifest["codebook_id"])
    if cb.sha != manifest["codebook_sha"]:
        sys.exit(f"the codebook on disk ({cb.sha[:12]}) is not the one this map was read under "
                 f"({str(manifest['codebook_sha'])[:12]}); admitting would re-gate against a "
                 f"different codebook")
    conn = store.connect(ROOT / "data" / "db" / "corpus.db")
    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    pin = cli_pin(dict(dom.reader.model))
    batches = Path(a.batches) if a.batches else run_dir / "batches"
    admitted = records_from_manifest(manifest, batch_source=BatchSource(batches), cache=cache,
                                     codebook=cb, cases=StoreCaseSource(conn), pin=pin,
                                     families=dom.reader.families)
    patches = patches_for(admitted, manifest=manifest)
    led = open_ledger(domain=dom)
    head = led.view()
    if not a.force and run_id_already_applied(head, a.run_id):
        sys.exit(f"run-id {a.run_id!r} already has patches in the ledger; admitting again would "
                 f"re-append every review.notes line the first admission wrote. Pass --force "
                 f"only if that is really what you want.")
    print(f"basis {basis_for(manifest)}", flush=True)
    print(f"{len(admitted)} accepted records -> {len(patches)} patches", flush=True)
    for cell_key, row in sorted(counts_by_cell(admitted).items()):
        print(f"  {cell_key}: {row['records']} records "
              f"({row['relevant']} relevant, {row['irrelevant']} irrelevant)", flush=True)
    print(f"before: {_summary(head)}", flush=True)
    if a.dry_run:
        print(f"after:  {_summary(_view_with(head, patches, dom.judged_fields))}", flush=True)
        res = led.apply(patches, note=f"{a.run_id} map admission", dry_run=True)
        print(f"{len(res.applied)} would apply, {len(res.skipped)} already present (dry run)",
              flush=True)
        return 0
    res = led.apply(patches, note=f"{a.run_id} map admission")
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}", flush=True)
    print(f"after:  {_summary(led.view())}", flush=True)
    return 0 if res.replay_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
