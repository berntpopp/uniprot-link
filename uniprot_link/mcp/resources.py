"""Static string resources for MCP instructions and discovery resources."""

from __future__ import annotations

from uniprot_link.services.constants import UNIPROT_RELEASE

RESEARCH_USE_NOTICE = (
    "Research use only; not for clinical decision support, diagnosis, "
    "treatment, or patient management."
)

UNIPROT_SERVER_INSTRUCTIONS = (
    "UniProt-Link grounds protein research in the UniProt SPARQL endpoint "
    f"(release {UNIPROT_RELEASE}).\n"
    "- Entry lookup: get_protein for a UniProtKB accession (e.g. P05067); then "
    "get_protein_sequence / get_protein_features / get_protein_variants / "
    "get_protein_diseases / get_protein_go_terms / get_protein_cross_references.\n"
    "- Discovery: find_proteins searches by gene, organism (taxon id), reviewed, "
    "keyword (KW-id or label), or EC number. Resolve organisms with get_taxon.\n"
    "- Identifier mapping: map_identifiers links an accession to PDB, Ensembl, "
    "RefSeq, HGNC, and other databases.\n"
    "- Grounding: get_protein_diseases returns both a clinical `definition` and the "
    "entry `involvement`; get_protein_go_terms carries ECO `evidence` + GO "
    "`evidence_codes`. Typed tools return structured output (outputSchema).\n"
    "- SPARQL power use: run_sparql_query executes any SPARQL 1.1 query (SELECT/"
    "ASK/CONSTRUCT/DESCRIBE, including SERVICE federation); a LIMIT is auto-injected "
    "into unbounded SELECTs. search_example_queries / get_example_query expose 126 "
    "curated, ready-to-run example queries to learn the data model.\n"
    "- Verbosity: get_protein / get_protein_sequence / get_protein_cross_references "
    "/ map_identifiers take response_mode (minimal | compact | standard | full, "
    "default compact); full restores raw IRIs. get_protein_sequence compact returns "
    "a first/last-30-residue preview; use standard/full for the complete sequence.\n"
    "- Read-only: every tool is read-only; run_sparql_query rejects write/UPDATE "
    "queries as invalid_input. Nonexistent accessions/taxa return not_found.\n"
    "- Chaining: every response carries _meta.next_commands, a ready-to-call list "
    "of {tool, arguments} steps, on success AND error. Discovery: "
    "get_server_capabilities or read uniprot://capabilities. "
    f"{RESEARCH_USE_NOTICE}"
)

UNIPROT_USAGE_NOTES = (
    "Start from an accession with get_protein, or resolve one with find_proteins "
    "(needs a gene/keyword/EC anchor, optionally an organism taxon id) or get_taxon. "
    "Then drill in with the get_protein_* tools. For anything the typed tools do not "
    "cover, write SPARQL with run_sparql_query — seed it from search_example_queries. "
    "Follow _meta.next_commands to advance without guessing the next tool."
)

UNIPROT_REFERENCE_NOTES = (
    "Error codes: invalid_input, not_found, query_syntax_error, query_timeout, "
    "rate_limited, upstream_unavailable, internal_error. The endpoint is a "
    "QLever-backed SPARQL 1.1 service over 21 named graphs (~232B triples). "
    "Avoid unbounded scans: anchor queries on an accession, gene, organism, or "
    "keyword. Result formats for run_sparql_query: json, xml, csv, tsv (result sets) "
    "and turtle, rdfxml, ntriples (CONSTRUCT/DESCRIBE)."
)

RECOMMENDED_CITATION = (
    "The UniProt Consortium. UniProt: the Universal Protein Knowledgebase in 2025. "
    "Nucleic Acids Res. 2025;53(D1):D609-D617. doi:10.1093/nar/gkae1010"
)

UNIPROT_PREFIX_NOTE = (
    "Canonical PREFIX block for hand-written queries against the UniProt endpoint."
)
