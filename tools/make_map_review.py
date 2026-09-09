r"""Render the cycle-004 map review round as a self-saving decision page (spec section 9).

Same mechanics as tools/make_reference_review.py - the page declares the `artifact` runtime
capability and "Save decisions" republishes the page with the decision state embedded, so the
saved page IS the record - with six sections instead of two, cross links where a record has
several reasons, the reader's values, the checker's second opinion, the verified quotes, the
holding summary, and a CourtListener link.

Two modes, and only one of them costs anything:

  --check   D5's 100% checker pass. Builds the domain's checker provider through
            corpus_engine/reader/providers/factory.py and runs `check_queue` over every
            queued record (unit cap = the queue's size, one case per unit). This CALLS THE
            CODEX CLI; it belongs to the live steps, and the tests drive it with a scripted
            provider instead. It writes the per-case answers beside the queue and records
            the checker path - which plan type and which pin - into the queue manifest, so a
            round can never be read as if its second opinion had come from somewhere else.
  --build   Render the page. No network, no provider: the checker answers are read off disk.

Input : runs/<run-id>/review-round-<n>.json          (Queue.to_json(), written by the caller)
        runs/<run-id>/review-round-<n>-checker.json  (check_queue output, from --check)
Output: reports/review-queue-map-cycle-004.{html,md}

Publish with: capabilities={"artifact": {}}

  .venv\Scripts\python tools\make_map_review.py --check --queue runs\<run>\review-round-1.json
  .venv\Scripts\python tools\make_map_review.py --build --queue runs\<run>\review-round-1.json
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Reuse the save mechanism the user's existing review pages run on rather than forking it:
# the markers, the escaping and the CourtListener link builder all come from the cycle page
# generator unchanged.
_spec = importlib.util.spec_from_file_location("make_review", ROOT / "pipeline" / "make_review.py")
_mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mr)

STATE_MARKER = _mr.STATE_MARKER          # "__REVIEW_STATE__"
TB64_MARKER = _mr.TB64_MARKER            # "__TEMPLATE_B64__"
esc = _mr.esc
cl_link = _mr.cl_link

from corpus_engine.mapper.queue import (QueueCard, Queue, SECTIONS,  # noqa: E402
                                        check_queue, checker_path)
from corpus_engine.reader.schema import (CHARACTERIZATION_VALUES,  # noqa: E402
                                         DURATION_VALUES, OWNER_FREEDOM_VALUES,
                                         POLARITY_VALUES, RESTRICTION_VALUES,
                                         UNDER_THIRTY_VALUES, WHO_VALUES)

DEFAULT_STEM = "reports/review-queue-map-cycle-004"

# The vocabulary a card may set. Read from the reader's schema, never re-declared here, so a
# codebook that adds a value works without editing this tool. `quotes` (section F) carries no
# vocabulary: a fuzzy quote is kept or sent for a full read, never re-typed on the page.
VOCAB = {"relevant": ["true", "false"],
         "polarity": list(POLARITY_VALUES) + ["null"],
         "who_was_letting": list(WHO_VALUES),
         "duration_of_occupancy": [v if v is not None else "null" for v in DURATION_VALUES],
         "characterization": [v if v is not None else "null" for v in CHARACTERIZATION_VALUES],
         "under_thirty_days": [v if v is not None else "null" for v in UNDER_THIRTY_VALUES],
         "owner_freedom_characterization": [v if v is not None else "null"
                                            for v in OWNER_FREEDOM_VALUES],
         "restriction_nature": [v if v is not None else "null" for v in RESTRICTION_VALUES]}


def write_text(path: Path, text: str) -> None:
    """LF, UTF-8 without BOM, one trailing newline - explicit bytes, not the platform's idea
    of a line ending."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _conflict_view(cf: dict) -> dict:
    """A section-G card's `conflict` (CONFLICT_KEYS shape), trimmed to what the page's client
    JS needs to render the warning box - deliberately not the export shape's own key spelling,
    so the page's embedded JSON never carries a second copy of it. Spec section 7: the card
    shows BOTH bases, not only the human one - `them_who`/`them_prompt`/`them_run` are the
    re-read's own `model`/`prompt_version`/`run_id`, beside the human `reviewer`/`run_id`."""
    hb = cf.get("human_basis") or {}
    rb = cf.get("reread_basis") or {}
    return {"field": cf.get("field"), "human_value": cf.get("human_value"),
            "human_who": hb.get("reviewer") or "reviewer", "human_run": hb.get("run_id") or "?",
            "them_value": cf.get("reread_value"), "them_who": rb.get("model") or "the re-read",
            "them_prompt": rb.get("prompt_version") or "?", "them_run": rb.get("run_id") or "?",
            "kind": cf.get("kind")}


def _for_page(sections: dict) -> dict:
    """A shallow copy of the queue's per-section card lists, safe to embed in the page's own
    JSON blob: every card's `conflict` (section G only) is narrowed through `_conflict_view`
    first. `sections` itself (the queue's own object) is left untouched, since the markdown
    summary below still walks it directly."""
    out = {}
    for sec, cards in sections.items():
        new_cards = []
        for c in cards or ():
            c2 = dict(c)
            if c2.get("conflict"):
                c2["conflict"] = _conflict_view(c2["conflict"])
            new_cards.append(c2)
        out[sec] = new_cards
    return out


def build_pages(queue: dict, out_stem: Path, *, checker: dict | None = None) -> tuple:
    """queue: `Queue.to_json()`. checker: `{case_id: {"values": {...}, "status": ...}}`."""
    checker = {str(k): v for k, v in (checker or {}).items()}
    sections = queue["sections"]
    n_cards = sum(len(v) for v in sections.values())
    data = {"sections": _for_page(sections), "titles": queue["titles"], "checker": checker,
            "run_id": queue["run_id"], "cap": queue["cap"], "deferred": queue["deferred"]}
    data_json = json.dumps(data).replace("</", "<\\/")
    content = (CONTENT_TMPL.replace("{{DATA}}", data_json)
               .replace("{{VOCAB}}", json.dumps(VOCAB))
               .replace("{{RUN}}", esc(queue["run_id"]))
               .replace("{{N_CARDS}}", str(n_cards))
               .replace("{{CAP}}", str(queue["cap"]))
               .replace("{{N_DEFERRED}}", str(len(queue["deferred"]))))
    # Full document the page republishes itself as (doctype first, per the artifact
    # capability contract). It still carries the markers, so a saved copy can be saved again.
    full = ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "</head><body>" + content + "</body></html>")
    tb64 = base64.b64encode(full.encode("utf-8")).decode("ascii")
    out = content.replace(TB64_MARKER, tb64).replace(f'"{STATE_MARKER}"', "[]")

    html_path = Path(str(out_stem) + ".html")
    md_path = Path(str(out_stem) + ".md")
    write_text(html_path, out)
    try:                                   # a repo-relative path in the durable checklist, so
        shown = html_path.resolve().relative_to(ROOT).as_posix()   # the committed file does
    except ValueError:                                             # not name one machine's disk
        shown = html_path.as_posix()
    md = [f"# Cycle-004 map review - {queue['run_id']}", "",
          f"{n_cards} cards this round (cap {queue['cap']}); "
          f"{len(queue['deferred'])} carried to the next round.",
          f"Page: {shown} (decisions are saved into the page itself).", ""]
    for sec, title in queue["titles"].items():
        cards = sections.get(sec) or []
        if not cards:
            continue
        md.append(f"\n## {sec}. {title} ({len(cards)})\n")
        for c in cards:
            md.append(f"- [ ] {c.get('cite') or c['case_id']} - {c.get('name') or ''} "
                      f"[{c['case_id']}] - decide {c['decide_field']} "
                      f"reader={c['values'].get(c['decide_field'])} "
                      f"also={','.join(c.get('other_reasons') or []) or '-'}")
    write_text(md_path, "\n".join(md))
    return html_path, md_path, len(tb64)


def cards_from_doc(doc: dict) -> Queue:
    """The queue manifest read back as a `Queue`, for a pass that only needs the case ids and
    their jurisdictions (`--check`). The cards' records are the manifest's own values, not a
    re-read of the ledger: the checker must be asked about the round that was WRITTEN, even
    if the ledger has moved since."""
    cards = []
    for sec, _key, _title in SECTIONS:
        for c in (doc.get("sections") or {}).get(sec) or ():
            record = dict(c.get("values") or {})
            record.update({"case_id": c["case_id"], "jurisdiction": c.get("jur") or "?",
                           "nulled_fields": list(c.get("nulled_fields") or ())})
            cards.append(QueueCard(int(c["case_id"]), sec, c["reason"],
                                   tuple(c.get("other_reasons") or ()), record,
                                   tuple(c.get("disagreements") or ()),
                                   tuple(c.get("fuzzy") or ()),
                                   conflict=c.get("conflict")))
    return Queue(doc.get("run_id", ""), tuple(cards), tuple(doc.get("deferred") or ()),
                 int(doc.get("cap") or len(cards)))


def checker_pin_for(domain):
    """The pin for the domain's `reader.checker`, spelled exactly as tools/map_reader.py
    spells it, so the round's second opinion is addressed by the same pin the map's own
    checker sample was."""
    from corpus_engine.reader.model import ModelPin
    c = domain.reader.checker
    if not c:
        raise SystemExit("this domain declares no reader.checker; there is no second opinion "
                         "to ask, and D5's pass is not defined without one")
    return ModelPin(c["model_id"], c["family"], extra={"cli_model": c["cli_model"]})


def default_checker(domain, *, log=print):
    """(reader_factory, pin, why) for `--check`. Called only by the live pass.

    `providers.factory.provider_for` resolves the claude-cli subscription reader and the
    OpenRouter candidates; the codex checker is neither, so it is constructed here the one
    way the map itself constructs it rather than pretending the factory has a path for it.
    """
    from corpus_engine import store
    from corpus_engine.reader.cache import ResponseCache
    from corpus_engine.reader.driver import Reader
    from corpus_engine.reader.providers.codex_cli import CodexCliProvider
    from corpus_engine.reader.sources import StoreCaseSource
    from corpus_engine.textnorm_version import NORM_VERSION

    provider = CodexCliProvider(domain.reader.checker["cli_model"])
    if not provider.is_available():
        raise SystemExit("codex cli not available; D5's checker pass cannot run without it")
    conn = store.connect(ROOT / "data" / "db" / "corpus.db")
    source = StoreCaseSource(conn)
    cache = ResponseCache(ROOT / "data" / "reader" / "cache")

    def factory():
        return Reader(provider, source, cache=cache, log=log, domain=domain,
                      store_norm_version=f"v{NORM_VERSION}")

    return factory, checker_pin_for(domain), f"codex cli {domain.reader.checker['cli_model']}"


def run_check(queue_doc: dict, out_path: Path, *, reader_factory, codebook, checker_pin,
              budget, manifest_path: Path | None = None) -> dict:
    """D5's 100% pass, and the manifest note that says which path it took (R10)."""
    queue = cards_from_doc(queue_doc)
    results = check_queue(queue, reader_factory=reader_factory, codebook=codebook,
                          checker_pin=checker_pin, budget=budget)
    write_text(out_path, json.dumps({str(k): v for k, v in sorted(results.items())}, indent=1))
    # One unit per DISTINCT case, not per card: section G can queue two cards for one case
    # and `check_queue` asks the checker about the case once (final review, nit 13).
    queue_doc["checker_path"] = checker_path(
        checker_pin, unit_cap=len({c.case_id for c in queue.cards}))
    queue_doc["checker_results"] = out_path.as_posix()
    if manifest_path is not None:
        write_text(manifest_path, json.dumps(queue_doc, indent=1))
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="run the checker at 100%% over the queued records (CALLS CODEX)")
    mode.add_argument("--build", action="store_true", help="render the page")
    ap.add_argument("--queue", required=True, help="the queue manifest (Queue.to_json())")
    ap.add_argument("--checker", default=None,
                    help="check_queue output; defaults to <queue>-checker.json")
    ap.add_argument("--out-stem", default=DEFAULT_STEM)
    ap.add_argument("--max-units", type=int, default=None,
                    help="unit ceiling for --check (default: the queue's size, i.e. 100%%)")
    a = ap.parse_args(argv)

    queue_path = Path(a.queue)
    doc = json.loads(queue_path.read_text(encoding="utf-8"))
    checker_out = Path(a.checker) if a.checker else queue_path.with_name(
        queue_path.stem + "-checker.json")
    if a.check:
        from corpus_engine.domain import load_domain
        from corpus_engine.reader.codebook import load_codebook
        from corpus_engine.reader.model import Budget

        domain = load_domain()
        n = sum(len(v) for v in (doc.get("sections") or {}).values())
        budget = Budget(max_units=a.max_units if a.max_units is not None else n)
        factory, pin, why = default_checker(domain)
        codebook = load_codebook(domain, domain.reader.codebook)
        print(f"checker: {why}; {n} queued records at 100%", flush=True)
        results = run_check(doc, checker_out, reader_factory=factory, codebook=codebook,
                            checker_pin=pin, budget=budget, manifest_path=queue_path)
        tally: dict[str, int] = {}
        for r in results.values():
            key = r["status"].split(":")[0]
            tally[key] = tally.get(key, 0) + 1
        print(f"{len(results)} checked {tally} -> {checker_out.as_posix()}", flush=True)
        return 0

    checker = json.loads(checker_out.read_text(encoding="utf-8")) if checker_out.exists() else {}
    html_path, md_path, tb64_len = build_pages(doc, Path(a.out_stem), checker=checker)
    print(f"wrote {html_path.as_posix()} ({html_path.stat().st_size // 1024} KB) + "
          f"{md_path.as_posix()}; template {tb64_len // 1024} KB b64", flush=True)
    return 0


CONTENT_TMPL = r"""<title>Cycle-004 map review</title>
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
.xlink{font:500 12px var(--sans);color:var(--accent);text-decoration:none;margin-left:8px}
.xlink:hover{text-decoration:underline}
.cmp{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
.cmp>div{flex:1 1 220px;background:var(--panel2);border:1px solid var(--border);
border-radius:8px;padding:8px 10px}
.cmp .lab{font:600 10px var(--mono);letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}
.cmp .val{font:600 15px var(--mono);margin-top:3px;overflow-wrap:anywhere}
.cmp .chk .val{color:var(--accent)}
table.cand{width:100%;border-collapse:collapse;margin:6px 0 2px;font:400 12.5px var(--mono)}
table.cand td{padding:2px 6px 2px 0;border-bottom:1px solid var(--border);vertical-align:top}
table.cand td.c{color:var(--muted);width:34%}
td .nulled{text-decoration:line-through;color:var(--muted)}
td .tag{font-size:10.5px;color:var(--neg);margin-left:6px;letter-spacing:.04em}
.ev{margin:8px 0 0}
.ev .lab{font:600 10px var(--mono);letter-spacing:.11em;text-transform:uppercase;
color:var(--muted);margin-top:8px}
blockquote{margin:6px 0;padding:8px 12px;background:var(--quote);
border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
font:400 14px/1.6 var(--serif);overflow-wrap:anywhere;max-height:220px;overflow-y:auto}
blockquote.src{border-left-color:var(--link)}
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
<h1>Cycle-004 map review</h1>
<p class="sub">Run <b>{{RUN}}</b>. <b>{{N_CARDS}}</b> cards this round (cap {{CAP}});
<b>{{N_DEFERRED}}</b> records wait for the next round in the same order. Each card asks you to
decide <i>one field</i> on one case: the reader's value stands unless you change it, and the
checker is a second reader from a different model family, not an authority. Deciding a card is
what moves the record from machine-only to human-reviewed. Decisions are saved into this page
itself when you press <b>Save decisions</b>; if the viewer cannot save, use <b>Copy JSON</b>
and paste it back. Citations link to CourtListener.</p>
<div class="bar">
  <button id="save-top">Save decisions</button>
  <button id="copy-top" class="alt">Copy JSON</button>
  <span class="status" id="status-top"></span>
</div>
<section id="sec-G"><h2><span class="k">G</span> Re-read conflicts with a human decision
  <span class="count" id="cnt-G"></span></h2>
  <p class="blurb">A mapper-v3 re-read disagrees with a value you already decided by hand.
  Your value stands unless you change it - there is no "adopt" here, since the re-read's
  answer is already shown on the card.</p><div id="cards-G"></div></section>
<section id="sec-A"><h2><span class="k">A</span> Favorable and under thirty days
  <span class="count" id="cnt-A"></span></h2>
  <p class="blurb">The claim the corpus exists to support: the owner's liberty to let, in a
  case about occupancy shorter than a month.</p><div id="cards-A"></div></section>
<section id="sec-B"><h2><span class="k">B</span> Householder letting by the night
  <span class="count" id="cnt-B"></span></h2>
  <p class="blurb">A householder letting rooms by the night - the closest historical analogue
  to a short-term rental.</p><div id="cards-B"></div></section>
<section id="sec-C"><h2><span class="k">C</span> Reader / checker disagreement
  <span class="count" id="cnt-C"></span></h2>
  <p class="blurb">A second model family read the same opinion and answered differently on
  relevance, polarity or characterization.</p><div id="cards-C"></div></section>
<section id="sec-D"><h2><span class="k">D</span> Polarity mixed
  <span class="count" id="cnt-D"></span></h2>
  <p class="blurb">The reader could not put the case on one side of the owner's right to
  let.</p><div id="cards-D"></div></section>
<section id="sec-E"><h2><span class="k">E</span> Judged fields erased by the quote gate
  <span class="count" id="cnt-E"></span></h2>
  <p class="blurb">The reader filled the field and the gate voided it, because no verbatim
  quote supported it. The value below is what the gate left, not what the model said.</p>
  <div id="cards-E"></div></section>
<section id="sec-F"><h2><span class="k">F</span> Fuzzy quote match
  <span class="count" id="cnt-F"></span></h2>
  <p class="blurb">The supporting quote matched the opinion only approximately and the
  mechanical rule would not call the difference OCR noise.</p><div id="cards-F"></div></section>
</div>
<div class="savebar">
  <button id="save">Save decisions</button>
  <button id="copy" class="alt">Copy JSON</button>
  <span class="status" id="status"></span>
</div>
<script type="application/json" id="review-state">"__REVIEW_STATE__"</script>
<script>
const DOC = {{DATA}};
const DATA = DOC.sections;
const CHECKER = DOC.checker || {};
const VOCAB = {{VOCAB}};
const TB64 = "__TEMPLATE_B64__";
const SECTIONS = [['G','reread_conflict'],['A','favorable_under_thirty'],
                  ['B','householder_nights'],['C','checker_disagreement'],
                  ['D','polarity_mixed'],['E','gate_erased'],['F','fuzzy_quote']];
const SEC_OF_REASON = {};
for (const [s, r] of SECTIONS) SEC_OF_REASON[r] = s;

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
const checkerValue = (it, field) => {
  const c = CHECKER[String(it.case_id)];
  if (!c || !c.values || !(field in c.values)) return undefined;
  return c.values[field];
};

function quotes(list){
  const rows = (list || []).map(q => {
    const tag = q.status && q.status !== 'verified'
      ? `<span class="who">${esc(q.status)}</span>` : '';
    const sup = (Array.isArray(q.supports) ? q.supports : (q.supports ? [q.supports] : [])).join(', ');
    return `<blockquote>&ldquo;${esc(q.text || '')}&rdquo;<span class="who">supports: ${esc(sup)}</span>${tag}</blockquote>`;
  }).join('');
  return rows ? `<div class="ev"><div class="lab">Verified quotes</div>${rows}</div>` : '';
}

function fuzzyBlock(list){
  const rows = (list || []).map(f => `
    <blockquote>&ldquo;${esc(f.text || '')}&rdquo;<span class="who">quote as extracted &middot;
      coverage ${esc(f.quote_coverage)} &middot; ${esc(f.classification || '')}</span></blockquote>
    <blockquote class="src">${esc(f.source || '')}<span class="who">the opinion at the match</span></blockquote>`).join('');
  return rows ? `<div class="ev"><div class="lab">Fuzzy quote against its source</div>${rows}</div>` : '';
}

function card(it){
  const field = it.decide_field;
  const k = it.case_id + '::' + field;
  const sec = it.section;
  const st = state[k] || {};
  const div = document.createElement('div');
  div.className = 'item' + (st.decision ? ' decided' : '');
  div.id = anchor(sec, it.case_id);

  const cross = (it.other_reasons || []).map(r =>
    `<a class="xlink" href="#${anchor(SEC_OF_REASON[r], it.case_id)}">also ${esc(r)} &rarr;</a>`).join('');
  const rows = (it.disagreements || []).map(d =>
    `<tr><td class="c">${esc(d.field)}</td><td>reader ${esc(show(d.reader_value))} &middot;
      checker ${esc(show(d.checker_value))}</td></tr>`).join('');
  const dis = rows ? `<table class="cand">${rows}</table>` : '';
  const fpRows = (it.first_passes || []).map(p =>
    `<tr><td class="c">${esc(p.who)}</td><td><b>${esc(p.outcome)}</b> &mdash; ${esc(p.note || '')}</td></tr>`).join('');
  const fp = fpRows ? `<div class="warn">Two independent first passes disagree on this card; both are shown, neither is a vote.</div><table class="cand">${fpRows}</table>` : '';

  const nulled = (it.nulled_fields || []).length
    ? `<div class="warn">The quote gate voided <b>${esc((it.nulled_fields || []).join(', '))}</b>
       on this record (extraction status <code>${esc(show(it.extraction_status))}</code>): the
       reader answered and no verbatim quote supported it.</div>` : '';

  const cf = it.conflict;
  const conflict = cf ? `<div class="warn">A mapper-v3 re-read disagrees with a decision you
       already made. Your <b>${esc(cf.field)}</b> is <code>${esc(show(cf.human_value))}</code>
       (${esc(cf.human_who)}, run ${esc(cf.human_run)}); the re-read
       (${esc(cf.them_who)}, prompt ${esc(cf.them_prompt)}, run ${esc(cf.them_run)}) reads
       <code>${esc(show(cf.them_value))}</code>. Your value stands unless you change it
       here.</div>` : '';

  const readerVal = field === 'quotes' ? `${(it.quotes || []).length} quotes`
                                       : show((it.values || {})[field]);
  const cv = checkerValue(it, field);
  const cstat = (CHECKER[String(it.case_id)] || {}).status || 'not asked';
  const checkerCell = cv === undefined ? esc(cstat) : esc(show(cv));

  const vocab = VOCAB[field];
  const opts = (vocab || []).map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  const adoptRow = (sec === 'G' || cv === undefined) ? ''
    : `<label><input type="radio" name="d-${k}" value="adopt"> Adopt checker value <code>${esc(show(cv))}</code></label>`;
  const setRow = vocab
    ? `<label><input type="radio" name="d-${k}" value="set"> Set to: <select>${opts}</select></label>` : '';

  div.innerHTML = `
    <div><span class="nm">${esc(it.name || '')}</span>${cross}</div>
    <div class="cite"><a href="${clq(it.cite)}" target="_blank" rel="noopener">${esc(it.cite || '')}</a></div>
    <div class="meta">${esc(it.court || '')} &middot; ${esc(it.jur || '')} &middot; ${esc(it.year || '')} &middot; case ${esc(it.case_id)} &middot; deciding <b>${esc(field)}</b></div>
    <div class="cmp">
      <div><div class="lab">Reader says</div><div class="val">${esc(readerVal)}</div></div>
      <div class="chk"><div class="lab">Checker says</div><div class="val">${checkerCell}</div></div>
    </div>
    ${dis}${fp}
    ${nulled}
    ${conflict}
    ${it.holding_summary ? `<p class="hold">Holding: ${esc(it.holding_summary)}</p>` : ''}
    ${quotes(it.quotes)}
    ${fuzzyBlock(it.fuzzy)}
    <div class="controls">
      <label><input type="radio" name="d-${k}" value="keep"> Keep reader value <code>${esc(readerVal)}</code></label>
      ${adoptRow}
      ${setRow}
      <label><input type="radio" name="d-${k}" value="unsure"> Unsure &mdash; needs full read</label>
      <input type="text" placeholder="note (optional)">
    </div>`;

  const sel = div.querySelector('select');
  const note = div.querySelector('input[type=text]');
  if (sel && st.decision === 'set' && st.value != null) sel.value = String(st.value);
  if (st.note) note.value = st.note;
  const radios = div.querySelectorAll('input[type=radio]');
  radios.forEach(r => {
    if (st.decision === r.value) r.checked = true;
    r.onchange = () => { record(div, it, k, field, r.value, sel, note); };
  });
  if (sel) sel.onchange = () => {
    const r = div.querySelector('input[type=radio][value=set]');
    r.checked = true; record(div, it, k, field, 'set', sel, note);
  };
  note.oninput = () => {
    const cur = state[k];
    if (cur) { cur.note = note.value; dirty++; updateBar(); }
  };
  return div;
}

function record(div, it, k, field, decision, sel, note){
  let value = null;
  if (decision === 'keep') value = field === 'quotes' ? null : ((it.values || {})[field] ?? null);
  else if (decision === 'adopt') value = checkerValue(it, field) ?? null;
  else if (decision === 'set' && sel) value = sel.value === 'null' ? null : sel.value;
  state[k] = {case_id: it.case_id, field: field, decision: decision,
              value: value, note: note.value || ''};
  div.classList.add('decided');
  dirty++; updateCounts(); updateBar();
}

function decisions(){
  const out = [];
  for (const [sec] of SECTIONS)
    for (const it of (DATA[sec] || [])) {
      const d = state[it.case_id + '::' + it.decide_field];
      if (d && d.decision) out.push(d);
    }
  return out;
}

function updateCounts(){
  for (const [sec] of SECTIONS) {
    const items = DATA[sec] || [];
    const done = items.filter(it => (state[it.case_id + '::' + it.decide_field] || {}).decision).length;
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
  const items = DATA[sec] || [];
  if (!items.length) document.getElementById('sec-' + sec).style.display = 'none';
  for (const it of items) root.appendChild(card(it));
}
for (const id of ['save','save-top'])
  document.getElementById(id).onclick = (e) => save(e.currentTarget);
for (const id of ['copy','copy-top'])
  document.getElementById(id).onclick = copyJson;
updateCounts(); updateBar();
</script>
"""


if __name__ == "__main__":
    raise SystemExit(main())
