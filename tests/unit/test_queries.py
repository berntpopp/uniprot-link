"""Unit tests for SPARQL query builders and input validation."""

from __future__ import annotations

import pytest

from uniprot_link.exceptions import InvalidInputError
from uniprot_link.services import queries as q
from uniprot_link.services.queries import validation as V


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

    def test_classify_rejects_graph_returning_forms(self) -> None:
        for bad in (
            "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
            "DESCRIBE <https://example.org/protein/P05067>",
        ):
            with pytest.raises(InvalidInputError, match="only SELECT and ASK"):
                q.classify_sparql_operation(bad)

    def test_classify_rejects_real_service_at_any_group_depth(self) -> None:
        for bad in (
            "SELECT ?s WHERE { SERVICE <https://evil.example/sparql> { ?s ?p ?o } }",
            "SELECT ?s WHERE { { OPTIONAL { SERVICE ?endpoint { ?s ?p ?o } } } }",
        ):
            with pytest.raises(InvalidInputError, match="SERVICE"):
                q.classify_sparql_operation(bad)

    def test_classify_ignores_service_decoys_in_noncode(self) -> None:
        query = """SELECT ?s WHERE {
            ?s ?p "SERVICE <https://example.org/sparql>" .
            # SERVICE <https://example.org/sparql> { ?s ?p ?o }
            BIND(<https://example.org/SERVICE> AS ?iri)
        }"""
        assert q.classify_sparql_operation(query) == "SELECT"

    def test_classify_does_not_mistake_service_prefix_for_clause(self) -> None:
        query = "PREFIX service: <https://example.org/vocab/> SELECT ?s WHERE { ?s service:p ?o }"
        assert q.classify_sparql_operation(query) == "SELECT"


class TestOperationGuardTokenBoundary:
    """R-03 (#29): the operation guard must key on a real keyword TOKEN, not a
    whitespace split.

    SPARQL allows no whitespace between the leading keyword and a following
    ``*``/``{``/``?``/``(``/``<``. The old ``_leading_token`` split on whitespace,
    so ``SELECT*{...}`` tokenised as ``SELECT*{?s`` -- matching neither the
    read-op set (LIMIT injection + SERVICE reject) nor the write/graph set
    (CONSTRUCT/DESCRIBE reject). All three controls fell open at once.
    """

    def test_leading_token_extracts_keyword_on_token_boundary(self) -> None:
        # The exact F-08/R-03 evidence from the issue: no space after the keyword.
        assert V._leading_token("SELECT*{?s ?p ?o}") == "SELECT"
        assert V._leading_token("ASK{ ?s ?p ?o }") == "ASK"
        assert V._leading_token("CONSTRUCT{?a ?b ?c}WHERE{?a ?b ?c}") == "CONSTRUCT"
        assert V._leading_token("DESCRIBE<https://example.org/x>") == "DESCRIBE"
        assert V._leading_token("SELECT(COUNT(*) AS ?n){?s ?p ?o}") == "SELECT"

    def test_leading_token_after_prefix_without_whitespace(self) -> None:
        # A PREFIX block whose IRI is blanked, then a no-whitespace SELECT.
        q_ = "PREFIX up:<http://purl.uniprot.org/core/>SELECT*{?s a up:Protein}"
        assert V._leading_token(q_) == "SELECT"

    def test_inject_limit_bounds_no_whitespace_select(self) -> None:
        # An unbounded ``SELECT*`` must still receive a bounding LIMIT (the old
        # code injected nothing because the token was ``SELECT*{?s``).
        out, injected = q.inject_limit("SELECT*{?s ?p ?o}", default=50, maximum=10000)
        assert injected is True
        assert out.rstrip().endswith("LIMIT 50")

    def test_classify_rejects_no_whitespace_write_and_graph_forms(self) -> None:
        for bad in (
            "CONSTRUCT{?a ?b ?c}WHERE{?a ?b ?c}",
            "DESCRIBE<https://example.org/protein/P05067>",
            "DESCRIBE{?s ?p ?o}",
            "INSERT{?s ?p ?o}WHERE{?s ?p ?o}",
            "DELETE{?s ?p ?o}WHERE{?s ?p ?o}",
        ):
            with pytest.raises(InvalidInputError, match="only SELECT and ASK"):
                q.classify_sparql_operation(bad)

    def test_classify_rejects_service_in_no_whitespace_select(self) -> None:
        # The headline bypass: SERVICE federation smuggled behind ``SELECT*``.
        for bad in (
            "SELECT*{ SERVICE <https://evil.example/sparql> {?s ?p ?o} }",
            "ASK{SERVICE <https://evil.example/sparql>{?s ?p ?o}}",
        ):
            with pytest.raises(InvalidInputError, match="SERVICE"):
                q.classify_sparql_operation(bad)

    def test_classify_rejects_service_in_unknown_leading_form(self) -> None:
        # Fail-closed: a query we cannot classify must NOT fall through to execute
        # while carrying a SERVICE clause. The leading token is unknown here (the
        # query opens with a brace), yet SERVICE must still be rejected.
        with pytest.raises(InvalidInputError, match="SERVICE"):
            q.classify_sparql_operation("{ SERVICE <https://evil.example/sparql> {?s ?p ?o} }")

    def test_classify_read_forms_still_allowed(self) -> None:
        assert q.classify_sparql_operation("SELECT*{?s ?p ?o}") == "SELECT"
        assert q.classify_sparql_operation("ASK{?s ?p ?o}") == "ASK"

    def test_classify_rejects_service_behind_leading_whitespace_variants(self) -> None:
        # A leading tab / newline / SPARQL comment / unicode whitespace / BOM must
        # not desync this classifier from the endpoint: SERVICE is rejected in
        # every case (the read/unknown token still triggers the code-only search).
        for bad in (
            "\tSELECT*{ SERVICE <https://evil.example/s> {?s ?p ?o} }",
            "\n\n  SELECT*{ SERVICE <https://evil.example/s> {?s ?p ?o} }",
            "# leading comment\nSELECT*{ SERVICE <https://evil.example/s> {?s ?p ?o} }",
            "\u00a0SELECT*{ SERVICE <https://evil.example/s> {?s ?p ?o} }",  # NBSP
            "\ufeffSELECT*{ SERVICE <https://evil.example/s> {?s ?p ?o} }",  # BOM
        ):
            with pytest.raises(InvalidInputError, match="SERVICE"):
                q.classify_sparql_operation(bad)

    def test_classify_rejects_construct_behind_leading_bom_and_whitespace(self) -> None:
        # The CONSTRUCT/DESCRIBE reject must also survive a leading BOM / NBSP /
        # tab: the advertised "graph-returning forms are rejected" contract holds.
        for bad in (
            "\ufeffCONSTRUCT{?a ?b ?c}WHERE{?a ?b ?c}",
            "\u00a0DESCRIBE<https://example.org/x>",
            "\tCONSTRUCT{?a ?b ?c}WHERE{?a ?b ?c}",
        ):
            with pytest.raises(InvalidInputError, match="only SELECT and ASK"):
                q.classify_sparql_operation(bad)

    def test_service_decoys_still_ignored_in_no_whitespace_select(self) -> None:
        # A SERVICE token that lives only in a comment / string literal / IRI is
        # still harmless, even for a no-whitespace SELECT.
        query = 'SELECT*{ ?s ?p "SERVICE <https://x/s>" . # SERVICE <https://x/s> { ?s ?p ?o }\n }'
        assert q.classify_sparql_operation(query) == "SELECT"

    def test_comment_terminates_on_lone_cr_not_only_lf(self) -> None:
        # SPARQL 1.1 §19.4: a comment ends on CR *or* LF. If the blanker only
        # stopped on LF, a lone CR would blank the WHOLE tail -- hiding the real
        # SELECT+SERVICE from the guard while the endpoint (which honours CR) still
        # executes it. That is the exact F-08/R-03 desync, resurrected by a `\r`.
        assert q.classify_sparql_operation("# c\rASK{?s ?p ?o}") == "ASK"
        for bad in (
            "# c\rSELECT*{ SERVICE <https://evil.example/s> {?s ?p ?o} }",
            "# c\r\nSELECT*{ SERVICE <https://evil.example/s> {?s ?p ?o} }",  # CRLF
            "PREFIX up:<http://x/>\r# c\rSELECT*{ SERVICE <https://evil.example/s> {?s} }",
        ):
            with pytest.raises(InvalidInputError, match="SERVICE"):
                q.classify_sparql_operation(bad)
        # ...and a graph form hidden behind a lone-CR comment is still rejected.
        with pytest.raises(InvalidInputError, match="only SELECT and ASK"):
            q.classify_sparql_operation("# c\rCONSTRUCT{?a ?b ?c}WHERE{?a ?b ?c}")

    def test_blank_noncode_stops_a_comment_at_cr(self) -> None:
        # A real LIMIT after a lone-CR comment must remain visible (not blanked),
        # so it is neither dropped nor double-injected.
        out, injected = q.inject_limit("SELECT*{?s ?p ?o}# c\rLIMIT 5", default=50, maximum=10000)
        assert injected is False
        assert out.upper().count("LIMIT") == 1
        assert "LIMIT 5" in out


class TestProteinSummaryAnchor:
    def test_requires_protein_type_anchor(self) -> None:
        # The required `a up:Protein` anchor is what makes a bogus accession
        # return zero rows (-> not_found) instead of one all-unbound OPTIONAL row.
        query = q.protein_summary("P05067")
        assert "uniprotkb:P05067 a up:Protein ." in query

    def test_anchor_uses_base_accession_for_isoforms(self) -> None:
        query = q.protein_summary("P05067-2")
        assert "uniprotkb:P05067 a up:Protein ." in query


class TestEntryStatus:
    def test_entry_status_builds_obsolete_aware_gate(self) -> None:
        query = q.entry_status("P05067")
        assert "a up:Protein" in query
        assert "up:obsolete ?obsolete" in query
        assert "up:replacedBy ?replacedBy" in query
        assert "isoform_exists" not in query  # no suffix -> no isoform probe

    def test_entry_status_probes_isoform_when_suffix_present(self) -> None:
        query = q.entry_status("P05067-2")
        assert "isoform:P05067-2" in query
        assert "isoform_exists" in query
        assert "uniprotkb:P05067 a up:Protein" in query  # anchors on base


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


class TestLimitCapBypass:
    """F-08: a SELECT must never reach the endpoint result-unbounded.

    Adversarial cases that the *old* ``inject_limit`` (raw ``\\blimit\\s+\\d+``
    substring scan, existing LIMITs left untouched) failed to bound.
    """

    def test_huge_explicit_limit_is_clamped_to_maximum(self) -> None:
        # An oversized explicit LIMIT must be rewritten DOWN to ``maximum`` --
        # the endpoint must never be asked for 999_999_999 rows.
        out, _ = q.inject_limit(
            "SELECT ?s WHERE { ?s ?p ?o } LIMIT 999999999", default=50, maximum=10000
        )
        assert "999999999" not in out
        assert "LIMIT 10000" in out
        # exactly one LIMIT clause survives (no double-LIMIT syntax error)
        assert out.upper().count("LIMIT") == 1

    def test_limit_hidden_in_comment_does_not_block_injection(self) -> None:
        # The only "LIMIT" is inside a ``#`` comment -> it is NOT a real clause,
        # so a structural LIMIT must still be injected (old code was fooled).
        query = "SELECT ?s WHERE { ?s ?p ?o }\n# LIMIT 5 -- decoy in a comment"
        out, injected = q.inject_limit(query, default=50, maximum=10000)
        assert injected is True
        assert out.rstrip().endswith("LIMIT 50")
        assert "# LIMIT 5" in out  # comment preserved verbatim

    def test_limit_hidden_in_string_literal_does_not_block_injection(self) -> None:
        # The only "LIMIT" is inside a string literal -> not a real clause.
        query = 'SELECT ?s WHERE { ?s ?p ?o . FILTER(?o = "LIMIT 100") }'
        out, injected = q.inject_limit(query, default=50, maximum=10000)
        assert injected is True
        assert out.rstrip().endswith("LIMIT 50")
        assert '"LIMIT 100"' in out  # literal preserved verbatim

    def test_iri_fragment_hash_is_not_mistaken_for_a_comment(self) -> None:
        # A ``#`` inside an ``<...#frag>`` IRI on the same line as a real LIMIT
        # must NOT blank the rest of the line (which would drop the real LIMIT and
        # trigger a spurious second injection -> invalid double-LIMIT).
        query = "SELECT ?o WHERE { <http://ex.org/x#p> ?p ?o } LIMIT 100"
        out, injected = q.inject_limit(query, default=50, maximum=10000)
        assert injected is False
        assert out.upper().count("LIMIT") == 1
        assert "LIMIT 100" in out

    def test_less_than_operator_is_not_mistaken_for_an_iri(self) -> None:
        # A ``<`` comparison operator sharing a line with a real LIMIT must not be
        # swallowed as an IRI (which would blank the trailing LIMIT).
        query = "SELECT ?o WHERE { ?s ?p ?o FILTER(?o < 5) } LIMIT 200"
        out, injected = q.inject_limit(query, default=50, maximum=10000)
        assert injected is False
        assert out.upper().count("LIMIT") == 1
        assert "LIMIT 200" in out

    def test_subquery_limit_still_forces_an_outer_limit(self) -> None:
        # A LIMIT only inside a sub-SELECT does not bound the OUTER result set:
        # an outer LIMIT must still be injected.
        query = "SELECT ?s WHERE { { SELECT ?s WHERE { ?s ?p ?o } LIMIT 5 } }"
        out, injected = q.inject_limit(query, default=50, maximum=10000)
        assert injected is True
        assert out.rstrip().endswith("LIMIT 50")
        assert "LIMIT 5" in out  # the sub-query limit is preserved

    def test_oversized_subquery_limit_is_also_clamped(self) -> None:
        query = "SELECT ?s WHERE { { SELECT ?s WHERE { ?s ?p ?o } LIMIT 88888888 } } LIMIT 3"
        out, _ = q.inject_limit(query, default=50, maximum=10000)
        assert "88888888" not in out
        assert "LIMIT 10000" in out
        assert "LIMIT 3" in out  # small outer limit untouched

    def test_construct_and_describe_are_never_limit_injected(self) -> None:
        # Graph-returning forms are bounded by the streamed HTTP byte cap (F-17),
        # never by a bogus row LIMIT appended to a CONSTRUCT/DESCRIBE.
        c_out, c_inj = q.inject_limit(
            "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", default=50, maximum=10000
        )
        assert c_inj is False
        assert "LIMIT" not in c_out.upper()
        d_out, d_inj = q.inject_limit("DESCRIBE <http://ex.org/x>", default=50, maximum=10000)
        assert d_inj is False
        assert "LIMIT" not in d_out.upper()

    def test_same_line_prefix_iri_fragment_does_not_bypass_limit_injection(self) -> None:
        # F-08 gate: a valid SAME-LINE prefix whose IRI ends in a ``#`` fragment
        # (``rdf-schema#``) must NOT let the ``#`` be read as a comment that
        # swallows the trailing ``SELECT`` -- the query is still a SELECT and MUST
        # get a bounding LIMIT injected (else an unbounded SELECT reaches the
        # endpoint). Old ``_leading_form`` mis-classified this as ``PREFIX``.
        query = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
            "SELECT ?s WHERE { ?s rdfs:label ?l }"
        )
        out, injected = q.inject_limit(query, default=50, maximum=10000)
        assert injected is True
        assert out.rstrip().endswith("LIMIT 50")
        assert "rdf-schema#" in out  # the prefix IRI survives verbatim
        assert out.upper().count("LIMIT") == 1  # exactly the one injected clause

    def test_variable_and_prefixed_limit_tokens_are_not_rewritten(self) -> None:
        # F-08 regression: the LIMIT-clause regex must match only a real SPARQL
        # ``LIMIT`` keyword at a token boundary -- never a variable ``?limit`` or a
        # prefixed name ``ex:limit`` -- so an oversized numeric object literal that
        # follows them survives untouched (old ``\\blimit\\s+\\d+`` rewrote it down
        # to ``maximum``, corrupting the query data).
        var_q = "SELECT ?s WHERE { ?s ?limit 999999999 } LIMIT 5"
        var_out, var_inj = q.inject_limit(var_q, default=50, maximum=10000)
        assert var_inj is False  # the real outer ``LIMIT 5`` already bounds it
        assert "999999999" in var_out  # data literal survives, NOT clamped
        assert "10000" not in var_out
        assert "LIMIT 5" in var_out

        pn_q = "SELECT ?s WHERE { ?s ex:limit 999999999 } LIMIT 5"
        pn_out, pn_inj = q.inject_limit(pn_q, default=50, maximum=10000)
        assert pn_inj is False
        assert "999999999" in pn_out  # data literal survives, NOT clamped
        assert "10000" not in pn_out
        assert "LIMIT 5" in pn_out


class TestFindProteins:
    def test_requires_an_anchor(self) -> None:
        with pytest.raises(InvalidInputError):
            q.find_proteins(reviewed=True)

    def test_anchor_error_names_real_tool(self) -> None:
        with pytest.raises(InvalidInputError) as exc:
            q.find_proteins()
        assert "search_sparql_query" in exc.value.message
        # every "sparql_query" mention is part of "search_sparql_query" (no bare typo)
        assert exc.value.message.count("sparql_query") == exc.value.message.count(
            "search_sparql_query"
        )

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

    def test_gene_symbol_rejects_blank_naming_the_field(self) -> None:
        # gene_symbol is REQUIRED at the tool layer but pydantic allows a blank
        # string. A blank/whitespace value must be rejected with field=gene_symbol
        # -- never spliced in as skos:prefLabel "" (success:true, 0 rows), and never
        # reported against the generic `filters` anchor error (#30 review HIGH).
        for blank in ("", "   ", "\t"):
            with pytest.raises(InvalidInputError) as exc:
                q.find_proteins(gene=blank)
            assert exc.value.field == "gene_symbol"

    def test_mnemonic_filter_rejects_malformed_value(self) -> None:
        # A mnemonic is ``NAME_SPECIES`` (e.g. BRCA1_HUMAN). A malformed value must
        # be rejected with invalid_input naming the field -- never spliced into the
        # query to silently match nothing (the silently-empty filter defect).
        with pytest.raises(InvalidInputError) as exc:
            q.find_proteins(gene="BRCA1", mnemonic="__gf_conformance_no_such_value__")
        assert exc.value.field == "mnemonic"
        # a well-formed mnemonic still builds
        assert 'up:mnemonic "BRCA1_HUMAN"' in q.find_proteins(gene="BRCA1", mnemonic="brca1_human")

    def test_keyword_filter_rejects_malformed_value(self) -> None:
        # keyword is a KW-id (KW-0007) or a keyword label; a value that is neither
        # (leading underscore / control chars) is rejected, not matched to nothing.
        with pytest.raises(InvalidInputError) as exc:
            q.find_proteins(gene="BRCA1", keyword="__gf_conformance_no_such_value__")
        assert exc.value.field == "keyword"
        # a KW-id and a plain label both still build
        assert "keywords/7>" in q.find_proteins(gene="BRCA1", keyword="KW-0007")
        assert 'skos:prefLabel "3D-structure"' in q.find_proteins(
            gene="BRCA1", keyword="3D-structure"
        )

    def test_name_contains_pairs_with_taxon(self) -> None:
        query = q.find_proteins(organism_taxon=9606, name_contains="kinase")
        assert "CONTAINS(LCASE(?name)" in query

    def test_name_contains_single_word_is_one_contains(self) -> None:
        query = q.find_proteins(organism_taxon=9606, name_contains="kinase")
        assert query.count("CONTAINS(LCASE(?name)") == 1
        assert "&&" not in query

    def test_name_contains_multiword_ands_each_token(self) -> None:
        """F6: 'polynucleotide kinase' must match 'polynucleotide phosphatase/kinase'."""
        query = q.find_proteins(organism_taxon=9606, name_contains="polynucleotide kinase")
        # each whitespace token becomes its own CONTAINS, AND-ed together
        assert query.count("CONTAINS(LCASE(?name)") == 2
        assert "&&" in query
        assert 'LCASE("polynucleotide")' in query
        assert 'LCASE("kinase")' in query


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

    def test_protein_variants_count_is_a_cheap_typed_count(self) -> None:
        query = q.protein_variants_count("P38398")
        assert "COUNT(DISTINCT ?a)" in query
        assert "up:Natural_Variant_Annotation" in query
        assert "up:range" not in query  # no expensive FALDO range join
        assert "skos:related" not in query
        disease = q.protein_variants_count("P38398", disease_associated_only=True)
        assert "?a skos:related ?d ." in disease

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

    def test_features_strips_isoform_suffix(self) -> None:
        """F1: an isoform accession must anchor on the BASE entry (features are entry-level)."""
        query = q.protein_features("P05067-2", ["domain"])
        assert "uniprotkb:P05067 up:annotation" in query
        assert "P05067-2" not in query

    def test_cross_references_strips_isoform_suffix(self) -> None:
        """F1-twin: xref/map must anchor on the BASE entry for an isoform accession."""
        query = q.protein_cross_references("P05067-2")
        assert "uniprotkb:P05067 rdfs:seeAlso" in query
        assert "P05067-2" not in query

    def test_go_terms_strips_isoform_suffix(self) -> None:
        """F1-twin: GO terms must anchor on the BASE entry for an isoform accession."""
        query = q.protein_go_terms("P05067-2")
        assert "uniprotkb:P05067 up:classifiedWith" in query
        assert "P05067-2" not in query

    def test_sequence_anchors_on_base_for_isoform(self) -> None:
        """F2: the sequence query anchors on the base entry so isoforms are returned."""
        query = q.protein_sequence("P05067-2")
        assert "uniprotkb:P05067 up:sequence" in query
        assert "uniprotkb:P05067-2" not in query

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

    def test_search_examples_text_path_avoids_filter_exists(self) -> None:
        """QLever rejects EXISTS in expression position (HTTP 400); the text path
        must filter via HAVING over GROUP_CONCAT, never FILTER EXISTS."""
        query = q.search_example_queries("disease cancer")
        assert "EXISTS" not in query
        assert "HAVING(" in query
        # Each token is matched against BOTH the comment- and keyword-concat.
        assert 'LCASE("disease")' in query
        assert 'LCASE("cancer")' in query

    def test_search_examples_multiword_builds_having_over_concat(self) -> None:
        """F: multiword text builds one CONTAINS per token per field inside a
        HAVING over GROUP_CONCAT (never a FILTER EXISTS -> QLever HTTP 400)."""
        query = q.search_example_queries("protein domain architecture")
        assert "EXISTS" not in query
        assert "HAVING(" in query
        # 3 tokens x 2 fields (comment-concat + keyword-concat) = 6 CONTAINS.
        assert query.count("CONTAINS(LCASE(GROUP_CONCAT(") == 6

    def test_search_examples_no_text_omits_having(self) -> None:
        """The no-text path is unchanged: no HAVING, no EXISTS, plain GROUP BY."""
        query = q.search_example_queries(None)
        assert "HAVING" not in query
        assert "EXISTS" not in query
        assert "GROUP BY ?ex" in query


class TestFindProteinsTwoPhase:
    def test_no_pre_limit_global_sort(self) -> None:
        q_ = q.find_proteins(gene="BRCA1", reviewed=True)
        assert "up:reviewed true" in q_
        assert "DESC(?reviewed)" not in q_
        assert "ORDER BY" not in q_  # sorted in Python; no pre-LIMIT global sort

    def test_count_mode_builds_count_query(self) -> None:
        q_ = q.find_proteins(gene="BRCA1", reviewed=True, count=True)
        assert "COUNT(DISTINCT ?protein)" in q_
        assert "LIMIT" not in q_

    def test_count_mode_includes_name_filter_when_name_contains(self) -> None:
        q_ = q.find_proteins(organism_taxon=9606, name_contains="kinase", count=True)
        assert "COUNT(DISTINCT ?protein)" in q_
        assert "CONTAINS(LCASE(?name)" in q_
