"""MCP structured-output (outputSchema/structuredContent) tests."""

from __future__ import annotations

import pytest

from uniprot_link.mcp.facade import create_uniprot_mcp

_TYPED_TOOLS = {
    "get_server_capabilities",
    "get_protein",
    "get_protein_sequence",
    "get_protein_features",
    "get_protein_variants",
    "get_protein_diseases",
    "get_protein_cross_references",
    "get_protein_go_terms",
    "map_identifiers",
    "find_proteins",
    "get_taxon",
    "run_sparql_query",
    "search_example_queries",
    "get_example_query",
}


@pytest.mark.asyncio
async def test_capabilities_emits_structured_content() -> None:
    mcp = create_uniprot_mcp()
    res = await mcp.call_tool("get_server_capabilities", {})
    # structuredContent present...
    assert res.structured_content is not None
    assert res.structured_content["server"] == "uniprot-link"
    # ...and a back-compat serialized TextContent block.
    assert res.content and res.content[0].text


@pytest.mark.asyncio
async def test_all_typed_tools_declare_output_schema() -> None:
    mcp = create_uniprot_mcp()
    for name in _TYPED_TOOLS:
        tool = await mcp.get_tool(name)
        assert tool.output_schema is not None, f"{name} has no output_schema"
