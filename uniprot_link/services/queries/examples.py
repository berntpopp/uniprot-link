"""SPARQL builders for the curated example-query catalog (sparql-examples graph)."""

from __future__ import annotations

from uniprot_link.services.constants import SPARQL_EXAMPLES_GRAPH, prefix_block
from uniprot_link.services.queries.validation import escape_literal, validate_example_iri


def search_example_queries(text: str | None = None, limit: int = 25) -> str:
    """Build a SELECT over the curated example catalog (optional text filter).

    The optional text filter matches each whitespace token against the example's
    comment text OR its keywords. Both are multi-valued per example, so the match
    is applied AFTER grouping, via a ``HAVING`` over the ``GROUP_CONCAT`` of
    comments and keywords. EXISTS is deliberately avoided: the QLever endpoint
    (``constants.py``) rejects EXISTS in expression position (BIND/FILTER) with
    HTTP 400 -- the same constraint proteins.py works around with a
    BOUND-over-OPTIONAL sub-SELECT (see proteins.py:198). Ref:
    https://github.com/ad-freiburg/qlever/wiki/Current-deviations-from-the-SPARQL-1.1-standard
    """
    having = ""
    if text:
        tokens = [escape_literal(t) for t in text.strip().split() if t][:6]
        if tokens:
            clauses = " || ".join(
                f'CONTAINS(LCASE(GROUP_CONCAT(?comment; separator=" ")), LCASE("{t}")) || '
                f'CONTAINS(LCASE(GROUP_CONCAT(?kw; separator=" ")), LCASE("{t}"))'
                for t in tokens
            )
            having = f"HAVING({clauses})\n"
    # GROUP BY ?ex only (Bug 12): an example can carry >1 rdfs:comment AND >1
    # matching rdf:type, which previously produced duplicate rows. ?comment and
    # ?type are collapsed with SAMPLE under distinct aliases (?desc/?qtype -- the
    # SPARQL alias must not reuse an in-scope variable). UniProt-native vs
    # federated ranking is decided in shaping from the example IRI host.
    return f"""{prefix_block()}
SELECT ?ex (SAMPLE(?comment) AS ?desc) (SAMPLE(?type) AS ?qtype)
       (GROUP_CONCAT(DISTINCT ?kw; separator=", ") AS ?keywords)
WHERE {{
  GRAPH <{SPARQL_EXAMPLES_GRAPH}> {{
    ?ex a sh:SPARQLExecutable ; rdfs:comment ?comment .
    OPTIONAL {{ ?ex schema:keywords ?kw }}
    OPTIONAL {{ ?ex a ?type .
               FILTER(?type IN (sh:SPARQLSelectExecutable, sh:SPARQLAskExecutable,
                                sh:SPARQLConstructExecutable)) }}
  }}
}}
GROUP BY ?ex
{having}ORDER BY ?ex
LIMIT {limit}"""


def get_example_query(example_iri: str) -> str:
    """Build a SELECT for a single example's full query text and metadata."""
    # M1: validate IRI components (scheme/host + no IRIREF terminators) before
    # splicing into ``<...>`` -- a scheme prefix check alone allowed break-out.
    iri = f"<{validate_example_iri(example_iri)}>"
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
