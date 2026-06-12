"""SPARQL builders for the UniProt taxonomy graph."""

from __future__ import annotations

from uniprot_link.services.constants import prefix_block
from uniprot_link.services.queries.validation import escape_literal, validate_taxon


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
