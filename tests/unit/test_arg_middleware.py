"""End-to-end tests for ArgValidationMiddleware via the real facade.

These calls fail at argument binding *before* any tool body runs, so no network
call happens and no respx mocking is needed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from uniprot_link.mcp.facade import create_uniprot_mcp


def _structured(result: Any) -> dict[str, Any]:
    sc = result.structured_content
    return sc if isinstance(sc, dict) else json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_wrong_keyword_routes_through_envelope() -> None:
    mcp = create_uniprot_mcp()
    # `bogus_arg` is neither a real param nor a known alias -> pure routing case.
    result = await mcp.call_tool("find_proteins", {"bogus_arg": "9606"})
    env = _structured(result)
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "bogus_arg"
    assert "organism_taxon" in env["allowed_values"]
    assert env["hint"].startswith("find_proteins(")
    assert env["_meta"]["next_commands"][0]["tool"] == "get_server_capabilities"
    # never leak the pydantic docs URL
    assert "pydantic.dev" not in json.dumps(env)


@pytest.mark.asyncio
async def test_non_alias_near_miss_gets_did_you_mean() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("find_proteins", {"organism_taxa": "9606"}))
    assert "organism_taxon" in env["message"]


@pytest.mark.asyncio
async def test_wrong_type_routes_through_envelope() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("find_proteins", {"organism_taxon": "notanint"}))
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "organism_taxon"


@pytest.mark.asyncio
async def test_missing_required_routes_through_envelope() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("get_protein", {}))
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "accession"
    assert "missing" in env["message"].lower()


@pytest.mark.asyncio
async def test_invalid_enum_value_returns_valid_values_for_aspect() -> None:
    """F1: a bad enum *value* lists the valid VALUES, not the argument names."""
    mcp = create_uniprot_mcp()
    env = _structured(
        await mcp.call_tool("get_protein_go_terms", {"accession": "P05067", "aspect": "function"})
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "aspect"
    assert env["allowed_values"] == [
        "biological_process",
        "molecular_function",
        "cellular_component",
    ]
    assert "accession" not in env["allowed_values"]  # not the argument names
    assert "argument names" not in env["message"]


@pytest.mark.asyncio
async def test_invalid_detail_value_returns_valid_values() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("get_server_capabilities", {"detail": "banana"}))
    assert env["field"] == "detail"
    assert env["allowed_values"] == ["summary", "full"]


@pytest.mark.asyncio
async def test_invalid_result_format_returns_valid_values() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(
        await mcp.call_tool(
            "search_sparql_query",
            {"query": "SELECT * WHERE {?s ?p ?o}", "result_format": "banana"},
        )
    )
    assert env["field"] == "result_format"
    assert env["allowed_values"] == ["json", "xml", "csv", "tsv", "turtle", "rdfxml", "ntriples"]


@pytest.mark.asyncio
async def test_unknown_argument_name_still_lists_names() -> None:
    """Regression: a wrong NAME still lists argument names (the other category)."""
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("find_proteins", {"bogus_arg": "9606"}))
    assert env["field"] == "bogus_arg"
    assert "organism_taxon" in env["allowed_values"]
    assert "argument names" in env["message"]


@pytest.mark.asyncio
async def test_alias_normalized_and_disclosed() -> None:
    """taxon -> organism_taxon and legacy gene -> gene_symbol land + are disclosed."""
    import uniprot_link.mcp.service_adapters as service_adapters

    seen: dict[str, Any] = {}

    class _Svc:
        async def find_proteins(self, **kw: Any) -> dict[str, Any]:
            seen.update(kw)
            return {"count": 0, "proteins": []}

    service_adapters.set_sparql_service(_Svc())  # type: ignore[arg-type]
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool("find_proteins", {"gene": "PNKP", "taxon": "9606"})
        env = _structured(result)
        assert env["success"] is True
        applied = {tuple(pair) for pair in env["_meta"]["argument_aliases_applied"]}
        assert ("taxon", "organism_taxon") in applied
        assert ("gene", "gene_symbol") in applied  # fleet-canon flip
        assert seen["organism_taxon"] == 9606  # alias landed + coerced str->int
        assert seen["gene"] == "PNKP"  # gene_symbol param -> service `gene` kwarg
    finally:
        service_adapters.set_sparql_service(None)
