"""MCP facade, tools, resources, and error envelope for uniprot-link."""

from __future__ import annotations

__all__ = ["create_uniprot_mcp"]


def __getattr__(name: str) -> object:
    """Lazily expose the facade factory."""
    if name == "create_uniprot_mcp":
        from uniprot_link.mcp.facade import create_uniprot_mcp

        return create_uniprot_mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
