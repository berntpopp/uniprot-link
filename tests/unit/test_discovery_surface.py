"""Discovery-surface tests: tools resource, capabilities detail, signature drift."""

from __future__ import annotations

import json
from typing import Any

import pytest

from uniprot_link.mcp.arg_help import tool_signature
from uniprot_link.mcp.facade import create_uniprot_mcp


def _structured(result: Any) -> dict[str, Any]:
    sc = result.structured_content
    return sc if isinstance(sc, dict) else json.loads(result.content[0].text)


async def _read(mcp: Any, uri: str) -> str:
    result = await mcp.read_resource(uri)
    return result.contents[0].content  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_capabilities_summary_is_default_and_light() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("get_server_capabilities", {}))
    assert env["detail"] == "summary"
    assert "tool_signatures" in env
    assert env["tool_signatures"]["find_proteins"].startswith("find_proteins(")
    assert "organism_taxon" in env["argument_aliases"]  # alias doc present
    # heavy reference blocks are NOT in the summary
    assert "named_graphs" not in env
    assert "prefixes" not in env


@pytest.mark.asyncio
async def test_capabilities_exposes_argument_value_sets() -> None:
    """F1: enum value sets are discoverable BEFORE a failed call."""
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("get_server_capabilities", {}))
    avs = env["argument_value_sets"]
    assert avs["get_protein_go_terms"]["aspect"] == [
        "biological_process",
        "molecular_function",
        "cellular_component",
    ]
    assert avs["get_server_capabilities"]["detail"] == ["summary", "full"]
    assert avs["search_sparql_query"]["result_format"][0] == "json"
    assert avs["get_protein"]["response_mode"] == ["minimal", "compact", "standard", "full"]


@pytest.mark.asyncio
async def test_capabilities_full_restores_heavy_blocks() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("get_server_capabilities", {"detail": "full"}))
    assert env["detail"] == "full"
    assert env["named_graph_count"] == 21
    assert env["prefixes"]["up"] == "http://purl.uniprot.org/core/"
    assert "tool_signatures" in env


@pytest.mark.asyncio
async def test_tools_resource_lists_all_with_signatures() -> None:
    mcp = create_uniprot_mcp()
    payload = json.loads(await _read(mcp, "uniprot://tools"))
    names = {t["name"] for t in payload["tools"]}
    assert len(names) == 15
    fp = next(t for t in payload["tools"] if t["name"] == "find_proteins")
    # gene_symbol is now REQUIRED (no `=` default) -> it leads the signature.
    assert fp["signature"].startswith("find_proteins(gene_symbol, organism_taxon=")
    assert fp["summary"]  # one-line summary present


@pytest.mark.asyncio
async def test_find_tools_advertise_taxon_id_or_name_union() -> None:
    """Both find tools retain branch-level constraints for ids and names."""
    mcp = create_uniprot_mcp()
    for name in ("find_proteins", "find_proteins_batch"):
        tool = await mcp.get_tool(name)
        schema = tool.parameters["properties"]["organism_taxon"]
        branches = schema["anyOf"]
        assert {branch.get("type") for branch in branches} == {"integer", "string", "null"}
        integer = next(branch for branch in branches if branch.get("type") == "integer")
        string = next(branch for branch in branches if branch.get("type") == "string")
        assert integer["minimum"] == 1
        assert string["minLength"] == 1
        assert "scientific" in schema["description"]
        assert "common" in schema["description"]


@pytest.mark.asyncio
async def test_signatures_match_live_schema_no_drift() -> None:
    """Drift guard: hardcoded description signatures match generated ones."""
    mcp = create_uniprot_mcp()
    for tool in await mcp.list_tools():
        sig = tool_signature(tool.name, tool.parameters)
        assert sig in (tool.description or ""), f"{tool.name}: '{sig}' not in description"
