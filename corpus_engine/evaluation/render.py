"""The markdown report from the evaluation's JSON dict. Numbers in tables, limitations verbatim."""
from __future__ import annotations


def _est(e: dict) -> str:
    if e.get("status") != "ok":
        return e.get("status", "unavailable")
    return f"{e['value']:.3f} ({e['lo']:.3f}-{e['hi']:.3f}, n={e['n']:,})"


def _kappa(k: dict) -> str:
    if k.get("status") != "ok":
        return k.get("status", "unavailable")
    return f"{k['value']:.3f}"


def _tier(t: dict) -> str:
    return f"{t['human_reviewed'] + t['machine_only']:,} ({t['human_reviewed']:,} human / {t['machine_only']:,} machine)"


def _envelope(env: dict) -> list[str]:
    out = [f"Population: {env['population']}", ""]
    if env["exclusions"]:
        out += ["Exclusions:"] + [f"- {x}" for x in env["exclusions"]] + [""]
    out += ["Limitations:"] + [f"- {x}" for x in env["limitations"]] + [""]
    if env["provenance"].get("inputs"):
        out += ["Provenance:"] + [f"- {p[0]} ({p[2]}) sha256 {p[1] or '-'}" for p in env["provenance"]["inputs"]] + [""]
    return out


def markdown(doc: dict) -> str:
    g, p, a, c, led = doc["gold_recovery"], doc["precision"], doc["agreement"], doc["coverage"], doc["ledger"]
    L = [f"# Evaluation of the corpus, cycle {doc['cycle']} ({doc['evaluation_id']})", "",
         f"Generated {doc['generated_at']} at ledger seq {led['reporting_seq']:,} "
         f"(content {led['content_sha256'][:12]}), code {doc['code'].get('git_revision', '?')}.", "",
         "Published counts (`open_ledger().view().counts()`):", "",
         "| population | count |", "|---|---|",
         f"| relevant | {_tier(led['counts']['relevant'])} |",
         f"| favorable | {_tier(led['counts']['favorable'])} |",
         f"| favorable householder | {_tier(led['counts']['favorable_householder'])} |", "",
         "## Headline", "",
         "| measure | headline | denominator | uncertainty |", "|---|---|---|---|",
         f"| gold recovery (union) | {_est(g['union']['recovery'])} | {g['union']['resolved']:,} resolved gold cases | {g['envelope']['uncertainty']['type']} |",
         f"| machine-tier precision | {_est(p['precision'])} | {p['decided']:,} decided of {p['n']:,} sampled | {p['envelope']['uncertainty']['type']} |",
         f"| polarity accuracy | {_est(p['field_accuracy'].get('polarity', {'status': 'unavailable'}))} | records found relevant | sampling |",
         f"| who_was_letting accuracy | {_est(p['field_accuracy'].get('who_was_letting', {'status': 'unavailable'}))} | records found relevant | sampling |",
         f"| blind agreement (audit) | {_audit_headline(a)} | audit cards | sampling |",
         f"| unread-tail coverage | {_scenarios_headline(c)} | unread shard-02 cases | {c['envelope']['uncertainty']['type']} |", "",
         "## 1. Gold recovery", ""]
    L += ["| tier | entries | resolved | signaled | read | relevant | human-reviewed | recovery |", "|---|---|---|---|---|---|---|---|"]
    for name, t in list(g["tiers"].items()) + [("union", g["union"])]:
        L.append(f"| {name} | {t['entries']:,} | {t['resolved']:,} | {t['signaled']:,} | {t['read']:,} | {t['relevant']:,} | {t['relevant_human']:,} | {_est(t['recovery'])} |")
    # gold.py writes this key hyphenated ("brief-doctrine"); tolerate an underscored caller too
    # (e.g. a hand-built test fixture) rather than KeyError on an otherwise-valid document.
    doc_inv = g["inventory"].get("brief-doctrine") or g["inventory"].get("brief_doctrine") or {"entries": 0, "resolved": 0}
    L += ["", f"Inventory: brief-doctrine {doc_inv['entries']} entries, {doc_inv['resolved']} resolved (not in the denominator).", ""]
    if g["misses"]:
        L += ["| cite | case | tier | lost at | detail |", "|---|---|---|---|---|"]
        L += [f"| {m['cite']} | {m['case_id'] or '-'} | {m['tier']} | {m['lost_at']} | {m['detail']} |" for m in g["misses"]]
        L.append("")
    if g["unresolved"]:
        L += ["Unresolved cites (no case in the store; ingest coverage gap):", "",
              "| cite | tier |", "|---|---|"]
        L += [f"| {u['cite']} | {u['tier']} |" for u in g["unresolved"]]
        L.append("")
    L += _envelope(g["envelope"])
    L += ["## 2. Machine-tier precision", "",
          f"Sample: {p['n']:,} of {p['frame_size']:,} machine-only relevant records at seq {p['sampling_seq']:,}; "
          f"{p['decided']:,} decided, {p['unresolved']:,} unresolved.", "",
          f"Precision: {_est(p['precision'])}", ""]
    L += _envelope(p["envelope"])
    L += ["## 3. Field accuracy", "", "| field | accuracy |", "|---|---|"]
    L += [f"| {f} | {_est(e)} |" for f, e in p["field_accuracy"].items()]
    L += ["", f"Joint correctness (relevant, polarity, who_was_letting all match): {_est(p['joint_correctness'])}", ""]
    for f, m in p.get("confusion", {}).items():
        cols = sorted({c for row in m.values() for c in row})
        L += [f"Confusion, {f} (draw-time by row, adjudicated by column):", "",
              "| draw-time \\ adjudicated | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        L += [f"| {row} | " + " | ".join(f"{m[row].get(c, 0):,}" for c in cols) + " |" for row in sorted(m)]
        L.append("")
    if p.get("subgroups"):
        s = p["subgroups"]["favorable_householder"]
        L += [f"Favorable-householder subgroup: n={s['n']}, precision {_est(s['precision'])}.", ""]
    if p.get("revisions"):
        L += ["Revisions after reveal: " + ", ".join(f"{f} {n}" for f, n in p["revisions"].items()), ""]
    L += ["## 4. Reviewer agreement", ""]
    for r in a["rounds"]:
        L += [f"### {r['round_id']} ({r['kind']}, {r['exposure']})", "", f"Selection rule: {r['selection_rule']}", "",
              "| pair | field | n | raw agreement | kappa |", "|---|---|---|---|---|"]
        for pair, fields in r["pairs"].items():
            for f, st in fields.items():
                L.append(f"| {pair} | {f} | {st['n']:,} | {_est(st['raw'])} | {_kappa(st['kappa'])} |")
        L.append("")
    if a["excluded"]:
        L += ["Excluded rounds:"] + [f"- {e['round_id']}: {e['reason']} ({e['cards']} cards)" for e in a["excluded"]] + [""]
    if a["unregistered_run_ids"]:
        L += ["Reviewer run ids in the ledger not named by the registry: " + ", ".join(a["unregistered_run_ids"]), ""]
    L += _envelope(a["envelope"])
    L += ["## 5. Unread-tail coverage", "", "| band | read cases | relevant | yield | unread cases |", "|---|---|---|---|---|"]
    for b in c["bands"]:
        y = f"{b['relevant'] / b['read_cases']:.3f}" if b["read_cases"] else "-"
        L.append(f"| {b['lo']:.2f}-{b['hi']:.2f} | {b['read_cases']:,} | {b['relevant']:,} | {y} | {b['unread_cases']:,} |")
    L += ["", "| scenario | assumption | estimated relevant |", "|---|---|---|"]
    L += [f"| {s['name']} | {s['assumption']} | {s['estimated_relevant']:,} |" for s in c["scenarios"]]
    L.append("")
    L += _envelope(c["envelope"])
    L += ["## Rounds registry", "", "See `runs/evaluation/rounds.json` (hash in the agreement provenance).", ""]
    return "\n".join(L)


def _audit_headline(a: dict) -> str:
    for r in a["rounds"]:
        if r["kind"] == "audit" and "claude-astra" in r["pairs"] and "relevant" in r["pairs"]["claude-astra"]:
            return _est(r["pairs"]["claude-astra"]["relevant"]["raw"])
    return "unavailable"


def _scenarios_headline(c: dict) -> str:
    if not c["scenarios"]:
        return "unavailable"
    vals = [s["estimated_relevant"] for s in c["scenarios"]]
    return f"{min(vals):,}-{max(vals):,} (three scenarios)"
