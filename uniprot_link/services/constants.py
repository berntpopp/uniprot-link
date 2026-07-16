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

# Focused primary id-mapping targets (genomic / structural / protein-family
# identifiers). map_identifiers defaults to this set so it is genuinely distinct
# from the exhaustive get_protein_cross_references (which keeps the
# drug/disease-association DBs such as DrugBank, ChEMBL, OpenTargets, DisGeNET).
MAP_IDENTIFIER_DATABASES = [
    "PDB",
    "AlphaFoldDB",
    "Ensembl",
    "RefSeq",
    "GeneID",
    "HGNC",
    "KEGG",
    "OrthoDB",
    "Pfam",
    "InterPro",
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

# Secondary-structure feature keys. Excluded from get_protein_features by default
# (they dominate the payload and are rarely the answer to a domain/region/site
# question); included on request via include_secondary_structure or an explicit
# feature_types filter.
SECONDARY_STRUCTURE_TYPES: frozenset[str] = frozenset({"beta_strand", "helix", "turn"})

# GO top-level roots -> aspect bucket (terms carry no hasOBONamespace here).
GO_ASPECT_ROOTS: dict[str, str] = {
    "GO_0008150": "biological_process",
    "GO_0003674": "molecular_function",
    "GO_0005575": "cellular_component",
}

# ECO evidence-ontology id -> GO three-letter evidence code. UniProt GO
# annotations carry an ECO IRI (e.g. ECO_0000314); these map them via the
# authoritative evidenceontology Default mapping (gaf-eco-mapping-derived.txt).
# The raw ECO id is ALWAYS reported under a term's `evidence` list; only mapped
# ids additionally appear under `evidence_codes` (an unmapped id is therefore
# still visible as its raw ECO id, never silently dropped).
ECO_TO_GO_CODE: dict[str, str] = {
    "ECO_0000314": "IDA",
    "ECO_0000316": "IGI",
    "ECO_0000353": "IPI",
    "ECO_0000315": "IMP",
    "ECO_0000270": "IEP",
    "ECO_0000269": "EXP",
    "ECO_0000250": "ISS",
    "ECO_0000266": "ISO",
    "ECO_0000247": "ISA",
    "ECO_0000255": "ISM",
    "ECO_0000317": "IGC",
    "ECO_0000318": "IBA",
    "ECO_0000319": "IBD",
    "ECO_0000320": "IKR",
    "ECO_0000321": "IRD",
    "ECO_0000245": "RCA",
    "ECO_0000501": "IEA",
    "ECO_0007669": "IEA",
    "ECO_0007005": "HDA",
    "ECO_0007007": "HEP",
    "ECO_0007003": "HGI",
    "ECO_0007001": "HMP",
    "ECO_0006056": "HTP",
    "ECO_0000304": "TAS",
    "ECO_0000303": "NAS",
    "ECO_0000305": "IC",
    "ECO_0000307": "ND",
}


# Curated name -> taxon-id index for model organisms (the overwhelming majority
# of real name lookups). A hit lets get_taxon resolve a name with ZERO network
# round-trips; misses fall through to the endpoint scan. Each taxon_id is the one
# UniProt reviewed entries use, so it feeds find_proteins(organism_taxon=...)
# directly. Records: (scientific_name, common_name|None, rank|None, taxon_id,
# extra_aliases). Verified live against the endpoint on 2026-06-12.
_COMMON_TAXA_RECORDS: tuple[tuple[str, str | None, str | None, str, tuple[str, ...]], ...] = (
    ("Homo sapiens", "Human", "Species", "9606", ("human",)),
    ("Mus musculus", "Mouse", "Species", "10090", ("mouse", "house mouse")),
    ("Rattus norvegicus", "Rat", "Species", "10116", ("rat", "brown rat")),
    ("Bos taurus", "Bovine", "Species", "9913", ("cow", "cattle", "bovine")),
    ("Sus scrofa", "Pig", "Species", "9823", ("pig",)),
    ("Gallus gallus", "Chicken", "Species", "9031", ("chicken",)),
    ("Canis lupus familiaris", "Dog", "Subspecies", "9615", ("dog",)),
    ("Macaca mulatta", "Rhesus macaque", "Species", "9544", ("rhesus macaque", "rhesus monkey")),
    ("Pan troglodytes", "Chimpanzee", "Species", "9598", ("chimpanzee", "chimp")),
    ("Danio rerio", "Zebrafish", "Species", "7955", ("zebrafish",)),
    ("Xenopus tropicalis", "Western clawed frog", "Species", "8364", ("xenopus tropicalis",)),
    ("Drosophila melanogaster", "Fruit fly", "Species", "7227", ("fruit fly", "drosophila")),
    ("Caenorhabditis elegans", None, "Species", "6239", ("c. elegans", "c elegans", "roundworm")),
    (
        "Arabidopsis thaliana",
        "Thale cress",
        "Species",
        "3702",
        ("arabidopsis", "thale cress", "mouse-ear cress"),
    ),
    ("Zea mays", "Maize", "Species", "4577", ("maize", "corn")),
    ("Oryza sativa subsp. japonica", "Rice", None, "39947", ("rice", "oryza sativa")),
    (
        "Saccharomyces cerevisiae (strain ATCC 204508 / S288c)",
        "Baker's yeast",
        "Strain",
        "559292",
        (
            "saccharomyces cerevisiae",
            "baker's yeast",
            "bakers yeast",
            "brewer's yeast",
            "yeast",
            "budding yeast",
        ),
    ),
    (
        "Schizosaccharomyces pombe (strain 972 / ATCC 24843)",
        "Fission yeast",
        "Strain",
        "284812",
        ("schizosaccharomyces pombe", "fission yeast", "s. pombe"),
    ),
    (
        "Escherichia coli (strain K12)",
        "E. coli K-12",
        "Strain",
        "83333",
        ("escherichia coli", "e. coli", "e coli", "ecoli"),
    ),
    (
        "Severe acute respiratory syndrome coronavirus 2",
        "SARS-CoV-2",
        None,
        "2697049",
        ("sars-cov-2", "sars cov 2", "sars-cov2", "2019-ncov", "covid", "covid-19"),
    ),
)

# name (lowercased) -> curated record dict (taxon_id, scientific_name, [common_name], [rank]).
COMMON_TAXA: dict[str, dict[str, str]] = {}
for _sci, _common, _rank, _tid, _aliases in _COMMON_TAXA_RECORDS:
    _record: dict[str, str] = {"taxon_id": _tid, "scientific_name": _sci}
    if _common:
        _record["common_name"] = _common
    if _rank:
        _record["rank"] = _rank
    for _name in (_sci, _common, *_aliases):
        if _name:
            COMMON_TAXA[_name.lower()] = _record


def lookup_common_taxon(name: str) -> dict[str, str] | None:
    """Return a curated taxon record for a common organism name, else ``None``."""
    return COMMON_TAXA.get(name.strip().lower())


# Average isotopic residue masses (Da) -- standard ExPASy/UniProt values. The sum
# of residue masses plus one water (a peptide bond releases water) gives the
# average molecular mass UniProt reports as up:mass. Used to derive mass for
# non-canonical isoforms, which carry a sequence but no up:mass triple.
AVERAGE_RESIDUE_MASS: dict[str, float] = {
    "A": 71.0788,
    "R": 156.1875,
    "N": 114.1038,
    "D": 115.0886,
    "C": 103.1388,
    "E": 129.1155,
    "Q": 128.1307,
    "G": 57.0519,
    "H": 137.1411,
    "I": 113.1594,
    "L": 113.1594,
    "K": 128.1741,
    "M": 131.1926,
    "F": 147.1766,
    "P": 97.1167,
    "S": 87.0782,
    "T": 101.1051,
    "W": 186.2132,
    "Y": 163.1760,
    "V": 99.1326,
    "U": 150.0388,
    "O": 237.3018,
}
WATER_MASS = 18.01524
