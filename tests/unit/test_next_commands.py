from __future__ import annotations

from uniprot_link.mcp.next_commands import after_entry_subresource


def test_after_entry_subresource_excludes_current_and_caps_at_three() -> None:
    out = after_entry_subresource("P38398", "get_protein_features")
    assert len(out) == 3
    assert all(c["arguments"]["accession"] == "P38398" for c in out)
    assert all(c["tool"] != "get_protein_features" for c in out)
    assert all("tool" in c and "arguments" in c for c in out)


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
