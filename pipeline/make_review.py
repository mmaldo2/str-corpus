"""Render the cycle human-review queue as a self-saving decision page.

v2: decisions are real input. The page declares the `artifact` runtime
capability; "Save decisions" publishes a new version of the page with the
decision state embedded, which the pipeline session then reads back and
commits to the repo as the durable record. Where the capability is absent
(e.g. non-claude.ai viewer) the page falls back to copy-to-clipboard JSON.

Inputs (per run):
  runs/<run>/review-queue.json      four queues + case info
  runs/<run>/fuzzy-diffs.json       side-by-side + trivial/needs-human class
  runs/<run>/adjudications.json     third-reader recommendations
  runs/cycle-001-remap/verified/*   re-mapped, re-verified records

Outputs:
  reports/review-queue.html   (content-only file for the Artifact tool)
  reports/review-queue.md     (durable plain checklist)

Usage: python pipeline/make_review.py --run-id cycle-001-shard-02
"""

import argparse
import base64
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STATE_MARKER = "__REVIEW_STATE__"
TB64_MARKER = "__TEMPLATE_B64__"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def cl_link(cite: str) -> str:
    return "https://www.courtlistener.com/?q=%22" + esc((cite or "").replace(" ", "+")) + "%22"


def load_data(run_id: str) -> dict:
    run = ROOT / "runs" / run_id
    queue = json.loads((run / "review-queue.json").read_text(encoding="utf-8"))
    diffs = json.loads((run / "fuzzy-diffs.json").read_text(encoding="utf-8"))
    adj = json.loads((run / "adjudications.json").read_text(encoding="utf-8"))
    remap = []
    remap_dir = ROOT / "runs" / (run_id.split("-shard")[0] + "-remap") / "verified"
    for f in sorted(remap_dir.glob("*.json")):
        remap.extend(json.loads(f.read_text(encoding="utf-8")))

    info_by_case = {}
    for lst in (queue["fuzzy"], queue["disagreements"], queue["nulled"],
                queue["householder_nights"]):
        for e in lst:
            info_by_case[e["case_id"]] = {
                k: e.get(k) for k in ("cite", "name", "year", "jur", "court")
            }
    diff_by = {(d["case_id"], d["quote"]): d for d in diffs}
    adj_by = {(a["case_id"], a["field"]): a for a in adj}

    A = queue["householder_nights"]
    B = []
    for e in queue["fuzzy"]:
        d = diff_by.get((e["case_id"], e["quote"]), {})
        B.append({**e, "source": d.get("source"),
                  "classification": d.get("classification", "needs-human"),
                  "coverage": d.get("quote_coverage")})
    C = []
    for e in queue["disagreements"]:
        a = adj_by.get((e["case_id"], e["field"]), {})
        C.append({**e, "recommendation": a.get("recommendation"),
                  "justification": a.get("justification"),
                  "supporting_quote": a.get("supporting_quote")})
    # D: only the remap cases where the two models DISAGREE (agreed cases
    # auto-accept into the ledger, same standard as the main run), rendered
    # C-style with third-reader recommendations.
    remap_by = {r["case_id"]: r for r in remap}
    D = []
    remap_dir2 = ROOT / "runs" / (run_id.split("-shard")[0] + "-remap")
    if (remap_dir2 / "remap-disagreements.json").exists():
        rdis = json.loads(
            (remap_dir2 / "remap-disagreements.json").read_text(encoding="utf-8"))
        radj = {}
        if (remap_dir2 / "adjudications.json").exists():
            radj = {(a["case_id"], a["field"]): a for a in json.loads(
                (remap_dir2 / "adjudications.json").read_text(encoding="utf-8"))}
        for d in rdis:
            a = radj.get((d["case_id"], d["field"]), {})
            r = remap_by.get(d["case_id"], {})
            D.append({**info_by_case.get(d["case_id"], {}),
                      "case_id": d["case_id"], "field": d["field"],
                      "claude": d.get("claude"), "codex": d.get("codex"),
                      "recommendation": a.get("recommendation"),
                      "justification": a.get("justification"),
                      "supporting_quote": a.get("supporting_quote"),
                      "holding": r.get("holding_summary")})
    return {"A": A, "B": B, "C": C, "D": D}


def build_pages(run_id: str) -> None:
    data = load_data(run_id)
    data_json = json.dumps(data).replace("</", "<\\/")
    cycle_label = run_id.split("-shard")[0].replace("cycle-", "Cycle ")
    content = (CONTENT_TMPL.replace("{{DATA}}", data_json)
               .replace("{{CYCLE}}", cycle_label)
               .replace("<title>Cycle 001 Review Queue</title>",
                        f"<title>{cycle_label} Review Queue</title>")
               .replace("'rq1-'", f"'rq-{run_id}-'"))
    # full-document template used by the page to republish itself
    full = ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "</head><body>" + content + "</body></html>")
    tb64 = base64.b64encode(full.encode("utf-8")).decode("ascii")
    # carry forward previously saved decisions if a snapshot exists
    snap = ROOT / "runs" / run_id / "decisions-snapshot.json"
    initial_state = "{}"
    if snap.exists():
        initial_state = json.dumps(
            json.loads(snap.read_text(encoding="utf-8"))
        ).replace("</", "<\\/")
    out = content.replace(TB64_MARKER, tb64).replace(
        f'"{STATE_MARKER}"', initial_state
    )
    cycle = run_id.split("-shard")[0]
    (ROOT / "reports" / f"review-queue-{cycle}.html").write_text(out, encoding="utf-8")

    md = [f"# {cycle} — Human review queue (with recommendations)\n"]
    for key, title in (("A", "Householder x nights priority cases"),
                       ("B", "Fuzzy quotes (side-by-side)"),
                       ("C", "Disagreements (with third-reader recommendation)"),
                       ("D", "Re-mapped records (re-verified)")):
        md.append(f"\n## {key}. {title} ({len(data[key])})")
        for e in data[key]:
            cite = e.get("cite") or e.get("case_id")
            extra = ""
            if key == "B":
                extra = f" — {e.get('classification')}"
            if key == "C":
                extra = f" — {e['field']}: rec={e.get('recommendation')}"
            if key == "D":
                extra = f" — remapped: {e.get('polarity')}/{e.get('who')}/{e.get('duration')}"
            md.append(f"- [ ] {cite} {e.get('name') or ''}{extra}")
    (ROOT / "reports" / f"review-queue-{cycle}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote reports/review-queue-{cycle}.html (+md); template",
          len(tb64) // 1024, "KB b64")


CONTENT_TMPL = r"""<title>Cycle 001 Review Queue</title>
<style>
:root{--bg:#101418;--panel:#171d24;--panel2:#1d242d;--border:#2a333d;--border2:#38434f;
--text:#e8eaed;--muted:#9aa5b1;--amber:#ffc14d;--mint:#46f9b8;--sky:#6aa9ff;--magenta:#ff6b8a;
--sans:'Source Sans 3',system-ui,sans-serif;--mono:'IBM Plex Mono',ui-monospace,Consolas,monospace}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 var(--sans);padding:28px 28px 90px}
.wrap{max-width:900px;margin:0 auto}
h1{font-family:Georgia,serif;font-weight:600;font-size:26px;margin:0 0 4px}
.sub{color:var(--muted);max-width:75ch}
section{margin-top:34px}
h2{font-size:17px;border-bottom:1px solid var(--border);padding-bottom:8px}
h2 .k{display:inline-flex;width:24px;height:24px;border-radius:6px;background:var(--amber);
color:#101418;align-items:center;justify-content:center;font:700 13px var(--sans);margin-right:6px}
h2 .count{float:right;font:600 12px var(--mono);color:var(--mint)}
.blurb{color:var(--muted);font-size:13.5px;margin-top:-4px}
.item{background:var(--panel);border:1px solid var(--border);border-radius:10px;
padding:12px 14px;margin:10px 0}
.item.decided{border-color:#22493a}
.cite a{color:var(--sky);text-decoration:none;font:500 13px var(--mono)}
.cite a:hover{text-decoration:underline}
.meta{color:var(--muted);font:400 12px var(--mono)}
blockquote{margin:8px 0;padding:8px 12px;background:#0b0e12;border-left:3px solid var(--amber);
border-radius:0 8px 8px 0;font-size:13.5px;color:#d9dee3;overflow-wrap:break-word}
blockquote.src{border-left-color:var(--sky)}
.rec{margin:8px 0;padding:8px 12px;background:#0f1d17;border:1px solid #2c4a3a;border-radius:8px;font-size:13.5px}
.rec .lab{font:600 10px var(--mono);letter-spacing:.12em;color:var(--mint);text-transform:uppercase}
.vs{margin-top:4px}.claude{color:var(--sky)}.codex{color:var(--magenta)}
p{margin:6px 0;font-size:13.5px;color:#c9d1d9}
.controls{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;align-items:center}
.controls button{background:var(--panel2);color:var(--muted);border:1px solid var(--border2);
border-radius:999px;padding:4px 12px;font:600 12px var(--sans);cursor:pointer}
.controls button:hover{color:var(--text)}
.controls button.on{background:var(--mint);border-color:var(--mint);color:#101418}
.controls button.on.neg{background:var(--magenta);border-color:var(--magenta)}
.controls input[type=text]{flex:1;min-width:160px;background:#0b0e12;border:1px solid var(--border);
border-radius:8px;color:var(--text);font:400 12.5px var(--sans);padding:5px 9px}
.chip{font:600 10.5px var(--mono);border-radius:999px;padding:2px 9px;border:1px solid var(--border2);color:var(--muted)}
.chip.triv{color:#101418;background:var(--mint);border-color:var(--mint)}
.chip.hum{color:#101418;background:var(--amber);border-color:var(--amber)}
.savebar{position:fixed;left:0;right:0;bottom:0;background:#0b0e12ee;border-top:1px solid var(--border);
padding:12px 28px;display:flex;gap:14px;align-items:center;backdrop-filter:blur(4px)}
.savebar .status{font:500 12.5px var(--mono);color:var(--muted)}
.savebar button{background:var(--mint);color:#101418;border:none;border-radius:8px;
padding:9px 20px;font:700 14px var(--sans);cursor:pointer}
.savebar button:disabled{opacity:.4;cursor:default}
.savebar .alt{background:var(--panel2);color:var(--text);border:1px solid var(--border2)}
button:focus-visible,input:focus-visible{outline:2px solid var(--sky);outline-offset:2px}
</style>
<div class="wrap">
<h1>{{CYCLE}} — Human Review Queue</h1>
<p class="sub">Every item carries a machine recommendation where one exists — your job is to
confirm or override. Decisions are saved into this page itself when you press
<b>Save decisions</b> (bottom bar); the pipeline reads them back as the durable record.
Citations link to CourtListener.</p>
<div id="sections"></div>
</div>
<div class="savebar">
  <button id="save">Save decisions</button>
  <button id="copy" class="alt">Copy JSON</button>
  <span class="status" id="status"></span>
</div>
<script type="application/json" id="review-state">"__REVIEW_STATE__"</script>
<script>
const DATA = {{DATA}};
const TB64 = "__TEMPLATE_B64__";
let state = {};
try { state = JSON.parse(document.getElementById('review-state').textContent) || {}; } catch(e) {}
if (typeof state !== 'object' || state === null || typeof state === 'string') state = {};
let dirty = 0;

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const clq = c => 'https://www.courtlistener.com/?q=%22' + encodeURIComponent(String(c||'')) + '%22';
const head = e => `<span class="cite"><a href="${clq(e.cite)}" target="_blank" rel="noopener">${esc(e.cite || e.case_id)}</a></span> <b>${esc(e.name||'')}</b> <span class="meta">(${esc(e.jur)} ${esc(e.year)})</span>`;

const SECTIONS = [
  {key:'A', title:'Householder × nights — priority favorable cases',
   blurb:'The highest-value stratum. Confirm the holding reads right, then citator-check before any use.',
   opts:[['accept','Accept'],['needs-work','Needs work'],['reject','Reject','neg']],
   extra:[['citator','Citator checked']],
   render:e=>`${head(e)}<div class="meta">court called it: ${esc(e.characterization)}</div><p>${esc(e.holding)}</p>`+
     (e.quotes||[]).map(q=>`<blockquote>&ldquo;${esc(q.t)}&rdquo;<span class="meta"> — p. ${esc(q.p)} (${esc(q.s)})</span></blockquote>`).join('')},
  {key:'B', title:'Fuzzy quotes — AI quote vs. corpus text',
   blurb:'Top (amber): what the AI reader quoted. Bottom (blue): what the corpus actually says at that spot. 22 are pre-classified as trivial scan noise — one click to confirm.',
   opts:[['ocr-ok','Scan noise — OK'],['mismatch','Real mismatch','neg']],
   render:e=>`${head(e)}<span class="chip ${e.classification==='trivial-ocr'?'triv':'hum'}">${e.classification==='trivial-ocr'?'machine: trivial OCR':'machine: needs judgment'}</span>
     <blockquote>&ldquo;${esc(e.quote)}&rdquo;<span class="meta"> — as quoted (p. ${esc(e.page)}, supports ${esc(e.supports)})</span></blockquote>
     <blockquote class="src">${esc(e.source)}<span class="meta"> — corpus text at match</span></blockquote>`},
  {key:'C', title:'Cross-model disagreements — with third-reader recommendation',
   blurb:'Two AI readers split; a third read the case and recommends. Accept the recommendation or override.',
   opts:[['accept-rec','Accept recommendation'],['claude','Side with A'],['codex','Side with B'],['other','Other','neg']],
   render:e=>`${head(e)}<div class="vs">field <b>${esc(e.field)}</b>: <span class="claude">A (Claude): ${esc(e.claude)}</span> vs <span class="codex">B (Codex): ${esc(e.codex)}</span></div>
     <div class="rec"><div class="lab">Third reader recommends: ${esc(e.recommendation)}</div>
     <p>${esc(e.justification)}</p>${e.supporting_quote?`<blockquote>&ldquo;${esc(e.supporting_quote)}&rdquo;</blockquote>`:''}</div>`},
  {key:'D', title:'Re-mapped records — contested fields only',
   blurb:'The 19 voided records were re-extracted, re-verified, and cross-checked by a second model. Seven cases with full agreement auto-accepted into the ledger (same standard as the main run). Below are only the contested fields, each with a third-reader recommendation.',
   opts:[['accept-rec','Accept recommendation'],['claude','Side with A'],['codex','Side with B'],['other','Other','neg']],
   render:e=>`${head(e)}<div class="vs">field <b>${esc(e.field)}</b>: <span class="claude">A (re-map): ${esc(e.claude)}</span> vs <span class="codex">B (Codex): ${esc(e.codex)}</span></div>
     ${e.holding?`<p class="meta">${esc(e.holding)}</p>`:''}
     <div class="rec"><div class="lab">Third reader recommends: ${esc(e.recommendation)}</div>
     <p>${esc(e.justification)}</p>${e.supporting_quote?`<blockquote>&ldquo;${esc(e.supporting_quote)}&rdquo;</blockquote>`:''}</div>`},
];

function itemKey(sec, i){ return sec + '-' + i; }
function render(){
  const root = document.getElementById('sections');
  root.innerHTML = '';
  for(const S of SECTIONS){
    const items = DATA[S.key] || [];
    const sec = document.createElement('section');
    sec.innerHTML = `<h2><span class="k">${S.key}</span> ${esc(S.title)} <span class="count" id="cnt-${S.key}"></span></h2><p class="blurb">${esc(S.blurb)}</p>`;
    items.forEach((e, i) => {
      const k = itemKey(S.key, i);
      const st = state[k] || {};
      const div = document.createElement('div');
      div.className = 'item' + (st.decision ? ' decided' : '');
      div.dataset.k = k;
      let controls = S.opts.map(([v, label, neg]) =>
        `<button data-v="${v}" class="${st.decision===v?'on':''} ${neg||''}">${label}</button>`).join('');
      for(const [v, label] of (S.extra || []))
        controls += `<button data-x="${v}" class="${st[v]?'on':''}">${label}${st[v]?' ✓':''}</button>`;
      controls += `<input type="text" placeholder="note (optional)" value="${esc(st.note||'')}">`;
      div.innerHTML = S.render(e) + `<div class="controls">${controls}</div>`;
      div.querySelectorAll('button[data-v]').forEach(b => b.onclick = () => {
        state[k] = {...(state[k]||{}), decision: b.dataset.v, at: new Date().toISOString()};
        dirty++; render();
      });
      div.querySelectorAll('button[data-x]').forEach(b => b.onclick = () => {
        state[k] = {...(state[k]||{}), [b.dataset.x]: !(state[k]||{})[b.dataset.x]};
        dirty++; render();
      });
      const inp = div.querySelector('input[type=text]');
      inp.onchange = () => { state[k] = {...(state[k]||{}), note: inp.value}; dirty++; updateBar(); };
      sec.appendChild(div);
    });
    root.appendChild(sec);
    const done = items.filter((_, i) => (state[itemKey(S.key, i)]||{}).decision).length;
    sec.querySelector(`#cnt-${S.key}`).textContent = done + '/' + items.length;
  }
  updateBar();
}
function updateBar(){
  const total = SECTIONS.reduce((n, S) => n + (DATA[S.key]||[]).length, 0);
  const done = Object.values(state).filter(s => s && s.decision).length;
  document.getElementById('status').textContent =
    `${done}/${total} decided` + (dirty ? ` · ${dirty} unsaved change${dirty>1?'s':''}` : ' · saved');
}
function rebuildDoc(){
  const tmpl = new TextDecoder().decode(Uint8Array.from(atob(TB64), c => c.charCodeAt(0)));
  const stateMarker = '"__REVIEW_' + 'STATE__"';
  const tb64Marker = '"' + '__TEMPLATE_' + 'B64__' + '"';
  const payload = JSON.stringify({...state, _meta:{savedAt:new Date().toISOString()}})
    .replace(/</g, '\\u003c');
  return tmpl.split('"__REVIEW_' + 'STATE__"').join(payload)
             .split('__TEMPLATE_' + 'B64__').join(TB64);
}
document.getElementById('save').onclick = async () => {
  const btn = document.getElementById('save');
  btn.disabled = true; btn.textContent = 'Saving…';
  try {
    const art = (typeof claude !== 'undefined' && claude.use)
      ? await claude.use('artifact') : null;
    if(!art){ throw new Error('no-capability'); }
    await art.publish(rebuildDoc());
    dirty = 0; btn.textContent = 'Saved ✓';
  } catch(err) {
    btn.textContent = 'Save decisions';
    document.getElementById('status').textContent =
      err.message === 'no-capability'
        ? 'Saving unavailable in this viewer — use Copy JSON and send it back.'
        : 'Save failed (' + (err.code || err.message) + ') — try again or Copy JSON.';
    btn.disabled = false; return;
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = 'Save decisions'; updateBar(); }, 1200);
};
document.getElementById('copy').onclick = async () => {
  try {
    await navigator.clipboard.writeText(JSON.stringify(state, null, 1));
    document.getElementById('status').textContent = 'Decision JSON copied to clipboard.';
  } catch(e) {
    document.getElementById('status').textContent = 'Clipboard blocked — select and copy from console.';
  }
};
render();
</script>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="cycle-001-shard-02")
    build_pages(ap.parse_args().run_id)
