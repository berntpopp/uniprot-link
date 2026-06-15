"""Unit tests for argument-help pure functions."""

from __future__ import annotations

from uniprot_link.mcp.arg_help import (
    did_you_mean,
    enum_values_for,
    normalize_alias_args,
    tool_signature,
)


def test_enum_values_for_direct_enum() -> None:
    schema = {"properties": {"detail": {"enum": ["summary", "full"], "type": "string"}}}
    assert enum_values_for(schema, "detail") == ["summary", "full"]


def test_enum_values_for_anyof_optional_branch() -> None:
    # Literal[...] | None renders as anyOf: [{enum: [...]}, {type: null}].
    schema = {
        "properties": {
            "aspect": {
                "anyOf": [
                    {"enum": ["biological_process", "molecular_function"], "type": "string"},
                    {"type": "null"},
                ]
            }
        }
    }
    assert enum_values_for(schema, "aspect") == ["biological_process", "molecular_function"]


def test_enum_values_for_no_enum_returns_none() -> None:
    schema = {"properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 1000}}}
    assert enum_values_for(schema, "limit") is None


def test_enum_values_for_unknown_param_returns_none() -> None:
    assert enum_values_for({"properties": {}}, "nope") is None


def test_normalize_applies_alias_when_canonical_valid_and_absent() -> None:
    valid = ["gene_symbol", "organism_taxon", "reviewed"]
    args, applied = normalize_alias_args(valid, {"taxon": "9606", "gene_symbol": "PNKP"})
    assert args == {"organism_taxon": "9606", "gene_symbol": "PNKP"}
    assert applied == [("taxon", "organism_taxon")]


def test_normalize_flips_legacy_gene_to_gene_symbol() -> None:
    """Fleet canon: `gene`/`genes` are inbound aliases for `gene_symbol(s)`."""
    valid = ["gene_symbol", "organism_taxon"]
    args, applied = normalize_alias_args(valid, {"gene": "BRCA1"})
    assert args == {"gene_symbol": "BRCA1"}
    assert ("gene", "gene_symbol") in applied
    bargs, bapplied = normalize_alias_args(["gene_symbols"], {"genes": ["PNKP", "NAA10"]})
    assert bargs == {"gene_symbols": ["PNKP", "NAA10"]}
    assert ("genes", "gene_symbols") in bapplied


def test_normalize_does_not_overwrite_explicit_canonical() -> None:
    valid = ["organism_taxon"]
    args, applied = normalize_alias_args(valid, {"taxon": "1", "organism_taxon": "9606"})
    assert args == {"organism_taxon": "9606"}  # explicit value wins; alias dropped
    assert applied == []


def test_normalize_ignores_alias_when_canonical_not_a_param() -> None:
    valid = ["gene_symbol"]  # organism_taxon is not a param of this tool
    args, applied = normalize_alias_args(valid, {"taxon": "9606"})
    assert args == {"taxon": "9606"}  # untouched -> will become a clean did-you-mean
    assert applied == []


def test_query_alias_rewrites_to_text_on_search_tool() -> None:
    """F6: search_example_queries accepts query=/q= for its `text` param."""
    args, applied = normalize_alias_args(["text", "limit"], {"query": "disease"})
    assert args == {"text": "disease"}
    assert ("query", "text") in applied
    args2, applied2 = normalize_alias_args(["text", "limit"], {"q": "disease"})
    assert args2 == {"text": "disease"}
    assert ("q", "text") in applied2


def test_query_stays_query_on_run_sparql_tool() -> None:
    """F6: where `query` is itself the canonical param, the alias is a no-op."""
    args, applied = normalize_alias_args(["query", "result_format"], {"query": "SELECT ?s {}"})
    assert args == {"query": "SELECT ?s {}"}  # canonical param untouched
    assert applied == []


def test_did_you_mean_prefers_alias_map() -> None:
    assert did_you_mean("organism", ["gene", "organism_taxon"]) == "organism_taxon"


def test_did_you_mean_falls_back_to_fuzzy() -> None:
    assert did_you_mean("organism_taxa", ["gene", "organism_taxon"]) == "organism_taxon"


def test_did_you_mean_returns_none_when_no_match() -> None:
    assert did_you_mean("zzz", ["gene", "organism_taxon"]) is None


def test_tool_signature_required_first_then_optional() -> None:
    schema = {
        "properties": {"accession": {}, "response_mode": {}},
        "required": ["accession"],
    }
    assert tool_signature("get_protein", schema) == "get_protein(accession, response_mode=)"


def test_tool_signature_all_optional() -> None:
    schema = {"properties": {"gene": {}, "organism_taxon": {}}}
    assert tool_signature("find_proteins", schema) == "find_proteins(gene=, organism_taxon=)"


def test_build_arg_error_envelope_unexpected_keyword() -> None:
    from uniprot_link.mcp.envelope import build_arg_error_envelope

    env = build_arg_error_envelope(
        tool_name="find_proteins",
        loc="species",
        error_type="unexpected_keyword_argument",
        valid_params=["gene", "organism_taxon"],
        signature="find_proteins(gene=, organism_taxon=)",
        suggestion="organism_taxon",
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["recovery_action"] == "reformulate_input"
    assert env["retryable"] is False
    assert env["field"] == "species"
    assert env["allowed_values"] == ["gene", "organism_taxon"]
    assert env["hint"] == "find_proteins(gene=, organism_taxon=)"
    assert "organism_taxon" in env["message"]  # did-you-mean surfaced
    assert env["_meta"]["tool"] == "find_proteins"
    assert env["_meta"]["request_id"]
    assert env["_meta"]["next_commands"][0]["tool"] == "get_server_capabilities"


def test_build_arg_error_envelope_missing_argument_wording() -> None:
    from uniprot_link.mcp.envelope import build_arg_error_envelope

    env = build_arg_error_envelope(
        tool_name="get_protein",
        loc="accession",
        error_type="missing_argument",
        valid_params=["accession", "response_mode"],
        signature="get_protein(accession, response_mode=)",
        suggestion=None,
    )
    assert "missing" in env["message"].lower()
    assert env["field"] == "accession"


def test_build_arg_error_envelope_enum_value_lists_values_not_names() -> None:
    from uniprot_link.mcp.envelope import build_arg_error_envelope

    env = build_arg_error_envelope(
        tool_name="get_protein_go_terms",
        loc="aspect",
        error_type="literal_error",
        valid_params=["accession", "aspect", "limit"],
        signature="get_protein_go_terms(accession, aspect=, limit=)",
        suggestion=None,
        enum_values=["biological_process", "molecular_function", "cellular_component"],
    )
    assert env["field"] == "aspect"
    # Valid VALUES, never the argument names.
    assert env["allowed_values"] == [
        "biological_process",
        "molecular_function",
        "cellular_component",
    ]
    assert "accession" not in env["allowed_values"]
    # Wording must say values, not "argument names".
    assert "argument names" not in env["message"]
    assert "value" in env["message"].lower()


def test_build_arg_error_envelope_numeric_value_omits_allowed_values() -> None:
    from uniprot_link.mcp.envelope import build_arg_error_envelope

    env = build_arg_error_envelope(
        tool_name="get_protein_features",
        loc="limit",
        error_type="less_than_equal",
        valid_params=["accession", "feature_types", "limit"],
        signature="get_protein_features(accession, feature_types=, limit=)",
        suggestion=None,
        value_message="Input should be less than or equal to 1000",
    )
    assert env["field"] == "limit"
    assert "argument names" not in env["message"]
    assert "less than or equal to 1000" in env["message"]
    # No fabricated value list for a numeric-constraint error.
    assert "allowed_values" not in env
