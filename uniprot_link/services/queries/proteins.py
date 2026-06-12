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
    count: bool = False,
) -> str:
    """Build a SELECT for proteins matching structured filters.

    At least one strong anchor (gene, mnemonic, ec_number, keyword) — or the
    pair (organism_taxon + name_contains) — is required to avoid scanning the
    48-billion-triple UniProtKB graph.

    ``count=True`` returns ``SELECT (COUNT(DISTINCT ?protein) AS ?n)`` with no
    ORDER BY/LIMIT — the cheap reviewed-segment size probe for the service's
    two-phase pagination.

    There is **no SPARQL ORDER BY**: a pre-LIMIT ``ORDER BY DESC(?reviewed)
    ?mnemonic`` sorted the full match set and was the find_proteins latency
    hotspot (8.7s -> ~3s on broad keywords, verified live). The service applies
    reviewed-first ranking via two bound segment queries and sorts each returned
    page by mnemonic in Python (``shaping``), per the AGENTS.md QLever discipline.
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
            "run_sparql_query or search_example_queries.",
            field="filters",
        )

    # `name` is OPTIONAL unless name_contains requires filtering on it. Keeping
    # universally-present fields (mnemonic/reviewed/organism) as REQUIRED joins
    # lets QLever do bound joins instead of materialising large OPTIONAL
    # relations, which is the difference between ~5s and a 45s timeout.
    #
    # F6: multi-word name_contains is matched per-WORD (each token must appear
    # somewhere in the name), not as one literal substring. "polynucleotide
    # kinase" therefore matches "Bifunctional polynucleotide phosphatase/kinase".
    # Single-word input is unchanged. Capped at 6 tokens to bound the query.
    name_tokens = [escape_literal(t) for t in name_contains.split()][:6] if name_contains else []
    if name_tokens:
        conditions = " && ".join(f'CONTAINS(LCASE(?name), LCASE("{t}"))' for t in name_tokens)
        name_pattern = f"  ?protein up:recommendedName/up:fullName ?name .\n  FILTER({conditions})"
    else:
        name_pattern = "  OPTIONAL { ?protein up:recommendedName/up:fullName ?name }"

    # No leading `?protein a up:Protein` anchor: it is a 48-billion-triple scan
    # that QLever must plan around, and it is redundant — the required
    # mnemonic/reviewed/organism (and any encodedBy) joins already imply
    # protein-hood. Leading with the selective filter keeps the join bound.
    body = "\n".join(filters)
    if count:
        # Include the name-filter join only when name_contains is the anchor
        # (the OPTIONAL name otherwise does not affect the count).
        name_join = name_pattern if name_contains else ""
        return f"""{prefix_block()}
SELECT (COUNT(DISTINCT ?protein) AS ?n)
WHERE {{
{body}
  ?protein up:mnemonic ?mnemonic ;
           up:reviewed ?reviewed ;
           up:organism ?taxid .
{name_join}
}}"""
    # No ORDER BY: the page is bound + LIMITed cheaply, then sorted in Python.
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
LIMIT {limit} OFFSET {offset}"""


def entry_status(accession: str) -> str:
    """Build a SELECT classifying an entry as active / obsolete / absent.

    0 rows -> absent. A row with ``up:obsolete true`` -> obsolete (with any
    ``up:replacedBy`` accessions). Otherwise active. When the accession carries a
    ``-N`` isoform suffix, an ``EXISTS`` probe reports whether that isoform is
    real (so get_protein can reject a typo'd index, F-ISO). Obsolete entries keep
    ``a up:Protein`` (verified live on Z9Z9Z9 / A0A009K1D9), so the bare existence
    ASK could not distinguish them -- this query can.
    """
    acc = validate_accession(accession)
    base = acc.split("-")[0]
    iso_select = ""
    iso_bind = ""
    if "-" in acc:
        iso_select = " ?isoform_exists"
        iso_bind = (
            f"\n  BIND(EXISTS {{ uniprotkb:{base} up:sequence isoform:{acc} }} AS ?isoform_exists)"
        )
    return f"""{prefix_block()}
SELECT ?obsolete ?replacedBy{iso_select} WHERE {{
  uniprotkb:{base} a up:Protein .
  OPTIONAL {{ uniprotkb:{base} up:obsolete ?obsolete }}
  OPTIONAL {{ uniprotkb:{base} up:replacedBy ?replacedBy }}{iso_bind}
}}"""


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
       ?has_variants ?has_diseases ?has_structure
WHERE {{
  uniprotkb:{base} a up:Protein .
  # Cheap bound EXISTS presence flags (verified ~206 ms live) that drive
  # content-aware next_commands and tell the caller what the entry carries.
  BIND(EXISTS {{ uniprotkb:{base} up:annotation ?_v . ?_v a up:Natural_Variant_Annotation }} AS ?has_variants)
  BIND(EXISTS {{ uniprotkb:{base} up:annotation ?_d . ?_d a up:Disease_Annotation }} AS ?has_diseases)
  BIND(EXISTS {{ uniprotkb:{base} rdfs:seeAlso ?_x . ?_x up:database database:PDB }} AS ?has_structure)
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
    """Build a SELECT for an entry's sequence(s) (canonical + isoforms).

    Anchors on the base entry so an isoform accession (``P05067-2``) still returns
    the full isoform set; the service then selects the requested isoform's specific
    sequence (F2 — anchoring on the isoform IRI returned no rows -> not_found).
    """
    acc = validate_accession(accession).split("-")[0]
    return f"""{prefix_block()}
SELECT ?isoform (STRLEN(?value) AS ?length) ?mass ?value
WHERE {{
  uniprotkb:{acc} up:sequence ?isoform .
  ?isoform rdf:value ?value .
  OPTIONAL {{ ?isoform up:mass ?mass }}
}}
ORDER BY ?isoform"""


def protein_features(
    accession: str, feature_types: list[str] | None = None, limit: int = 1000
) -> str:
    """Build a SELECT for sequence features with FALDO coordinates.

    A ``feature_types`` filter binds ``?type`` via ``VALUES`` *before* matching
    ``?a a ?type`` — a bound join. The earlier ``?a a ?type . FILTER(?type IN …)``
    form materialised every annotation's rdf:type (including superclasses) and
    was ~5x slower on QLever (e.g. 11s vs 2s for a single domain filter).

    ``limit`` only changes the trailing LIMIT integer (not the join shape), so it
    does not alter QLever's plan; the service clamps it to [1, 1000].

    Features are entry-level: an isoform accession (``P05067-2``) is normalised to
    the base entry so the anchor is real (F1 — anchoring on the isoform IRI matched
    no annotations and silently returned 0 features).
    """
    acc = validate_accession(accession).split("-")[0]
    if feature_types:
        classes: list[str] = []
        for ft in feature_types:
            cls = FEATURE_TYPES.get(ft.strip().lower())
            if cls is None:
                # The full allowed list goes in the structured `allowed` field,
                # never the (length-capped) message — so it can never truncate.
                raise InvalidInputError(
                    f"Unknown feature type '{ft}'. See allowed_values "
                    "or call get_server_capabilities (feature_types).",
                    field="feature_types",
                    allowed=sorted(FEATURE_TYPES),
                    hint="feature_types keys are listed in get_server_capabilities.",
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
LIMIT {limit}"""


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


def protein_variants_count(accession: str, disease_associated_only: bool = False) -> str:
    """Build a cheap ``COUNT(DISTINCT ?a)`` of an entry's natural variants.

    Counts the typed annotations directly -- no FALDO range join -- so it is far
    cheaper than the data query and yields the true total for the standardized
    truncation envelope (F5). Runs only when the variants page is truncated.
    """
    acc = validate_accession(accession).split("-")[0]
    disease = "  ?a skos:related ?d .\n" if disease_associated_only else ""
    return f"""{prefix_block()}
SELECT (COUNT(DISTINCT ?a) AS ?n)
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
  ?a a up:Natural_Variant_Annotation .
{disease}}}"""


def protein_diseases(accession: str) -> str:
    """Build a SELECT for disease annotations linked to an entry.

    Two distinct comments are returned: the *annotation* ``rdfs:comment``
    (involvement — "the disease is caused by variants affecting this entry") and
    the linked *disease vocabulary* entry's ``rdfs:comment`` (the clinical
    definition). The disease vocabulary has no ``skos:definition``; the
    definition lives on ``rdfs:comment`` of the ``up:Disease`` resource (verified
    live). Also surfaces the disease ``up:mnemonic`` (e.g. AOA4).
    """
    acc = validate_accession(accession).split("-")[0]
    return f"""{prefix_block()}
SELECT ?disease ?diseaseLabel ?comment ?definition ?mnemonic ?mim
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
  ?a a up:Disease_Annotation .
  OPTIONAL {{ ?a rdfs:comment ?comment }}
  OPTIONAL {{
    ?a up:disease ?disease .
    ?disease skos:prefLabel ?diseaseLabel .
    OPTIONAL {{ ?disease rdfs:comment ?definition }}
    OPTIONAL {{ ?disease up:mnemonic ?mnemonic }}
    OPTIONAL {{ ?disease rdfs:seeAlso ?mim . ?mim up:database database:MIM }}
  }}
}}
ORDER BY ?diseaseLabel"""


def protein_cross_references(accession: str, databases: list[str] | None = None) -> str:
    """Build a SELECT for cross-references grouped by database.

    Cross-references are entry-level: an isoform accession is normalised to the
    base entry (F1-twin — the isoform IRI carries no ``rdfs:seeAlso`` xrefs).
    """
    acc = validate_accession(accession).split("-")[0]
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
    """Build a SELECT for Gene Ontology annotations with ECO evidence.

    Evidence is reified: a statement (subject=entry, predicate=up:classifiedWith,
    object=?go) carries ``up:attribution``/``up:evidence`` to an ECO IRI. The
    evidence join is OPTIONAL so terms without a statement still appear.

    NOTE: aggregation is done in Python (``shape_go_terms``), NOT via SPARQL
    GROUP_CONCAT. A ``GROUP_CONCAT(DISTINCT ?eco)`` over this reified OPTIONAL
    returns empty on QLever (verified live on P04637: GROUP BY drops the
    evidence) — a sharp edge. One row per (term, evidence) is emitted instead;
    the row count stays small (P04637: 216 rows / 173 terms).

    GO annotations are entry-level: an isoform accession is normalised to the base
    entry (F1-twin — the isoform IRI carries no ``up:classifiedWith`` GO terms).
    """
    acc = validate_accession(accession).split("-")[0]
    return f"""{prefix_block()}
PREFIX obo: <http://purl.obolibrary.org/obo/>
SELECT ?go ?label ?aspect ?eco
WHERE {{
  uniprotkb:{acc} up:classifiedWith ?go .
  FILTER(STRSTARTS(STR(?go), "http://purl.obolibrary.org/obo/GO_"))
  OPTIONAL {{ ?go rdfs:label ?label }}
  OPTIONAL {{ ?go rdfs:subClassOf ?aspect .
             FILTER(?aspect IN (obo:GO_0008150, obo:GO_0003674, obo:GO_0005575)) }}
  OPTIONAL {{ ?st rdf:subject uniprotkb:{acc} ; rdf:predicate up:classifiedWith ;
                 rdf:object ?go ; up:attribution ?attr . ?attr up:evidence ?eco }}
}}
ORDER BY ?aspect ?label
LIMIT 2000"""


def map_identifiers(accession: str, databases: list[str] | None = None) -> str:
    """Alias of cross-reference retrieval, optionally scoped to databases."""
    return protein_cross_references(accession, databases)
