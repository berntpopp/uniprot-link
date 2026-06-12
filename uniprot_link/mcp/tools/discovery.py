"""Discovery tool: get_server_capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from uniprot_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from uniprot_link.mcp.capabilities import (
    collect_tool_enums,
    collect_tool_signatures,
    project_capabilities,
)
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
            "Return the uniprot-link discovery surface. detail='summary' (default) "
            "is light: identity/build/release, the tool list WITH call signatures, "
            "accepted argument aliases, response modes, recommended workflows, error "
            "taxonomy, and limits -- enough to call any tool without guessing an "
            "argument name. detail='full' adds the heavy reference blocks (21 named "
            "graphs with triple counts, the full SPARQL prefix map, full latency "
            "bands, feature-type and cross-reference vocabularies). Call this first "
            "in a cold session, or read uniprot://tools (signatures only) or "
            "uniprot://capabilities (full). "
            "Signature: get_server_capabilities(detail=)."
        ),
    )
    async def get_server_capabilities(
        detail: Annotated[
            Literal["summary", "full"],
            Field(description="summary (default, light) or full (adds named graphs/prefixes)."),
        ] = "summary",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            signatures = await collect_tool_signatures(mcp)
            enums = await collect_tool_enums(mcp)
            return project_capabilities(detail, signatures, enums)

        return await run_mcp_tool(
            "get_server_capabilities",
            call,
            context=McpErrorContext("get_server_capabilities"),
        )
