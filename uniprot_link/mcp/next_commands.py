"""Builders for `_meta.next_commands` entries: `{tool, arguments}` steps."""

from __future__ import annotations

import re
from typing import Any

from uniprot_link.services.queries.validation import looks_like_accession

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


def looks_like_gene_symbol(value: str) -> bool:
    """True only for a genuine gene-symbol shape (never an accession attempt).

    Distinguishes a gene typed into the accession slot (``BRCA1``, ``G6PD``) from
    a mangled/near-miss accession (``Q96T60XYZ``, ``P05067``) so error recovery
    only suggests find_proteins(gene=...) when it would actually help.
    """
    v = (value or "").strip()
    if not v or not _GENE_SHAPE.match(v):
        return False
    return not looks_like_accession(v)


def protein_not_found_recovery(value: str) -> list[dict[str, Any]]:
    """Recovery for a failed get_protein lookup.

    A genuine gene symbol in the accession slot (``BRCA1``) is redirected to
    find_proteins(gene=...). A mangled/near-miss accession (``Q96T60XYZ``) or a
    digit blob (``999999``) is NOT replayed as a gene -- it points at discovery.
    """
    if looks_like_gene_symbol(value):
        return [cmd("find_proteins", gene=value.strip()), cmd("get_server_capabilities")]
    return [cmd("get_server_capabilities"), cmd("search_example_queries", text="protein")]


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


def after_get_protein(
    accession: str,
    *,
    has_variants: bool = False,
    has_diseases: bool = False,
    has_structure: bool = False,
) -> list[dict[str, Any]]:
    """Suggest sub-resources, content-gated by what the entry actually has.

    Sequence + features are always useful; the annotation tools are offered only
    when the cheap presence flags say there is something to fetch -- avoiding the
    static-suggestion trap (proposing diseases/variants on an entry that has
    none). Trimmed to 3 (token diet).
    """
    chain = [cmd("get_protein_sequence", accession=accession)]
    if has_diseases:
        chain.append(cmd("get_protein_diseases", accession=accession))
    if has_variants:
        chain.append(cmd("get_protein_variants", accession=accession))
    chain.append(cmd("get_protein_features", accession=accession))
    if has_structure:
        chain.append(cmd("get_protein_cross_references", accession=accession))
    return chain[:3]


def after_obsolete_entry(replaced_by: list[str]) -> list[dict[str, Any]]:
    """After an obsolete get_protein: point at the live replacement entries."""
    if not replaced_by:
        return [cmd("get_server_capabilities")]
    return [cmd("get_protein", accession=a) for a in replaced_by[:2]]


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
