from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from corpus_engine.indexer.embed import partition_runs
from corpus_engine.selector.coverage import covered, mark_covered
from corpus_engine.selector.model import (ENGINE_VERSION, Partition, PlanUnit, Selector, ShardPlan, ShardReport,
                                          SignalRef, Skip, load_selectors)
from corpus_engine.selector.packing import build_batches, pack_batches
from corpus_engine.selector.ports import fingerprint
from corpus_engine.selector.runners import RUNNERS, EngineContext
from corpus_engine.store import paths


def _already_read_ids_with_skips(runs_dir: Path, ledger_dir: Path, *, log=print) -> tuple[set[int], int]:
    """Collect case ids already read from extraction files and ledger manifests.

    Malformed input is skipped, not fatal: a non-list top-level JSON document or an
    unreadable/unparseable extraction file; an unparseable manifest line; a manifest
    record with no integer case_id. Each skipped item is logged once via `log` and
    counted; the count is returned alongside the ids so a caller (shard()) can record
    it in the run manifest.
    """
    ids: set[int] = set()
    skipped = 0
    for f in runs_dir.glob("*/extractions*/*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            skipped += 1
            log(f"WARN already_read_ids: skipping unreadable extraction file {f}: {type(e).__name__}: {e}")
            continue
        if not isinstance(data, list):
            skipped += 1
            log(f"WARN already_read_ids: skipping extraction file {f}: top-level JSON is not a list")
            continue
        for r in data:
            if not (isinstance(r, dict) and r.get("case_id") is not None):
                continue
            try:
                ids.add(int(r["case_id"]))
            except (TypeError, ValueError):
                skipped += 1
                log(f"WARN already_read_ids: skipping record with non-integer case_id in {f}")
    manifest_dir = ledger_dir / "manifest"
    for f in manifest_dir.glob("*.jsonl") if manifest_dir.exists() else []:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            skipped += 1
            log(f"WARN already_read_ids: skipping unreadable manifest file {f}: {type(e).__name__}: {e}")
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                log(f"WARN already_read_ids: skipping unparseable manifest line in {f}")
                continue
            cid = rec.get("case_id") if isinstance(rec, dict) else None
            if cid is None:
                skipped += 1
                log(f"WARN already_read_ids: skipping manifest record without case_id in {f}")
                continue
            try:
                ids.add(int(cid))
            except (TypeError, ValueError):
                skipped += 1
                log(f"WARN already_read_ids: skipping manifest record with non-integer case_id in {f}")
    return ids, skipped


def already_read_ids(runs_dir: Path, ledger_dir: Path) -> set[int]:
    ids, _skipped = _already_read_ids_with_skips(runs_dir, ledger_dir)
    return ids


def _partition_counts(conn) -> dict[str, int]:
    return {f"{e}|{j}": n for e, j, n in conn.execute(
        "SELECT era_partition, jurisdiction, count(*) FROM cases WHERE is_duplicate_of IS NULL GROUP BY 1,2")}


def plan(conn, domain, *, seeds, embedder=None, selectors: list[Selector] | None = None, runs=None) -> ShardPlan:
    sels = selectors if selectors is not None else load_selectors(domain)
    counts = _partition_counts(conn)
    runs = runs if runs is not None else partition_runs(conn)
    units, skips = [], []
    for s in sels:
        parts = [Partition(e, j) for e in s.era_scope for j in s.jurisdiction_scope]
        empty = [p for p in parts if counts.get(p.key, 0) == 0]
        live = [p for p in parts if counts.get(p.key, 0) > 0]
        if empty:
            skips.append(Skip(s.key, tuple(empty), "partition_empty"))
        if not live:
            continue
        fp = fingerprint(conn, s, live, seeds=seeds, min_seeds=domain.sharding.min_seeds, runs=runs)
        if isinstance(fp, Skip):
            skips.append(fp); continue
        for p in live:
            if not covered(conn, s.key, p.key, fp):
                units.append(PlanUnit(s.key, p, fp))
    digest = hashlib.sha256("".join(s.digest() for s in sels).encode()).hexdigest()[:16]
    return ShardPlan("", tuple(units), tuple(skips), digest)


def _gold_ids(domain) -> set[int]:
    out = set(); gp = Path(domain.gold_path)
    if gp.exists():
        for line in gp.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("case_id"):
                out.add(int(json.loads(line)["case_id"]))
    return out


def shard(conn, domain, run_id: str, *, seeds, embedder=None, dry_run=False, stamp=None, runs_dir: Path | None = None,
          ledger_dir: Path | None = None, out_dir: Path | None = None, log=print, runs=None) -> ShardReport:
    ts = getattr(stamp, "ts", None) or time.strftime("%Y-%m-%dT%H:%M:%S")
    sels = load_selectors(domain); by_key = {s.key: s for s in sels}
    runs = runs if runs is not None else partition_runs(conn)
    pl = plan(conn, domain, seeds=seeds, embedder=embedder, selectors=sels, runs=runs)
    pl = ShardPlan(run_id, pl.units, pl.skips, pl.selectors_digest)
    ctx = EngineContext(conn, domain, embedder, seeds)
    written: dict = {}
    for sk in pl.skips:
        log(f"SKIP {sk.key[0]}@v{sk.key[1]}: {sk.reason} ({len(sk.partitions)} partitions)")
    if not dry_run:
        for u in pl.units:
            s = by_key[u.key]
            try:
                sigs = RUNNERS[s.kind](ctx, s, u.partition)
                conn.executemany("""INSERT INTO signals (case_id, selector_id, selector_version, matched_text, char_span_start,
                                    char_span_end, chunk_id, cosine, era_partition, jurisdiction, run_id, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                                 [(g.case_id, g.selector_id, g.selector_version, g.matched_text, g.char_span[0], g.char_span[1],
                                   g.chunk_id, g.cosine, u.partition.era, u.partition.jurisdiction, run_id, ts) for g in sigs])
                mark_covered(conn, u.key, u.partition.key, u.fingerprint, run_id, ts, len(sigs))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            written[(u.key, u.partition.key)] = len(sigs)
            log(f"{s.label} x {u.partition.key}: {len(sigs)} signals")
    runs_dir = runs_dir or paths().runs
    exclude, exclude_skipped = _already_read_ids_with_skips(runs_dir, ledger_dir or paths().ledger, log=log)
    gold = _gold_ids(domain)
    seed_hashes = {}
    for s in sels:
        if "seed_set" in s.params:
            try:
                seed_hashes[s.params["seed_set"]] = seeds.resolve(s.params["seed_set"]).hash
            except Exception as e:                     # noqa: BLE001 — reported, not fatal
                seed_hashes[s.params["seed_set"]] = f"unresolved: {type(e).__name__}"
    manifest = {"engine_version": ENGINE_VERSION, "run_id": run_id, "ts": ts, "selectors_digest": pl.selectors_digest,
                "selectors": [{"label": s.label, "digest": s.digest(), "kind": s.kind} for s in sels],
                "embed_runs": {k[0] + "|" + k[1]: sorted(v) for k, v in runs.items()},
                "seed_hashes": seed_hashes, "batch_size": domain.sharding.batch_size,
                "exclude_count": len(exclude), "exclude_sha256": hashlib.sha256(",".join(map(str, sorted(exclude))).encode()).hexdigest(),
                "exclude_skipped_files": exclude_skipped,
                "units_run": len(pl.units) if not dry_run else 0,
                "skips": [{"selector": f"{k[0]}@v{k[1]}", "reason": r, "partitions": [p.key for p in ps]} for k, ps, r in
                          ((s.key, s.partitions, s.reason) for s in pl.skips)]}
    if dry_run:
        batches = build_batches(conn, run_id, gold_ids=gold, exclude_ids=exclude, batch_size=domain.sharding.batch_size)
        return ShardReport(pl, written, 0, None, sum(len(b["cases"]) for b in batches), len(exclude), manifest)
    out = out_dir or (runs_dir / run_id / "batches")
    n = pack_batches(conn, run_id, out, gold_ids=gold, exclude_ids=exclude, batch_size=domain.sharding.batch_size)
    (out.parent / "shard-manifest.json").write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    cases = sum(len(json.loads(f.read_text(encoding="utf-8"))["cases"]) for f in out.glob("batch-*.json"))
    return ShardReport(pl, written, n, out, cases, len(exclude), manifest)


def attribution(conn, case_ids) -> dict[int, tuple[SignalRef, ...]]:
    ids = [int(c) for c in case_ids]; out = {c: () for c in ids}
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        for cid, sid, ver, run, cos in conn.execute(
                f"""SELECT DISTINCT case_id, selector_id, selector_version, run_id, cosine FROM signals
                    WHERE case_id IN ({','.join('?' * len(chunk))}) ORDER BY case_id, selector_id, selector_version, run_id""", chunk):
            out[cid] = out[cid] + (SignalRef(sid, ver, run, cos),)
    return out


def probe(conn, domain, selector: Selector, partition: Partition, *, seeds, embedder=None, limit: int = 50):
    ctx = EngineContext(conn, domain, embedder, seeds)
    return RUNNERS[selector.kind](ctx, selector, partition)[:limit]
