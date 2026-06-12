"""SPARQL builders for UniProtKB protein lookups and searches.

Every builder returns a complete query string (prefix block + body). See
``validation`` for accession/taxon checks and escaping.
"""

from __future__ import annotations

import re

from uniprot_link.exceptions import InvalidInputError
from uniprot_link.services.constants import FEATURE_TYPES, prefix_block
from uniprot_link.services.queries.validation import (
    escape_literal,
    validate_accession,
    validate_taxon,
)


def find_proteins(
    *,
    gene: str | None = None,
    mnemonic: str | None = None,
    ec_number: str | None = None,
    keyword: str | None = None,
    organism_taxon: str | int | None = None,
    organism_name: str | None = None,
    reviewed: bool | None = None,
    name_contains: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> str:
    """Build a SELECT for proteins matching structured filters.

    At least one strong anchor (gene, mnemonic, ec_number, keyword) — or the
    pair (organism_taxon + name_contains) — is required to avoid scanning the
    48-billion-triple UniProtKB graph.
    """
    filters: list[str] = []
    strong = False

    if gene:
        g = escape_literal(gene.strip())
        filters.append(
            f"  ?protein up:encodedBy ?_gene .\n"
            f'  {{ ?_gene skos:prefLabel "{g}" }} UNION {{ ?_gene skos:altLabel "{g}" }}'
        )
        strong = True
    if mnemonic:
        m = escape_literal(mnemonic.strip().upper())
        filters.append(f'  ?protein up:mnemonic "{m}" .')
        strong = True
    if ec_number:
        ec = ec_number.strip()
        if not re.match(r"^\d+(\.\d+){0,3}(\.-)*$", ec):
            raise InvalidInputError(f"'{ec_number}' is not a valid EC number.", field="ec_number")
        filters.append(f"  ?protein up:enzyme <http://purl.uniprot.org/enzyme/{ec}> .")
        strong = True
    if keyword:
        kw = escape_literal(keyword.strip())
        kw_match = re.match(r"^KW-?(\d+)$", keyword.strip(), re.IGNORECASE)
        if kw_match:
            # Keyword IRIs use the integer id with leading zeros stripped:
            # KW-0007 (Acetylation) -> .../keywords/7.
            kw_id = int(kw_match.group(1))
            filters.append(
                f"  ?protein up:classifiedWith <http://purl.uniprot.org/keywords/{kw_id}> ."
            )
        else:
            filters.append(f'  ?protein up:classifiedWith ?_kw . ?_kw skos:prefLabel "{kw}" .')
        strong = True
    if organism_taxon is not None:
        tid = validate_taxon(organism_taxon)
        filters.append(f"  ?protein up:organism taxon:{tid} .")
    if organism_name:
        on = escape_literal(organism_name.strip())
        filters.append(
            f"  ?protein up:organism ?_org . ?_org up:scientificName ?_osn ."
            f' FILTER(CONTAINS(LCASE(?_osn), LCASE("{on}")))'
        )
    if reviewed is not None:
        filters.append(f"  ?protein up:reviewed {str(reviewed).lower()} .")

    has_pair_anchor = organism_taxon is not None and bool(name_contains)
    if not strong and not has_pair_anchor:
        raise InvalidInputError(
            "find_proteins needs at least one of: gene, mnemonic, ec_number, keyword "
            "(or organism_taxon together with name_contains). For broad text search use "
            "sparql_query or search_example_queries.",
            field="filters",
        )

    # `name` is OPTIONAL unless name_contains requires filtering on it. Keeping
    # universally-present fields (mnemonic/reviewed/organism) as REQUIRED joins
    # lets QLever do bound joins instead of materialising large OPTIONAL
    # relations, which is the difference between ~5s and a 45s timeout.
    if name_contains:
        nc = escape_literal(name_contains.strip())
        name_pattern = (
            "  ?protein up:recommendedName/up:fullName ?name .\n"
            f'  FILTER(CONTAINS(LCASE(?name), LCASE("{nc}")))'
        )
    else:
        name_pattern = "  OPTIONAL { ?protein up:recommendedName/up:fullName ?name }"

    # No leading `?protein a up:Protein` anchor: it is a 48-billion-triple scan
    # that QLever must plan around, and it is redundant — the required
    # mnemonic/reviewed/organism (and any encodedBy) joins already imply
    # protein-hood. Leading with the selective filter keeps the join bound.
    body = "\n".join(filters)
    return f"""{prefix_block()}
SELECT ?protein ?mnemonic ?reviewed ?name ?taxid ?organism
WHERE {{
{body}
  ?protein up:mnemonic ?mnemonic ;
           up:reviewed ?reviewed ;
           up:organism ?taxid .
  ?taxid up:scientificName ?organism .
{name_pattern}
}}
ORDER BY DESC(?reviewed) ?mnemonic
LIMIT {limit} OFFSET {offset}"""


def entry_exists_ask(accession: str) -> str:
    """Build an ASK that is true iff the UniProtKB entry exists."""
    base = validate_accession(accession).split("-")[0]
    return f"""{prefix_block()}
ASK {{ uniprotkb:{base} a up:Protein }}"""


def protein_summary(accession: str) -> str:
    """Build a SELECT for a single entry's core summary.

    Anchors directly on the entry IRI and isolates gene aggregation in a
    sub-SELECT so the outer query needs no GROUP BY over large literals (which
    otherwise times out on QLever).
    """
    acc = validate_accession(accession)
    base = acc.split("-")[0]
    return f"""{prefix_block()}
SELECT ?mnemonic ?reviewed ?fullName ?shortName ?existence ?genes
       ?organism ?commonName ?taxid ?mass ?length ?function ?created ?modified
WHERE {{
  uniprotkb:{base} a up:Protein .
  OPTIONAL {{ uniprotkb:{base} up:mnemonic ?mnemonic }}
  OPTIONAL {{ uniprotkb:{base} up:reviewed ?reviewed }}
  OPTIONAL {{ uniprotkb:{base} up:recommendedName ?rn .
             OPTIONAL {{ ?rn up:fullName ?fullName }}
             OPTIONAL {{ ?rn up:shortName ?shortName }} }}
  OPTIONAL {{ uniprotkb:{base} up:existence ?existence }}
  OPTIONAL {{ uniprotkb:{base} up:organism ?taxid .
             OPTIONAL {{ ?taxid up:scientificName ?organism }}
             OPTIONAL {{ ?taxid up:commonName ?commonName }} }}
  OPTIONAL {{ uniprotkb:{base} up:created ?created }}
  OPTIONAL {{ uniprotkb:{base} up:modified ?modified }}
  OPTIONAL {{ isoform:{base}-1 up:mass ?mass ; rdf:value ?seqval .
             BIND(STRLEN(?seqval) AS ?length) }}
  OPTIONAL {{ uniprotkb:{base} up:annotation ?fa .
             ?fa a up:Function_Annotation ; rdfs:comment ?function }}
  OPTIONAL {{ SELECT (GROUP_CONCAT(DISTINCT ?g; separator=", ") AS ?genes)
             WHERE {{ uniprotkb:{base} up:encodedBy/skos:prefLabel ?g }} }}
}}
LIMIT 1"""


def protein_sequence(accession: str) -> str:
    """Build a SELECT for an entry's sequence(s) (canonical + isoforms)."""
    acc = validate_accession(accession)
    return f"""{prefix_block()}
SELECT ?isoform (STRLEN(?value) AS ?length) ?mass ?value
WHERE {{
  uniprotkb:{acc} up:sequence ?isoform .
  ?isoform rdf:value ?value .
  OPTIONAL {{ ?isoform up:mass ?mass }}
}}
ORDER BY ?isoform"""


def protein_features(accession: str, feature_types: list[str] | None = None) -> str:
    """Build a SELECT for sequence features with FALDO coordinates.

    A ``feature_types`` filter binds ``?type`` via ``VALUES`` *before* matching
    ``?a a ?type`` — a bound join. The earlier ``?a a ?type . FILTER(?type IN …)``
    form materialised every annotation's rdf:type (including superclasses) and
    was ~5x slower on QLever (e.g. 11s vs 2s for a single domain filter).
    """
    acc = validate_accession(accession)
    if feature_types:
        classes: list[str] = []
        for ft in feature_types:
            cls = FEATURE_TYPES.get(ft.strip().lower())
            if cls is None:
                # Echo the accepted keys inline so the agent self-corrects
                # without a separate capabilities round trip.
                allowed = ", ".join(sorted(FEATURE_TYPES))
                raise InvalidInputError(
                    f"Unknown feature type '{ft}'. Allowed: {allowed}.",
                    field="feature_types",
                )
            classes.append(f"up:{cls}")
        type_block = f"  VALUES ?type {{ {' '.join(classes)} }}\n  ?a a ?type .\n"
        type_guard = ""
    else:
        type_block = "  ?a a ?type .\n"
        type_guard = '\n  FILTER(STRSTARTS(STR(?type), "http://purl.uniprot.org/core/"))'
    return f"""{prefix_block()}
SELECT ?type ?begin ?end ?comment
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
{type_block}  ?a up:range ?r .
  ?r faldo:begin/faldo:position ?begin .
  ?r faldo:end/faldo:position ?end .
  OPTIONAL {{ ?a rdfs:comment ?comment }}{type_guard}
}}
ORDER BY ?begin
LIMIT 1000"""


def protein_variants(
    accession: str, limit: int = 200, disease_associated_only: bool = False
) -> str:
    """Build a SELECT for natural-variant annotations.

    The FALDO range is a REQUIRED join with explicit hops (not a property path
    inside OPTIONAL) and there is no ORDER BY — both avoid QLever timeouts on
    heavily-variant entries. Rows are sorted disease-associated-first, then by
    position, during shaping.

    When ``disease_associated_only`` is True the ``skos:related`` disease join is
    REQUIRED rather than OPTIONAL, returning only disease-linked variants (a small
    set that fits any limit). ``disease_block`` is interpolated once, so it must
    already carry literal single braces, not the doubled f-string form.
    """
    acc = validate_accession(accession).split("-")[0]
    if disease_associated_only:
        disease_block = "  ?a skos:related ?d . ?d skos:prefLabel ?disease ."
    else:
        disease_block = "  OPTIONAL { ?a skos:related ?d . ?d skos:prefLabel ?disease }"
    return f"""{prefix_block()}
SELECT ?begin ?end ?substitution ?wildType ?comment ?disease ?dbsnp
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
  ?a a up:Natural_Variant_Annotation ; up:range ?r .
  ?r faldo:begin ?b . ?b faldo:position ?begin .
  ?r faldo:end ?e . ?e faldo:position ?end .
  OPTIONAL {{ ?a up:substitution ?substitution }}
  OPTIONAL {{ ?a rdfs:comment ?comment }}
{disease_block}
  OPTIONAL {{ ?a rdfs:seeAlso ?dbsnp . ?dbsnp up:database database:dbSNP }}
  OPTIONAL {{ isoform:{acc}-1 rdf:value ?seq }}
  BIND(SUBSTR(?seq, ?begin, 1 + ?end - ?begin) AS ?wildType)
}}
LIMIT {limit}"""


def protein_diseases(accession: str) -> str:
    """Build a SELECT for disease annotations linked to an entry (with MIM)."""
    acc = validate_accession(accession).split("-")[0]
    return f"""{prefix_block()}
SELECT ?disease ?diseaseLabel ?comment ?mim
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
  ?a a up:Disease_Annotation .
  OPTIONAL {{ ?a rdfs:comment ?comment }}
  OPTIONAL {{
    ?a up:disease ?disease .
    ?disease skos:prefLabel ?diseaseLabel .
    OPTIONAL {{ ?disease rdfs:seeAlso ?mim . ?mim up:database database:MIM }}
  }}
}}
ORDER BY ?diseaseLabel"""


def protein_cross_references(accession: str, databases: list[str] | None = None) -> str:
    """Build a SELECT for cross-references grouped by database."""
    acc = validate_accession(accession)
    db_filter = ""
    if databases:
        values = " ".join(
            f"<http://purl.uniprot.org/database/{escape_literal(d.strip())}>" for d in databases
        )
        db_filter = f"  VALUES ?db {{ {values} }}\n"
    return f"""{prefix_block()}
SELECT ?db ?database ?xref
WHERE {{
  uniprotkb:{acc} rdfs:seeAlso ?xref .
  ?xref up:database ?db .
{db_filter}  BIND(REPLACE(STR(?db), "^.*/", "") AS ?database)
}}
ORDER BY ?database
LIMIT 2000"""


def protein_go_terms(accession: str) -> str:
    """Build a SELECT for Gene Ontology annotations grouped by aspect root."""
    acc = validate_accession(accession)
    return f"""{prefix_block()}
PREFIX obo: <http://purl.obolibrary.org/obo/>
SELECT ?go ?label ?aspect
WHERE {{
  uniprotkb:{acc} up:classifiedWith ?go .
  FILTER(STRSTARTS(STR(?go), "http://purl.obolibrary.org/obo/GO_"))
  OPTIONAL {{ ?go rdfs:label ?label }}
  OPTIONAL {{ ?go rdfs:subClassOf ?aspect .
             FILTER(?aspect IN (obo:GO_0008150, obo:GO_0003674, obo:GO_0005575)) }}
}}
ORDER BY ?aspect ?label
LIMIT 1000"""


def map_identifiers(accession: str, databases: list[str] | None = None) -> str:
    """Alias of cross-reference retrieval, optionally scoped to databases."""
    return protein_cross_references(accession, databases)
