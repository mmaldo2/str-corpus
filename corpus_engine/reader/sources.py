from __future__ import annotations
import json
from typing import Mapping, Sequence
from corpus_engine.reader.model import CaseText, ReaderError


class StoreCaseSource:
    def __init__(self, conn):
        self.conn = conn
    def fetch(self, case_ids: Sequence[int]) -> list[CaseText]:
        ids = [int(c) for c in case_ids]; rows = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]; ph = ",".join("?" * len(chunk))
            for r in self.conn.execute(f"""SELECT case_id, cite, name_abbreviation, court, jurisdiction, decision_year,
                                             raw_text, norm_text, page_map FROM cases WHERE case_id IN ({ph})""", chunk):
                rows[r[0]] = CaseText(r[0], r[1] or "", r[2] or "", r[3] or "", r[4] or "", r[5], r[6] or "", r[7] or "",
                                      json.loads(r[8]) if r[8] else [])
        missing = [c for c in ids if c not in rows]
        if missing:
            raise ReaderError(f"cases not in store: {missing[:5]}")
        return [rows[c] for c in ids]


class InlinedCaseSource:
    def __init__(self, cases: Mapping[int, CaseText]):
        self.cases = dict(cases)
    def fetch(self, case_ids: Sequence[int]) -> list[CaseText]:
        missing = [c for c in case_ids if int(c) not in self.cases]
        if missing:
            raise ReaderError(f"cases not inlined: {missing[:5]}")
        return [self.cases[int(c)] for c in case_ids]
