"""Capabilities payload and uniprot:// discovery resources."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from uniprot_link import __version__
from uniprot_link.api.client import RESULT_FORMATS
from uniprot_link.buildinfo import build_info
from uniprot_link.mcp.resources import (
    RECOMMENDED_CITATION,
    RESEARCH_USE_NOTICE,
    UNIPROT_PREFIX_NOTE,
    UNIPROT_REFERENCE_NOTES,
    UNIPROT_USAGE_NOTES,
)
from uniprot_link.services.constants import (
    COMMON_XREF_DATABASES,
    FEATURE_TYPES,
    NAMED_GRAPHS,
    PREFIXES,
    UNIPROT_RELEASE,
    prefix_block,
)
from uniprot_link.services.shaping import RESPONSE_MODES

if TYPE_CHECKING:
    from fastmcp import FastMCP

TOOLS: list[str] = [
    "get_server_capabilities",
    "run_sparql_query",
    "search_example_queries",
    "get_example_query",
    "find_proteins",
    "get_protein",
    "get_protein_sequence",
    "get_protein_features",
    "get_protein_variants",
    "get_protein_diseases",
    "get_protein_cross_references",
    "get_protein_go_terms",
    "map_identifiers",
    "get_taxon",
]


def build_capabilities() -> dict[str, Any]:
    """Return the discovery surface describing this server."""
    return {
        "server": "uniprot-link",
        "server_version": __version__,
        "build": build_info(),
        "uniprot_release": UNIPROT_RELEASE,
        "endpoint": "https://sparql.uniprot.org/sparql",
        "sparql_engine": "QLever",
        "research_use_only": True,
        "research_use_notice": RESEARCH_USE_NOTICE,
        "recommended_citation": RECOMMENDED_CITATION,
        "tools": TOOLS,
        "tool_count": len(TOOLS),
        "result_formats": list(RESULT_FORMATS.keys()),
        "named_graphs": NAMED_GRAPHS,
        "named_graph_count": len(NAMED_GRAPHS),
        "prefixes": PREFIXES,
        "feature_types": sorted(FEATURE_TYPES.keys()),
        "common_xref_databases": COMMON_XREF_DATABASES,
        "response_modes": list(RESPONSE_MODES),
        "default_response_mode": "compact",
        "provenance_policy": (
            "Static provenance (research-use restriction, citation, UniProt "
            "release) is declared here and applies to ALL tool outputs; it is "
            "not repeated per-call to conserve context tokens."
        ),
        "per_call_meta": ["tool", "request_id", "next_commands"],
        "latency_profile": {
            "note": (
                "Cold upstream SPARQL latency. An identical repeated call is "
                "served from a 1h in-process cache in ~0 ms (see the `cached` "
                "field on responses). Bands are coarse guidance, not promises."
            ),
            "bands": {
                "fast": {
                    "typical_ms": "0-700",
                    "tools": [
                        "get_protein",
                        "get_protein_sequence",
                        "get_protein_features",
                        "get_protein_variants",
                        "get_protein_diseases",
                        "get_protein_cross_references",
                        "get_protein_go_terms",
                        "map_identifiers",
                        "get_taxon (by id or curated common name)",
                        "get_server_capabilities",
                    ],
                },
                "medium": {
                    "typical_ms": "1000-3000",
                    "tools": ["search_example_queries", "get_example_query"],
                },
                "slow_cold_scan": {
                    "typical_ms": "3000-12000",
                    "tools": [
                        "find_proteins (cold)",
                        "get_taxon (uncached name scan)",
                        "run_sparql_query (unbounded or federated)",
                    ],
                },
            },
        },
        "read_only": True,
        "not_found_contract": (
            "Nonexistent accessions/taxa return error_code 'not_found' on every "
            "get_protein*/get_taxon tool; run_sparql_query rejects write/UPDATE "
            "queries as 'invalid_input' (read-only)."
        ),
        "result_ordering": {
            "find_proteins": (
                "Reviewed (Swiss-Prot) first, then by mnemonic (entry name), then "
                "accession -- deterministic across identical calls and pages."
            ),
        },
        "recommended_workflows": [
            "accession -> get_protein -> get_protein_{sequence,features,variants,diseases}",
            "gene + organism_taxon -> find_proteins -> get_protein",
            "organism name -> get_taxon -> find_proteins(organism_taxon=...)",
            "learn SPARQL -> search_example_queries -> get_example_query -> run_sparql_query",
        ],
        "error_codes": [
            "invalid_input",
            "not_found",
            "query_syntax_error",
            "query_timeout",
            "rate_limited",
            "upstream_unavailable",
            "internal_error",
        ],
        "limits": {
            "default_select_limit": 50,
            "max_select_limit": 10000,
            "server_query_timeout_minutes": 45,
            "find_proteins_requires_anchor": (
                "gene, mnemonic, ec_number, keyword, or organism_taxon+name_contains"
            ),
        },
        "notes": UNIPROT_REFERENCE_NOTES,
    }


def register_capability_resources(mcp: FastMCP) -> None:
    """Register the uniprot:// resource family on a FastMCP instance."""

    @mcp.resource("uniprot://capabilities", mime_type="application/json")
    def capabilities() -> str:
        return json.dumps(build_capabilities(), indent=2)

    @mcp.resource("uniprot://usage", mime_type="text/plain")
    def usage() -> str:
        return UNIPROT_USAGE_NOTES

    @mcp.resource("uniprot://reference", mime_type="text/plain")
    def reference() -> str:
        return UNIPROT_REFERENCE_NOTES

    @mcp.resource("uniprot://prefixes", mime_type="text/plain")
    def prefixes() -> str:
        return f"# {UNIPROT_PREFIX_NOTE}\n{prefix_block()}"

    @mcp.resource("uniprot://research-use", mime_type="text/plain")
    def research_use() -> str:
        return RESEARCH_USE_NOTICE

    @mcp.resource("uniprot://citation", mime_type="text/plain")
    def citation() -> str:
        return RECOMMENDED_CITATION
