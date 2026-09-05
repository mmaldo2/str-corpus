"""Render the contested reference labels of the reader kit as a self-saving decision page.

Same shape as pipeline/make_review.py (the cycle review queues the user already
adjudicates): the page declares the `artifact` runtime capability, and "Save
decisions" republishes the page with the decision state embedded, so the saved
page IS the record. Where the capability is absent the page falls back to
copy-to-clipboard JSON. A durable plain checklist is written alongside.

Queue: kit cases where at least 3 of the 5 measured reader candidates returned
the same non-null post-gate value for a field AND that value differs from the
kit reference label. The user decides which label the reference should carry.

Input:
  data/reader/review/reference-v1/contested.json   (from the polarity diagnostic)

Outputs:
  reports/review-queue-reference-v1.html   (content-only file for the Artifact tool)
  reports/review-queue-reference-v1.md     (durable plain checklist)

Publish with: capabilities={"artifact": {}}

Usage: python tools/make_reference_review.py
"""

import argparse
import base64
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Reuse the save mechanism the user's existing review pages run on, rather than
# forking it: the markers, the escaping and the CourtListener link builder all
# come from the cycle page generator unchanged.
_spec = importlib.util.spec_from_file_location(
    "make_review", ROOT / "pipeline" / "make_review.py")
_mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mr)

STATE_MARKER = _mr.STATE_MARKER          # "__REVIEW_STATE__"
TB64_MARKER = _mr.TB64_MARKER            # "__TEMPLATE_B64__"
esc = _mr.esc
cl_link = _mr.cl_link

DEFAULT_CONTESTED = ROOT / "data" / "reader" / "review" / "reference-v1" / "contested.json"
DEFAULT_STEM = "reports/review-queue-reference-v1"

# Fixed order and short labels for the five measured candidates.
CANDIDATES = [
    ("anthropic/claude-opus-5", "opus-5"),
    ("openai/gpt-5.6-terra", "gpt-5.6-terra"),
    ("z-ai/glm-5.3", "glm-5.3"),
    ("google/gemini-3.7-flash", "gemini-3.7-flash"),
    ("anthropic/claude-sonnet-5", "sonnet-5"),
]

FIELDS = [
    ("polarity", "A", "Polarity"),
    ("who_was_letting", "B", "Who was letting"),
]

# Wording, not structure. A contested document may carry a `page` block to name its own
# queue - a second queue built on a different rule must not describe itself with the first
# one's prose. Everything absent falls back to the v1 wording, so the v1 document renders
# byte-identically. The values are trusted HTML fragments: this generator's own input, not
# anything a reviewer types.
PAGE_DEFAULTS = {
    "title": "Reference adjudication v1",
    # line breaks preserved so the v1 page regenerates byte-for-byte
    "intro": """These are reader-kit cases where at least <b>3 of the 5</b> measured reader
models agreed with each other <i>against</i> the ledger's reference label. A model majority
is not authority — it is a flag that the reference label may be wrong. Your decision sets
what the reference carries, and the kit is what every future reader is scored against.
Decisions are saved into this page itself when you press <b>Save decisions</b>; if the
viewer cannot save, use <b>Copy JSON</b> and paste it back. Citations link to CourtListener.""",
    "blurbs": {
        "A": """Polarity is the outcome for the owner's right to let ({n} cases).
  A majority of <code>irrelevant</code> means the models read the case as out of scope
  altogether, not as a polarity value.""",
        "B": """Who the letting party was ({n} cases). Cases contested on both
  fields appear in both sections and are cross-linked.""",
    },
    "lede": ("{cases} cases where 3+ of 5 reader candidates agreed against the ledger label; "
             "{decisions} field decisions."),
}


def page_text(doc: dict) -> dict:
    """The page's wording: the defaults, overridden key by key from `doc["page"]`."""
    page = dict(doc.get("page") or {})
    out = dict(PAGE_DEFAULTS, **{k: v for k, v in page.items() if k != "blurbs"})
    out["blurbs"] = dict(PAGE_DEFAULTS["blurbs"], **(page.get("blurbs") or {}))
    return out
SEC_OF_FIELD = {f: s for f, s, _ in FIELDS}
VOCAB = {
    "polarity": ["favorable", "adverse", "mixed", "null"],
    "who_was_letting": ["householder", "commercial_operator",
                        "non_resident_owner", "unclear"],
}


def _short(candidate: str) -> str:
    for full, label in CANDIDATES:
        if full == candidate:
            return label
    return candidate


def _evidence(entries) -> list:
    out = []
    for e in (entries or [])[:2]:
        out.append({"cand": _short(e.get("candidate")),
                    "quote": e.get("quote") or "",
                    "holding": e.get("holding_summary") or ""})
    return out


def build_items(doc: dict) -> dict:
    """One item per (case, contested field); a case contested on both appears twice."""
    data = {"A": [], "B": []}
    for case in doc.get("contested", []):
        fields = [f for f in case.get("contested_fields", []) if f in SEC_OF_FIELD]
        for field in fields:
            maj = (case.get("majority") or {}).get(field) or {}
            cands = []
            for full, label in CANDIDATES:
                c = (case.get("candidates") or {}).get(full) or {}
                v = c.get(field) or {}
                cands.append({
                    "label": label,
                    "value": v.get("model_value"),
                    "gated": v.get("gated_value"),
                    "nulled": bool(v.get("gate_nulled")),
                    "present": bool(c.get("record_present", False)),
                })
            other = [SEC_OF_FIELD[f] for f in fields if f != field]
            data[SEC_OF_FIELD[field]].append({
                "case_id": case.get("case_id"),
                "name": case.get("name"),
                "cite": case.get("cite"),
                "court": case.get("court"),
                "jur": case.get("jurisdiction"),
                "year": case.get("year"),
                "field": field,
                "ref": (case.get("reference") or {}).get(field),
                "ref_relevant": (case.get("reference") or {}).get("relevant"),
                "maj": maj.get("majority_value"),
                "maj_n": maj.get("majority_n"),
                "non_null_n": maj.get("non_null_n"),
                "cands": cands,
                "ev_maj": _evidence((case.get("evidence_for_majority") or {}).get(field)),
                "ev_ref": _evidence((case.get("evidence_for_reference") or {}).get(field)),
                "other": other[0] if other else None,
            })
    return data


def write_text(path: Path, text: str) -> None:
    """LF, UTF-8 without BOM, one trailing newline - explicit bytes, not the
    platform's idea of a line ending."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def build_pages(contested: Path, out_stem: Path) -> tuple:
    doc = json.loads(Path(contested).read_text(encoding="utf-8"))
    data = build_items(doc)
    data_json = json.dumps(data).replace("</", "<\\/")
    page = page_text(doc)

    content = (CONTENT_TMPL
               .replace("{{DATA}}", data_json)
               .replace("{{VOCAB}}", json.dumps(VOCAB))
               .replace("{{TITLE}}", page["title"])
               .replace("{{INTRO}}", page["intro"])
               .replace("{{BLURB_A}}", page["blurbs"]["A"].format(n=len(data["A"])))
               .replace("{{BLURB_B}}", page["blurbs"]["B"].format(n=len(data["B"])))
               # a section with nothing in it is not a queue; hide it rather than offer the
               # reviewer an empty heading with a "0 / 0 decided" counter beside it
               .replace("{{HIDE_A}}", "" if data["A"] else ' style="display:none"')
               .replace("{{HIDE_B}}", "" if data["B"] else ' style="display:none"')
               .replace("{{N_CASES}}", str(len(doc.get("contested", [])))))
    # Full document the page republishes itself as (doctype first, per the
    # artifact capability contract). It still carries the markers, so a saved
    # copy can be saved again.
    full = ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "</head><body>" + content + "</body></html>")
    tb64 = base64.b64encode(full.encode("utf-8")).decode("ascii")
    out = content.replace(TB64_MARKER, tb64).replace(f'"{STATE_MARKER}"', "[]")

    html_path = Path(str(out_stem) + ".html")
    md_path = Path(str(out_stem) + ".md")
    write_text(html_path, out)

    try:                               # a repo-relative path in the durable checklist, so the
        shown = html_path.resolve().relative_to(ROOT).as_posix()   # committed file does not
    except ValueError:                                             # name one machine's disk
        shown = html_path.as_posix()
    md = [f"# {page.get('md_title') or page['title'] + ' - contested kit reference labels'}",
          "",
          page["lede"].format(cases=len(doc.get("contested", [])),
                              decisions=len(data["A"]) + len(data["B"])),
          f"Page: {shown} (decisions are saved into the page itself).",
          ""]
    for field, key, title in FIELDS:
        if not data[key]:
            continue
        md.append(f"\n## {key}. {title} ({len(data[key])})\n")
        for e in data[key]:
            cite = e.get("cite") or e.get("case_id")
            md.append(f"- [ ] {cite} — {e.get('name') or ''} "
                      f"[{e['case_id']}] — ledger={e['ref']} vs majority={e['maj']} "
                      f"({e['maj_n']} of {e['non_null_n']})")
    write_text(md_path, "\n".join(md))
    return html_path, md_path, len(tb64)


CONTENT_TMPL = r"""<title>{{TITLE}}</title>
<style>
:root{
  --bg:#f6f6f4;--panel:#ffffff;--panel2:#eeefeb;--border:#dcdfd8;--border2:#c2c7bd;
  --text:#191d21;--muted:#5b6570;--head:#2b3138;
  --accent:#8a5a12;--ok:#0d6b48;--link:#0b53b0;--neg:#a51f52;--quote:#fbf9f3;
  --sans:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --serif:Georgia,'Iowan Old Style','Times New Roman',serif;
  --mono:ui-monospace,'IBM Plex Mono',Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#101418;--panel:#171d24;--panel2:#1d242d;--border:#2a333d;--border2:#3a4550;
  --text:#e8eaed;--muted:#9aa5b1;--head:#f0f2f4;
  --accent:#ffc14d;--ok:#46f9b8;--link:#6aa9ff;--neg:#ff6b8a;--quote:#0e1216;
}}
:root[data-theme="dark"]{
  --bg:#101418;--panel:#171d24;--panel2:#1d242d;--border:#2a333d;--border2:#3a4550;
  --text:#e8eaed;--muted:#9aa5b1;--head:#f0f2f4;
  --accent:#ffc14d;--ok:#46f9b8;--link:#6aa9ff;--neg:#ff6b8a;--quote:#0e1216;
}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 var(--sans);
padding:26px 22px 96px;overflow-x:hidden}
.wrap{max-width:940px;margin:0 auto}
h1{font-family:var(--serif);font-weight:600;font-size:26px;margin:0 0 6px;color:var(--head)}
.sub{color:var(--muted);max-width:78ch;font-size:13.5px}
section{margin-top:30px}
h2{font-size:17px;color:var(--head);border-bottom:1px solid var(--border);padding-bottom:8px}
h2 .k{display:inline-flex;width:24px;height:24px;border-radius:6px;background:var(--accent);
color:var(--bg);align-items:center;justify-content:center;font:700 13px var(--sans);margin-right:6px}
h2 .count{float:right;font:600 12px var(--mono);color:var(--ok)}
.blurb{color:var(--muted);font-size:13.5px;margin-top:-2px}
.item{background:var(--panel);border:1px solid var(--border);border-radius:10px;
padding:12px 14px;margin:12px 0;scroll-margin-top:12px}
.item.decided{border-color:var(--ok)}
.cite a{color:var(--link);text-decoration:none;font:500 13px var(--mono)}
.cite a:hover{text-decoration:underline}
.nm{font-family:var(--serif);font-size:16px;font-weight:600}
.meta{color:var(--muted);font:400 12px var(--mono);overflow-wrap:anywhere}
.xlink{font:500 12px var(--sans);color:var(--accent);text-decoration:none}
.xlink:hover{text-decoration:underline}
.cmp{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
.cmp>div{flex:1 1 220px;background:var(--panel2);border:1px solid var(--border);
border-radius:8px;padding:8px 10px}
.cmp .lab{font:600 10px var(--mono);letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}
.cmp .val{font:600 15px var(--mono);margin-top:3px;overflow-wrap:anywhere}
.cmp .maj .val{color:var(--accent)}
table.cand{width:100%;border-collapse:collapse;margin:6px 0 2px;font:400 12.5px var(--mono)}
table.cand td{padding:2px 6px 2px 0;border-bottom:1px solid var(--border);vertical-align:top}
table.cand td.c{color:var(--muted);width:34%}
td .nulled{text-decoration:line-through;color:var(--muted)}
td .tag{font-size:10.5px;color:var(--neg);margin-left:6px;letter-spacing:.04em}
td .agree{color:var(--accent)}
.ev{margin:8px 0 0}
.ev .lab{font:600 10px var(--mono);letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin-top:8px}
blockquote{margin:6px 0;padding:8px 12px;background:var(--quote);
border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
font:400 14px/1.6 var(--serif);overflow-wrap:anywhere;max-height:220px;overflow-y:auto}
blockquote.ref{border-left-color:var(--link)}
blockquote .who{display:block;margin-top:6px;font:400 11.5px var(--mono);color:var(--muted)}
.hold{font:400 12.5px/1.5 var(--sans);color:var(--muted);margin:2px 0 6px}
.warn{margin:8px 0 0;padding:7px 10px;border:1px dashed var(--border2);border-radius:8px;
font-size:12.5px;color:var(--muted)}
.controls{margin-top:11px;border-top:1px solid var(--border);padding-top:9px;
display:flex;flex-direction:column;gap:5px}
.controls label{display:flex;align-items:center;gap:7px;font-size:13.5px;flex-wrap:wrap}
.controls code{font:600 12.5px var(--mono);color:var(--accent)}
select,input[type=text]{background:var(--bg);border:1px solid var(--border2);border-radius:7px;
color:var(--text);font:400 12.5px var(--sans);padding:4px 8px}
input[type=text]{margin-top:4px;width:100%;box-sizing:border-box}
.bar{display:flex;gap:12px;align-items:center;margin:14px 0 2px}
.savebar{position:fixed;left:0;right:0;bottom:0;background:var(--panel);
border-top:1px solid var(--border);padding:11px 22px;display:flex;gap:12px;align-items:center}
button{background:var(--ok);color:var(--bg);border:none;border-radius:8px;
padding:8px 18px;font:700 13.5px var(--sans);cursor:pointer}
button.alt{background:var(--panel2);color:var(--text);border:1px solid var(--border2)}
button:disabled{opacity:.45;cursor:default}
.status{font:500 12.5px var(--mono);color:var(--muted)}
a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{
outline:2px solid var(--link);outline-offset:2px}
</style>
<div class="wrap">
<h1>{{TITLE}}</h1>
<p class="sub">{{INTRO}}</p>
<div class="bar">
  <button id="save-top">Save decisions</button>
  <button id="copy-top" class="alt">Copy JSON</button>
  <span class="status" id="status-top"></span>
</div>
<section{{HIDE_A}}>
  <h2><span class="k">A</span> Polarity <span class="count" id="cnt-A"></span></h2>
  <p class="blurb">{{BLURB_A}}</p>
  <div id="cards-A"></div>
</section>
<section{{HIDE_B}}>
  <h2><span class="k">B</span> Who was letting <span class="count" id="cnt-B"></span></h2>
  <p class="blurb">{{BLURB_B}}</p>
  <div id="cards-B"></div>
</section>
</div>
<div class="savebar">
  <button id="save">Save decisions</button>
  <button id="copy" class="alt">Copy JSON</button>
  <span class="status" id="status"></span>
</div>
<script type="application/json" id="review-state">"__REVIEW_STATE__"</script>
<script>
const DATA = {{DATA}};
const VOCAB = {{VOCAB}};
const TB64 = "__TEMPLATE_B64__";
const SECTIONS = [['A','polarity'],['B','who_was_letting']];

let state = {};
try {
  const raw = JSON.parse(document.getElementById('review-state').textContent);
  if (Array.isArray(raw)) for (const d of raw) { if (d && d.case_id != null && d.field) state[d.case_id + '::' + d.field] = d; }
} catch(e) {}
let dirty = 0;

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const clq = c => 'https://www.courtlistener.com/?q=%22' + encodeURIComponent(String(c||'')) + '%22';
const show = v => v === null || v === undefined ? 'null' : String(v);
const anchor = (sec, id) => 'c-' + sec + '-' + id;

function quotes(list, cls, label){
  const rows = list.map(q => {
    const body = q.quote
      ? `<blockquote class="${cls}">&ldquo;${esc(q.quote)}&rdquo;<span class="who">— ${esc(q.cand)}</span></blockquote>`
      : '';
    const hold = q.holding ? `<p class="hold">${esc(q.cand)} read the holding as: ${esc(q.holding)}</p>` : '';
    return body + hold;
  }).join('');
  return rows ? `<div class="ev"><div class="lab">${esc(label)}</div>${rows}</div>` : '';
}

function card(it){
  const k = it.case_id + '::' + it.field;
  const sec = it.field === 'polarity' ? 'A' : 'B';
  const st = state[k] || {};
  const div = document.createElement('div');
  div.className = 'item' + (st.decision ? ' decided' : '');
  div.id = anchor(sec, it.case_id);

  const cross = it.other
    ? ` <a class="xlink" href="#${anchor(it.other, it.case_id)}">also contested on ${it.other === 'A' ? 'polarity' : 'who was letting'} &rarr;</a>`
    : '';
  const rows = it.cands.map(c => {
    const v = show(c.value);
    const cell = !c.present ? '<span class="nulled">no record</span>'
      : c.nulled ? `<span class="nulled">${esc(v)}</span><span class="tag">gate-nulled</span>`
      : `<span class="${String(c.gated) === String(it.maj) ? 'agree' : ''}">${esc(v)}</span>`;
    return `<tr><td class="c">${esc(c.label)}</td><td>${cell}</td></tr>`;
  }).join('');

  const noQuote = ['irrelevant','unclear'].indexOf(String(it.maj)) >= 0
    && !it.ev_maj.some(q => q.quote);
  const warn = noQuote
    ? `<div class="warn">The majority value is <b>${esc(show(it.maj))}</b>, so no candidate
       offered a supporting quote — the models declined to place the case rather than
       pointing at language. Judge this one on the holding summaries.</div>`
    : '';

  const opts = (VOCAB[it.field] || []).map(v =>
    `<option value="${esc(v)}">${esc(v)}</option>`).join('');

  div.innerHTML = `
    <div><span class="nm">${esc(it.name || '')}</span>${cross}</div>
    <div class="cite"><a href="${clq(it.cite)}" target="_blank" rel="noopener">${esc(it.cite || '')}</a></div>
    <div class="meta">${esc(it.court || '')} · ${esc(it.jur || '')} · ${esc(it.year || '')} · case ${esc(it.case_id)}</div>
    <div class="cmp">
      <div><div class="lab">Ledger says</div><div class="val">${esc(show(it.ref))}</div></div>
      <div class="maj"><div class="lab">Majority (${esc(it.maj_n)} of 5) says</div>
        <div class="val">${esc(show(it.maj))}</div></div>
    </div>
    <table class="cand">${rows}</table>
    ${warn}
    ${quotes(it.ev_maj, '', 'Quotes offered for the majority value')}
    ${quotes(it.ev_ref, 'ref', 'Quotes offered for the ledger value')}
    <div class="controls">
      <label><input type="radio" name="d-${k}" value="keep"> Keep ledger value <code>${esc(show(it.ref))}</code></label>
      <label><input type="radio" name="d-${k}" value="adopt"> Adopt majority value <code>${esc(show(it.maj))}</code></label>
      <label><input type="radio" name="d-${k}" value="set"> Set to: <select>${opts}</select></label>
      <label><input type="radio" name="d-${k}" value="unsure"> Unsure — needs full read</label>
      <input type="text" placeholder="note (optional)">
    </div>`;

  const sel = div.querySelector('select');
  const note = div.querySelector('input[type=text]');
  if (st.decision === 'set' && st.value != null) sel.value = String(st.value);
  if (st.note) note.value = st.note;
  const radios = div.querySelectorAll('input[type=radio]');
  radios.forEach(r => {
    if (st.decision === r.value) r.checked = true;
    r.onchange = () => { record(div, it, k, r.value, sel, note); };
  });
  sel.onchange = () => {
    const r = div.querySelector('input[type=radio][value=set]');
    r.checked = true; record(div, it, k, 'set', sel, note);
  };
  note.oninput = () => {
    const cur = state[k];
    if (cur) { cur.note = note.value; dirty++; updateBar(); }
  };
  return div;
}

function record(div, it, k, decision, sel, note){
  let value = null;
  if (decision === 'keep') value = it.ref ?? null;
  else if (decision === 'adopt') value = it.maj ?? null;
  else if (decision === 'set') value = sel.value === 'null' ? null : sel.value;
  state[k] = {case_id: it.case_id, field: it.field, decision: decision,
              value: value, note: note.value || ''};
  div.classList.add('decided');
  dirty++; updateCounts(); updateBar();
}

function decisions(){
  const out = [];
  for (const [sec, field] of SECTIONS)
    for (const it of (DATA[sec] || [])) {
      const d = state[it.case_id + '::' + it.field];
      if (d && d.decision) out.push(d);
    }
  return out;
}

function updateCounts(){
  for (const [sec] of SECTIONS) {
    const items = DATA[sec] || [];
    const done = items.filter(it => (state[it.case_id + '::' + it.field] || {}).decision).length;
    document.getElementById('cnt-' + sec).textContent = done + ' / ' + items.length + ' decided';
  }
}

function updateBar(){
  const total = SECTIONS.reduce((n, s) => n + (DATA[s[0]] || []).length, 0);
  const done = decisions().length;
  const txt = `${done}/${total} decided` +
    (dirty ? ` · ${dirty} unsaved change${dirty > 1 ? 's' : ''}` : ' · saved');
  for (const id of ['status','status-top']) document.getElementById(id).textContent = txt;
}

function rebuildDoc(){
  const tmpl = new TextDecoder().decode(Uint8Array.from(atob(TB64), c => c.charCodeAt(0)));
  const payload = JSON.stringify(decisions()).replace(/</g, '\\u003c');
  return tmpl.split('"__REVIEW_' + 'STATE__"').join(payload)
             .split('__TEMPLATE_' + 'B64__').join(TB64);
}

async function save(btn){
  const others = [document.getElementById('save'), document.getElementById('save-top')];
  others.forEach(b => b.disabled = true);
  const label = btn.textContent;
  btn.textContent = 'Saving…';
  try {
    const art = (typeof claude !== 'undefined' && claude.use)
      ? await claude.use('artifact') : null;
    if(!art){ throw new Error('no-capability'); }
    await art.publish(rebuildDoc());
    dirty = 0; btn.textContent = 'Saved ✓';
  } catch(err) {
    btn.textContent = label;
    const msg = err.message === 'no-capability'
      ? 'Saving unavailable in this viewer — use Copy JSON and send it back.'
      : 'Save failed (' + (err.code || err.message) + ') — try again or Copy JSON.';
    for (const id of ['status','status-top']) document.getElementById(id).textContent = msg;
    others.forEach(b => b.disabled = false); return;
  }
  setTimeout(() => { others.forEach(b => b.disabled = false);
    btn.textContent = 'Save decisions'; updateBar(); }, 1200);
}

async function copyJson(){
  let msg;
  try {
    await navigator.clipboard.writeText(JSON.stringify(decisions(), null, 1));
    msg = 'Decision JSON copied to clipboard.';
  } catch(e) { msg = 'Clipboard blocked — open the console and copy from there.'; }
  for (const id of ['status','status-top']) document.getElementById(id).textContent = msg;
}

for (const [sec] of SECTIONS) {
  const root = document.getElementById('cards-' + sec);
  for (const it of (DATA[sec] || [])) root.appendChild(card(it));
}
for (const id of ['save','save-top'])
  document.getElementById(id).onclick = (e) => save(e.currentTarget);
for (const id of ['copy','copy-top'])
  document.getElementById(id).onclick = copyJson;
updateCounts(); updateBar();
</script>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--contested", default=str(DEFAULT_CONTESTED))
    ap.add_argument("--out-stem", default=DEFAULT_STEM)
    a = ap.parse_args()
    html_path, md_path, tb64_len = build_pages(Path(a.contested), Path(a.out_stem))
    size = html_path.stat().st_size
    print(f"wrote {html_path.as_posix()} ({size // 1024} KB) + {md_path.as_posix()}; "
          f"template {tb64_len // 1024} KB b64")
