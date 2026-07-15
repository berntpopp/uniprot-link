"""Taxonomy MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from uniprot_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from uniprot_link.mcp.envelope import McpErrorContext, run_mcp_tool
from uniprot_link.mcp.next_commands import cmd
from uniprot_link.mcp.service_adapters import get_sparql_service

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_taxonomy_tools(mcp: FastMCP) -> None:
    """Register taxonomy tools on a FastMCP instance."""

    @mcp.tool(
        name="get_taxon",
        output_schema=None,
        title="Get Taxon",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"taxonomy"},
        description=(
            "Resolve an organism in the UniProt taxonomy. Pass a numeric NCBI taxon "
            "id (e.g. 9606) for full detail (scientific/common name, rank, the DIRECT "
            "parent, and an optional ordered lineage from species up to root), or a "
            "scientific/common name to get candidate taxon ids. Use the resolved "
            "taxon id with find_proteins(gene_symbol=..., organism_taxon=...). Name matches are "
            "ranked best-first (an exact scientific/common-name hit leads, tagged "
            "match_quality:'exact'), so matches[0] and next_commands point at the "
            "right organism. Numeric-id and common-organism-name lookups are fast "
            "(~0 ms for common names); an uncommon name triggers a multi-second "
            "taxonomy scan. "
            "Signature: get_taxon(taxon, include_lineage=)."
        ),
    )
    async def get_taxon(
        taxon: Annotated[
            str,
            Field(
                description="NCBI taxon id (digits) or a scientific/common name.",
                min_length=1,
                examples=["9606", "Homo sapiens"],
            ),
        ],
        include_lineage: Annotated[
            bool, Field(description="Include the ancestor lineage (id lookups only).")
        ] = False,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            payload = await service.get_taxon(taxon, include_lineage)
            # find_proteins now REQUIRES gene_symbol, so a taxon lookup (which has no
            # gene) cannot emit a ready-to-run find_proteins call -- suggesting one
            # would only error. The by-name path still chains to the id detail.
            if "taxon_id" not in payload and payload.get("matches"):
                top = payload["matches"][0]["taxon_id"]
                payload["_meta"] = {"next_commands": [cmd("get_taxon", taxon=top)]}
            return payload

        return await run_mcp_tool("get_taxon", call, context=McpErrorContext("get_taxon"))
