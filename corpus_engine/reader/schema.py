"""The JSON Schema every reader Request carries (spec section 4).

OpenRouter sends it as `response_format.json_schema`, the Claude CLI as `--json-schema`.
A schema-valid response can still fail the quote gate (a quote that is not verbatim);
what it can no longer do is fill a judged field and name that field in no quote's
`supports`, which is the silent erasure the 2026-09-05 polarity diagnosis found.

`required` is the four fields `parse.REQUIRED` demands, not the two the spec names as the
minimum: `parse_records` rejects a response whose records omit `polarity` or `quotes`, and
a schema that permitted the omission would buy a split retry for a record the model was
entitled to send. Both are nullable/empty for an irrelevant record, so nothing is forced.

Two dialects. `dialect="default"` is the schema above, unchanged, and every non-openai
family (anthropic, google, deepseek, zai, minimax, qwen) accepts it. `dialect="openai-strict"`
is a pure structural transform of the same schema for OpenAI's structured-output ("strict")
JSON Schema subset, which the 2026-09-05 measurement found rejects it wholesale: every
request to openai/gpt-5.6-terra through OpenRouter failed with HTTP 400 "Invalid schema for
response_format" because the default schema sets `additionalProperties: True`, leaves most
properties out of `required`, and uses an `if`/`then` OpenAI's dialect does not support. The
transform (`_to_openai_strict`) walks the default schema and, on every object node: sets
`additionalProperties: False`; adds every property to `required`; and for a property that
was NOT already required, or that is an enum already carrying `None` (nullable by the
codebook's own vocabulary - see POLARITY_VALUES et al.), makes it nullable - a bare `type`
becomes `[type, "null"]`, an enum becomes `anyOf: [{"enum": [...]}, {"type": "null"}]` (the
form OpenAI's docs show for a nullable enum; a plain `enum` array mixing string values with
a `None` literal is the shape most likely to be rejected by "same-typed enum values" checks,
which is why this dialect never emits one). `if`/`then` is dropped outright: the
`quotes: minItems 1 when relevant` rule they encoded is still enforced by the codebook text
and by `gate.py`'s quote gate, neither of which reads this schema.
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
# D6/D7: the one place the `needs-review:<field>` flag prefix is spelled, so every module
# that writes or reads one of these flags (corpus_engine/reader/measure.py,
# tools/apply_reference_review.py, tools/apply_retraction_cascade.py, tools/build_reader_kit.py,
# tools/clear_superseded_flags.py) imports it from here instead of declaring its own copy
# (task-4-review finding 2: measure.py and apply_reference_review.py had drifted into two
# independent definitions of the same literal).
FLAG_PREFIX = "needs-review:"


def record_schema(codebook: Codebook, *, dialect: str = "default") -> dict:
    """The schema for `{"records": [Record, ...]}` under `codebook`'s judged fields.

    `dialect="default"` (the only shape before 2026-09-05) is returned unchanged - its
    sha is pinned in tests/test_reader_schema.py so this stays non-disruptive.
    `dialect="openai-strict"` runs the same schema through `_to_openai_strict` for the
    OpenAI structured-output subset (module docstring)."""
    schema = _default_schema(codebook)
    if dialect == "default":
        return schema
    if dialect == "openai-strict":
        return _to_openai_strict(schema)
    raise ValueError(f"unknown schema dialect: {dialect!r}")


def _default_schema(codebook: Codebook) -> dict:
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


_STRIP_KEYS = ("if", "then", "else")


def _make_nullable(sub: dict) -> dict:
    """`sub` is already recursively transformed. Widen it to also accept `null`,
    without touching a shape that already does."""
    if "enum" in sub:
        values = [v for v in sub["enum"] if v is not None]
        return {"anyOf": [{"enum": values}, {"type": "null"}]}
    if "anyOf" in sub:
        if not any(o == {"type": "null"} for o in sub["anyOf"]):
            return {**sub, "anyOf": [*sub["anyOf"], {"type": "null"}]}
        return sub
    t = sub.get("type")
    if isinstance(t, list):
        return sub if "null" in t else {**sub, "type": [*t, "null"]}
    if isinstance(t, str):
        return {**sub, "type": [t, "null"]}
    return sub          # no type/enum on this node (shouldn't occur in our schemas) - leave it


def _to_openai_strict(node):
    """Pure structural transform (module docstring): drop `if`/`then`/`else`; on every
    object node, require every property and make the ones that were optional (or an
    already-nullable enum) accept `null` too."""
    if isinstance(node, list):
        return [_to_openai_strict(v) for v in node]
    if not isinstance(node, dict):
        return node
    node = {k: _to_openai_strict(v) for k, v in node.items() if k not in _STRIP_KEYS}
    if node.get("type") == "object" and "properties" in node:
        original_required = set(node.get("required", []))
        props = node["properties"]                       # already recursively transformed above
        new_props = {}
        for name, sub in props.items():
            needs_null = name not in original_required or ("enum" in sub and None in sub["enum"])
            new_props[name] = _make_nullable(sub) if needs_null else sub
        node = {**node, "properties": new_props, "required": list(props.keys()), "additionalProperties": False}
    return node


def schema_sha(schema: dict | None) -> str:
    if not schema:
        return ""
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest()
