"""SPARQL query builders (split by responsibility; see AGENTS.md LoC cap).

Public API is re-exported here so callers keep using
``from uniprot_link.services import queries as Q`` unchanged.
"""

from __future__ import annotations

from uniprot_link.services.queries.examples import (
    get_example_query,
    search_example_queries,
)
from uniprot_link.services.queries.proteins import (
    entry_exists_ask,
    entry_status,
    find_proteins,
    map_identifiers,
    protein_cross_references,
    protein_diseases,
    protein_features,
    protein_go_terms,
    protein_sequence,
    protein_summary,
    protein_variants,
)
from uniprot_link.services.queries.taxonomy import (
    resolve_taxon_by_name,
    taxon_ancestors,
    taxon_core,
)
from uniprot_link.services.queries.validation import (
    clamp_limit,
    classify_sparql_operation,
    escape_literal,
    inject_limit,
    validate_accession,
    validate_taxon,
)

__all__ = [
    "clamp_limit",
    "classify_sparql_operation",
    "entry_exists_ask",
    "entry_status",
    "escape_literal",
    "find_proteins",
    "get_example_query",
    "inject_limit",
    "map_identifiers",
    "protein_cross_references",
    "protein_diseases",
    "protein_features",
    "protein_go_terms",
    "protein_sequence",
    "protein_summary",
    "protein_variants",
    "resolve_taxon_by_name",
    "search_example_queries",
    "taxon_ancestors",
    "taxon_core",
    "validate_accession",
    "validate_taxon",
]
