"""Builders for `_meta.next_commands` entries: `{tool, arguments}` steps."""

from __future__ import annotations

from typing import Any


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def after_find_proteins(accessions: list[str]) -> list[dict[str, Any]]:
    """After resolving proteins: fetch the first entry's detail."""
    if not accessions:
        return [cmd("search_example_queries", text="protein")]
    return [
        cmd("get_protein", accession=accessions[0]),
        cmd("get_protein_diseases", accession=accessions[0]),
    ]


def after_get_protein(accession: str) -> list[dict[str, Any]]:
    """After an entry summary: drill into the common sub-resources."""
    return [
        cmd("get_protein_sequence", accession=accession),
        cmd("get_protein_features", accession=accession),
        cmd("get_protein_diseases", accession=accession),
        cmd("get_protein_cross_references", accession=accession),
    ]


def after_entry_subresource(accession: str, current: str) -> list[dict[str, Any]]:
    """Chain back to entry context from any annotation tool (never a dead end)."""
    chain = [
        cmd("get_protein_variants", accession=accession),
        cmd("get_protein_diseases", accession=accession),
        cmd("get_protein_features", accession=accession),
        cmd("get_protein", accession=accession),
    ]
    return [c for c in chain if c["arguments"].get("accession") and c["tool"] != current][:3]


def after_get_example(query: str | None) -> list[dict[str, Any]]:
    """After fetching an example: offer to run it."""
    if not query:
        return []
    return [cmd("run_sparql_query", query=query)]
