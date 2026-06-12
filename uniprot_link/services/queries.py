"""SPARQL query builders and input validation for uniprot-link.

Every builder returns a complete query string (prefix block + body). User
input is validated and escaped before interpolation: accessions/taxa are
pattern-checked, and free-text values are escaped for safe inclusion in SPARQL
string literals.
"""

from __future__ import annotations

import re

from uniprot_link.exceptions import InvalidInputError
from uniprot_link.services.constants import (
    FEATURE_TYPES,
    SPARQL_EXAMPLES_GRAPH,
    prefix_block,
)

_ACCESSION_RE = re.compile(r"^[A-Z0-9]{6,10}(-\d+)?$", re.IGNORECASE)
_TAXON_RE = re.compile(r"^\d+$")
_SELECT_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_COMMENT_RE = re.compile(r"#[^\n]*")
_PREFIX_RE = re.compile(r"^\s*(?:PREFIX\s+[^:]*:\s*<[^>]*>|BASE\s*<[^>]*>)\s*", re.IGNORECASE)
_READ_OPS = {"SELECT", "ASK", "CONSTRUCT", "DESCRIBE"}
_WRITE_OPS = {"INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP", "ADD", "MOVE", "COPY", "WITH"}


def escape_literal(value: str) -> str:
    """Escape a string for safe use inside a SPARQL double-quoted literal."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def validate_accession(accession: str) -> str:
    """Validate and normalise a UniProtKB accession (uppercased)."""
    acc = accession.strip().upper()
    if not _ACCESSION_RE.match(acc):
        raise InvalidInputError(
            f"'{accession}' is not a valid UniProtKB accession "
            "(e.g. P05067, P38398, or an isoform like P05067-2).",
            field="accession",
        )
    return acc


def validate_taxon(taxon_id: str | int) -> str:
    """Validate an NCBI taxon id (digits only)."""
    tid = str(taxon_id).strip()
    if not _TAXON_RE.match(tid):
        raise InvalidInputError(
            f"'{taxon_id}' is not a valid NCBI taxon id (digits only, e.g. 9606).",
            field="taxon_id",
        )
    return tid


def clamp_limit(limit: int, *, default: int, maximum: int) -> int:
    """Clamp a requested LIMIT to ``[1, maximum]`` (falling back to ``default``)."""
    if limit is None or limit <= 0:
        limit = default
    return min(limit, maximum)


def inject_limit(query: str, *, default: int, maximum: int) -> tuple[str, bool]:
    """Ensure a SELECT query carries a LIMIT; return ``(query, was_injected)``.

    Existing LIMITs are left untouched (the endpoint still enforces them). Only
    SELECT queries without a LIMIT get one appended. ASK/CONSTRUCT/DESCRIBE are
    returned unchanged.
    """
    lowered = query.lower()
    if "select" not in lowered:
        return query, False
    if _SELECT_LIMIT_RE.search(query):
        return query, False
    return f"{query.rstrip().rstrip(';')}\nLIMIT {min(default, maximum)}", True


def classify_sparql_operation(query: str) -> str:
    """Return the leading query form; raise InvalidInputError on UPDATE/write forms.

    Detection keys on the first significant keyword after comments and PREFIX/BASE
    declarations, never a substring match anywhere — so a SELECT containing the
    literal "insert" is unaffected. Unknown leading tokens pass through (the
    endpoint will return a 400 -> query_syntax_error).

    This is a UX guard (clean invalid_input vs opaque internal_error), not a
    security boundary — the endpoint is read-only regardless. Limitation: a ``#``
    inside a same-line IRI fragment is treated as a comment, so a write whose verb
    shares a physical line with a ``<...#frag>`` IRI may classify as unknown and be
    rejected by the endpoint instead; the conventional one-declaration-per-line
    form is always caught here.
    """
    stripped = _COMMENT_RE.sub("", query)
    while True:
        new = _PREFIX_RE.sub("", stripped, count=1)
        if new == stripped:
            break
        stripped = new
    token = (stripped.strip().split(None, 1) or [""])[0].upper()
    if token in _READ_OPS:
        return token
    if token in _WRITE_OPS:
        raise InvalidInputError(
            "read-only: only SELECT/ASK/CONSTRUCT/DESCRIBE queries are allowed.",
            field="query",
        )
    return token  # unknown -> let the endpoint return a 400 (query_syntax_error)


# --------------------------------------------------------------------------
# Protein queries
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# Taxonomy queries
# --------------------------------------------------------------------------


def taxon_core(taxon_id: str | int) -> str:
    """Build a SELECT for a taxon's own names and rank (one row)."""
    tid = validate_taxon(taxon_id)
    return f"""{prefix_block()}
SELECT ?scientificName ?commonName ?rank
WHERE {{
  taxon:{tid} up:scientificName ?scientificName .
  OPTIONAL {{ taxon:{tid} up:commonName ?commonName }}
  OPTIONAL {{ taxon:{tid} up:rank ?rank }}
}}
LIMIT 1"""


def taxon_ancestors(taxon_id: str | int) -> str:
    """Build a depth-ranked ancestor SELECT (depth 0 = direct parent).

    UniProt asserts ``rdfs:subClassOf`` to the full ancestor closure, so the
    direct parent is the minimal element: the ancestor with no closure member
    between it and the taxon. ``COUNT(?between)`` ranks the chain species->root.
    """
    tid = validate_taxon(taxon_id)
    return f"""{prefix_block()}
SELECT ?ancestor ?name ?rank (COUNT(DISTINCT ?between) AS ?depth)
WHERE {{
  taxon:{tid} rdfs:subClassOf ?ancestor .
  ?ancestor up:scientificName ?name .
  OPTIONAL {{ ?ancestor up:rank ?rank }}
  OPTIONAL {{ taxon:{tid} rdfs:subClassOf ?between .
             ?between rdfs:subClassOf ?ancestor . FILTER(?between != ?ancestor) }}
}}
GROUP BY ?ancestor ?name ?rank
ORDER BY ?depth"""


def resolve_taxon_by_name(name: str, limit: int = 10) -> str:
    """Build a SELECT resolving a scientific/common name to taxon ids."""
    n = escape_literal(name.strip())
    return f"""{prefix_block()}
SELECT ?taxon ?scientificName ?commonName
WHERE {{
  ?taxon a up:Taxon ; up:scientificName ?scientificName .
  OPTIONAL {{ ?taxon up:commonName ?commonName }}
  FILTER(LCASE(?scientificName) = LCASE("{n}") || CONTAINS(LCASE(?scientificName), LCASE("{n}")))
}}
ORDER BY ?scientificName
LIMIT {limit}"""


# --------------------------------------------------------------------------
# Curated example-query catalog (sparql-examples named graph)
# --------------------------------------------------------------------------


def search_example_queries(text: str | None = None, limit: int = 25) -> str:
    """Build a SELECT over the curated example catalog (optional text filter)."""
    text_filter = ""
    if text:
        tokens = [escape_literal(t) for t in text.strip().split() if t][:6]
        if tokens:
            clauses = " || ".join(
                f'CONTAINS(LCASE(?comment), LCASE("{t}")) || '
                f'EXISTS {{ ?ex schema:keywords ?k2 . FILTER(CONTAINS(LCASE(?k2), LCASE("{t}"))) }}'
                for t in tokens
            )
            text_filter = f"    FILTER({clauses})\n"
    return f"""{prefix_block()}
SELECT ?ex ?comment ?type
       (GROUP_CONCAT(DISTINCT ?kw; separator=", ") AS ?keywords)
WHERE {{
  GRAPH <{SPARQL_EXAMPLES_GRAPH}> {{
    ?ex a sh:SPARQLExecutable ; rdfs:comment ?comment .
    OPTIONAL {{ ?ex schema:keywords ?kw }}
    OPTIONAL {{ ?ex a ?type .
               FILTER(?type IN (sh:SPARQLSelectExecutable, sh:SPARQLAskExecutable,
                                sh:SPARQLConstructExecutable)) }}
{text_filter}  }}
}}
GROUP BY ?ex ?comment ?type
ORDER BY ?ex
LIMIT {limit}"""


def get_example_query(example_iri: str) -> str:
    """Build a SELECT for a single example's full query text and metadata."""
    if not example_iri.startswith(("http://", "https://")):
        raise InvalidInputError(
            "example_id must be a full IRI as returned by search_example_queries.",
            field="example_id",
        )
    iri = f"<{example_iri}>"
    return f"""{prefix_block()}
PREFIX ex_ont: <https://purl.expasy.org/sparql-examples/ontology#>
SELECT ?comment ?query ?type
       (GROUP_CONCAT(DISTINCT ?kw; separator=", ") AS ?keywords)
       (GROUP_CONCAT(DISTINCT ?fed; separator=", ") AS ?federatesWith)
WHERE {{
  GRAPH <{SPARQL_EXAMPLES_GRAPH}> {{
    {iri} rdfs:comment ?comment .
    OPTIONAL {{ {iri} sh:select ?sel }}
    OPTIONAL {{ {iri} sh:ask ?ask }}
    OPTIONAL {{ {iri} sh:construct ?con }}
    BIND(COALESCE(?sel, ?ask, ?con) AS ?query)
    OPTIONAL {{ {iri} schema:keywords ?kw }}
    OPTIONAL {{ {iri} ex_ont:federatesWith ?fed }}
    OPTIONAL {{ {iri} a ?type .
               FILTER(?type IN (sh:SPARQLSelectExecutable, sh:SPARQLAskExecutable,
                                sh:SPARQLConstructExecutable)) }}
  }}
}}
GROUP BY ?comment ?query ?type
LIMIT 1"""
