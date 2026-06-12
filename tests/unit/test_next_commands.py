from __future__ import annotations

from uniprot_link.mcp.next_commands import after_entry_subresource


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


def test_after_get_protein_trimmed_to_two() -> None:
    from uniprot_link.mcp.next_commands import after_get_protein

    assert len(after_get_protein("P05067")) == 2


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
