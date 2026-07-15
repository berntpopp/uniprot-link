"""Protein (UniProtKB) MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from uniprot_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from uniprot_link.mcp.envelope import McpErrorContext, run_mcp_tool
from uniprot_link.mcp.next_commands import (
    after_entry_subresource,
    after_find_proteins,
    after_find_proteins_batch,
    after_get_protein,
    after_obsolete_entry,
    cmd,
)
from uniprot_link.mcp.service_adapters import get_sparql_service
from uniprot_link.services.constants import FEATURE_TYPES

if TYPE_CHECKING:
    from fastmcp import FastMCP

_ACC = Annotated[
    str,
    # No min_length: schema-level rejection would surface a raw pydantic error
    # instead of the server's structured envelope. Let validate_accession in the
    # query builder raise InvalidInputError (field="accession") so a bad value
    # flows through the polished error envelope with a helpful example + recovery.
    Field(
        description="UniProtKB accession, e.g. P05067 (isoforms like P05067-2 accepted).",
        examples=["P05067", "P38398"],
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
        output_schema=None,
        title="Find Proteins",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "search"},
        description=(
            "Search UniProtKB for the entries of a GENE and return matching entries "
            "(accession, mnemonic, recommended name, reviewed flag, organism). "
            "gene_symbol is REQUIRED; refine the hits with organism_taxon, reviewed, "
            "name_contains (matched per word, in any order, case-insensitive), or the "
            "structured filters mnemonic / ec_number / keyword. "
            "Reviewed (Swiss-Prot) hits are ranked first. UniProt SPARQL has no "
            "general full-text index; for EC-only, keyword-only, or free-text "
            "search WITHOUT a gene, use search_example_queries or search_sparql_query. "
            "Pair with get_protein for full detail. Results are ordered reviewed-first, "
            "then by mnemonic, then accession (stable across pages). Cold search can "
            "take several seconds; an identical repeat is cached (~0 ms). If you already "
            "know the accession, call get_protein directly -- it is far faster. "
            "Signature: find_proteins(gene_symbol, organism_taxon=, reviewed=, keyword=, "
            "ec_number=, mnemonic=, name_contains=, limit=, offset=)."
        ),
    )
    async def find_proteins(
        gene_symbol: Annotated[
            str,
            Field(description="Gene symbol to search for, e.g. BRCA1.", examples=["BRCA1", "TP53"]),
        ],
        organism_taxon: Annotated[
            int | None,
            Field(description="NCBI taxon id, e.g. 9606 for human.", ge=1, examples=[9606]),
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
            str | None,
            Field(
                description=(
                    "Words to match in the recommended protein name. Multi-word "
                    "input matches per word (each word must appear, in any order), "
                    "so 'polynucleotide kinase' matches 'Bifunctional "
                    "polynucleotide phosphatase/kinase'. Case-insensitive."
                )
            ),
        ] = None,
        limit: Annotated[int, Field(description="Max results per page.", ge=1, le=200)] = 25,
        offset: Annotated[int, Field(description="Pagination offset.", ge=0)] = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            payload = await service.find_proteins(
                gene=gene_symbol,
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
                "find_proteins",
                fallback=cmd("search_example_queries", text=gene_symbol or "protein"),
            ),
        )

    @mcp.tool(
        name="find_proteins_batch",
        output_schema=None,
        title="Find Proteins (Batch)",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "search", "batch"},
        description=(
            "Resolve SEVERAL gene symbols to UniProtKB entries in ONE call, "
            "running the lookups concurrently -- so N genes cost about one cold "
            "round-trip instead of N sequential ones. Use this for multi-gene "
            "tasks (e.g. 'get domains for PNKP and NAA10'). Returns by_gene "
            "(gene -> accessions, reviewed-first), a flat proteins list tagged "
            "with matched_gene, resolved_genes, and unresolved_genes (a symbol "
            "that matched nothing is disclosed, never silently dropped). Optionally "
            "scope by organism_taxon and reviewed. next_commands fan out to "
            "get_protein on each resolved gene's top hit. For a single gene use "
            "find_proteins. "
            "Signature: find_proteins_batch(gene_symbols, organism_taxon=, reviewed=, "
            "limit_per_gene=)."
        ),
    )
    async def find_proteins_batch(
        gene_symbols: Annotated[
            list[str],
            Field(
                description="Gene symbols to resolve, e.g. ['PNKP','NAA10'].",
                min_length=1,
                max_length=25,
                examples=[["PNKP", "NAA10"]],
            ),
        ],
        organism_taxon: Annotated[
            int | None, Field(description="NCBI taxon id, e.g. 9606 for human.", ge=1)
        ] = None,
        reviewed: Annotated[
            bool | None, Field(description="True = Swiss-Prot only; False = TrEMBL only.")
        ] = None,
        limit_per_gene: Annotated[
            int, Field(description="Max entries per gene (default 5).", ge=1, le=25)
        ] = 5,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().find_proteins_batch(
                gene_symbols, organism_taxon, reviewed, limit_per_gene
            )
            payload["_meta"] = {"next_commands": after_find_proteins_batch(payload["by_gene"])}
            return payload

        return await run_mcp_tool(
            "find_proteins_batch",
            call,
            context=McpErrorContext(
                "find_proteins_batch",
                fallback=cmd(
                    "find_proteins", gene_symbol=gene_symbols[0] if gene_symbols else "protein"
                ),
            ),
        )

    @mcp.tool(
        name="get_protein",
        output_schema=None,
        title="Get Protein",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein"},
        description=(
            "Return the core summary for a single UniProtKB entry by accession: "
            "mnemonic, reviewed flag, recommended/short name, gene(s), organism + "
            "taxon, protein existence, sequence length and mass, a function summary, "
            "and creation/modification dates, plus has_variants/has_diseases/"
            "has_structure presence flags that drive content-aware next_commands. "
            "An obsolete/demerged accession returns a flagged obsolete record "
            "(obsolete:true + replaced_by). response_mode (default compact) controls "
            "verbosity; standard/full add the created/modified dates. "
            "Signature: get_protein(accession, response_mode=)."
        ),
    )
    async def get_protein(
        accession: _ACC, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            payload = await service.get_protein(accession, response_mode)
            if payload.get("obsolete"):
                nxt = after_obsolete_entry(payload.get("replaced_by", []))
            else:
                nxt = after_get_protein(
                    payload["accession"],
                    has_variants=bool(payload.get("has_variants")),
                    has_diseases=bool(payload.get("has_diseases")),
                    has_structure=bool(payload.get("has_structure")),
                )
            payload["_meta"] = {"next_commands": nxt}
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
        output_schema=None,
        title="Get Protein Sequence",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "sequence"},
        description=(
            "Return the amino-acid sequence(s) for an entry: the canonical isoform "
            "(length, mass, sequence) plus any additional (non-canonical) isoforms. "
            "Pass a canonical accession for all isoforms, or an isoform accession "
            "(e.g. P05067-2) to get THAT isoform's specific sequence and mass. "
            "response_mode controls verbosity: minimal=metadata only; compact "
            "(default)=length/mass + a first/last-30-residue sequence_preview "
            "(sequence_truncated:true) — cheap for large proteins; standard/full "
            "return the complete sequence string. Set canonical_only=true to return "
            "only the canonical isoform (skip the additional-isoform list). "
            "Signature: get_protein_sequence(accession, response_mode=, canonical_only=)."
        ),
    )
    async def get_protein_sequence(
        accession: _ACC,
        response_mode: ResponseMode = "compact",
        canonical_only: Annotated[
            bool,
            Field(
                description="Return only the canonical isoform (omit the additional-isoform list)."
            ),
        ] = False,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_sequence(
                accession, response_mode, canonical_only=canonical_only
            )
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
        output_schema=None,
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
            "accepted keys as a filter_hint. Secondary-structure features "
            "(helix/strand/turn) are hidden by default and disclosed under "
            "excluded_secondary_structure; set include_secondary_structure=true (or "
            "name them in feature_types) to return them. "
            "Signature: get_protein_features(accession, feature_types=, limit=, "
            "include_secondary_structure=)."
        ),
    )
    async def get_protein_features(
        accession: _ACC,
        feature_types: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Feature-type keys to keep (omit for all). Closed vocabulary: an "
                    "unrecognised key is rejected (invalid_input), never matched to "
                    "nothing. See feature_types in get_server_capabilities."
                ),
                examples=[["domain", "region"]],
                # Declare the closed vocabulary as an item enum so the schema states
                # it (S4). The runtime (protein_features) is the enforcer -- it raises
                # invalid_input on an unknown key -- so pydantic need not bind it.
                json_schema_extra={"items": {"type": "string", "enum": sorted(FEATURE_TYPES)}},
            ),
        ] = None,
        limit: Annotated[
            int, Field(description="Max features to return (default 200).", ge=1, le=1000)
        ] = 200,
        include_secondary_structure: Annotated[
            bool,
            Field(description="Include helix/strand/turn features (hidden by default)."),
        ] = False,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_features(
                accession, feature_types, limit, include_secondary_structure
            )
            nxt = after_entry_subresource(
                payload["accession"], "get_protein_features", count=payload.get("count")
            )
            hint = payload.get("domain_region_hint")
            if hint and hint.get("suggestion"):
                # Surface the region re-query as the first ready-to-call step.
                nxt = [hint["suggestion"], *nxt][:2]
            payload["_meta"] = {"next_commands": nxt}
            return payload

        return await run_mcp_tool(
            "get_protein_features", call, context=McpErrorContext("get_protein_features")
        )


def _register_annotations(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_protein_variants",
        output_schema=None,
        title="Get Protein Variants",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "variants"},
        description=(
            "Return natural-variant annotations for an entry: position, wild-type "
            "residue, amino-acid substitution, an HGVS-style `notation` (e.g. "
            "`L176F`) for simple substitutions, `variant_type` (substitution|other), "
            "free-text description, structured linked `diseases`, and `dbsnp` rsIDs. "
            "Set disease_associated_only=true to keep only disease-linked variants. "
            "Signature: get_protein_variants(accession, limit=, disease_associated_only=)."
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
                    payload["accession"], "get_protein_variants", count=payload.get("count")
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_variants", call, context=McpErrorContext("get_protein_variants")
        )

    @mcp.tool(
        name="get_protein_diseases",
        output_schema=None,
        title="Get Protein Diseases",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "disease"},
        description=(
            "Return disease annotations associated with an entry: disease name, "
            "UniProt disease id, mnemonic, MIM id, the clinical `definition` (the "
            "disease vocabulary's own description), and `involvement` (the "
            "entry-specific note). Pairs with get_protein_variants for "
            "variant-level disease evidence. "
            "Signature: get_protein_diseases(accession)."
        ),
    )
    async def get_protein_diseases(accession: _ACC) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_diseases(accession)
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "get_protein_diseases", count=payload.get("count")
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_diseases", call, context=McpErrorContext("get_protein_diseases")
        )

    @mcp.tool(
        name="get_protein_cross_references",
        output_schema=None,
        title="Get Protein Cross-References",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "xref"},
        description=(
            "Return database cross-references for an entry, grouped by database "
            "(PDB, AlphaFoldDB, Ensembl, RefSeq, Reactome, STRING, InterPro, ...). "
            "Optionally restrict to specific databases (case-sensitive); any "
            "requested name that matched nothing is echoed under "
            "unmatched_databases with a did-you-mean, so a typo never reads as "
            "'no data'. response_mode (default compact) returns short ids; full "
            "restores raw IRIs. Returns every cross-reference database; use "
            "resolve_identifiers for a focused primary-id mapping. "
            "Signature: get_protein_cross_references(accession, databases=, response_mode=)."
        ),
    )
    async def get_protein_cross_references(
        accession: _ACC,
        databases: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Database short names to keep (case-sensitive; omit for all). A "
                    "malformed name is rejected (invalid_input); a well-formed name "
                    "that matched nothing is echoed under unmatched_databases."
                ),
                examples=[["PDB", "AlphaFoldDB"]],
            ),
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
        output_schema=None,
        title="Get Protein GO Terms",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "go"},
        description=(
            "Return Gene Ontology annotations for an entry, grouped by aspect "
            "(biological_process / molecular_function / cellular_component) where "
            "available, each with GO id, label, and (when annotated) ECO `evidence` "
            "ids plus mapped GO `evidence_codes` (IDA/IEA/IMP/...) for citation. "
            "Always returns `count` and `count_by_aspect`; pass `aspect` to scope to "
            "one ontology and `limit` to cap a large set (token economy). "
            "Signature: get_protein_go_terms(accession, aspect=, limit=)."
        ),
    )
    async def get_protein_go_terms(
        accession: _ACC,
        aspect: Annotated[
            Literal["biological_process", "molecular_function", "cellular_component"] | None,
            Field(description="Restrict to one GO aspect (omit for all)."),
        ] = None,
        limit: Annotated[
            int, Field(description="Max terms to return (0 = all).", ge=0, le=500)
        ] = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_go_terms(accession, aspect, limit)
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "get_protein_go_terms", count=payload.get("count")
                )
            }
            return payload

        return await run_mcp_tool(
            "get_protein_go_terms", call, context=McpErrorContext("get_protein_go_terms")
        )

    @mcp.tool(
        name="resolve_identifiers",
        output_schema=None,
        title="Resolve Identifiers",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"protein", "xref", "mapping"},
        description=(
            "Resolve a UniProtKB accession to its PRIMARY external identifiers: the "
            "genomic/structural/family core (PDB, AlphaFoldDB, Ensembl, RefSeq, "
            "GeneID, HGNC, KEGG, OrthoDB, Pfam, InterPro) by default. Optionally "
            "restrict to specific databases. Returns ids grouped by database plus "
            "the databases that matched and per-database counts. response_mode "
            "(default compact) returns short ids; full restores raw IRIs. For the "
            "exhaustive cross-reference set (incl. drug/disease databases like "
            "DrugBank/ChEMBL/OpenTargets) use get_protein_cross_references instead. "
            "Signature: resolve_identifiers(accession, databases=, response_mode=)."
        ),
    )
    async def resolve_identifiers(
        accession: _ACC,
        databases: Annotated[
            list[str] | None,
            Field(
                description="Target database short names (case-sensitive; omit for the primary set).",
                examples=[["PDB", "Ensembl"]],
            ),
        ] = None,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().map_identifiers(
                accession, databases, response_mode
            )
            payload["_meta"] = {
                "next_commands": after_entry_subresource(
                    payload["accession"], "resolve_identifiers"
                )
            }
            return payload

        return await run_mcp_tool(
            "resolve_identifiers", call, context=McpErrorContext("resolve_identifiers")
        )
