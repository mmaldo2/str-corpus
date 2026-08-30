"""Render the human-review queue (review-queue.json) as a checklist page
(reports/review-queue.html) + a durable markdown copy (reports/review-queue.md).

Checkbox state persists per-viewer in localStorage — a convenience, not a
record; the durable record of adjudications belongs in the repo.

Usage: python pipeline/make_review.py --run-id cycle-001-shard-02
"""

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cl_link(cite: str) -> str:
    q = html.escape((cite or "").replace(" ", "+"))
    return f"https://www.courtlistener.com/?q=%22{q}%22"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def case_head(e: dict) -> str:
    return (
        f'<span class="cite"><a href="{cl_link(e.get("cite"))}" target="_blank" '
        f'rel="noopener">{esc(e.get("cite") or e.get("case_id"))}</a></span> '
        f'<b>{esc(e.get("name") or "")}</b> '
        f'<span class="meta">({esc(e.get("jur"))} {esc(e.get("year"))} · {esc(e.get("court"))})</span>'
    )


def item(idx: str, body: str) -> str:
    return (
        f'<label class="item" data-k="{idx}"><input type="checkbox">'
        f'<div class="body">{body}</div></label>'
    )


def render(run_id: str) -> None:
    data = json.loads(
        (ROOT / "runs" / run_id / "review-queue.json").read_text(encoding="utf-8")
    )
    sections = []

    rows = []
    for i, e in enumerate(data["householder_nights"]):
        quotes = "".join(
            f'<blockquote>&ldquo;{esc(q["t"])}&rdquo;'
            f'<span class="meta"> — at p. {esc(q["p"])} ({esc(q["s"])})</span></blockquote>'
            for q in e["quotes"]
        )
        rows.append(item(f"hxn-{i}",
            f'{case_head(e)}<div class="meta">court called it: {esc(e.get("characterization"))}</div>'
            f'<p>{esc(e.get("holding"))}</p>{quotes}'
            f'<div class="todo">Verify holding against the opinion · KeyCite/Shepardize · [ ] citator-checked</div>'))
    sections.append(("A", "Householder × nights — priority favorable cases",
        "The highest-value stratum for the level-of-generality argument. Read, verify, citator-check.",
        rows))

    rows = []
    for i, e in enumerate(data["fuzzy"]):
        rows.append(item(f"fz-{i}",
            f'{case_head(e)}<blockquote>&ldquo;{esc(e["quote"])}&rdquo;'
            f'<span class="meta"> — at p. {esc(e["page"])} · similarity {esc(e["score"])} · supports: {esc(e["supports"])}</span></blockquote>'
            f'<div class="todo">Compare against the scanned page: is the difference OCR noise, or a real mismatch?</div>'))
    sections.append(("B", "Fuzzy-verified quotes",
        "Passed the quote gate only on the OCR-tolerance path. Confirm each against the source scan before any use.",
        rows))

    rows = []
    for i, d in enumerate(data["disagreements"]):
        rows.append(item(f"dg-{i}",
            f'{case_head(d)}<div class="vs">field <b>{esc(d["field"])}</b>: '
            f'<span class="claude">Claude: {esc(d.get("claude"))}</span> vs '
            f'<span class="codex">Codex: {esc(d.get("codex"))}</span>'
            f'<span class="meta"> · {esc(d.get("batch_id"))}</span></div>'
            f'<div class="todo">Read the case; record the correct value.</div>'))
    sections.append(("C", "Cross-model disagreements",
        "The two AI readers answered differently. Your call is the record.",
        rows))

    rows = []
    for i, e in enumerate(data["nulled"]):
        rows.append(item(f"nl-{i}",
            f'{case_head(e)}<div class="meta">who: {esc(e.get("who"))} · duration: {esc(e.get("duration"))} '
            f'· nulled: {esc(", ".join(e.get("nulled") or []))}</div>'
            f'<p>{esc(e.get("holding"))}</p>'
            f'<div class="meta">worker notes: {esc(e.get("notes"))}</div>'
            f'<div class="todo">The supporting quote failed verification, so the field was voided. Re-read: re-map, or discard.</div>'))
    sections.append(("D", "Quote-gate-nulled records",
        "Marked relevant, but the quote supporting polarity failed the verbatim gate — conclusions voided pending re-read.",
        rows))

    sec_html = ""
    md = ["# Cycle 001 — Human review queue\n",
          f"Source: `runs/{run_id}/review-queue.json`. Checkbox page: reports/review-queue.html "
          "(state is per-browser; record final adjudications in the repo).\n"]
    for key, title, blurb, rows in sections:
        sec_html += (
            f'<section><h2><span class="k">{key}</span> {esc(title)} '
            f'<span class="count" data-sec="{key}">0/{len(rows)}</span></h2>'
            f'<p class="blurb">{esc(blurb)}</p>{"".join(rows)}</section>'
        )
        md.append(f"\n## {key}. {title} ({len(rows)} items)\n{blurb}\n")
        for r_i, e in enumerate(
            data["householder_nights"] if key == "A" else
            data["fuzzy"] if key == "B" else
            data["disagreements"] if key == "C" else data["nulled"]
        ):
            cite = e.get("cite") or e.get("case_id")
            name = e.get("name") or ""
            extra = ""
            if key == "B":
                extra = f' — "{e["quote"][:110]}…" (p. {e.get("page")}, sim {e.get("score")})'
            if key == "C":
                extra = f' — {e["field"]}: Claude={e.get("claude")} vs Codex={e.get("codex")}'
            md.append(f"- [ ] {cite} {name}{extra}")

    page = PAGE_TMPL.replace("{{SECTIONS}}", sec_html)
    (ROOT / "reports" / "review-queue.html").write_text(page, encoding="utf-8")
    (ROOT / "reports" / "review-queue.md").write_text("\n".join(md), encoding="utf-8")
    print("wrote reports/review-queue.html and reports/review-queue.md")


PAGE_TMPL = """<title>Cycle 001 Review Queue</title>
<style>
:root{--bg:#101418;--panel:#171d24;--border:#2a333d;--text:#e8eaed;--muted:#9aa5b1;
--amber:#ffc14d;--mint:#46f9b8;--sky:#6aa9ff;--magenta:#ff6b8a;
--sans:'Source Sans 3',system-ui,sans-serif;--mono:'IBM Plex Mono',ui-monospace,Consolas,monospace}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 var(--sans);padding:28px}
.wrap{max-width:880px;margin:0 auto}
h1{font-family:Georgia,serif;font-weight:600;font-size:26px;margin:0 0 4px}
.sub{color:var(--muted);max-width:70ch}
section{margin-top:34px}
h2{font-size:17px;border-bottom:1px solid var(--border);padding-bottom:8px}
h2 .k{display:inline-flex;width:24px;height:24px;border-radius:6px;background:var(--amber);
color:#101418;align-items:center;justify-content:center;font:700 13px var(--sans);margin-right:6px}
h2 .count{float:right;font:600 12px var(--mono);color:var(--mint)}
.blurb{color:var(--muted);font-size:13.5px;margin-top:-4px}
.item{display:flex;gap:12px;background:var(--panel);border:1px solid var(--border);
border-radius:10px;padding:12px 14px;margin:10px 0;cursor:pointer}
.item input{margin-top:4px;accent-color:var(--mint);width:16px;height:16px;flex:none}
.item:has(input:checked){opacity:.45}
.body{min-width:0}
.cite a{color:var(--sky);text-decoration:none;font:500 13px var(--mono)}
.cite a:hover{text-decoration:underline}
.meta{color:var(--muted);font:400 12px var(--mono)}
blockquote{margin:8px 0;padding:8px 12px;background:#0b0e12;border-left:3px solid var(--amber);
border-radius:0 8px 8px 0;font-size:13.5px;color:#d9dee3;overflow-wrap:break-word}
.vs{margin-top:4px}
.claude{color:var(--sky)} .codex{color:var(--magenta)}
.todo{margin-top:6px;font:600 11.5px var(--mono);color:var(--amber)}
p{margin:6px 0;font-size:13.5px;color:#c9d1d9}
</style>
<div class="wrap">
<h1>Cycle 001 — Human Review Queue</h1>
<p class="sub">Four queues from the first extraction cycle. Checkboxes remember your progress
in this browser only — record final adjudications back in the repo. Each citation links to a
CourtListener search for the case.</p>
{{SECTIONS}}
</div>
<script>
const items=[...document.querySelectorAll('.item')];
function recount(){
  document.querySelectorAll('h2 .count').forEach(c=>{
    const sec=c.closest('section');const all=sec.querySelectorAll('.item');
    const done=sec.querySelectorAll('.item input:checked');
    c.textContent=done.length+'/'+all.length;});
}
items.forEach(it=>{
  const k='rq1-'+it.dataset.k, box=it.querySelector('input');
  try{ box.checked=localStorage.getItem(k)==='1'; }catch(e){}
  box.addEventListener('change',()=>{ try{localStorage.setItem(k,box.checked?'1':'0');}catch(e){} recount(); });
});
recount();
</script>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="cycle-001-shard-02")
    render(ap.parse_args().run_id)
