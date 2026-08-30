"""Pre-review passes over the cycle-001 human-review queue.

  remap    Re-extract the quote-gate-nulled records (spec §10 re-map queue)
           with tightened verbatim-quote instructions. Output goes through
           verify_quotes before anyone trusts it.
  adjudicate  Third-reader pass over cross-model disagreements: reads the
           case, weighs both values, outputs a recommendation WITH a written
           justification and a supporting quote. Recommendation only — the
           human remains the adjudicator.
  fuzzy    Mechanical classification of fuzzy-quote diffs: character-level
           opcodes; all-tiny substitutions => trivial-ocr, else needs-human.

Usage: python pipeline/pre_review.py {remap|adjudicate|fuzzy} [--run-id ...]
"""

import argparse
import difflib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"
RUNS = ROOT / "runs"
MAPPER_PROMPT = ROOT / "prompts" / "mapper.md"


def claude_call(payload: str, model: str = "sonnet", timeout: int = 900) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json"],
        input=payload, capture_output=True, text=True, encoding="utf-8",
        timeout=timeout, shell=(sys.platform == "win32"),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[:300]}")
    return json.loads(proc.stdout).get("result", "")


def parse_json_array(raw: str):
    s, e = raw.find("["), raw.rfind("]")
    if s < 0 or e <= s:
        return None
    try:
        return json.loads(raw[s : e + 1])
    except json.JSONDecodeError:
        return None


def case_text(conn, case_id: int) -> str:
    r = conn.execute("SELECT raw_text FROM cases WHERE case_id=?", (case_id,)).fetchone()
    return r[0] if r else ""


def cmd_remap(run_id: str) -> None:
    conn = sqlite3.connect(DB)
    queue = json.loads(
        (RUNS / run_id / "review-queue.json").read_text(encoding="utf-8")
    )["nulled"]
    out = []
    header = (
        MAPPER_PROMPT.read_text(encoding="utf-8")
        + "\n\n# RE-MAP NOTICE\nA previous extraction of these cases was VOIDED "
        "because a supporting quote failed verbatim verification. Copy quotes "
        "EXACTLY as printed, including OCR errors, archaic spelling, and odd "
        "punctuation. Do not clean anything up. If you cannot find a verbatim "
        "supporting passage, leave the field null and say so in notes.\n"
    )
    for i in range(0, len(queue), 8):
        group = queue[i : i + 8]
        payload = header + f'\nSet "worker": "claude-remap", "batch_id": "remap-{i//8:02d}".\n'
        for e in group:
            payload += (
                f"\n## case_id {e['case_id']} — {e.get('name')}, {e.get('cite')} "
                f"({e.get('jur')} {e.get('year')})\n### Opinion text\n"
                f"{case_text(conn, e['case_id'])}\n"
            )
        recs = parse_json_array(claude_call(payload))
        if recs:
            out.extend(recs)
            print(f"remap group {i//8}: {len(recs)} records")
        else:
            print(f"remap group {i//8}: PARSE FAILURE")
    d = RUNS / run_id / "extractions-remap"
    d.mkdir(exist_ok=True)
    (d / "remap-001.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(out)} re-mapped records -> {d}")


def cmd_adjudicate(run_id: str) -> None:
    conn = sqlite3.connect(DB)
    queue = json.loads(
        (RUNS / run_id / "review-queue.json").read_text(encoding="utf-8")
    )["disagreements"]
    by_case: dict = {}
    for dgt in queue:
        by_case.setdefault(dgt["case_id"], {"info": dgt, "fields": []})["fields"].append(dgt)
    cases = list(by_case.values())
    out = []
    for i in range(0, len(cases), 5):
        group = cases[i : i + 5]
        payload = (
            "You are a third, independent legal reader resolving disagreements "
            "between two prior AI readers of historical case law about "
            "compensated occupancy (lodgers, boarders, letting). For each case "
            "and each contested field, read the opinion and decide which value "
            "is correct (or supply a better one).\n\nField meanings: "
            "relevant: does the case bear on compensated occupancy of another's "
            "dwelling/rooms, its legal character, or its regulation? polarity: "
            "favorable = letting treated as lawful incident of ownership / "
            "protected; adverse = regulation or restriction of letting upheld; "
            "mixed; irrelevant. characterization: how the COURT classified the "
            "arrangement: lease | license | lodging | innkeeping | other.\n\n"
            "Output: a JSON array only, one object per contested field:\n"
            '{"case_id": ..., "field": "...", "recommendation": "...", '
            '"justification": "2-3 sentences grounded in the opinion", '
            '"supporting_quote": "verbatim short passage from the opinion"}\n'
        )
        for c in group:
            info = c["info"]
            payload += (
                f"\n## case_id {info['case_id']} — {info.get('name')}, "
                f"{info.get('cite')} ({info.get('jur')} {info.get('year')})\n"
            )
            for f in c["fields"]:
                payload += (
                    f"Contested field `{f['field']}`: reader A said "
                    f"`{f.get('claude')}`, reader B said `{f.get('codex')}`.\n"
                )
            payload += f"### Opinion text\n{case_text(conn, info['case_id'])}\n"
        recs = parse_json_array(claude_call(payload))
        if recs:
            out.extend(recs)
            print(f"adjudicate group {i//5}: {len(recs)} verdicts")
        else:
            print(f"adjudicate group {i//5}: PARSE FAILURE")
    (RUNS / run_id / "adjudications.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8"
    )
    print(f"{len(out)} recommendations -> adjudications.json")


_WORD = re.compile(r"[a-z0-9]+")


def cmd_fuzzy(run_id: str) -> None:
    diffs = json.loads(
        (RUNS / run_id / "fuzzy-diffs.json").read_text(encoding="utf-8")
    )
    for e in diffs:
        a = " ".join(_WORD.findall(e["quote"].lower()))
        b = " ".join(_WORD.findall(e["source"].lower()))
        sm = difflib.SequenceMatcher(a=a, b=b)
        # the source window carries extra context chars; only quote-side
        # (a-side) mismatches matter, and only their run lengths
        a_miss_runs = [
            i2 - i1
            for op, i1, i2, j1, j2 in sm.get_opcodes()
            if op in ("replace", "delete")
        ]
        coverage = 1 - (sum(a_miss_runs) / max(1, len(a)))
        e["classification"] = (
            "trivial-ocr"
            if coverage >= 0.92 and (not a_miss_runs or max(a_miss_runs) <= 4)
            else "needs-human"
        )
        e["quote_coverage"] = round(coverage, 3)
        e["miss_runs"] = a_miss_runs
    (RUNS / run_id / "fuzzy-diffs.json").write_text(
        json.dumps(diffs, indent=1), encoding="utf-8"
    )
    n_triv = sum(1 for e in diffs if e["classification"] == "trivial-ocr")
    print(f"{n_triv} trivial-ocr / {len(diffs) - n_triv} needs-human")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["remap", "adjudicate", "fuzzy"])
    ap.add_argument("--run-id", default="cycle-001-shard-02")
    a = ap.parse_args()
    {"remap": cmd_remap, "adjudicate": cmd_adjudicate, "fuzzy": cmd_fuzzy}[a.cmd](a.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
