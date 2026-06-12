"""Unit tests for the capabilities payload and config."""

from __future__ import annotations

from uniprot_link.config import ServerSettings, SparqlEndpointConfig
from uniprot_link.mcp.capabilities import TOOLS, build_capabilities


def test_capabilities_structure() -> None:
    caps = build_capabilities()
    assert caps["server"] == "uniprot-link"
    assert caps["tool_count"] == len(TOOLS) == 14
    assert caps["named_graph_count"] == 21
    assert "json" in caps["result_formats"]
    assert "not_found" in caps["error_codes"]
    assert any(g["name"] == "uniprot" for g in caps["named_graphs"])


def test_capabilities_advertises_response_modes_and_contracts() -> None:
    from uniprot_link.mcp.capabilities import build_capabilities

    cap = build_capabilities()
    assert cap["server_version"] == "0.7.0"
    assert cap["response_modes"] == ["minimal", "compact", "standard", "full"]
    assert cap["default_response_mode"] == "compact"
    assert "domain" in cap["feature_types"]
    # Bug 1: the dump-emitted classes now round-trip into the filter vocabulary.
    assert "natural_variant" in cap["feature_types"]
    assert "alternative_sequence" in cap["feature_types"]
    assert "sequence_conflict" in cap["feature_types"]
    assert cap["read_only"] is True
    assert "not_found" in cap["not_found_contract"].lower()


def test_capabilities_documents_result_ordering() -> None:
    cap = build_capabilities()
    ordering = cap["result_ordering"]["find_proteins"]
    assert "accession" in ordering and "reviewed" in ordering.lower()


def test_capabilities_documents_obsolete_and_map_dbs() -> None:
    cap = build_capabilities()
    assert cap["server_version"] == "0.7.0"
    assert "obsolete" in cap["not_found_contract"].lower()
    assert "PDB" in cap["map_identifier_databases"]
    assert "DrugBank" not in cap["map_identifier_databases"]
    assert "cross_references" in cap["result_ordering"]


def test_capabilities_has_latency_profile() -> None:
    cap = build_capabilities()
    lp = cap["latency_profile"]
    assert "note" in lp and "bands" in lp
    listed = " ".join(t for band in lp["bands"].values() for t in band["tools"])
    for tool in TOOLS:
        assert tool in listed, f"{tool} missing from latency_profile"


def test_capabilities_has_full_citation() -> None:
    from uniprot_link.mcp.capabilities import build_capabilities

    cap = build_capabilities()
    assert "Nucleic Acids Res" in cap["recommended_citation"]


def test_capabilities_prefixes_present() -> None:
    caps = build_capabilities()
    assert caps["prefixes"]["up"] == "http://purl.uniprot.org/core/"


def test_user_agent_contains_contact() -> None:
    cfg = SparqlEndpointConfig(contact_email="x@example.org")
    assert (
        cfg.user_agent
        == f"uniprot-link/{__import__('uniprot_link').__version__} (mailto:x@example.org)"
    )


def test_base_url_trailing_slash_stripped() -> None:
    cfg = SparqlEndpointConfig(base_url="https://example.org/sparql/")
    assert cfg.base_url == "https://example.org/sparql"


def test_settings_nested_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("UNIPROT_LINK_SPARQL__TIMEOUT", "42")
    monkeypatch.setenv("UNIPROT_LINK_PORT", "9001")
    settings = ServerSettings()
    assert settings.sparql.timeout == 42
    assert settings.port == 9001


def test_capabilities_carries_build_stamp() -> None:
    from uniprot_link import __version__
    from uniprot_link.mcp.capabilities import build_capabilities

    cap = build_capabilities()
    assert cap["build"]["version"] == __version__
    assert "git_sha" in cap["build"]
