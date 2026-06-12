from __future__ import annotations

from uniprot_link.mcp.next_commands import after_entry_subresource, after_run_sparql


def test_after_run_sparql_offers_get_protein_on_accession_iri() -> None:
    payload = {
        "query_type": "SELECT",
        "rows": [{"protein": "http://purl.uniprot.org/uniprot/P05067"}],
    }
    nxt = after_run_sparql(payload)
    assert nxt[0] == {"tool": "get_protein", "arguments": {"accession": "P05067"}}


def test_after_run_sparql_recognizes_bare_accession() -> None:
    nxt = after_run_sparql({"query_type": "SELECT", "rows": [{"acc": "P38398"}]})
    assert nxt[0] == {"tool": "get_protein", "arguments": {"accession": "P38398"}}


def test_after_run_sparql_falls_back_to_examples() -> None:
    nxt = after_run_sparql({"query_type": "SELECT", "rows": [{"x": "42"}]})
    assert nxt[0]["tool"] == "search_example_queries"


def test_after_run_sparql_ask_falls_back_to_examples() -> None:
    nxt = after_run_sparql({"query_type": "ASK", "boolean": True})
    assert nxt and nxt[0]["tool"] == "search_example_queries"


def test_after_entry_subresource_excludes_current_and_caps_at_two() -> None:
    out = after_entry_subresource("P38398", "get_protein_features")
    assert len(out) == 2
    assert all(c["arguments"]["accession"] == "P38398" for c in out)
    assert all(c["tool"] != "get_protein_features" for c in out)
    assert all("tool" in c and "arguments" in c for c in out)


def test_after_entry_subresource_zero_count_points_home() -> None:
    empty = after_entry_subresource("P05067", "get_protein_features", count=0)
    assert {c["tool"] for c in empty} <= {"get_protein", "get_server_capabilities"}
    nonempty = after_entry_subresource("P05067", "get_protein_features", count=5)
    assert any(c["tool"] == "get_protein_variants" for c in nonempty)


def test_after_get_protein_is_content_aware() -> None:
    from uniprot_link.mcp.next_commands import after_get_protein

    # No diseases/variants -> only sequence + features suggested (len 2).
    plain = after_get_protein("P05067", has_variants=False, has_diseases=False, has_structure=False)
    tools = [c["tool"] for c in plain]
    assert tools == ["get_protein_sequence", "get_protein_features"]
    assert "get_protein_diseases" not in tools

    # Disease-bearing entry surfaces diseases among the gated suggestions.
    rich = after_get_protein("P05067", has_variants=True, has_diseases=True, has_structure=True)
    rtools = [c["tool"] for c in rich]
    assert "get_protein_diseases" in rtools or "get_protein_variants" in rtools
    assert len(rich) <= 3


def test_after_obsolete_entry_points_at_replacement() -> None:
    from uniprot_link.mcp.next_commands import after_obsolete_entry

    out = after_obsolete_entry(["A0A9P2UQ24"])
    assert out[0] == {"tool": "get_protein", "arguments": {"accession": "A0A9P2UQ24"}}
    assert after_obsolete_entry([])[0]["tool"] == "get_server_capabilities"


def test_default_error_next_commands_protein_tool() -> None:
    from uniprot_link.mcp.next_commands import default_error_next_commands

    cmds = default_error_next_commands("get_protein_features", "invalid_input", {})
    assert cmds and cmds[0]["tool"] == "get_server_capabilities"


def test_recovery_does_not_reuse_nongene_accession() -> None:
    from uniprot_link.mcp.next_commands import protein_not_found_recovery

    c = protein_not_found_recovery("999999")
    assert all(x["arguments"].get("gene") != "999999" for x in c)
    c2 = protein_not_found_recovery("BRCA1")
    assert any(x["arguments"].get("gene") == "BRCA1" for x in c2)


def test_recovery_excludes_mangled_accession() -> None:
    from uniprot_link.mcp.next_commands import (
        looks_like_gene_symbol,
        protein_not_found_recovery,
    )

    # A mangled/near-miss accession must NOT be replayed as a gene symbol.
    bad = protein_not_found_recovery("Q96T60XYZ")
    assert not any(c["tool"] == "find_proteins" for c in bad)
    assert bad[0]["tool"] == "get_server_capabilities"
    # A real accession that 404s is not a gene either.
    assert not looks_like_gene_symbol("P05067")
    # Genuine genes are still offered -- including ones with a digit at pos 2.
    gene = protein_not_found_recovery("BRCA1")
    assert gene[0] == {"tool": "find_proteins", "arguments": {"gene": "BRCA1"}}
    assert looks_like_gene_symbol("G6PD")
    assert looks_like_gene_symbol("TP53")
    assert not looks_like_gene_symbol("Q96T60XYZ")


def test_after_find_proteins_batch_fans_out_to_top_hits() -> None:
    from uniprot_link.mcp.next_commands import after_find_proteins_batch

    nxt = after_find_proteins_batch({"PNKP": ["Q96T60"], "NAA10": ["P41227"]})
    accs = [c["arguments"]["accession"] for c in nxt]
    assert "Q96T60" in accs and "P41227" in accs
    assert all(c["tool"] == "get_protein" for c in nxt)


def test_after_find_proteins_batch_empty_points_to_examples() -> None:
    from uniprot_link.mcp.next_commands import after_find_proteins_batch

    nxt = after_find_proteins_batch({"ZZZ": []})
    assert nxt[0]["tool"] == "search_example_queries"
