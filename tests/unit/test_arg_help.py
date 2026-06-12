"""Unit tests for argument-help pure functions."""

from __future__ import annotations

from uniprot_link.mcp.arg_help import (
    did_you_mean,
    normalize_alias_args,
    tool_signature,
)


def test_normalize_applies_alias_when_canonical_valid_and_absent() -> None:
    valid = ["gene", "organism_taxon", "reviewed"]
    args, applied = normalize_alias_args(valid, {"taxon": "9606", "gene": "PNKP"})
    assert args == {"organism_taxon": "9606", "gene": "PNKP"}
    assert applied == [("taxon", "organism_taxon")]


def test_normalize_does_not_overwrite_explicit_canonical() -> None:
    valid = ["organism_taxon"]
    args, applied = normalize_alias_args(valid, {"taxon": "1", "organism_taxon": "9606"})
    assert args == {"organism_taxon": "9606"}  # explicit value wins; alias dropped
    assert applied == []


def test_normalize_ignores_alias_when_canonical_not_a_param() -> None:
    valid = ["gene"]  # organism_taxon is not a param of this tool
    args, applied = normalize_alias_args(valid, {"taxon": "9606"})
    assert args == {"taxon": "9606"}  # untouched -> will become a clean did-you-mean
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
