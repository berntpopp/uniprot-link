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
