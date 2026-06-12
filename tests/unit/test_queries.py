"""Unit tests for SPARQL query builders and input validation."""

from __future__ import annotations

import pytest

from uniprot_link.exceptions import InvalidInputError
from uniprot_link.services import queries as q


class TestValidation:
    def test_validate_accession_normalises(self) -> None:
        assert q.validate_accession(" p05067 ") == "P05067"
        assert q.validate_accession("P05067-2") == "P05067-2"

    def test_validate_accession_rejects_garbage(self) -> None:
        with pytest.raises(InvalidInputError):
            q.validate_accession("not-an-accession!")

    def test_validate_accession_rejects_numeric_blob(self) -> None:
        # "999999" is 6 alnum chars but not a real UniProtKB accession; it must
        # fail locally (cheap invalid_input) rather than round-trip for a 404.
        with pytest.raises(InvalidInputError):
            q.validate_accession("999999")
        for good in ["P05067", "P05067-2", "A0A024R1R8", "Q96T60", "P38398"]:
            assert q.validate_accession(good) == good.upper()

    def test_validate_taxon(self) -> None:
        assert q.validate_taxon(9606) == "9606"
        with pytest.raises(InvalidInputError):
            q.validate_taxon("human")

    def test_escape_literal_blocks_injection(self) -> None:
        escaped = q.escape_literal('a"b\\c')
        assert '\\"' in escaped
        assert "\\\\" in escaped


class TestReadOnlyGuard:
    def test_classify_allows_read_forms(self) -> None:
        assert q.classify_sparql_operation("PREFIX up: <x> SELECT * WHERE {?s ?p ?o}") == "SELECT"
        assert q.classify_sparql_operation("# c\nASK { ?s ?p ?o }") == "ASK"
        assert q.classify_sparql_operation('SELECT ?x WHERE { ?x rdfs:label "insert" }') == "SELECT"
        assert (
            q.classify_sparql_operation("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }") == "CONSTRUCT"
        )
        assert q.classify_sparql_operation("DESCRIBE <http://x>") == "DESCRIBE"
        assert q.classify_sparql_operation("select ?s where {?s ?p ?o}") == "SELECT"
        assert q.classify_sparql_operation("\n\n  SELECT ?s WHERE {?s ?p ?o}") == "SELECT"

    def test_classify_rejects_update_forms(self) -> None:
        for bad in (
            "INSERT DATA { <a> <b> <c> }",
            "DELETE WHERE {?s ?p ?o}",
            "WITH <g> DELETE {?s ?p ?o} WHERE {?s ?p ?o}",
            "LOAD <http://x>",
            "CLEAR GRAPH <g>",
            "DROP GRAPH <g>",
        ):
            with pytest.raises(InvalidInputError):
                q.classify_sparql_operation(bad)


class TestProteinSummaryAnchor:
    def test_requires_protein_type_anchor(self) -> None:
        # The required `a up:Protein` anchor is what makes a bogus accession
        # return zero rows (-> not_found) instead of one all-unbound OPTIONAL row.
        query = q.protein_summary("P05067")
        assert "uniprotkb:P05067 a up:Protein ." in query

    def test_anchor_uses_base_accession_for_isoforms(self) -> None:
        query = q.protein_summary("P05067-2")
        assert "uniprotkb:P05067 a up:Protein ." in query


class TestLimitInjection:
    def test_injects_limit_when_absent(self) -> None:
        out, injected = q.inject_limit("SELECT ?s WHERE { ?s ?p ?o }", default=50, maximum=10000)
        assert injected is True
        assert out.endswith("LIMIT 50")

    def test_respects_existing_limit(self) -> None:
        out, injected = q.inject_limit(
            "SELECT ?s WHERE { ?s ?p ?o } LIMIT 5", default=50, maximum=10000
        )
        assert injected is False
        assert "LIMIT 5" in out

    def test_leaves_ask_alone(self) -> None:
        out, injected = q.inject_limit("ASK { ?s ?p ?o }", default=50, maximum=10000)
        assert injected is False
        assert out == "ASK { ?s ?p ?o }"

    def test_clamp_limit(self) -> None:
        assert q.clamp_limit(0, default=25, maximum=200) == 25
        assert q.clamp_limit(9999, default=25, maximum=200) == 200


class TestFindProteins:
    def test_requires_an_anchor(self) -> None:
        with pytest.raises(InvalidInputError):
            q.find_proteins(reviewed=True)

    def test_gene_anchor_builds(self) -> None:
        query = q.find_proteins(gene="BRCA1", organism_taxon=9606)
        assert "up:encodedBy" in query
        assert '"BRCA1"' in query
        assert "taxon:9606" in query
        # Protein-hood is established by the required mnemonic join, not a
        # redundant leading `a up:Protein` scan (dropped for QLever speed).
        assert "up:mnemonic ?mnemonic" in query
        assert "?protein a up:Protein ." not in query

    def test_keyword_kw_id_strips_zeros(self) -> None:
        query = q.find_proteins(keyword="KW-0007", organism_taxon=9606)
        assert "keywords/7>" in query

    def test_ec_number_validation(self) -> None:
        with pytest.raises(InvalidInputError):
            q.find_proteins(ec_number="not.an.ec.x")

    def test_name_contains_pairs_with_taxon(self) -> None:
        query = q.find_proteins(organism_taxon=9606, name_contains="kinase")
        assert "CONTAINS(LCASE(?name)" in query


class TestProteinQueries:
    def test_summary_isolates_aggregation(self) -> None:
        query = q.protein_summary("P05067")
        assert "isoform:P05067-1" in query
        assert "GROUP_CONCAT" in query
        # no top-level GROUP BY (aggregation isolated in a sub-SELECT)
        assert "\nGROUP BY" not in query

    def test_variants_use_explicit_faldo_hops(self) -> None:
        query = q.protein_variants("P38398")
        assert "faldo:begin ?b" in query
        assert "ORDER BY" not in query

    def test_protein_variants_disease_only_requires_skos_related(self) -> None:
        q_only = q.protein_variants("P38398", limit=50, disease_associated_only=True)
        # required join (no OPTIONAL wrapper) when disease_associated_only
        assert "?a skos:related ?d . ?d skos:prefLabel ?disease ." in q_only
        q_all = q.protein_variants("P38398", limit=50)
        assert "OPTIONAL { ?a skos:related ?d . ?d skos:prefLabel ?disease }" in q_all

    def test_features_filter(self) -> None:
        query = q.protein_features("P05067", ["domain", "transmembrane"])
        assert "up:Domain_Extent_Annotation" in query
        assert "up:Transmembrane_Annotation" in query

    def test_features_unknown_type(self) -> None:
        with pytest.raises(InvalidInputError) as exc:
            q.protein_features("P05067", ["not_a_feature"])
        # the full vocabulary is in structured `allowed`, not the capped message
        e = exc.value
        assert e.field == "feature_types"
        assert e.allowed is not None
        assert "domain" in e.allowed
        # the full vocabulary is NOT dumped into the (length-capped) prose
        assert "domain, " not in e.message
        assert len(e.message) < 200

    def test_features_filter_uses_bound_values_join(self) -> None:
        # VALUES binds ?type first (fast); the slow FILTER(?type IN ...) is gone
        query = q.protein_features("P05067", ["domain"])
        assert "VALUES ?type {" in query
        assert "FILTER(?type IN" not in query

    def test_cross_references_db_filter(self) -> None:
        query = q.protein_cross_references("P05067", ["PDB"])
        assert "database/PDB>" in query

    def test_protein_diseases_includes_mim(self) -> None:
        query = q.protein_diseases("P38398")
        assert "?mim" in query
        assert "database:MIM" in query


class TestExampleQueries:
    def test_get_example_requires_iri(self) -> None:
        with pytest.raises(InvalidInputError):
            q.get_example_query("123_not_an_iri")

    def test_search_examples_text_filter(self) -> None:
        query = q.search_example_queries("disease")
        assert "sparql-examples" in query
        assert "disease" in query.lower()

    def test_search_examples_multiword_builds_or_filter(self) -> None:
        query = q.search_example_queries("protein domain architecture")
        # one CONTAINS clause per token, OR-combined
        assert query.count("CONTAINS(LCASE(?comment)") >= 3 or query.count("||") >= 2
