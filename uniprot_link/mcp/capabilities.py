"""Capabilities payload and uniprot:// discovery resources."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from uniprot_link import __version__
from uniprot_link.api.client import RESULT_FORMATS
from uniprot_link.buildinfo import build_info
from uniprot_link.mcp.arg_help import ARG_ALIASES, enum_values_for, tool_signature
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
    MAP_IDENTIFIER_DATABASES,
    NAMED_GRAPHS,
    PREFIXES,
    UNIPROT_RELEASE,
    prefix_block,
)
from uniprot_link.services.shaping import RESPONSE_MODES

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Reverse the alias map to {canonical: [accepted synonyms]} for human-facing docs.
_ALIAS_DOC: dict[str, list[str]] = {}
for _alias, _canonical in sorted(ARG_ALIASES.items()):
    _ALIAS_DOC.setdefault(_canonical, []).append(_alias)

# The light "summary" projection keeps just what a cold consumer needs to call any
# tool without guessing an argument name; the heavy reference blocks (named graphs,
# prefixes, vocabularies) stay behind detail='full' / uniprot://capabilities.
_SUMMARY_KEYS: tuple[str, ...] = (
    "server",
    "server_version",
    "build",
    "uniprot_release",
    "endpoint",
    "sparql_engine",
    "research_use_only",
    "research_use_notice",
    "recommended_citation",
    "tools",
    "tool_count",
    "response_modes",
    "default_response_mode",
    "recommended_workflows",
    "error_codes",
    "limits",
    "truncation_contract",
    "read_only",
)

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
        "map_identifier_databases": MAP_IDENTIFIER_DATABASES,
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
            "queries as 'invalid_input' (read-only). An obsolete/demerged accession "
            "is surfaced consistently: get_protein returns a flagged record "
            "(obsolete:true + replaced_by), while the data sub-tools return a "
            "'not_found' error carrying obsolete:true + replaced_by + a "
            "next_command to the live replacement."
        ),
        "obsolete_handling": (
            "Entries with up:obsolete=true (demerged or deleted) are never presented "
            "as live. get_protein returns {obsolete:true, obsolete_reason, "
            "replaced_by:[...]}; sequence/features/variants/diseases/go/xref/map "
            "raise an obsolete-flagged not_found. replaced_by may list multiple "
            "accessions (a demerge can split into several)."
        ),
        "truncation_contract": (
            "When a list is capped, the response carries `truncated` with a "
            "standard shape: {returned, total, reason, recovery}. `returned` is "
            "this page's size; `total` is the true available count where cheaply "
            "computable (features, GO terms, variants, find_proteins); `recovery` "
            "is the concrete next step (raise limit / page via offset / add a "
            "filter). run_sparql_query omits `total` (an arbitrary query's full "
            "count is not computable without re-running it). Cross-reference "
            "compact mode reports per-database {returned, total} under "
            "truncated_databases."
        ),
        "result_ordering": {
            "find_proteins": (
                "Reviewed (Swiss-Prot) first, then by mnemonic (entry name), then "
                "accession -- deterministic across identical calls and pages."
            ),
            "cross_references": (
                "Ids and database keys are sorted (stable across calls and identical "
                "between get_protein_cross_references and map_identifiers). compact "
                "caps each database at 25 ids with a truncated_databases note and "
                "always reports per-database counts; minimal returns counts only; "
                "standard/full return every id."
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


async def collect_tool_signatures(mcp: FastMCP) -> dict[str, str]:
    """Map every registered tool to its rendered signature (from the live schema)."""
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    return {t.name: tool_signature(t.name, t.parameters or {}) for t in tools}


async def collect_tool_enums(mcp: FastMCP) -> dict[str, dict[str, list[Any]]]:
    """Map ``{tool: {arg: [valid values]}}`` for every enum-constrained argument.

    Surfaces the value sets (aspect/detail/result_format/response_mode, ...) in the
    discovery payload so an LLM can pick a valid value BEFORE provoking an error
    (F1). Derived from the live JSON input schemas via the shared enum extractor.
    """
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    out: dict[str, dict[str, list[Any]]] = {}
    for tool in tools:
        schema = tool.parameters or {}
        enums = {
            arg: vals
            for arg in (schema.get("properties") or {})
            if (vals := enum_values_for(schema, arg)) is not None
        }
        if enums:
            out[tool.name] = enums
    return out


async def build_tools_overview(mcp: FastMCP) -> dict[str, Any]:
    """Lightweight discovery payload: name, one-line summary, and call signature."""
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    entries: list[dict[str, str]] = []
    for tool in tools:
        summary = (tool.description or "").split(". ")[0].strip()
        entries.append(
            {
                "name": tool.name,
                "summary": summary[:160],
                "signature": tool_signature(tool.name, tool.parameters or {}),
            }
        )
    return {"server": "uniprot-link", "tool_count": len(entries), "tools": entries}


def project_capabilities(
    detail: str,
    tool_signatures: dict[str, str],
    tool_enums: dict[str, dict[str, list[Any]]] | None = None,
) -> dict[str, Any]:
    """Return the full capabilities payload, or a light summary (default).

    ``detail='full'`` returns everything (named graphs, prefixes, vocabularies);
    ``detail='summary'`` returns just identity/build, the tool list WITH signatures,
    accepted argument aliases, enum value sets, workflows, error taxonomy, limits.
    """
    value_sets = tool_enums or {}
    full = build_capabilities()
    full["tool_signatures"] = tool_signatures
    full["argument_aliases"] = _ALIAS_DOC
    full["argument_value_sets"] = value_sets
    if detail == "full":
        full["detail"] = "full"
        return full
    summary: dict[str, Any] = {k: full[k] for k in _SUMMARY_KEYS if k in full}
    summary["tool_signatures"] = tool_signatures
    summary["argument_aliases"] = _ALIAS_DOC
    summary["argument_value_sets"] = value_sets
    summary["latency_note"] = full["latency_profile"]["note"]
    summary["detail"] = "summary"
    summary["more"] = (
        "Call get_server_capabilities(detail='full') or read uniprot://capabilities "
        "for named graphs, prefixes, and vocabularies; uniprot://tools lists signatures."
    )
    return summary


def register_capability_resources(mcp: FastMCP) -> None:
    """Register the uniprot:// resource family on a FastMCP instance."""

    @mcp.resource("uniprot://capabilities", mime_type="application/json")
    def capabilities() -> str:
        return json.dumps(build_capabilities(), indent=2)

    @mcp.resource("uniprot://tools", mime_type="application/json")
    async def tools_overview() -> str:
        return json.dumps(await build_tools_overview(mcp), indent=2)

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
