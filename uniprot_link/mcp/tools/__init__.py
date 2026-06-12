"""MCP tool registration entry points."""

from __future__ import annotations

from uniprot_link.mcp.tools.discovery import register_discovery_tools
from uniprot_link.mcp.tools.proteins import register_protein_tools
from uniprot_link.mcp.tools.query import register_query_tools
from uniprot_link.mcp.tools.taxonomy import register_taxonomy_tools

__all__ = [
    "register_discovery_tools",
    "register_protein_tools",
    "register_query_tools",
    "register_taxonomy_tools",
]
