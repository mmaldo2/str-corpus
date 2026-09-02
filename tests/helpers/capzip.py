import json, zipfile
from pathlib import Path

def make_cap_zip(path: Path, slug: str, vol: str, cases: list[dict]) -> Path:
    """cases: dicts with id, name, decision_date, jurisdiction (name), citations ([{cite,type}]),
    html (casebody html string), optional cites_to, analysis, first_page."""
    meta = []
    with zipfile.ZipFile(path, "w") as zf:
        for c in cases:
            fn = f"{c['id']:04d}-01"
            meta.append({
                "id": c["id"], "name": c["name"], "name_abbreviation": c.get("abbr", c["name"]),
                "decision_date": c["decision_date"], "docket_number": "", "first_page": c.get("first_page", "1"),
                "last_page": "9", "citations": c["citations"], "court": {"name": c.get("court", "Test Ct.")},
                "jurisdiction": {"id": 0, "name": c["jurisdiction"]}, "cites_to": c.get("cites_to", []),
                "analysis": c.get("analysis", {"ocr_confidence": 0.9, "sha256": "x", "pagerank": {"raw": 0.1, "percentile": 0.5}}),
                "last_updated": "", "provenance": {}, "file_name": fn, "first_page_order": 1, "last_page_order": 9,
            })
            zf.writestr(f"html/{fn}.html", c["html"])
        zf.writestr("metadata/CasesMetadata.json", json.dumps(meta))
        zf.writestr("metadata/VolumeMetadata.json", json.dumps({"volume_number": vol, "jurisdictions": []}))
    return path

HTML = ('<section class="casebody"><p>Page one text <a id="p2" class="page-label" data-label="2">*2</a>'
        'continues on page two about lodgers.</p></section>')
