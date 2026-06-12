"""Builders for `_meta.next_commands` entries: `{tool, arguments}` steps."""

from __future__ import annotations

import re
from typing import Any

_PROTEIN_TOOLS = {
    "get_protein",
    "get_protein_sequence",
    "get_protein_features",
    "get_protein_variants",
    "get_protein_diseases",
    "get_protein_cross_references",
    "get_protein_go_terms",
    "map_identifiers",
}
# A gene symbol shape: starts with a letter, short, alnum/.-_ only (e.g. BRCA1).
_GENE_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,11}$")


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def protein_not_found_recovery(value: str) -> list[dict[str, Any]]:
    """Recovery for a failed get_protein lookup without reusing a bad accession.

    A numeric/garbage accession must NOT be replayed as a gene symbol; only a
    gene-shaped value is offered to find_proteins(gene=...).
    """
    out: list[dict[str, Any]] = []
    value = (value or "").strip()
    if value and _GENE_SHAPE.match(value) and not value[:1].isdigit():
        out.append(cmd("find_proteins", gene=value))
    out.append(cmd("get_server_capabilities"))
    return out


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback.

    Guarantees ``next_commands`` is present on every error envelope (the server's
    documented "on success AND error" contract).
    """
    if tool == "get_protein":
        return protein_not_found_recovery(str(arguments.get("accession", "")))
    if tool in _PROTEIN_TOOLS or tool == "get_taxon":
        return [cmd("get_server_capabilities")]
    return [cmd("get_server_capabilities")]


def after_find_proteins(accessions: list[str]) -> list[dict[str, Any]]:
    """After resolving proteins: fetch the first entry's detail."""
    if not accessions:
        return [cmd("search_example_queries", text="protein")]
    return [
        cmd("get_protein", accession=accessions[0]),
        cmd("get_protein_diseases", accession=accessions[0]),
    ]


def after_get_protein(accession: str) -> list[dict[str, Any]]:
    """After an entry summary: the two highest-value sub-resources (token diet)."""
    return [
        cmd("get_protein_sequence", accession=accession),
        cmd("get_protein_features", accession=accession),
    ]


def after_entry_subresource(
    accession: str, current: str, count: int | None = None
) -> list[dict[str, Any]]:
    """Chain back to entry context from any annotation tool (never a dead end).

    When ``count == 0`` (the tool returned nothing for this entry), point home
    rather than at a sibling that is likely also empty — content-aware chaining.
    """
    if count == 0:
        return [
            cmd("get_protein", accession=accession),
            cmd("get_server_capabilities"),
        ]
    chain = [
        cmd("get_protein_variants", accession=accession),
        cmd("get_protein_diseases", accession=accession),
        cmd("get_protein_features", accession=accession),
        cmd("get_protein", accession=accession),
    ]
    return [c for c in chain if c["arguments"].get("accession") and c["tool"] != current][:2]


def after_get_example(query: str | None) -> list[dict[str, Any]]:
    """After fetching an example: offer to run it."""
    if not query:
        return []
    return [cmd("run_sparql_query", query=query)]
