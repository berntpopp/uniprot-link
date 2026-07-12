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
    "- Discovery: find_proteins(gene_symbol=, organism_taxon=, reviewed=, keyword=, "
    "ec_number=, mnemonic=, name_contains=) searches UniProtKB; organism_taxon is an "
    "NCBI taxon id (e.g. 9606) and common synonyms (taxon/organism/organism_id) are "
    "accepted as aliases; gene_symbol accepts gene/symbol as aliases; name_contains "
    "matches per word (any order). Resolve organism names to a taxon id with "
    "get_taxon. For several genes at once use find_proteins_batch(gene_symbols=[...]) "
    "-- it resolves them concurrently in one call and reports unresolved_genes.\n"
    "- Identifier mapping: resolve_identifiers links an accession to PDB, Ensembl, "
    "RefSeq, HGNC, and other databases.\n"
    "- Grounding: get_protein_diseases returns both a clinical `definition` and the "
    "entry `involvement`; get_protein_go_terms carries ECO `evidence` + GO "
    "`evidence_codes`. Typed tools return structured output (outputSchema).\n"
    "- SPARQL power use: search_sparql_query accepts bounded SELECT/ASK queries only; "
    "SERVICE federation and CONSTRUCT/DESCRIBE are rejected, and a LIMIT is auto-injected "
    "into unbounded SELECTs. search_example_queries / get_example_query expose 126 "
    "curated, ready-to-run example queries to learn the data model.\n"
    "- Verbosity: get_protein / get_protein_sequence / get_protein_cross_references "
    "/ resolve_identifiers take response_mode (minimal | compact | standard | full, "
    "default compact); full restores raw IRIs. get_protein_sequence compact returns "
    "a first/last-30-residue preview; use standard/full for the complete sequence.\n"
    "- Read-only: every tool is read-only; search_sparql_query rejects write/UPDATE "
    "queries as invalid_input. Nonexistent accessions/taxa return not_found.\n"
    "- Chaining: every response carries _meta.next_commands, a ready-to-call list "
    "of {tool, arguments} steps, on success AND error. A wrong argument name/type "
    "returns the same structured invalid_input envelope (valid names + a "
    "did-you-mean), never a raw error. Discovery: get_server_capabilities "
    "(detail='summary' default, 'full' for named graphs/prefixes), or read "
    "uniprot://tools (signatures) / uniprot://capabilities (full). "
    f"{RESEARCH_USE_NOTICE}"
)

UNIPROT_USAGE_NOTES = (
    "Start from an accession with get_protein, or resolve one with find_proteins "
    "(needs a gene/keyword/EC anchor, optionally an organism taxon id) or get_taxon. "
    "Then drill in with the get_protein_* tools. For anything the typed tools do not "
    "cover, write SPARQL with search_sparql_query — seed it from search_example_queries. "
    "Follow _meta.next_commands to advance without guessing the next tool."
)

UNIPROT_REFERENCE_NOTES = (
    "Error codes: invalid_input, not_found, query_syntax_error, query_timeout, "
    "rate_limited, upstream_unavailable, internal_error. The endpoint is a "
    "QLever-backed SPARQL 1.1 service over 21 named graphs (~232B triples). "
    "Avoid unbounded scans: anchor queries on an accession, gene, organism, or "
    "keyword. Result formats for search_sparql_query: json, xml, csv, tsv (result sets) "
    "only (SELECT/ASK result sets)."
)

RECOMMENDED_CITATION = (
    "The UniProt Consortium. UniProt: the Universal Protein Knowledgebase in 2025. "
    "Nucleic Acids Res. 2025;53(D1):D609-D617. doi:10.1093/nar/gkae1010"
)

UNIPROT_PREFIX_NOTE = (
    "Canonical PREFIX block for hand-written queries against the UniProt endpoint."
)
