"""The JSON Schema every reader Request carries (spec section 4).

OpenRouter sends it as `response_format.json_schema`, the Claude CLI as `--json-schema`.
A schema-valid response can still fail the quote gate (a quote that is not verbatim);
what it can no longer do is fill a judged field and name that field in no quote's
`supports`, which is the silent erasure the 2026-09-05 polarity diagnosis found.

`required` is the four fields `parse.REQUIRED` demands, not the two the spec names as the
minimum: `parse_records` rejects a response whose records omit `polarity` or `quotes`, and
a schema that permitted the omission would buy a split retry for a record the model was
entitled to send. Both are nullable/empty for an irrelevant record, so nothing is forced.
"""
from __future__ import annotations
import hashlib, json
from corpus_engine.reader.codebook import Codebook

POLARITY_VALUES = ("favorable", "adverse", "mixed")
WHO_VALUES = ("householder", "commercial_operator", "non_resident_owner", "unclear")
DURATION_VALUES = ["nights", "weeks", "months", "unclear", None]
CHARACTERIZATION_VALUES = ["lease", "license", "lodging", "innkeeping", "other", None]
UNDER_THIRTY_VALUES = ["yes", "no", "unclear", None]
OWNER_FREEDOM_VALUES = ["incident_of_ownership", "regulable_privilege", "commercial_use",
                        "not_addressed", None]
RESTRICTION_VALUES = ["licensing", "zoning", "nuisance", "tenant_protection", "tax", "other", None]
REQUIRED_RECORD_FIELDS = ["case_id", "relevant", "polarity", "quotes"]


def record_schema(codebook: Codebook) -> dict:
    """The schema for `{"records": [Record, ...]}` under `codebook`'s judged fields."""
    supports = list(codebook.judged_fields) + ["relevant"]
    record = {
        "type": "object",
        "additionalProperties": True,          # a model may carry extra fields; we ignore them
        "required": list(REQUIRED_RECORD_FIELDS),
        "properties": {
            "case_id": {"type": ["integer", "string"]},
            "schema_version": {"type": ["integer", "null"]},
            "cite": {"type": ["string", "null"]},
            "court": {"type": ["string", "null"]},
            "jurisdiction": {"type": ["string", "null"]},
            "year": {"type": ["integer", "null"]},
            "relevant": {"type": "boolean"},
            "relevance_score": {"type": ["number", "null"]},
            "polarity": {"enum": list(POLARITY_VALUES) + [None]},
            "who_was_letting": {"enum": list(WHO_VALUES) + [None]},
            "duration_of_occupancy": {"enum": list(DURATION_VALUES)},
            "characterization": {"enum": list(CHARACTERIZATION_VALUES)},
            "under_thirty_days": {"enum": list(UNDER_THIRTY_VALUES)},
            "owner_freedom_characterization": {"enum": list(OWNER_FREEDOM_VALUES)},
            "restriction_nature": {"enum": list(RESTRICTION_VALUES)},
            "holding_summary": {"type": ["string", "null"]},
            "doctrinal_concepts": {"type": "array", "items": {"type": "string"}},
            "new_terms_observed": {"type": "array", "items": {"type": "string"}},
            "worker": {"type": ["string", "null"]},
            "batch_id": {"type": ["string", "null"]},
            "notes": {"type": ["string", "null"]},
            "quotes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["text", "supports"],
                    "properties": {
                        "text": {"type": "string"},
                        "supports": {"type": "array", "minItems": 1,
                                     "items": {"enum": list(supports)}},
                    },
                },
            },
        },
        "if": {"properties": {"relevant": {"const": True}}, "required": ["relevant"]},
        "then": {"properties": {"quotes": {"minItems": 1}}},
    }
    return {"type": "object", "additionalProperties": False, "required": ["records"],
            "properties": {"records": {"type": "array", "items": record}}}


def schema_sha(schema: dict | None) -> str:
    if not schema:
        return ""
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest()
