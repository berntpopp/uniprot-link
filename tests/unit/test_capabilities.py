"""Unit tests for the capabilities payload and config."""

from __future__ import annotations

from uniprot_link.config import ServerSettings, SparqlEndpointConfig
from uniprot_link.mcp.capabilities import TOOLS, build_capabilities


def test_capabilities_structure() -> None:
    caps = build_capabilities()
    assert caps["server"] == "uniprot-link"
    assert caps["tool_count"] == len(TOOLS) == 15
    assert caps["named_graph_count"] == 21
    assert "json" in caps["result_formats"]
    assert "not_found" in caps["error_codes"]
    assert any(g["name"] == "uniprot" for g in caps["named_graphs"])


def test_capabilities_advertises_response_modes_and_contracts() -> None:
    from uniprot_link.mcp.capabilities import build_capabilities

    cap = build_capabilities()
    assert cap["server_version"] == "0.9.0"
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
    assert cap["server_version"] == "0.9.0"
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


def test_latency_bands_do_not_promise_features_diseases_as_fast() -> None:
    """F4: features/diseases measured ~2s cold; they must not be advertised as fast (0-700ms)."""
    bands = build_capabilities()["latency_profile"]["bands"]
    assert "get_protein_features" not in bands["fast"]["tools"]
    assert "get_protein_diseases" not in bands["fast"]["tools"]
    medium = " ".join(bands["medium"]["tools"])
    assert "get_protein_features" in medium
    assert "get_protein_diseases" in medium


def test_limits_document_find_proteins_page_size() -> None:
    """F5: the 25-per-page find_proteins behavior is documented (not just default_select_limit:50)."""
    limits = build_capabilities()["limits"]
    assert limits["find_proteins_page_size"] == 25
    assert limits["find_proteins_max_limit"] == 200
    assert limits["cross_reference_compact_id_cap"] == 25
    assert "run_sparql_query" in limits["default_select_limit_note"]


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
