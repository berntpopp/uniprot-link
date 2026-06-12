"""Static UniProt SPARQL constants: prefixes, named graphs, and release.

Values verified live against ``https://sparql.uniprot.org/sparql`` (release
2026_01, QLever engine) on 2026-06-11.
"""

from __future__ import annotations

# Release the bundled queries and named-graph counts were validated against.
UNIPROT_RELEASE = "2026_01"
SPARQL_EXAMPLES_GRAPH = "https://sparql.uniprot.org/.well-known/sparql-examples"

# Canonical PREFIX block prepended to generated queries and exposed as a
# resource so callers can hand-write compatible SPARQL.
PREFIXES: dict[str, str] = {
    "up": "http://purl.uniprot.org/core/",
    "uniprotkb": "http://purl.uniprot.org/uniprot/",
    "taxon": "http://purl.uniprot.org/taxonomy/",
    "isoform": "http://purl.uniprot.org/isoforms/",
    "keywords": "http://purl.uniprot.org/keywords/",
    "database": "http://purl.uniprot.org/database/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "faldo": "http://biohackathon.org/resource/faldo#",
    "sh": "http://www.w3.org/ns/shacl#",
    "schema": "https://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
}


def prefix_block(*names: str) -> str:
    """Return a ``PREFIX`` declaration block for the named prefixes.

    With no arguments, every known prefix is declared.
    """
    keys = names or tuple(PREFIXES)
    return "\n".join(f"PREFIX {key}: <{PREFIXES[key]}>" for key in keys)


# Named graphs in the default union dataset, with triple counts (2026_01).
NAMED_GRAPHS: list[dict[str, object]] = [
    {
        "name": "uniprot",
        "iri": "http://sparql.uniprot.org/uniprot",
        "triples": 48_498_379_324,
        "description": "UniProtKB protein entries (Swiss-Prot + TrEMBL).",
    },
    {
        "name": "uniparc",
        "iri": "http://sparql.uniprot.org/uniparc",
        "triples": 170_364_674_135,
        "description": "UniParc sequence archive (non-redundant).",
    },
    {
        "name": "uniref",
        "iri": "http://sparql.uniprot.org/uniref",
        "triples": 10_505_042_621,
        "description": "UniRef sequence-similarity clusters.",
    },
    {
        "name": "taxonomy",
        "iri": "http://sparql.uniprot.org/taxonomy",
        "triples": 60_528_740,
        "description": "NCBI/UniProt taxonomy.",
    },
    {
        "name": "proteomes",
        "iri": "http://sparql.uniprot.org/proteomes",
        "triples": 34_947_033,
        "description": "Proteome sets per organism.",
    },
    {
        "name": "citations",
        "iri": "http://sparql.uniprot.org/citations",
        "triples": 31_345_087,
        "description": "Literature citations.",
    },
    {
        "name": "citationmapping",
        "iri": "http://sparql.uniprot.org/citationmapping",
        "triples": 625_510_130,
        "description": "Computationally mapped citations.",
    },
    {
        "name": "diseases",
        "iri": "http://sparql.uniprot.org/diseases",
        "triples": 90_113,
        "description": "UniProt disease vocabulary.",
    },
    {
        "name": "keywords",
        "iri": "http://sparql.uniprot.org/keywords",
        "triples": 13_915,
        "description": "UniProt keyword vocabulary.",
    },
    {
        "name": "locations",
        "iri": "http://sparql.uniprot.org/locations",
        "triples": 6_781,
        "description": "Subcellular location vocabulary.",
    },
    {
        "name": "tissues",
        "iri": "http://sparql.uniprot.org/tissues",
        "triples": 4_113,
        "description": "Tissue vocabulary.",
    },
    {
        "name": "go",
        "iri": "http://sparql.uniprot.org/go",
        "triples": 683_368,
        "description": "Gene Ontology terms.",
    },
    {
        "name": "enzymes",
        "iri": "http://sparql.uniprot.org/enzymes",
        "triples": 181_758,
        "description": "Enzyme (EC) classification.",
    },
    {
        "name": "pathways",
        "iri": "http://sparql.uniprot.org/pathways",
        "triples": 17_823,
        "description": "UniPathway metabolic pathways.",
    },
    {
        "name": "chebi",
        "iri": "http://sparql.uniprot.org/chebi",
        "triples": 3_435_035,
        "description": "ChEBI small-molecule ontology.",
    },
    {
        "name": "rhea",
        "iri": "https://sparql.rhea-db.org/rhea",
        "triples": 2_021_817,
        "description": "Rhea biochemical reactions.",
    },
    {
        "name": "journal",
        "iri": "http://sparql.uniprot.org/journal",
        "triples": 43_537,
        "description": "Journal metadata.",
    },
    {
        "name": "database",
        "iri": "http://sparql.uniprot.org/database",
        "triples": 2_340,
        "description": "Cross-reference database descriptions.",
    },
    {
        "name": "obsolete",
        "iri": "http://sparql.uniprot.org/obsolete",
        "triples": 2_102_648_076,
        "description": "Obsolete / demerged entries.",
    },
    {
        "name": "core",
        "iri": "http://purl.uniprot.org/core",
        "triples": 2_816,
        "description": "UniProt core ontology (the up: vocabulary).",
    },
    {
        "name": "sparql-examples",
        "iri": SPARQL_EXAMPLES_GRAPH,
        "triples": 1_349,
        "description": "Curated, executable example queries (SIB).",
    },
]

# Common UniProtKB cross-reference databases (for map_identifiers hints).
COMMON_XREF_DATABASES = [
    "PDB",
    "AlphaFoldDB",
    "EMBL",
    "RefSeq",
    "Ensembl",
    "GeneID",
    "KEGG",
    "HGNC",
    "MIM",
    "Reactome",
    "STRING",
    "InterPro",
    "Pfam",
    "PROSITE",
    "OrthoDB",
    "GeneCards",
    "OpenTargets",
    "DisGeNET",
    "ChEMBL",
    "DrugBank",
]

# Feature annotation classes commonly requested via get_protein_features.
FEATURE_TYPES: dict[str, str] = {
    "domain": "Domain_Extent_Annotation",
    "region": "Region_Annotation",
    "transmembrane": "Transmembrane_Annotation",
    "intramembrane": "Intramembrane_Annotation",
    "topological_domain": "Topological_Domain_Annotation",
    "binding_site": "Binding_Site_Annotation",
    "active_site": "Active_Site_Annotation",
    "site": "Site_Annotation",
    "motif": "Motif_Annotation",
    "signal_peptide": "Signal_Peptide_Annotation",
    "transit_peptide": "Transit_Peptide_Annotation",
    "chain": "Chain_Annotation",
    "peptide": "Peptide_Annotation",
    "modified_residue": "Modified_Residue_Annotation",
    "glycosylation": "Glycosylation_Annotation",
    "lipidation": "Lipidation_Annotation",
    "disulfide_bond": "Disulfide_Bond_Annotation",
    "cross_link": "Cross-link_Annotation",
    "coiled_coil": "Coiled_Coil_Annotation",
    "compositional_bias": "Compositional_Bias_Annotation",
    "repeat": "Repeat_Annotation",
    "zinc_finger": "Zinc_Finger_Annotation",
    "dna_binding": "DNA_Binding_Annotation",
    "np_binding": "Nucleotide_Binding_Annotation",
    "beta_strand": "Beta_Strand_Annotation",
    "helix": "Helix_Annotation",
    "turn": "Turn_Annotation",
    "mutagenesis": "Mutagenesis_Annotation",
    # Range-bearing classes the unfiltered dump also emits (validated live on
    # Q96T60). Without these, a returned `type` failed to round-trip into the
    # filter vocabulary (Bug 1). Any further unmapped class is surfaced by
    # shaping as `_unmapped:<Class>` so it is visibly non-filterable.
    "natural_variant": "Natural_Variant_Annotation",
    "alternative_sequence": "Alternative_Sequence_Annotation",
    "sequence_conflict": "Sequence_Conflict_Annotation",
}

# Reverse: annotation class local-name -> friendly key (for round-tripping the
# returned `type` back into a valid feature_types filter input).
FEATURE_CLASS_TO_KEY: dict[str, str] = {cls: key for key, cls in FEATURE_TYPES.items()}

# GO top-level roots -> aspect bucket (terms carry no hasOBONamespace here).
GO_ASPECT_ROOTS: dict[str, str] = {
    "GO_0008150": "biological_process",
    "GO_0003674": "molecular_function",
    "GO_0005575": "cellular_component",
}
