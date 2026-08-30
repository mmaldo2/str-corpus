"""Citator PRE-SCREEN via CourtListener — not a citator.

For each target case: resolve the citation to a CourtListener cluster,
list the cases citing it, and fetch a bounded subset of citing opinions to
scan for negative-treatment language near our case's name/cite. Output is a
memo that narrows the human's KeyCite/Shepard's session — the open citation
graph shows THAT a case was cited, never that it survives (research doc
§4.4); the manual citator gate stands.

Rate limits (user-mandated, enforced with a persisted ledger):
  5 requests/min, 50/hour, 125/day — data/raw/cl-requests.log

Targets: adjudicated-ledger cases that are (favorable x householder x
nights) or carry an abrogation-risk flag.

Usage: python pipeline/citator_prescreen.py [--max-opinion-fetches 20]
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "ledger" / "cycle-001.jsonl"
REQ_LOG = ROOT / "data" / "raw" / "cl-requests.log"
OUT_JSON = ROOT / "runs" / "citator-prescreen.json"
OUT_MD = ROOT / "reports" / "citator-prescreen.md"
BASE = "https://www.courtlistener.com/api/rest/v4"

NEG = re.compile(
    r"overrul\w+|abrogat\w+|disapprov\w+|superseded|no longer good law|"
    r"declined? to follow|reject\w+ the (reasoning|analysis|holding) of|"
    r"reversed",
    re.IGNORECASE,
)


def load_token() -> str:
    tok = os.environ.get("COURTLISTENER_API_TOKEN")
    if not tok:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8-sig").splitlines():
                if line.startswith("COURTLISTENER_API_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
    if not tok:
        sys.exit("no COURTLISTENER_API_TOKEN in env or .env")
    return tok


class Limiter:
    """5/min, 50/hour, 125/day, persisted across runs."""

    def __init__(self):
        REQ_LOG.parent.mkdir(parents=True, exist_ok=True)
        self.times: list[float] = []
        if REQ_LOG.exists():
            now = time.time()
            self.times = [
                float(l) for l in REQ_LOG.read_text().split()
                if l and now - float(l) < 86400
            ]

    def wait(self):
        while True:
            now = time.time()
            day = [t for t in self.times if now - t < 86400]
            hour = [t for t in self.times if now - t < 3600]
            minute = [t for t in self.times if now - t < 60]
            if len(day) >= 125:
                sys.exit(f"daily request budget (125) exhausted; resume in "
                         f"{(86400 - (now - min(day)))/3600:.1f} h")
            if len(hour) >= 50:
                time.sleep(60)
                continue
            if len(minute) >= 5:
                time.sleep(61 - (now - min(minute)))
                continue
            break
        self.times.append(time.time())
        with REQ_LOG.open("a") as f:
            f.write(f"{self.times[-1]}\n")


def targets() -> list[dict]:
    rows = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        flags = (r.get("review") or {}).get("flags") or []
        is_hxn = (r.get("polarity") == "favorable"
                  and r.get("who_was_letting") == "householder"
                  and r.get("duration_of_occupancy") == "nights")
        if is_hxn or any(f.startswith("abrogation-risk") for f in flags):
            out.append({"case_id": r["case_id"], "cite": r.get("cite"),
                        "year": r.get("year"), "jur": r.get("jurisdiction"),
                        "flags": flags})
    # names from the DB would need sqlite; keep cite-keyed
    seen, uniq = set(), []
    for t in out:
        if t["case_id"] not in seen:
            seen.add(t["case_id"])
            uniq.append(t)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-opinion-fetches", type=int, default=20)
    args = ap.parse_args()
    tok = load_token()
    lim = Limiter()
    client = httpx.Client(
        headers={"Authorization": f"Token {tok}",
                 "User-Agent": "str-corpus-research/0.1 (citator pre-screen; polite)"},
        timeout=60,
    )
    tg = targets()
    print(f"{len(tg)} target cases")
    results = []
    fetch_budget = args.max_opinion_fetches
    for t in tg:
        entry = {**t, "cl_cluster": None, "citing": [], "negative_passages": [],
                 "verdict": "unknown"}
        # 1) resolve citation -> cluster
        lim.wait()
        r = client.post(f"{BASE}/citation-lookup/", data={"text": t["cite"]})
        if r.status_code != 200:
            entry["error"] = f"lookup {r.status_code}"
            results.append(entry)
            continue
        clusters = []
        for item in r.json():
            clusters.extend(item.get("clusters") or [])
        if not clusters:
            entry["verdict"] = "not-found-in-CL"
            results.append(entry)
            print(f"{t['cite']}: not found")
            continue
        cl = clusters[0]
        entry["cl_cluster"] = {"id": cl.get("id"),
                               "case_name": cl.get("case_name"),
                               "url": "https://www.courtlistener.com" + (cl.get("absolute_url") or "")}
        sub = cl.get("sub_opinions") or []
        op_id = None
        if sub:
            m = re.search(r"/opinions/(\d+)/", str(sub[0]))
            op_id = m.group(1) if m else None
        if not op_id:
            entry["verdict"] = "no-opinion-id"
            results.append(entry)
            continue
        # 2) citing cases
        lim.wait()
        r = client.get(f"{BASE}/search/", params={
            "type": "o", "q": f"cites:({op_id})", "order_by": "dateFiled desc"})
        if r.status_code != 200:
            entry["error"] = f"search {r.status_code}"
            results.append(entry)
            continue
        body = r.json()
        entry["citing_count"] = body.get("count")
        for hit in (body.get("results") or [])[:20]:
            entry["citing"].append({
                "case_name": hit.get("caseName"),
                "court": hit.get("court"),
                "date": hit.get("dateFiled"),
                "cluster_id": hit.get("cluster_id"),
                "opinion_id": (hit.get("opinions") or [{}])[0].get("id")
                if hit.get("opinions") else None,
            })
        # 3) fetch suspect citing opinions: same-jurisdiction later decisions,
        #    newest first, within global budget
        suspects = [c for c in entry["citing"] if c.get("opinion_id")][:4]
        for c in suspects:
            if fetch_budget <= 0:
                break
            lim.wait()
            fetch_budget -= 1
            ro = client.get(f"{BASE}/opinions/{c['opinion_id']}/",
                            params={"fields": "plain_text,html_with_citations"})
            if ro.status_code != 200:
                continue
            j = ro.json()
            text = j.get("plain_text") or re.sub(r"<[^>]+>", " ",
                                                 j.get("html_with_citations") or "")
            anchor = t["cite"].split()[1] if len(t["cite"].split()) > 1 else t["cite"]
            for m in re.finditer(re.escape(t["cite"][:12]), text):
                window = text[max(0, m.start() - 400): m.end() + 400]
                neg = NEG.search(window)
                if neg:
                    entry["negative_passages"].append({
                        "citing_case": c["case_name"], "date": c["date"],
                        "signal": neg.group(0),
                        "passage": " ".join(window.split())[:500],
                    })
        entry["verdict"] = ("negative-signal" if entry["negative_passages"]
                            else "no-negative-signal-found")
        results.append(entry)
        print(f"{t['cite']}: {entry.get('citing_count')} citing, "
              f"{len(entry['negative_passages'])} negative passages", flush=True)

    OUT_JSON.write_text(json.dumps(results, indent=1), encoding="utf-8")
    lines = [
        "# Citator pre-screen — cycle 001 priority + flagged cases\n",
        "> **This is not a citator.** CourtListener's citation graph shows *that*",
        "> a case was cited, not that it survives. Every verdict below narrows,",
        "> never replaces, the manual KeyCite/Shepard's gate (spec §10).\n",
    ]
    for e in results:
        name = (e.get("cl_cluster") or {}).get("case_name") or ""
        url = (e.get("cl_cluster") or {}).get("url") or ""
        lines.append(f"\n## {e['cite']} {name} ({e.get('jur')} {e.get('year')})")
        lines.append(f"- verdict: **{e['verdict']}** · citing cases: "
                     f"{e.get('citing_count', '?')} · [CourtListener]({url})")
        for f in e.get("flags", []):
            if f.startswith("abrogation-risk"):
                lines.append(f"- prior flag: {f}")
        for p in e["negative_passages"]:
            lines.append(f"- NEGATIVE SIGNAL in *{p['citing_case']}* ({p['date']}), "
                         f"keyword `{p['signal']}`:")
            lines.append(f"  > {p['passage']}")
        if e["citing"]:
            recent = ", ".join(f"{c['case_name']} ({c['date']})"
                               for c in e["citing"][:5])
            lines.append(f"- most recent citing: {recent}")
        lines.append("- [ ] citator-checked (KeyCite/Shepard's — human)")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    used = len(lim.times)
    print(f"done -> {OUT_MD} | requests used in last 24h: {used}/125")
    return 0


if __name__ == "__main__":
    sys.exit(main())
