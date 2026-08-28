"""Ingest static.case.law volume zips into SQLite.

Reads metadata/CasesMetadata.json + html/<file>.html from each zip in
data/raw/<slug>/, keeps only cases in the target jurisdictions, extracts text
from the HTML casebody with page-label anchors REMOVED (their offsets become
the page_map), normalizes per textnorm, assigns era partitions, and records
typed citations for gold-set resolution and parallel-publication dedupe.

Dedupe runs as a final pass: cases sharing any normalized citation string are
one case; the copy from an official-type citation's own reporter wins, others
get is_duplicate_of set. Duplicates stay in the DB (auditability) but shard
queries exclude them.

Usage:
    python pipeline/ingest.py [--limit-volumes N] [--db PATH]
"""

import argparse
import io
import json
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

from lxml import html as lxml_html

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textnorm import NORM_VERSION, normalize_cite, normalize_text

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_DB = ROOT / "data" / "db" / "corpus.db"

TARGET_JURISDICTIONS = {"Tex.", "Pa.", "La.", "N.Y."}

ERA_BOUNDS = [(1860, "pre-1860"), (1900, "1860-1900"), (1930, "1900-1930"),
              (1970, "1930-1970"), (10_000, "1970-2020")]

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "blockquote", "section",
              "article", "aside", "div", "tr"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id INTEGER PRIMARY KEY,
    name TEXT, name_abbreviation TEXT,
    cite TEXT,                      -- primary (official if present) citation
    court TEXT, jurisdiction TEXT,
    decision_date TEXT, decision_year INTEGER, era_partition TEXT,
    reporter TEXT, volume TEXT, file_name TEXT,
    first_page TEXT, last_page TEXT,
    raw_text TEXT, norm_text TEXT,
    page_map TEXT,                  -- json [[raw_char_offset, page_int_or_str], ...]
    norm_version INTEGER,
    ocr_confidence REAL, source_sha256 TEXT,
    cl_cluster_id INTEGER,          -- CourtListener cluster id when known (A4)
    is_duplicate_of INTEGER REFERENCES cases(case_id)
);
CREATE TABLE IF NOT EXISTS citations (
    case_id INTEGER REFERENCES cases(case_id),
    cite TEXT, cite_norm TEXT, type TEXT,
    PRIMARY KEY (case_id, cite)
);
CREATE INDEX IF NOT EXISTS idx_citations_norm ON citations(cite_norm);
CREATE INDEX IF NOT EXISTS idx_cases_partition ON cases(era_partition, jurisdiction);
CREATE TABLE IF NOT EXISTS ingest_log (
    zip_key TEXT PRIMARY KEY,       -- "<slug>/<vol>"
    n_cases_total INTEGER, n_cases_ingested INTEGER,
    norm_version INTEGER, ts TEXT
);
"""


def era_partition(year: int) -> str:
    for bound, label in ERA_BOUNDS:
        if year < bound:
            return label
    raise ValueError(year)


def parse_year(decision_date: str) -> int:
    m = re.match(r"(\d{4})", decision_date or "")
    return int(m.group(1)) if m else 0


def extract_text_and_pages(html_bytes: bytes) -> tuple[str, list[tuple[int, str]]]:
    """Extract casebody text in document order. Page-label anchors are
    excluded from the text; each contributes (offset, label) to the page map.
    Block-level boundaries become newlines."""
    # static.case.law HTML is UTF-8 without a charset declaration; lxml's
    # byte-level encoding guess mangles em-dashes etc., so decode explicitly.
    doc = lxml_html.fromstring(html_bytes.decode("utf-8"))
    body = doc if doc.get("class") == "casebody" else doc
    parts: list[str] = []
    pages: list[tuple[int, str]] = []
    length = 0

    def emit(s: str) -> None:
        nonlocal length
        if s:
            parts.append(s)
            length += len(s)

    def walk(el) -> None:
        cls = el.get("class") or ""
        if el.tag == "a" and "page-label" in cls:
            pages.append((length, el.get("data-label") or el.text_content().strip("*")))
            if el.tail:
                emit(el.tail)
            return
        if el.text:
            emit(el.text)
        for child in el:
            walk(child)
        if el.tag in BLOCK_TAGS:
            emit("\n")
        if el.tail:
            emit(el.tail)

    walk(body)
    # No post-processing: page offsets index into exactly this string.
    return "".join(parts), pages


def primary_cite(citations: list[dict]) -> str:
    for c in citations:
        if c.get("type") == "official":
            return c["cite"]
    return citations[0]["cite"] if citations else ""


def ingest_zip(conn: sqlite3.Connection, zip_path: Path, slug: str, vol: str) -> tuple[int, int]:
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        meta_name = next((n for n in names if n.endswith("CasesMetadata.json")), None)
        if not meta_name:
            return (0, 0)
        cases_meta = json.load(io.TextIOWrapper(zf.open(meta_name), encoding="utf-8"))
        n_ingested = 0
        for cm in cases_meta:
            if cm["jurisdiction"]["name"] not in TARGET_JURISDICTIONS:
                continue
            html_name = next(
                (n for n in names if n.endswith(f"html/{cm['file_name']}.html")), None
            )
            if html_name is None:
                continue
            raw_html = zf.read(html_name)
            raw_text, page_labels = extract_text_and_pages(raw_html)
            # page map starts at the case's first page, then label transitions
            page_map = [[0, cm.get("first_page")]] + [
                [off, label] for off, label in page_labels
            ]
            year = parse_year(cm.get("decision_date", ""))
            conn.execute(
                """INSERT OR REPLACE INTO cases
                   (case_id, name, name_abbreviation, cite, court, jurisdiction,
                    decision_date, decision_year, era_partition, reporter, volume,
                    file_name, first_page, last_page, raw_text, norm_text,
                    page_map, norm_version, ocr_confidence, source_sha256)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cm["id"], cm.get("name"), cm.get("name_abbreviation"),
                    primary_cite(cm.get("citations", [])),
                    (cm.get("court") or {}).get("name"),
                    cm["jurisdiction"]["name"],
                    cm.get("decision_date"), year,
                    era_partition(year) if year else None,
                    slug, vol, cm["file_name"],
                    cm.get("first_page"), cm.get("last_page"),
                    raw_text, normalize_text(raw_text),
                    json.dumps(page_map), NORM_VERSION,
                    (cm.get("analysis") or {}).get("ocr_confidence"),
                    (cm.get("analysis") or {}).get("sha256"),
                ),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                [
                    (cm["id"], c["cite"], normalize_cite(c["cite"]), c.get("type"))
                    for c in cm.get("citations", [])
                ],
            )
            n_ingested += 1
        return (len(cases_meta), n_ingested)


def dedupe(conn: sqlite3.Connection) -> int:
    """Cases sharing a normalized citation are one case; official-reporter
    copy wins (the case whose own reporter matches its official cite)."""
    rows = conn.execute(
        """SELECT c1.case_id AS a, c2.case_id AS b
           FROM citations x
           JOIN citations y ON x.cite_norm = y.cite_norm AND x.case_id < y.case_id
           JOIN cases c1 ON c1.case_id = x.case_id
           JOIN cases c2 ON c2.case_id = y.case_id
           GROUP BY a, b"""
    ).fetchall()
    n = 0
    for a, b in rows:
        ca = conn.execute(
            "SELECT case_id, reporter, cite FROM cases WHERE case_id=?", (a,)
        ).fetchone()
        cb = conn.execute(
            "SELECT case_id, reporter, cite FROM cases WHERE case_id=?", (b,)
        ).fetchone()

        def is_official(row) -> bool:
            t = conn.execute(
                "SELECT type FROM citations WHERE case_id=? AND cite=?",
                (row[0], row[2]),
            ).fetchone()
            return bool(t and t[0] == "official")

        winner, loser = (ca, cb) if is_official(ca) or not is_official(cb) else (cb, ca)
        conn.execute(
            "UPDATE cases SET is_duplicate_of=? WHERE case_id=? AND is_duplicate_of IS NULL",
            (winner[0], loser[0]),
        )
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--limit-volumes", type=int, default=0)
    ap.add_argument("--reporter", help="only ingest this reporter slug")
    ap.add_argument("--skip-dedupe", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")

    done = {
        r[0]
        for r in conn.execute(
            "SELECT zip_key FROM ingest_log WHERE norm_version=?", (NORM_VERSION,)
        )
    }
    zips = sorted(
        RAW_DIR.glob(f"{args.reporter}/*.zip") if args.reporter else RAW_DIR.glob("*/*.zip")
    )
    todo = [z for z in zips if f"{z.parent.name}/{z.stem}" not in done]
    if args.limit_volumes:
        todo = todo[: args.limit_volumes]
    print(f"{len(zips)} zips on disk; {len(done)} already ingested; {len(todo)} to do")

    for i, z in enumerate(todo, 1):
        slug, vol = z.parent.name, z.stem
        try:
            total, ingested = ingest_zip(conn, z, slug, vol)
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
            print(f"[{i}/{len(todo)}] ERROR {slug}/{vol}: {e}", flush=True)
            continue
        conn.execute(
            "INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?)",
            (f"{slug}/{vol}", total, ingested, NORM_VERSION,
             time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        conn.commit()
        if i % 200 == 0 or i == len(todo):
            print(f"[{i}/{len(todo)}] {slug}/{vol}: {ingested}/{total} cases", flush=True)

    if not args.skip_dedupe:
        n = dedupe(conn)
        conn.commit()
        print(f"dedupe: {n} duplicate pairs resolved")

    total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    dupes = conn.execute(
        "SELECT COUNT(*) FROM cases WHERE is_duplicate_of IS NOT NULL"
    ).fetchone()[0]
    print(f"cases: {total} ({dupes} marked duplicate)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
