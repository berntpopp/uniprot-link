"""Discovery tool: get_server_capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from uniprot_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from uniprot_link.mcp.capabilities import build_capabilities
from uniprot_link.mcp.envelope import McpErrorContext, run_mcp_tool
from uniprot_link.mcp.schemas import CAPABILITIES_SCHEMA

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_discovery_tools(mcp: FastMCP) -> None:
    """Register discovery tools on a FastMCP instance."""

    @mcp.tool(
        name="get_server_capabilities",
        title="Get Server Capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=CAPABILITIES_SCHEMA,
        tags={"discovery"},
        description=(
            "Return the uniprot-link discovery surface: the full tool list, the 21 "
            "UniProt named graphs with triple counts, canonical SPARQL prefixes, "
            "supported result formats, recommended workflows, feature-type and "
            "cross-reference vocabularies, error taxonomy, and limits. Call this "
            "first in a cold session, or read the uniprot://capabilities resource."
        ),
    )
    async def get_server_capabilities() -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            return dict(build_capabilities())

        return await run_mcp_tool(
            "get_server_capabilities",
            call,
            context=McpErrorContext("get_server_capabilities"),
        )
