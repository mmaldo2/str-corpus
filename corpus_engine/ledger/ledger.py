from __future__ import annotations
import copy, json, os
from dataclasses import dataclass, field, replace
from pathlib import Path
from corpus_engine.domain import Domain, load_domain
from corpus_engine.ledger.fold import State, apply_patch
from corpus_engine.ledger.log import PatchLog, patch_id, provisional_seqs
from corpus_engine.ledger.render import render_cycle
from corpus_engine.ledger.types import Patch, SeedSet, StaleSnapshot, NotTraditionEvidence, LedgerError
from corpus_engine.store import paths


@dataclass
class ApplyResult:
    applied: list[Patch]
    skipped: list[Patch]
    files_written: list[Path]
    replay_ok: bool
    # The writes D2 refused, as conflict entries (review finding 2). A refused patch is still
    # APPENDED - the log is append-only and the replay is the truth, so the disagreement is
    # recorded rather than swallowed - but it changed nothing, so it is NOT in `applied`, and
    # a tool that finds this non-empty must say so and fail rather than report success.
    rejected: list[dict] = field(default_factory=list)


def _refused(before: State, after: State) -> list[dict]:
    """The conflicts the trial fold added and REFUSED (a historical one still applied).

    Entries are appended per case, so what is new is what is past the count head already had.
    Deep copies, each with the `case_id` the fold keys them by, because this list is flat and
    a caller reporting a refusal needs to name the record."""
    out = []
    for cid, entries in after.conflicts.items():
        seen = len(before.conflicts.get(cid, ()))
        out += [dict(copy.deepcopy(c), case_id=cid) for c in entries[seen:]
                if not c.get("historical")]
    return out


@dataclass
class LedgerView:
    name: str
    as_of: int
    state: State
    patches: list[Patch]
    domain: Domain

    def records(self, **filters) -> list[dict]:
        out = []
        for cid in self.state.order:
            r = self.state.records[cid]
            if all(r.get(k) == v for k, v in filters.items()):
                out.append(r)
        return out

    def record(self, case_id: int) -> dict:
        return self.state.records[case_id]

    def history(self, case_id: int) -> list[Patch]:
        return [p for p in self.patches if p.case_id == case_id]

    def reviewed(self, case_id: int) -> bool:
        judged = set(self.domain.judged_fields) | {"review.status"}
        return any(p.basis.reviewer and p.op in ("set", "append") and p.field in judged
                   for p in self.history(case_id))

    def conflicts(self, case_id: int | None = None, *,
                  historical: bool = False) -> dict[int, list[dict]]:
        """Every write that landed on a field a human had already decided (D2).

        `{case_id: [{"field", "attempted", "standing", "by", "at", "op", "historical"}, ...]}`.
        By default only the writes the fold REFUSED. `historical=True` adds the six
        grandfathered writes from below `PROTECTION_FROM_SEQ`, which were applied and are
        listed for the record only - they carry no flag and changed no committed byte.
        Deep copies, not the fold's own entries: the queue reads this and must not be able
        to edit the state through a nested `by` dict."""
        rows = self.state.conflicts
        if case_id is not None:
            rows = {case_id: rows[case_id]} if case_id in rows else {}
        out = {}
        for cid, entries in rows.items():
            kept = [copy.deepcopy(c) for c in entries if historical or not c.get("historical")]
            if kept:
                out[cid] = kept
        return out

    def provenance(self, case_id: int) -> dict[str, str]:
        """`{field: "human"|"reader"|"rule"}` for this record. Empty for a case with no
        judged field ever written - never a KeyError, because the re-read asks about every
        record it re-reads and a missing entry means "nobody has decided this field"."""
        return dict(self.state.provenance.get(case_id, {}))

    def counts(self, *, by: tuple[str, ...] = (), **filters):
        from corpus_engine.ledger.tally import counts
        return counts(self, by=by, **filters)

    def matrix(self):
        if self.name != "tradition":
            raise NotTraditionEvidence(self.name)
        from corpus_engine.ledger.tally import matrix
        return matrix(self)

    def seed_set(self) -> SeedSet:
        if self.name != "tradition":
            raise NotTraditionEvidence(self.name)
        import hashlib
        ids = tuple(sorted(cid for cid in self.state.order
                           if self.state.in_file.get(cid) and self.state.records[cid].get("relevant")
                           and self.state.records[cid].get("polarity") == "favorable" and self.reviewed(cid)))
        h = hashlib.sha256((",".join(map(str, ids)) + f"@{self.as_of}").encode()).hexdigest()
        return SeedSet(case_ids=ids, hash=h)

    def manifest(self, cycle: str) -> list[dict]:
        out = []
        for p in self.patches:
            if p.op == "admit" and p.cycle == cycle:
                r = self.state.records.get(p.case_id, {})
                outcome = ("invalid" if r.get("extraction_status") == "extraction-invalid"
                           else "relevant" if p.new.get("relevant") else "irrelevant")
                out.append({"case_id": p.case_id, "cycle": cycle, "run_id": p.basis.run_id,
                            "outcome": outcome, "stratum": None})
        seen = {}
        for e in out:                      # admit patches deduped by case_id; last admit wins
            seen[e["case_id"]] = e
        return list(seen.values())

    def render(self) -> dict[str, bytes]:
        by_cycle: dict[str, list[dict]] = {}
        for cid in self.state.order:                       # admission order = stable tiebreak
            if self.state.in_file.get(cid):
                by_cycle.setdefault(self.state.cycles[cid], []).append(self.state.records[cid])
        return {f"{cyc}.jsonl": render_cycle(sorted(recs, key=lambda r: r.get("year") or 0))
                for cyc, recs in by_cycle.items()}


class Ledger:
    def __init__(self, ledger_dir: Path, name: str, domain: Domain):
        self.dir = ledger_dir if name == "tradition" else ledger_dir / name
        self.name = name
        self.domain = domain
        self.log = PatchLog(self.dir / "patches.jsonl")
        self._views: dict[int | None, LedgerView] = {}

    def _replay(self, patches: list[Patch]) -> State:
        state = State()
        for p in patches:
            apply_patch(state, p, judged=tuple(self.domain.judged_fields), cascade=p.cascade)
        return state

    def view(self, as_of: int | None = None) -> LedgerView:
        if as_of in self._views:
            return self._views[as_of]
        patches = self.log.read()
        if as_of is not None:
            patches = [p for p in patches if p.seq <= as_of]
        v = LedgerView(self.name, patches[-1].seq if patches else 0, self._replay(patches), patches, self.domain)
        self._views[as_of] = v
        return v

    def apply(self, patches: list[Patch], *, note: str, at: str | None = None,
              dry_run: bool = False) -> ApplyResult:
        patches = [replace(p, note=note) if not p.note else p for p in patches]
        self._views.clear()                                # the log is the only truth: never
        existing = {p.patch_id for p in self.log.read()}    # validate against a view a caller
        fresh = [p for p in patches if patch_id(p) not in existing]  # may have mutated via a
        skipped = [p for p in patches if patch_id(p) in existing]    # shallow-copied trial state
        head = self.view()
        # Stamp the seqs the append is about to assign BEFORE the trial fold: a patch carries
        # seq 0 until then, and D2's baseline would read 0 as history and let the trial state
        # accept a write the real log refuses (review finding 1).
        fresh = provisional_seqs(fresh, head.as_of)
        trial = copy.deepcopy(head.state)
        stamped_old = []
        for p in fresh:                                    # validate everything before writing
            old = apply_patch(trial, p, judged=tuple(self.domain.judged_fields), cascade=p.cascade)
            stamped_old.append(old)
        rejected = _refused(head.state, trial)
        refused_at = {c["at"] for c in rejected}
        if dry_run:
            return ApplyResult([p for p in fresh if p.seq not in refused_at], skipped, [],
                               True, rejected)
        self.dir.mkdir(parents=True, exist_ok=True)
        lock = self.dir / ".lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LedgerError(f"stale lock {lock}: a previous apply() did not finish; "
                              "remove it after confirming no other process is writing")
        try:
            stamped = self.log.append([replace(p, old=o) for p, o in zip(fresh, stamped_old)], at=at)
            self._views.clear()
            written = self._write_snapshot(self.view())
            replay_ok = all(path.read_bytes() == data for path, data in written)
        finally:
            os.close(fd)
            lock.unlink()
        # `append` re-stamps the same seqs `provisional_seqs` used (same head, under the
        # write lock), so a refused patch is identified by the seq the trial fold recorded.
        return ApplyResult([p for p in stamped if p.seq not in refused_at], skipped,
                           [p for p, _ in written], replay_ok, rejected)

    def _write_snapshot(self, v: LedgerView) -> list[tuple[Path, bytes]]:
        out = []
        for fname, data in v.render().items():
            path = self.dir / fname
            tmp = path.with_suffix(".jsonl.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            out.append((path, data))
        mdir = self.dir / "manifest"; mdir.mkdir(exist_ok=True)
        for cyc in sorted({c for c in v.state.cycles.values()}):
            data = "".join(json.dumps(e, sort_keys=True) + "\n" for e in v.manifest(cyc)).encode("utf-8")
            (mdir / f"{cyc}.jsonl").write_bytes(data)
        return out

    def rewrite_snapshot(self) -> None:
        self._write_snapshot(self.view())


def open_ledger(root: Path | None = None, *, name: str = "tradition", domain: Domain | None = None) -> Ledger:
    ledger_dir = root if root is not None else paths().ledger
    return Ledger(ledger_dir, name, domain or load_domain())
