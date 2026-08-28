"""Build the gold-standard evaluation set (spec §9, amendments A4/A9/A10).

Subcommands:
    fetch     Download source briefs: Zaatari via TAMES (free, gentle),
              known self-published amicus briefs, and — when
              COURTLISTENER_API_TOKEN is set — RECAP documents for the
              district dockets. Missing sources are appended to
              data/gold/needs-human.md, never silently skipped.
    harvest   Extract text from downloaded PDFs, run eyecite, keep historical
              citations, resolve locally against the corpus citations index
              (A4), and write data/gold/gold.jsonl (tier: brief) plus
              unresolved rows to needs-human.md.
    add-treatise  Parse data/gold/treatise_anchors.md (markdown table with
              Case | Citation | ... columns) into gold.jsonl (tier: treatise).

Gold rules (A9): pre-1990 decisions only; two tiers reported separately —
headline recall is computed on tier=brief only.
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textnorm import normalize_cite

ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = ROOT / "data" / "gold"
BRIEFS_DIR = GOLD_DIR / "briefs"
GOLD_JSONL = GOLD_DIR / "gold.jsonl"
NEEDS_HUMAN = GOLD_DIR / "needs-human.md"
DB = ROOT / "data" / "db" / "corpus.db"

YEAR_CUTOFF = 1990

TAMES_CASES = {
    "zaatari": "https://search.txcourts.gov/Case.aspx?cn=03-17-00812-CV&coa=coa03",
}

# Self-published briefs with stable URLs (verified reachable during the
# grilling session's research pass; failures land in needs-human.md).
DIRECT_PDFS = {
    "marfil-amicus-slf": "https://www.slfliberty.org/wp-content/uploads/2025/05/Marfil-v.-New-Braunfels-Amicus-Brief.pdf",
}

# District dockets holding the STR litigation record (CourtListener ids from
# the grilling session's research). Fetched via RECAP API when a token exists.
RECAP_DOCKETS = {
    "nekrilov-dnj": 16646707,
    "marfil-wdtex": 17024209,
    "bodin-edla": 69644320,
}

HEADERS = {"User-Agent": "str-corpus-research/0.1 (legal-history gold set; polite)"}


def note_needs_human(lines: list[str]) -> None:
    NEEDS_HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with NEEDS_HUMAN.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(f"- {line}\n")


def fetch_tames(client: httpx.Client, key: str, url: str) -> int:
    """TAMES case pages link brief PDFs via SearchMedia.aspx. Sequential,
    2s delay — the site 502s under load."""
    dest = BRIEFS_DIR / key
    dest.mkdir(parents=True, exist_ok=True)
    r = client.get(url)
    r.raise_for_status()
    links = re.findall(r'href="(SearchMedia\.aspx[^"]+)"', r.text)
    n = 0
    for i, rel in enumerate(dict.fromkeys(links)):
        pdf_url = "https://search.txcourts.gov/" + rel.replace("&amp;", "&")
        out = dest / f"doc-{i:03d}.pdf"
        if out.exists():
            n += 1
            continue
        time.sleep(2)
        try:
            pr = client.get(pdf_url)
            pr.raise_for_status()
            if pr.content[:4] == b"%PDF":
                out.write_bytes(pr.content)
                n += 1
        except httpx.HTTPError as e:
            note_needs_human([f"TAMES fetch failed for {key}: {pdf_url} ({e})"])
    return n


def fetch_recap(client: httpx.Client, token: str, key: str, docket_id: int) -> int:
    dest = BRIEFS_DIR / key
    dest.mkdir(parents=True, exist_ok=True)
    auth = {"Authorization": f"Token {token}"}
    url = (
        "https://www.courtlistener.com/api/rest/v4/recap-documents/"
        f"?docket_entry__docket={docket_id}&is_available=true&fields=id,filepath_local,description,absolute_url"
    )
    n = 0
    while url:
        r = client.get(url, headers=auth)
        r.raise_for_status()
        data = r.json()
        for doc in data.get("results", []):
            fp = doc.get("filepath_local")
            if not fp:
                continue
            out = dest / f"recap-{doc['id']}.pdf"
            if out.exists():
                n += 1
                continue
            dl = f"https://storage.courtlistener.com/{fp}"
            time.sleep(1)
            try:
                pr = client.get(dl)
                pr.raise_for_status()
                out.write_bytes(pr.content)
                n += 1
            except httpx.HTTPError:
                note_needs_human([f"RECAP doc {doc['id']} download failed for {key}"])
        url = data.get("next")
    return n


def cmd_fetch(args) -> int:
    import os

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=HEADERS, timeout=120, follow_redirects=True) as client:
        for key, url in TAMES_CASES.items():
            try:
                n = fetch_tames(client, key, url)
                print(f"{key}: {n} PDFs (TAMES)")
            except httpx.HTTPError as e:
                print(f"{key}: TAMES fetch failed ({e})")
                note_needs_human([f"TAMES page fetch failed for {key}: {url} ({e})"])
        for key, url in DIRECT_PDFS.items():
            out = BRIEFS_DIR / "direct" / f"{key}.pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists():
                continue
            try:
                r = client.get(url)
                r.raise_for_status()
                if r.content[:4] == b"%PDF":
                    out.write_bytes(r.content)
                    print(f"{key}: fetched")
                else:
                    note_needs_human([f"Not a PDF at {url} ({key})"])
            except httpx.HTTPError as e:
                note_needs_human([f"Direct PDF fetch failed: {key} {url} ({e})"])
        token = os.environ.get("COURTLISTENER_API_TOKEN")
        if token:
            for key, docket_id in RECAP_DOCKETS.items():
                try:
                    n = fetch_recap(client, token, key, docket_id)
                    print(f"{key}: {n} RECAP docs")
                except httpx.HTTPError as e:
                    note_needs_human([f"RECAP fetch failed for {key} (docket {docket_id}): {e}"])
        else:
            note_needs_human(
                [
                    "RECAP fetch skipped: COURTLISTENER_API_TOKEN not set "
                    f"(dockets: {RECAP_DOCKETS})",
                    "Ladd v. Real Estate Commission (Pa. 33 MAP 2018): briefs not "
                    "publicly retrievable via UJS; request from IJ (ij.org) or Prothonotary.",
                    "Federal appellate briefs (3d/5th Cir.) largely absent from RECAP; "
                    "PACER purchases require an approved purchase list (A10).",
                ]
            )
            print("RECAP skipped (no COURTLISTENER_API_TOKEN); noted in needs-human.md")
    return 0


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
    except Exception as e:  # encrypted/corrupt PDFs land in needs-human
        note_needs_human([f"PDF text extraction failed: {path.name} ({e})"])
        return ""
    text = "\n".join(pages)
    # join line-break hyphenation before eyecite sees it
    text = re.sub(r"(?<=[a-zA-Z])-\s*\n\s*(?=[a-zA-Z])", "", text)
    return text


def cmd_harvest(args) -> int:
    from eyecite import clean_text, get_citations

    conn = sqlite3.connect(DB)
    rows: dict[str, dict] = {}
    pdfs = sorted(BRIEFS_DIR.glob("**/*.pdf"))
    print(f"{len(pdfs)} brief PDFs")
    for pdf in pdfs:
        text = pdf_text(pdf)
        if not text:
            continue
        cleaned = clean_text(text, ["all_whitespace"])
        source = f"{pdf.parent.name}/{pdf.name}"
        for cite in get_citations(cleaned):
            if type(cite).__name__ != "FullCaseCitation":
                continue
            span_start = cite.span()[0] if cite.span() else 0
            context = cleaned[max(0, span_start - 300) : span_start]
            corrected = cite.corrected_citation()
            year = None
            meta_year = getattr(cite.metadata, "year", None)
            if meta_year and str(meta_year).isdigit():
                year = int(meta_year)
            if year and year >= YEAR_CUTOFF:
                continue
            key = normalize_cite(corrected)
            entry = rows.setdefault(
                key,
                {
                    "cite": corrected,
                    "cite_norm": key,
                    "year_in_brief": year,
                    "tier": "brief",
                    "case_id": None,
                    "sources": [],
                    "cited_for": [],
                },
            )
            if source not in entry["sources"]:
                entry["sources"].append(source)
            if context.strip():
                # keep the LAST occurrences: in-text citing sentences, not
                # the table-of-authorities listing that opens every brief
                entry["cited_for"].append(context.strip()[-300:])
                entry["cited_for"] = entry["cited_for"][-3:]

    letting_markers = re.compile(
        r"leas\w+|rent\w+|let\b|letting|rooms?\b|boarder|boarding|lodg\w+|"
        r"tenant|occupan\w+|short-?term|dwelling|homestead|incident of ownership|"
        r"right to (lease|let|rent|use)|property right",
        re.IGNORECASE,
    )

    def classify_domain(entry: dict) -> str:
        """Domain by the BRIEF'S OWN citing context (not our selector
        lexicon): 'letting' when the brief cites it for a letting/property-
        use proposition, else 'doctrine'. Auditable via cited_for."""
        joined = " ".join(entry.get("cited_for") or [])
        return "letting" if letting_markers.search(joined) else "doctrine"

    resolved = unresolved = dropped_modern = 0
    out = []
    for key, entry in rows.items():
        entry["domain"] = classify_domain(entry)
        hit = conn.execute(
            """SELECT c.case_id, c.decision_year, c.name_abbreviation
               FROM citations ct JOIN cases c ON c.case_id = ct.case_id
               WHERE ct.cite_norm = ? AND c.is_duplicate_of IS NULL""",
            (key,),
        ).fetchone()
        if hit:
            case_id, year, name = hit
            if year and year >= YEAR_CUTOFF:
                dropped_modern += 1
                continue
            entry.update({"case_id": case_id, "decision_year": year, "name": name})
            resolved += 1
        else:
            if entry["year_in_brief"] is None:
                # unresolvable and undated: candidate for CL lookup / human
                unresolved += 1
            else:
                unresolved += 1
        out.append(entry)

    GOLD_JSONL.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if GOLD_JSONL.exists():
        existing = [
            json.loads(line)
            for line in GOLD_JSONL.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("tier") != "brief"
        ]
    with GOLD_JSONL.open("w", encoding="utf-8") as f:
        for e in out + existing:
            f.write(json.dumps(e) + "\n")
    print(
        f"harvest: {len(out)} historical cites (resolved {resolved}, "
        f"unresolved {unresolved}, dropped-modern {dropped_modern})"
    )
    if unresolved:
        note_needs_human(
            [f"unresolved gold cite: {e['cite']} (from {e['sources'][0]})"
             for e in out if e["case_id"] is None][:50]
        )
    return 0


def cmd_add_treatise(args) -> int:
    src = GOLD_DIR / "treatise_anchors.md"
    if not src.exists():
        print(f"missing {src}")
        return 1
    conn = sqlite3.connect(DB)
    added = resolved = 0
    entries = []
    for line in src.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() in ("case", "case name", "---", ""):
            continue
        if set(cells[0]) <= {"-", " ", ":"}:
            continue
        name, cite_field = cells[0], cells[1]
        if not re.search(r"\d", cite_field):
            continue
        # parallel citations separated by ';' — resolve on the first that hits
        variants = [v.strip() for v in cite_field.split(";") if v.strip()]
        cite, key, hit = variants[0], normalize_cite(variants[0]), None
        for v in variants:
            k = normalize_cite(v)
            hit = conn.execute(
                """SELECT c.case_id, c.decision_year FROM citations ct
                   JOIN cases c ON c.case_id = ct.case_id
                   WHERE ct.cite_norm = ? AND c.is_duplicate_of IS NULL""",
                (k,),
            ).fetchone()
            if hit:
                cite, key = v, k
                break
        entry = {
            "cite": cite, "cite_norm": key, "name": name, "tier": "treatise",
            "case_id": hit[0] if hit else None,
            "decision_year": hit[1] if hit else None,
            "sources": ["treatise_anchors.md"],
        }
        entries.append(entry)
        added += 1
        resolved += bool(hit)
    existing = []
    if GOLD_JSONL.exists():
        existing = [
            json.loads(line)
            for line in GOLD_JSONL.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("tier") != "treatise"
        ]
    with GOLD_JSONL.open("w", encoding="utf-8") as f:
        for e in existing + entries:
            f.write(json.dumps(e) + "\n")
    print(f"treatise: {added} anchors, {resolved} resolved in corpus")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("harvest")
    sub.add_parser("add-treatise")
    args = ap.parse_args()
    return {"fetch": cmd_fetch, "harvest": cmd_harvest, "add-treatise": cmd_add_treatise}[
        args.cmd
    ](args)


if __name__ == "__main__":
    sys.exit(main())
