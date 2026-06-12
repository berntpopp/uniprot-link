"""Taxonomy MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from uniprot_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from uniprot_link.mcp.envelope import McpErrorContext, run_mcp_tool
from uniprot_link.mcp.next_commands import cmd
from uniprot_link.mcp.schemas import TAXON_SCHEMA
from uniprot_link.mcp.service_adapters import get_sparql_service

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_taxonomy_tools(mcp: FastMCP) -> None:
    """Register taxonomy tools on a FastMCP instance."""

    @mcp.tool(
        name="get_taxon",
        output_schema=TAXON_SCHEMA,
        title="Get Taxon",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"taxonomy"},
        description=(
            "Resolve an organism in the UniProt taxonomy. Pass a numeric NCBI taxon "
            "id (e.g. 9606) for full detail (scientific/common name, rank, the DIRECT "
            "parent, and an optional ordered lineage from species up to root), or a "
            "scientific/common name to get candidate taxon ids. Use the resolved "
            "taxon id with find_proteins(organism_taxon=...)."
        ),
    )
    async def get_taxon(
        taxon: Annotated[
            str,
            Field(description="NCBI taxon id (digits) or a scientific/common name.", min_length=1),
        ],
        include_lineage: Annotated[
            bool, Field(description="Include the ancestor lineage (id lookups only).")
        ] = False,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            payload = await service.get_taxon(taxon, include_lineage)
            if "taxon_id" in payload:
                payload["_meta"] = {
                    "next_commands": [cmd("find_proteins", organism_taxon=int(payload["taxon_id"]))]
                }
            elif payload.get("matches"):
                # By-name resolution: chain into id detail + a protein search so
                # name -> id -> find never dead-ends (Bug 5).
                top = payload["matches"][0]["taxon_id"]
                payload["_meta"] = {
                    "next_commands": [
                        cmd("get_taxon", taxon=top),
                        cmd("find_proteins", organism_taxon=int(top)),
                    ]
                }
            return payload

        return await run_mcp_tool("get_taxon", call, context=McpErrorContext("get_taxon"))
