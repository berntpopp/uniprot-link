"""JSON output schemas for the typed MCP tools (MCP 2025-06-18 structured output).

FastMCP 3.4.2 returns ``structuredContent`` (plus a serialized ``TextContent``
JSON block for back-compat) when a tool declares an ``output_schema``. The
schemas here are deliberately **permissive** — ``additionalProperties: true`` and
nothing ``required`` — because:

- ``response_mode`` projects fields out (minimal/compact drop fields);
- the error envelope (``success: false`` + ``error_code`` + ...) is returned by
  the same tool body and must also validate;
- optional record fields are *omitted* (not null) by shaping.

So the schema documents the success-payload shape for typed clients without ever
rejecting a legitimate response.
"""

from __future__ import annotations

from typing import Any

_META = {"type": "object", "additionalProperties": True}


def _envelope(**properties: Any) -> dict[str, Any]:
    """A permissive object schema carrying the common envelope keys + extras."""
    props: dict[str, Any] = {
        "success": {"type": "boolean"},
        "_meta": _META,
        # error envelope keys (present only on failure)
        "error_code": {"type": "string"},
        "message": {"type": "string"},
        "retryable": {"type": "boolean"},
        "recovery_action": {"type": "string"},
        "field": {"type": "string"},
        "allowed_values": {"type": "array"},
        "hint": {"type": "string"},
        **properties,
    }
    return {"type": "object", "additionalProperties": True, "properties": props}


_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_ARR = {"type": "array"}
_OBJ = {"type": "object", "additionalProperties": True}

# Response-Envelope Standard v1.1: externally sourced free text (UniProtKB
# rdfs:comment literals -- function summaries, feature descriptions, disease
# involvement notes + clinical definitions, variant descriptions, curated
# SPARQL-example descriptions) is emitted as this typed object (see
# uniprot_link.mcp.untrusted_content.UntrustedText), never a bare string. The
# `kind` const is the schema-level proof of the typed literal.
_UNTRUSTED_TEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "kind": {"const": "untrusted_text"},
        "text": {"type": "string"},
        "provenance": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "record_id": {"type": "string"},
                "retrieved_at": {"type": "string"},
            },
        },
        "raw_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}


def _fenced_array(**fenced_item_properties: Any) -> dict[str, Any]:
    """A permissive array whose ITEM schema declares the fenced field(s).

    v1.1 requires the `untrusted_text` object (`kind` const) to be visible in the
    array `items` schema, not only at the top level -- a bare permissive array
    hides the literal even when the runtime data is fenced. Items stay
    `additionalProperties: True` and nothing is `required`, so a projected/omitted
    field never rejects a legitimate response.
    """
    return {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": True,
            "properties": {**fenced_item_properties},
        },
    }


CAPABILITIES_SCHEMA = _envelope(
    server=_STR,
    server_version=_STR,
    uniprot_release=_STR,
    tools=_ARR,
    named_graphs=_ARR,
    feature_types=_ARR,
)

FIND_PROTEINS_SCHEMA = _envelope(
    count=_INT, proteins=_ARR, truncated=_OBJ, reviewed_count=_INT, reviewed_hint=_STR
)

FIND_PROTEINS_BATCH_SCHEMA = _envelope(
    gene_count=_INT,
    count=_INT,
    by_gene=_OBJ,
    proteins=_ARR,
    resolved_genes=_ARR,
    unresolved_genes=_ARR,
)

PROTEIN_SCHEMA = _envelope(
    accession=_STR,
    requested_accession=_STR,
    mnemonic=_STR,
    reviewed=_BOOL,
    recommended_name=_STR,
    genes=_ARR,
    organism=_STR,
    taxon_id=_STR,
    sequence_length=_INT,
    mass_da=_INT,
    function=_UNTRUSTED_TEXT_SCHEMA,
    obsolete=_BOOL,
    replaced_by=_ARR,
    has_variants=_BOOL,
    has_diseases=_BOOL,
    has_structure=_BOOL,
    isoform=_STR,
)

SEQUENCE_SCHEMA = _envelope(
    accession=_STR, canonical=_OBJ, isoform_count=_INT, isoforms=_ARR, requested_isoform=_STR
)

FEATURES_SCHEMA = _envelope(
    accession=_STR,
    count=_INT,
    features=_fenced_array(description=_UNTRUSTED_TEXT_SCHEMA),
    filter_hint=_OBJ,
    truncated=_OBJ,
    excluded_secondary_structure=_OBJ,
)

VARIANTS_SCHEMA = _envelope(
    accession=_STR,
    count=_INT,
    variants=_fenced_array(description=_UNTRUSTED_TEXT_SCHEMA),
    truncated=_OBJ,
)

DISEASES_SCHEMA = _envelope(
    accession=_STR,
    count=_INT,
    diseases=_fenced_array(definition=_UNTRUSTED_TEXT_SCHEMA, involvement=_UNTRUSTED_TEXT_SCHEMA),
)

CROSS_REFERENCES_SCHEMA = _envelope(
    accession=_STR,
    database_count=_INT,
    total=_INT,
    counts=_OBJ,
    by_database=_OBJ,
    truncated_databases=_OBJ,
    requested_databases=_ARR,
    unmatched_databases=_ARR,
    database_hint=_OBJ,
)

GO_TERMS_SCHEMA = _envelope(
    accession=_STR, count=_INT, by_aspect=_OBJ, count_by_aspect=_OBJ, truncated=_OBJ
)

MAP_IDENTIFIERS_SCHEMA = _envelope(
    accession=_STR,
    database_count=_INT,
    counts=_OBJ,
    by_database=_OBJ,
    requested_databases=_ARR,
    mapped_databases=_ARR,
    unmatched_databases=_ARR,
    database_hint=_OBJ,
    truncated_databases=_OBJ,
)

TAXON_SCHEMA = _envelope(
    taxon_id=_STR,
    scientific_name=_STR,
    common_name=_STR,
    rank=_STR,
    parent_taxon_id=_STR,
    lineage=_ARR,
    query=_STR,
    match_count=_INT,
    matches=_ARR,
)

EXAMPLE_LIST_SCHEMA = _envelope(
    count=_INT,
    query_text=_STR,
    examples=_fenced_array(description=_UNTRUSTED_TEXT_SCHEMA),
)

EXAMPLE_DETAIL_SCHEMA = _envelope(
    example_id=_STR,
    description=_UNTRUSTED_TEXT_SCHEMA,
    query=_STR,
    query_type=_STR,
    keywords=_ARR,
)

# search_sparql_query is dynamic (columns vary): keep it generic.
SPARQL_RESULT_SCHEMA = _envelope(
    query_type=_STR,
    columns=_ARR,
    row_count=_INT,
    rows=_ARR,
    boolean=_BOOL,
    content_type=_STR,
    data=_STR,
    byte_length=_INT,
    truncated=_OBJ,
)
