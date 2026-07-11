"""MCP facade for uniprot-link."""

from __future__ import annotations

from fastmcp import FastMCP

from uniprot_link import __version__
from uniprot_link.mcp.capabilities import register_capability_resources
from uniprot_link.mcp.log_filters import install_log_sanitizer
from uniprot_link.mcp.middleware import ArgValidationMiddleware
from uniprot_link.mcp.resources import UNIPROT_SERVER_INSTRUCTIONS
from uniprot_link.mcp.tools import (
    register_discovery_tools,
    register_protein_tools,
    register_query_tools,
    register_taxonomy_tools,
)


def create_uniprot_mcp() -> FastMCP:
    """Build a FastMCP instance with all uniprot-link tools and resources."""
    # FastMCP logs the raw pydantic arg-validation error (caller-controlled names/
    # values) before our middleware catches it -- strip forbidden code points from
    # that log sink so a hostile call can never write them into the process log.
    install_log_sanitizer()

    mcp = FastMCP(
        name="uniprot-link",
        version=__version__,
        instructions=UNIPROT_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )

    register_discovery_tools(mcp)
    register_query_tools(mcp)
    register_protein_tools(mcp)
    register_taxonomy_tools(mcp)
    register_capability_resources(mcp)
    mcp.add_middleware(ArgValidationMiddleware())

    return mcp
