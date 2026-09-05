"""One-time: freeze the reader kit (spec Section 6): 155 human-reviewed ledger records + 45 machine-irrelevant reads, texts inlined."""
import hashlib, json, random, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                                  # noqa: E402
from corpus_engine.domain import load_domain                                     # noqa: E402
from corpus_engine.ledger import open_ledger                                     # noqa: E402
from corpus_engine.ranker.labels import labelled_reads, read_extractions         # noqa: E402
from corpus_engine.reader.measure import KIT_SEED, kit_sample_50                 # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                         # noqa: E402

if __name__ == "__main__":
    dom = load_domain(); out = ROOT / dom.reader.kit_path
    if out.exists():
        sys.exit(f"{out} exists; a new kit is a new version")
    conn = store.connect(); view = open_ledger(domain=dom).view()
    human = []
    for cid in view.state.order:
        if view.state.in_file.get(cid) and view.reviewed(cid):
            r = view.state.records[cid]
            human.append({"case_id": int(cid), "source": "human", "relevant": bool(r.get("relevant")), "polarity": r.get("polarity"),
                          "who_was_letting": r.get("who_was_letting")})
    labels = labelled_reads(view, read_extractions(store.paths().runs), conn)
    neg = [l for l in labels if l.label == 0]; rng = random.Random(KIT_SEED)
    strata = {}
    for l in neg:
        strata.setdefault((l.era, l.jurisdiction), []).append(l)
    picked = []
    quota = max(1, 45 // len(strata))
    for k in sorted(strata):
        picked += rng.sample(strata[k], min(quota, len(strata[k])))
    picked = picked[:45]
    machine = [{"case_id": l.case_id, "source": "machine", "relevant": False, "polarity": "irrelevant", "who_was_letting": None} for l in picked]
    reference = human + machine
    ids = [r["case_id"] for r in reference]
    meta = {r[0]: r for r in conn.execute(f"SELECT case_id, era_partition, jurisdiction FROM cases WHERE case_id IN ({','.join('?'*len(ids))})", ids)}
    for r in reference:
        r["era"], r["jurisdiction"] = meta[r["case_id"]][1], meta[r["case_id"]][2]
    sig = {}
    for i in range(0, len(ids), 500):
        ch = ids[i:i+500]
        for cid, sid, ver, mt in conn.execute(f"SELECT case_id, selector_id, selector_version, matched_text FROM signals WHERE case_id IN ({','.join('?'*len(ch))})", ch):
            sig.setdefault(cid, []).append({"selector_id": sid, "selector_version": ver, "matched_text": mt or ""})
    groups = {}
    for r in sorted(reference, key=lambda r: r["case_id"]):
        groups.setdefault((r["era"], r["jurisdiction"]), []).append(r["case_id"])
    batches, n = [], 0
    for (era, jur), cids in sorted(groups.items()):
        for j in range(0, len(cids), 18):
            n += 1
            batches.append({"batch_id": f"kit-v1-batch-{n:03d}", "era_partition": era, "jurisdiction": jur,
                            "cases": [{"case_id": c, "signals": sig.get(c, [])[:6]} for c in cids[j:j+18]]})
    texts = {str(t.case_id): {"cite": t.cite, "name": t.name, "court": t.court, "jurisdiction": t.jurisdiction, "year": t.year,
                              "raw_text": t.raw_text, "norm_text": t.norm_text, "page_map": t.page_map} for t in StoreCaseSource(conn).fetch(ids)}
    kit = {"version": "v1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": KIT_SEED, "reference": reference, "batches": batches, "texts": texts}
    out.parent.mkdir(parents=True, exist_ok=True); (out.parent / "batches").mkdir(exist_ok=True)
    out.write_bytes(json.dumps(kit, sort_keys=True).encode("utf-8"))
    for b in batches:
        (out.parent / "batches" / f"{b['batch_id']}.json").write_bytes(json.dumps(b, indent=1).encode("utf-8"))
    (out.parent / "sample-50.json").write_bytes(json.dumps(kit_sample_50(reference)).encode("utf-8"))
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"kit: {len(human)} human + {len(machine)} machine = {len(reference)} cases, {len(batches)} batches, {sum(len(t['raw_text']) for t in texts.values()):,} chars")
    print("sha256:", h, "-> set reader.kit_sha256 in domain.yaml")
