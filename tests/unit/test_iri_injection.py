"""M1: IRIREF-injection hardening for SPARQL query builders.

``escape_literal`` guards double-quoted string-literal contexts but NOT ``<...>``
IRIREF contexts. User input spliced into an IRI -- the cross-reference database
name (``proteins.protein_cross_references``) and the curated-example IRI
(``examples.get_example_query``) -- must be validated with IRI-aware validators
before the splice, so a value carrying IRI terminators (``>``, whitespace,
``{}`` ...) cannot break out of the ``<...>`` and inject graph patterns.
"""

from __future__ import annotations

import pytest

from uniprot_link.exceptions import InvalidInputError
from uniprot_link.services import queries as q
from uniprot_link.services.queries.validation import (
    validate_database_name,
    validate_example_iri,
)

# Valid example IRIs drawn from the shaping test corpus (tests/unit/test_shaping.py)
# -- these MUST keep validating so real get_example_query calls still work.
VALID_EXAMPLE_IRIS = [
    "https://sparql.uniprot.org/.well-known/sparql-examples/26",
    "https://sparql.rhea-db.org/.well-known/sparql-examples/114",
]


class TestValidateDatabaseName:
    def test_accepts_real_database_keys(self) -> None:
        for name in ("PDB", "HGNC", "Ensembl", "AlphaFoldDB"):
            assert validate_database_name(name) == name

    @pytest.mark.parametrize(
        "bad",
        [
            "PDB> } OPTIONAL{?s ?p ?o} #",  # IRIREF break-out + graph pattern
            "a/b",
            "a:b",
            "a%20",
            "a@b",
            "",
        ],
    )
    def test_rejects_injection_and_bad_shapes(self, bad: str) -> None:
        with pytest.raises(InvalidInputError):
            validate_database_name(bad)


class TestValidateExampleIri:
    def test_accepts_corpus_iris(self) -> None:
        for iri in VALID_EXAMPLE_IRIS:
            assert validate_example_iri(iri) == iri

    @pytest.mark.parametrize(
        "bad",
        [
            "https://sparql.uniprot.org/26> } OPTIONAL{?s ?p ?o}",  # IRIREF break-out
            "https://sparql.uniprot.org/a}b",  # closing brace
            "https://sparql.uniprot.org/a b",  # space
            "https://sparql.uniprot.org/a\x01b",  # control char
            "ftp://sparql.uniprot.org/26",  # non-http scheme
            "javascript:alert(1)",  # non-http scheme, empty netloc
        ],
    )
    def test_rejects_iri_terminators_and_bad_scheme(self, bad: str) -> None:
        with pytest.raises(InvalidInputError):
            validate_example_iri(bad)


class TestBuildersRejectMaliciousInput:
    def test_cross_references_rejects_injected_database(self) -> None:
        with pytest.raises(InvalidInputError):
            q.protein_cross_references("P05067", ["PDB> } OPTIONAL{?s ?p ?o} #"])

    def test_cross_references_still_builds_for_valid_db(self) -> None:
        query = q.protein_cross_references("P05067", ["PDB"])
        assert "database/PDB>" in query

    def test_get_example_query_rejects_injected_iri(self) -> None:
        malicious = "https://sparql.uniprot.org/26> } OPTIONAL{?s ?p ?o} #"
        with pytest.raises(InvalidInputError):
            q.get_example_query(malicious)

    def test_get_example_query_still_builds_for_valid_iri(self) -> None:
        query = q.get_example_query(VALID_EXAMPLE_IRIS[0])
        assert f"<{VALID_EXAMPLE_IRIS[0]}>" in query
