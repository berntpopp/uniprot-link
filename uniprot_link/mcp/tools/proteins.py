"""Protein (UniProtKB) MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from uniprot_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from uniprot_link.mcp.envelope import McpErrorContext, run_mcp_tool
from uniprot_link.mcp.next_commands import (
    after_entry_subresource,
    after_find_proteins,
    after_get_protein,
    cmd,
)
from uniprot_link.mcp.service_adapters import get_sparql_service

if TYPE_CHECKING:
    from fastmcp import FastMCP

_ACC = Annotated[
    str,
    Field(
        description="UniProtKB accession, e.g. P05067 (isoforms like P05067-2 accepted).",
        min_length=6,
    ),
]

ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(description="Verbosity: minimal | compact | standard | full (default compact)."),
]


def register_protein_tools(mcp: FastMCP) -> None:
    """Register UniProtKB protein tools on a FastMCP instance."""
    _register_find_and_summary(mcp)
    _register_sequence_and_features(mcp)
    _register_annotations(mcp)


def _register_find_and_summary(mcp: FastMCP) -> None:
    @mcp.tool(
        name="find_proteins",
        title="Find Proteins",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "search"},
        description=(
            "Search UniProtKB by structured filters and return matching entries "
            "(accession, mnemonic, recommended name, reviewed flag, organism). "
            "Requires at least one anchor: gene symbol, mnemonic, EC number, keyword "
            "(KW-id or label), OR organism_taxon together with name_contains. "
            "Reviewed (Swiss-Prot) hits are ranked first. UniProt SPARQL has no "
            "general full-text index, so for broad text use search_example_queries "
            "or run_sparql_query. Pair with get_protein for full detail."
        ),
    )
    async def find_proteins(
        gene: Annotated[str | None, Field(description="Gene symbol, e.g. BRCA1.")] = None,
        organism_taxon: Annotated[
            int | None, Field(description="NCBI taxon id, e.g. 9606 for human.", ge=1)
        ] = None,
        reviewed: Annotated[
            bool | None, Field(description="True = Swiss-Prot only; False = TrEMBL only.")
        ] = None,
        keyword: Annotated[
            str | None, Field(description="UniProt keyword (KW-id like KW-0007, or a label).")
        ] = None,
        ec_number: Annotated[str | None, Field(description="EC number, e.g. 2.7.11.1.")] = None,
        mnemonic: Annotated[
            str | None, Field(description="Entry mnemonic, e.g. BRCA1_HUMAN.")
        ] = None,
        name_contains: Annotated[
            str | None, Field(description="Substring of the recommended protein name.")
        ] = None,
        limit: Annotated[int, Field(description="Max results per page.", ge=1, le=200)] = 25,
        offset: Annotated[int, Field(description="Pagination offset.", ge=0)] = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            payload = await service.find_proteins(
                gene=gene,
                organism_taxon=organism_taxon,
                reviewed=reviewed,
                keyword=keyword,
                ec_number=ec_number,
                mnemonic=mnemonic,
                name_contains=name_contains,
                limit=limit,
                offset=offset,
            )
            accessions = [p["accession"] for p in payload["proteins"] if p.get("accession")]
            payload["_meta"] = {"next_commands": after_find_proteins(accessions)}
            return payload

        return await run_mcp_tool(
            "find_proteins",
            call,
            context=McpErrorContext(
                "find_proteins", fallback=cmd("search_example_queries", text=gene or "protein")
            ),
        )

    @mcp.tool(
        name="get_protein",
        title="Get Protein",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein"},
        description=(
            "Return the core summary for a single UniProtKB entry by accession: "
            "mnemonic, reviewed flag, recommended/short name, gene(s), organism + "
            "taxon, protein existence, sequence length and mass, a function summary, "
            "and creation/modification dates. `_meta.next_commands` points at the "
            "sequence/features/variants/diseases/xref tools. response_mode "
            "(default compact) controls verbosity; full restores raw IRIs."
        ),
    )
    async def get_protein(
        accession: _ACC, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            payload = await service.get_protein(accession, response_mode)
            payload["_meta"] = {"next_commands": after_get_protein(payload["accession"])}
            return payload

        return await run_mcp_tool(
            "get_protein",
            call,
            # No explicit fallback: the default recovery sanitizes the accession
            # (a numeric/garbage value is never replayed as gene=...). See
            # next_commands.protein_not_found_recovery.
            context=McpErrorContext("get_protein", arguments={"accession": accession}),
        )


def _register_sequence_and_features(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_protein_sequence",
        title="Get Protein Sequence",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "sequence"},
        description=(
            "Return the amino-acid sequence(s) for an entry: the canonical isoform "
            "(length, mass, sequence) plus any additional (non-canonical) isoforms. "
            "Pass an accession; isoform suffixes are normalised to the parent entry. "
            "response_mode controls verbosity: minimal=metadata only; compact "
            "(default)=length/mass + a first/last-30-residue sequence_preview "
            "(sequence_truncated:true) — cheap for large proteins; standard/full "
            "return the complete sequence string."
        ),
    )
    async def get_protein_sequence(
        accession: _ACC, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_sequence(accession, response_mode)
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "get_protein_sequence"
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_sequence", call, context=McpErrorContext("get_protein_sequence")
        )

    @mcp.tool(
        name="get_protein_features",
        title="Get Protein Features",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "features"},
        description=(
            "Return sequence features with begin/end coordinates (FALDO) for an "
            "entry: domains, regions, transmembrane segments, binding/active sites, "
            "PTMs, signal peptides, secondary structure, mutagenesis sites, and more. "
            "feature_types=['domain'] returns positional domain extents; each "
            "returned `type` round-trips to the filter vocabulary. Filter keys come "
            "from capabilities (feature_types); a zero-match filter echoes the "
            "accepted keys as a filter_hint."
        ),
    )
    async def get_protein_features(
        accession: _ACC,
        feature_types: Annotated[
            list[str] | None,
            Field(description="Feature-type keys to keep (omit for all)."),
        ] = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_features(accession, feature_types)
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "get_protein_features"
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_features", call, context=McpErrorContext("get_protein_features")
        )


def _register_annotations(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_protein_variants",
        title="Get Protein Variants",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "variants"},
        description=(
            "Return natural-variant annotations for an entry: position, wild-type "
            "residue, amino-acid substitution, an HGVS-style `notation` (e.g. "
            "`L176F`) for simple substitutions, `variant_type` (substitution|other), "
            "free-text description, structured linked `diseases`, and `dbsnp` rsIDs. "
            "Set disease_associated_only=true to keep only disease-linked variants."
        ),
    )
    async def get_protein_variants(
        accession: _ACC,
        limit: Annotated[int, Field(description="Max variants to return.", ge=1, le=2000)] = 200,
        disease_associated_only: Annotated[
            bool, Field(description="Return only variants linked to a disease.")
        ] = False,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_variants(
                accession, limit, disease_associated_only
            )
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "get_protein_variants"
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_variants", call, context=McpErrorContext("get_protein_variants")
        )

    @mcp.tool(
        name="get_protein_diseases",
        title="Get Protein Diseases",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "disease"},
        description=(
            "Return disease annotations associated with an entry: disease name, "
            "UniProt disease id, MIM id, and the descriptive comment. Pairs with "
            "get_protein_variants for variant-level disease evidence."
        ),
    )
    async def get_protein_diseases(accession: _ACC) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_diseases(accession)
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "get_protein_diseases"
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_diseases", call, context=McpErrorContext("get_protein_diseases")
        )

    @mcp.tool(
        name="get_protein_cross_references",
        title="Get Protein Cross-References",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "xref"},
        description=(
            "Return database cross-references for an entry, grouped by database "
            "(PDB, AlphaFoldDB, Ensembl, RefSeq, Reactome, STRING, InterPro, ...). "
            "Optionally restrict to specific databases. response_mode (default "
            "compact) returns short ids; full restores raw IRIs. "
            "Returns every cross-reference database; use map_identifiers for a focused primary-id mapping."
        ),
    )
    async def get_protein_cross_references(
        accession: _ACC,
        databases: Annotated[
            list[str] | None, Field(description="Database short names to keep (omit for all).")
        ] = None,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_cross_references(
                accession, databases, response_mode
            )
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "get_protein_cross_references"
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_cross_references",
            call,
            context=McpErrorContext("get_protein_cross_references"),
        )

    @mcp.tool(
        name="get_protein_go_terms",
        title="Get Protein GO Terms",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "go"},
        description=(
            "Return Gene Ontology annotations for an entry, grouped by aspect "
            "(biological_process / molecular_function / cellular_component) where "
            "available, each with GO id and label."
        ),
    )
    async def get_protein_go_terms(accession: _ACC) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_go_terms(accession)
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "get_protein_go_terms"
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_go_terms", call, context=McpErrorContext("get_protein_go_terms")
        )

    @mcp.tool(
        name="map_identifiers",
        title="Map Identifiers",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "xref", "mapping"},
        description=(
            "Map a UniProtKB accession to external database identifiers (PDB, "
            "Ensembl, RefSeq, HGNC, GeneID, KEGG, Reactome, ...). Optionally restrict "
            "to specific databases. Returns ids grouped by database plus the list of "
            "databases that had a match. response_mode (default compact) returns "
            "short ids; full restores raw IRIs. "
            "Defaults to primary id-mapping databases (PDB, Ensembl, RefSeq, HGNC, ...); for the exhaustive xref list use get_protein_cross_references."
        ),
    )
    async def map_identifiers(
        accession: _ACC,
        databases: Annotated[
            list[str] | None,
            Field(description="Target database short names (omit for all available)."),
        ] = None,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().map_identifiers(
                accession, databases, response_mode
            )
            payload["_meta"] = {
                "next_commands": after_entry_subresource(payload["accession"], "map_identifiers")
            }
            return payload

        return await run_mcp_tool(
            "map_identifiers", call, context=McpErrorContext("map_identifiers")
        )
