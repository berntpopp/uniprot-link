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
    "resolve_identifiers",
    "find_proteins",
    "get_taxon",
    "search_sparql_query",
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
async def test_no_tool_publishes_output_schema() -> None:
    """Tool-Surface Budget v1: outputSchema is suppressed on every tool.

    It was ~39% of the advertised surface, is optional in MCP, and no model reads
    it. structuredContent is unaffected -- FastMCP still emits it for any dict
    return (asserted in test_capabilities_emits_structured_content and
    test_every_tool_still_emits_structured_content)."""
    mcp = create_uniprot_mcp()
    for name in _TYPED_TOOLS:
        tool = await mcp.get_tool(name)
        assert tool.output_schema is None, f"{name} still publishes an output_schema"


@pytest.mark.asyncio
async def test_every_tool_still_emits_structured_content() -> None:
    """Dropping outputSchema must NOT drop structuredContent (the dict envelope).

    The unknown-argument path is a cheap way to force a real (error) envelope out
    of every tool without touching the network."""
    mcp = create_uniprot_mcp()
    for name in _TYPED_TOOLS:
        res = await mcp.call_tool(name, {"__gf_no_such_arg__": "x"})
        assert res.structured_content is not None, f"{name} lost structuredContent"
        assert res.structured_content.get("success") is False
        assert res.is_error is True, f"{name} error envelope has isError=false"
