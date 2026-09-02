"""Two-tier counts and the tradition matrix (ADR-0002)."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from corpus_engine.ledger.types import TierCount
from corpus_engine.store import era_partition


class CountTable(dict):
    total: TierCount
    def render_markdown(self) -> str:
        lines = ["| key | human-reviewed | machine-only |", "|---|---|---|"]
        for k, t in sorted(self.items(), key=lambda kv: str(kv[0])):
            lines.append(f"| {' / '.join(str(x) for x in k) or 'all'} | {t.human_reviewed} | {t.machine_only} |")
        lines.append(f"| total | {self.total.human_reviewed} | {self.total.machine_only} |")
        return "\n".join(lines)


def _population(view, **filters):
    for cid in view.state.order:
        if not view.state.in_file.get(cid):
            continue
        r = view.state.records[cid]
        if not r.get("relevant"):
            continue
        if all(r.get(k) == v for k, v in filters.items()):
            yield cid, r


def counts(view, *, by: tuple[str, ...] = (), **filters) -> CountTable:
    acc: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    tot = [0, 0]
    for cid, r in _population(view, **filters):
        key = tuple(r.get(f) for f in by)
        i = 0 if view.reviewed(cid) else 1
        acc[key][i] += 1
        tot[i] += 1
    table = CountTable({k: TierCount(*v) for k, v in acc.items()})
    table.total = TierCount(*tot)
    return table


@dataclass
class TraditionMatrix:
    cells: dict[tuple[str, str, str, str], TierCount]
    def empty_cells(self, *, minimum: int = 1, tier: str = "human_reviewed") -> list[tuple]:
        out = []
        for k, t in self.cells.items():
            n = t.human_reviewed if tier == "human_reviewed" else t.human_reviewed + t.machine_only
            if n < minimum:
                out.append(k)
        return sorted(out)
    def render_markdown(self) -> str:
        lines = ["| era | region | tier | duration | human-reviewed | machine-only |", "|---|---|---|---|---|---|"]
        for k, t in sorted(self.cells.items()):
            lines.append(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]} | {t.human_reviewed} | {t.machine_only} |")
        return "\n".join(lines)


def matrix(view) -> TraditionMatrix:
    d = view.domain
    acc: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for cid, r in _population(view, polarity="favorable"):
        key = (era_partition(r.get("year"), d.era_bounds), d.regions.get(r.get("jurisdiction"), "other"),
               d.letting_tiers.get(r.get("who_was_letting"), "unclear"), r.get("duration_of_occupancy") or "unclear")
        acc[key][0 if view.reviewed(cid) else 1] += 1
    # every era x region x tier x duration combination present as a key, zero-filled
    eras = list(d.eras); regions = sorted(set(d.regions.values())); tiers = sorted(set(d.letting_tiers.values()))
    for e in eras:
        for rg in regions:
            for t in tiers:
                for du in ("nights", "weeks", "months", "unclear"):
                    acc.setdefault((e, rg, t, du), [0, 0])
    return TraditionMatrix({k: TierCount(*v) for k, v in acc.items()})
