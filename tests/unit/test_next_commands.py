from __future__ import annotations

from uniprot_link.mcp.next_commands import after_entry_subresource


def test_after_entry_subresource_excludes_current_and_caps_at_three() -> None:
    out = after_entry_subresource("P38398", "get_protein_features")
    assert len(out) == 3
    assert all(c["arguments"]["accession"] == "P38398" for c in out)
    assert all(c["tool"] != "get_protein_features" for c in out)
    assert all("tool" in c and "arguments" in c for c in out)
