"""MCP facade for uniprot-link."""

from __future__ import annotations

from fastmcp import FastMCP

from uniprot_link import __version__
from uniprot_link.mcp.capabilities import register_capability_resources
from uniprot_link.mcp.log_filters import install_log_sanitizer
from uniprot_link.mcp.middleware import ArgValidationMiddleware
from uniprot_link.mcp.notfound_guard import (
    NotFoundGuard,
    install_protocol_error_handler,
    install_validation_log_filter,
)
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

    # FastMCP-core not-found reflection guard: core echoes the caller's OWN
    # requested tool name / resource URI / prompt name (with any control/zero-width/
    # bidi/NUL code points) to the caller and to logs BEFORE backend middleware runs.
    # NotFoundGuard preflights the tool NAME (unknown -> fixed name-free envelope) and
    # fixes the on_read_resource boundary; add it FIRST so it is the OUTERMOST
    # middleware. See notfound_guard.py.
    mcp.add_middleware(NotFoundGuard())

    # Layer 5: scrub the FastMCP-core / MCP-SDK validation logs (at ANY level) that
    # would echo the caller-supplied name/URI. Attach after FastMCP is built so its
    # non-propagating Rich handlers exist (idempotent; process-global).
    install_validation_log_filter()

    register_discovery_tools(mcp)
    register_query_tools(mcp)
    register_protein_tools(mcp)
    register_taxonomy_tools(mcp)
    register_capability_resources(mcp)
    mcp.add_middleware(ArgValidationMiddleware())

    # Layer 3 protocol backstop: wrap the raw tool/resource/prompt request handlers
    # as the OUTERMOST guard so FastMCP core cannot reflect a caller-supplied name/
    # URI/prompt name (nor its code points) in a not-found JSON-RPC error frame.
    # Installed last, after all handlers exist.
    install_protocol_error_handler(mcp)

    return mcp
