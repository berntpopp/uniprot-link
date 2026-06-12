"""MCP facade for uniprot-link."""

from __future__ import annotations

from fastmcp import FastMCP

from uniprot_link.mcp.capabilities import register_capability_resources
from uniprot_link.mcp.resources import UNIPROT_SERVER_INSTRUCTIONS
from uniprot_link.mcp.tools import (
    register_discovery_tools,
    register_protein_tools,
    register_query_tools,
    register_taxonomy_tools,
)


def create_uniprot_mcp() -> FastMCP:
    """Build a FastMCP instance with all uniprot-link tools and resources."""
    mcp = FastMCP(
        name="uniprot-link",
        instructions=UNIPROT_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )

    register_discovery_tools(mcp)
    register_query_tools(mcp)
    register_protein_tools(mcp)
    register_taxonomy_tools(mcp)
    register_capability_resources(mcp)

    return mcp
