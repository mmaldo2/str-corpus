"""Pure per-zip parsing: a static.case.law volume zip in, row tuples out.
No database access, so it runs in worker processes (Task 3)."""
from __future__ import annotations
import io, json, zipfile
from dataclasses import dataclass, field
from pathlib import Path
from corpus_engine.domain import Domain
from corpus_engine.ingest.parse import extract_text_and_pages, parse_year, primary_cite
from corpus_engine.store import era_partition
from corpus_engine.textnorm_bridge import NORM_VERSION, normalize_cite, normalize_text

CASE_COLUMNS = ("case_id", "name", "name_abbreviation", "cite", "court", "jurisdiction",
                "decision_date", "decision_year", "era_partition", "reporter", "volume",
                "file_name", "first_page", "last_page", "raw_text", "norm_text",
                "page_map", "norm_version", "ocr_confidence", "source_sha256")


@dataclass(frozen=True)
class ZipRows:
    slug: str
    vol: str
    n_total: int
    cases: list[tuple] = field(default_factory=list)
    citations: list[tuple] = field(default_factory=list)
    cites_to: list[tuple] = field(default_factory=list)
    pagerank: list[tuple] = field(default_factory=list)


def admitted(cm: dict, slug: str, domain: Domain) -> bool:
    return cm["jurisdiction"]["name"] in domain.jurisdictions or slug in domain.reporter_slugs


def graph_rows(cm: dict) -> tuple[list[tuple], list[tuple]]:
    cid = cm["id"]
    ct = []
    for c in cm.get("cites_to") or []:
        for cited in c.get("case_ids") or []:
            ct.append((cid, int(cited), c.get("cite"), c.get("category"), c.get("reporter"),
                       c.get("year"), c.get("weight"), c.get("opinion_index")))
    pr = (cm.get("analysis") or {}).get("pagerank") or {}
    prs = [(cid, pr.get("raw"), pr.get("percentile"))] if pr else []
    return ct, prs


def case_rows_from_zip(zip_path: Path, domain: Domain) -> ZipRows:
    slug, vol = zip_path.parent.name, zip_path.stem
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        meta_name = next((n for n in names if n.endswith("CasesMetadata.json")), None)
        if not meta_name:
            return ZipRows(slug, vol, 0)
        cases_meta = json.load(io.TextIOWrapper(zf.open(meta_name), encoding="utf-8"))
        out = ZipRows(slug, vol, len(cases_meta))
        for cm in cases_meta:
            if not admitted(cm, slug, domain):
                continue
            html_name = next((n for n in names if n.endswith(f"html/{cm['file_name']}.html")), None)
            if html_name is None:
                continue
            raw_text, page_labels = extract_text_and_pages(zf.read(html_name))
            page_map = [[0, cm.get("first_page")]] + [[off, label] for off, label in page_labels]
            year = parse_year(cm.get("decision_date", ""))
            analysis = cm.get("analysis") or {}
            out.cases.append((
                cm["id"], cm.get("name"), cm.get("name_abbreviation"), primary_cite(cm.get("citations", [])),
                (cm.get("court") or {}).get("name"), cm["jurisdiction"]["name"],
                cm.get("decision_date"), year, era_partition(year, domain.era_bounds) if year else None,
                slug, vol, cm["file_name"], cm.get("first_page"), cm.get("last_page"),
                raw_text, normalize_text(raw_text), json.dumps(page_map), NORM_VERSION,
                analysis.get("ocr_confidence"), analysis.get("sha256")))
            out.citations.extend((cm["id"], c["cite"], normalize_cite(c["cite"]), c.get("type"))
                                 for c in cm.get("citations", []))
            ct, prs = graph_rows(cm)
            out.cites_to.extend(ct); out.pagerank.extend(prs)
        return out
