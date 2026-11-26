"""Discovery-surface tests: tools resource, capabilities detail, signature drift."""

from __future__ import annotations

import json
import re
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
    env = _structured(await mcp.call_tool("get_server_capabilities", {}))["result"]
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
    env = _structured(await mcp.call_tool("get_server_capabilities", {}))["result"]
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
    env = _structured(await mcp.call_tool("get_server_capabilities", {"detail": "full"}))["result"]
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
async def test_variant_tool_advertises_positive_optional_position_bounds() -> None:
    mcp = create_uniprot_mcp()
    tool = await mcp.get_tool("get_protein_variants")
    for name in ("position_start", "position_end"):
        schema = tool.parameters["properties"][name]
        integer = next(branch for branch in schema["anyOf"] if branch.get("type") == "integer")
        assert integer["minimum"] == 1
        assert name not in tool.parameters.get("required", [])


@pytest.mark.asyncio
async def test_signatures_match_live_schema_no_drift() -> None:
    """Drift guard: hardcoded description signatures match generated ones."""
    mcp = create_uniprot_mcp()
    for tool in await mcp.list_tools():
        sig = tool_signature(tool.name, tool.parameters)
        assert sig in (tool.description or ""), f"{tool.name}: '{sig}' not in description"


# ponytail: copy of genefoundry-router scripts/surface.py `lead_states_return` (D1, Tool-Schema
# Documentation v1.1); re-vendor if the router's rule changes.
_LEAD_VERBS = (  # noqa: SIM905 - byte-for-byte copy of the router rule
    "get fetch retrieve list look lookup search find resolve report read predict annotate "
    "compute calculate count summarize summarise map translate convert describe show check "
    "validate classify score rank query browse discover explain compare diff normalize normalise "
    "expand evaluate assess enumerate identify locate export download match suggest recommend "
    "inspect generate render estimate"
).split()
_VERB_LEAD = re.compile(
    rf"^(?:use this (?:tool )?to )?(?:{'|'.join(_LEAD_VERBS)})(?:s|es|ies)?\b", re.IGNORECASE
)
_RETURNS = re.compile(
    r"(?<!not )(?<!n't )(?<!n\u2019t )(?<!never )\breturn(?:s|ed|ing)?\b(?!\s*[~<\d])|→|->",
    re.IGNORECASE,
)
_FIELD_LIST = re.compile(r"\w+\W+\w+[^:]*:\s+[^.;:]+,")
_SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+")


def _lead_states_return(description: str | None) -> bool:
    lead = _SENTENCE_END.split(" ".join((description or "").split()), maxsplit=1)[0][:300]
    return bool(_VERB_LEAD.match(lead) or _RETURNS.search(lead) or _FIELD_LIST.search(lead))


@pytest.mark.asyncio
async def test_every_description_lead_states_what_it_returns() -> None:
    """D1: each tool's first sentence says what the tool returns."""
    tools = await create_uniprot_mcp().list_tools()
    failing = [t.name for t in tools if not _lead_states_return(t.description)]
    assert failing == []
